"""Asynchronous monitoring worker for Slurm jobs and cluster state.

Runs periodically in a QThread to poll jobs and partition states, emitting signals on changes.
"""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

from ..core.signals import QMutex, QMutexLocker, QThread, Signal

from .client import SlurmClient
from .models import JobState, SlurmJob, SlurmPartition

logger = logging.getLogger(__name__)


class SlurmMonitorWorker(QThread):
    """Background worker thread monitoring Slurm jobs and cluster resources."""

    jobs_updated = Signal(list)
    partitions_updated = Signal(list)
    job_state_changed = Signal(object, object, object)  # job, old_state, new_state
    job_started = Signal(object)  # job
    job_finished = Signal(object)  # job
    error_occurred = Signal(str)

    def __init__(self, slurm_client: SlurmClient, parent=None) -> None:
        super().__init__(parent)
        self.client = slurm_client
        self._interval = 10
        self._user_filter: Optional[str] = None
        self._is_running = False
        self._mutex = QMutex()
        self._previous_jobs: Dict[str, SlurmJob] = {}
        self._force_refresh = False

    def start_monitoring(self, interval_seconds: int = 10) -> None:
        """Start the background monitoring thread."""
        with QMutexLocker(self._mutex):
            self._interval = max(1, interval_seconds)
            self._is_running = True
        if not self.isRunning():
            self.start()

    def stop_monitoring(self) -> None:
        """Stop the background monitoring thread."""
        with QMutexLocker(self._mutex):
            self._is_running = False
        self.wait(2000)

    def set_interval(self, seconds: int) -> None:
        """Update polling frequency in seconds."""
        with QMutexLocker(self._mutex):
            self._interval = max(1, seconds)

    def set_user_filter(self, user: Optional[str]) -> None:
        """Filter jobs by username."""
        with QMutexLocker(self._mutex):
            self._user_filter = user
        self.refresh_now()

    def refresh_now(self) -> None:
        """Trigger an immediate poll on the next loop iteration."""
        with QMutexLocker(self._mutex):
            self._force_refresh = True

    def run(self) -> None:
        """Execution loop polling Slurm client at regular intervals."""
        logger.info("SlurmMonitorWorker started.")
        while True:
            with QMutexLocker(self._mutex):
                if not self._is_running:
                    break
                user_filter = self._user_filter
                interval = self._interval
                self._force_refresh = False

            if self.client.is_connected:
                try:
                    self._poll_once(user_filter)
                except Exception as exc:
                    logger.error("Error during Slurm polling cycle: %s", exc)
                    self.error_occurred.emit(str(exc))
            else:
                logger.debug("Slurm client is disconnected; skipping cycle.")

            # Sleep in small slices to remain responsive to stop/refresh
            elapsed = 0
            while elapsed < interval:
                with QMutexLocker(self._mutex):
                    if not self._is_running or self._force_refresh:
                        break
                time.sleep(0.2)
                elapsed += 0.2

        logger.info("SlurmMonitorWorker stopped.")

    def _poll_once(self, user_filter: Optional[str]) -> None:
        """Perform a single polling cycle fetching jobs and partitions."""
        current_jobs = self.client.get_jobs(user=user_filter)
        self.jobs_updated.emit(current_jobs)

        current_job_dict = {job.job_id: job for job in current_jobs}

        # Check existing jobs for state transitions
        for job_id, current_job in current_job_dict.items():
            if job_id in self._previous_jobs:
                old_job = self._previous_jobs[job_id]
                if old_job.state != current_job.state:
                    self.job_state_changed.emit(current_job, old_job.state, current_job.state)

                    if old_job.state == JobState.PENDING and current_job.state == JobState.RUNNING:
                        self.job_started.emit(current_job)

                    if current_job.is_done:
                        self.job_finished.emit(current_job)
            else:
                # Newly appeared job
                if current_job.state == JobState.RUNNING:
                    self.job_started.emit(current_job)

        # Detect jobs that finished and disappeared from squeue
        for job_id, old_job in self._previous_jobs.items():
            if job_id not in current_job_dict:
                if old_job.is_active:
                    # Job was active and is no longer in queue -> marked as finished (assumed COMPLETED)
                    finished_job = SlurmJob(
                        job_id=old_job.job_id,
                        name=old_job.name,
                        user=old_job.user,
                        partition=old_job.partition,
                        state=JobState.COMPLETED,
                        time_used=old_job.time_used,
                        time_limit=old_job.time_limit,
                        nodes=old_job.nodes,
                        cpus=old_job.cpus,
                        work_dir=old_job.work_dir,
                        reason="Job completed and left queue",
                        nodelist=old_job.nodelist,
                        raw_state="COMPLETED",
                    )
                    self.job_state_changed.emit(finished_job, old_job.state, JobState.COMPLETED)
                    self.job_finished.emit(finished_job)

        self._previous_jobs = current_job_dict

        partitions = self.client.get_partitions()
        self.partitions_updated.emit(partitions)
