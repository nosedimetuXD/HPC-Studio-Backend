"""Unit tests for SlurmMonitorWorker background thread and Qt signals."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest


from hpc_studio.slurm.client import SlurmClient
from hpc_studio.slurm.models import JobState, SlurmJob, SlurmPartition
from hpc_studio.slurm.monitor import SlurmMonitorWorker


@pytest.fixture
def mock_slurm_client():
    client = MagicMock(spec=SlurmClient)
    client.is_connected = True
    client.get_jobs.return_value = []
    client.get_partitions.return_value = []
    return client


class TestSlurmMonitorWorker:
    """Test SlurmMonitorWorker signals and state transitions."""

    def test_worker_initialization(self, mock_slurm_client):
        worker = SlurmMonitorWorker(slurm_client=mock_slurm_client)
        assert worker.client == mock_slurm_client
        assert worker._interval == 10
        assert worker._user_filter is None

    def test_set_interval_and_user_filter(self, mock_slurm_client):
        worker = SlurmMonitorWorker(slurm_client=mock_slurm_client)
        worker.set_interval(30)
        assert worker._interval == 30

        worker.set_interval(0)
        assert worker._interval == 1  # max(1, 0)

        worker.set_user_filter("testuser")
        assert worker._user_filter == "testuser"
        assert worker._force_refresh is True

    def test_poll_once_job_state_transitions(self, qtbot, mock_slurm_client):
        worker = SlurmMonitorWorker(slurm_client=mock_slurm_client)

        jobs_updated_signals = []
        partitions_updated_signals = []
        state_changed_signals = []
        job_started_signals = []
        job_finished_signals = []

        worker.jobs_updated.connect(jobs_updated_signals.append)
        worker.partitions_updated.connect(partitions_updated_signals.append)
        worker.job_state_changed.connect(lambda j, old, new: state_changed_signals.append((j, old, new)))
        worker.job_started.connect(job_started_signals.append)
        worker.job_finished.connect(job_finished_signals.append)

        # Cycle 1: Job 101 is PENDING, Job 102 is RUNNING
        job101_pending = SlurmJob(
            job_id="101",
            name="job1",
            user="user1",
            partition="gpu",
            state=JobState.PENDING,
        )
        job102_running = SlurmJob(
            job_id="102",
            name="job2",
            user="user1",
            partition="gpu",
            state=JobState.RUNNING,
        )
        mock_slurm_client.get_jobs.return_value = [job101_pending, job102_running]
        part1 = SlurmPartition(
            name="gpu",
            state="up",
            total_nodes=4,
            idle_nodes=2,
            busy_nodes=2,
            other_nodes=0,
            max_time="24:00:00",
            cpus_per_node="64",
        )
        mock_slurm_client.get_partitions.return_value = [part1]

        worker._poll_once(user_filter=None)

        assert len(jobs_updated_signals) == 1
        assert len(jobs_updated_signals[0]) == 2
        assert len(partitions_updated_signals) == 1
        # 102 was newly appeared RUNNING -> job_started emitted
        assert len(job_started_signals) == 1
        assert job_started_signals[0].job_id == "102"
        assert len(job_finished_signals) == 0

        # Cycle 2: Job 101 transitioned PENDING -> RUNNING, Job 102 transitioned RUNNING -> COMPLETED
        job101_running = SlurmJob(
            job_id="101",
            name="job1",
            user="user1",
            partition="gpu",
            state=JobState.RUNNING,
        )
        job102_completed = SlurmJob(
            job_id="102",
            name="job2",
            user="user1",
            partition="gpu",
            state=JobState.COMPLETED,
        )
        mock_slurm_client.get_jobs.return_value = [job101_running, job102_completed]

        worker._poll_once(user_filter=None)

        assert len(jobs_updated_signals) == 2
        # State changes for both 101 and 102
        assert len(state_changed_signals) == 2
        # job 101 started
        assert len(job_started_signals) == 2
        assert job_started_signals[1].job_id == "101"
        # job 102 finished
        assert len(job_finished_signals) == 1
        assert job_finished_signals[0].job_id == "102"

        # Cycle 3: Job 101 disappears from queue (left queue while running)
        mock_slurm_client.get_jobs.return_value = []
        worker._poll_once(user_filter=None)

        assert len(jobs_updated_signals) == 3
        # 101 was active and vanished -> finished event emitted
        finished_ids = [j.job_id for j in job_finished_signals]
        assert "101" in finished_ids

    def test_worker_thread_lifecycle(self, qtbot, mock_slurm_client):
        worker = SlurmMonitorWorker(slurm_client=mock_slurm_client)

        with qtbot.waitSignal(worker.jobs_updated, timeout=5000):
            worker.start_monitoring(interval_seconds=1)

        assert worker.isRunning() is True

        worker.stop_monitoring()
        assert worker.isRunning() is False
