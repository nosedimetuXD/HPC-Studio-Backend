"""Asynchronous Transfer Queue Manager for non-blocking SFTP uploads and downloads.

Features:
- Thread-safe transfer queue backed by QThread / QThreadPool.
- Support for individual file transfers and recursive directory transfers.
- Progress monitoring with sliding-window calculations for real-time speed (MB/s) and ETA.
- Job lifecycle states (PENDING, RUNNING, COMPLETED, FAILED, CANCELLED).
- Integration with LifecycleSignals (file_transfer_started, file_transfer_progress, file_transfer_completed).
"""

from __future__ import annotations

import collections
import logging
import os
import posixpath
import stat
import threading
import time
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

import paramiko

try:
    from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
    PYSIDE_AVAILABLE = True
except ImportError:
    PYSIDE_AVAILABLE = False
    from hpc_studio.core.signals import QObject, Signal

from hpc_studio.core.signals import LifecycleSignals, get_signals

from .client import SFTPClientManager, SFTPError
from .models import RemoteFileInfo, TransferDirection, TransferJob, TransferStatus

logger = logging.getLogger(__name__)


class SpeedTracker:
    """Sliding-window speed and ETA estimator."""

    def __init__(self, window_seconds: float = 2.0) -> None:
        self.window_seconds = window_seconds
        # Stores (timestamp, transferred_bytes)
        self._history: Deque[Tuple[float, int]] = collections.deque()
        self._last_speed: float = 0.0

    def update(self, current_bytes: int, now: Optional[float] = None) -> float:
        """Record current bytes transferred and compute instantaneous speed in bytes/sec."""
        current_time = time.monotonic() if now is None else now
        self._history.append((current_time, current_bytes))

        # Evict entries older than window_seconds
        cutoff = current_time - self.window_seconds
        while len(self._history) > 1 and self._history[0][0] < cutoff:
            self._history.popleft()

        if len(self._history) < 2:
            return self._last_speed

        t_start, b_start = self._history[0]
        t_end, b_end = self._history[-1]
        dt = t_end - t_start

        if dt > 0.05:
            delta_bytes = max(0, b_end - b_start)
            self._last_speed = delta_bytes / dt

        return self._last_speed

    def estimate_eta(self, remaining_bytes: int) -> Optional[float]:
        """Estimate time remaining in seconds."""
        if remaining_bytes <= 0:
            return 0.0
        if self._last_speed <= 0.0:
            return None
        return remaining_bytes / self._last_speed

    def reset(self) -> None:
        """Reset history."""
        self._history.clear()
        self._last_speed = 0.0


class TransferWorkerSignals(QObject):
    """Signals emitted by TransferWorker."""

    job_started = Signal(str)  # job_id
    job_progress = Signal(str, int, int, float, float)  # job_id, transferred, total, speed_bps, eta
    job_finished = Signal(str, bool, str)  # job_id, success, message


class TransferWorker(QRunnable if PYSIDE_AVAILABLE else object):
    """Worker runnable executing a single TransferJob over SFTP."""

    def __init__(
        self,
        job: TransferJob,
        sftp_manager: SFTPClientManager,
        signals: Optional[TransferWorkerSignals] = None,
        lifecycle_signals: Optional[LifecycleSignals] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> None:
        if PYSIDE_AVAILABLE:
            super().__init__()
            self.setAutoDelete(True)
        self.job = job
        self.sftp_manager = sftp_manager
        self.signals = signals or TransferWorkerSignals()
        self.lifecycle_signals = lifecycle_signals
        self.cancel_event = cancel_event or threading.Event()
        self.speed_tracker = SpeedTracker(window_seconds=2.0)

    def cancel(self) -> None:
        """Signal job cancellation."""
        self.cancel_event.set()

    def run(self) -> None:
        """Execute the upload or download transfer."""
        if self.cancel_event.is_set():
            self._mark_cancelled()
            return

        self.job.status = TransferStatus.RUNNING
        self.job.started_at = time.time()
        self.speed_tracker.reset()

        logger.info(
            "Transfer started [%s]: %s -> %s (%s)",
            self.job.job_id,
            self.job.source_path,
            self.job.dest_path,
            self.job.direction.value,
        )

        self.signals.job_started.emit(self.job.job_id)
        if self.lifecycle_signals:
            self.lifecycle_signals.file_transfer_started.emit(
                self.job.source_path, self.job.dest_path
            )

        try:
            raw_sftp = self.sftp_manager.raw_client
            if raw_sftp is None:
                raise RuntimeError("SFTP client is not connected.")

            if self.job.direction == TransferDirection.UPLOAD:
                self._execute_upload(raw_sftp)
            else:
                self._execute_download(raw_sftp)

            if self.cancel_event.is_set():
                self._mark_cancelled()
                return

            self.job.status = TransferStatus.COMPLETED
            self.job.completed_at = time.time()
            self.job.transferred_bytes = self.job.total_bytes
            self.job.speed_bps = 0.0
            self.job.eta_seconds = 0.0

            success_msg = f"Transfer completed: {posixpath.basename(self.job.dest_path)}"
            self.signals.job_finished.emit(self.job.job_id, True, success_msg)
            if self.lifecycle_signals:
                self.lifecycle_signals.file_transfer_completed.emit(
                    self.job.job_id, True, success_msg
                )

        except Exception as exc:
            if self.cancel_event.is_set():
                self._mark_cancelled()
                return

            err_msg = str(exc)
            logger.error("Transfer failed [%s]: %s", self.job.job_id, err_msg)
            self.job.status = TransferStatus.FAILED
            self.job.error_message = err_msg
            self.job.completed_at = time.time()
            self.job.speed_bps = 0.0
            self.job.eta_seconds = None

            self.signals.job_finished.emit(self.job.job_id, False, err_msg)
            if self.lifecycle_signals:
                self.lifecycle_signals.file_transfer_completed.emit(
                    self.job.job_id, False, err_msg
                )

    def _mark_cancelled(self) -> None:
        """Mark job as cancelled and emit completion."""
        self.job.status = TransferStatus.CANCELLED
        self.job.completed_at = time.time()
        self.job.speed_bps = 0.0
        self.job.eta_seconds = None
        msg = "Transfer cancelled by user."
        self.signals.job_finished.emit(self.job.job_id, False, msg)
        if self.lifecycle_signals:
            self.lifecycle_signals.file_transfer_completed.emit(self.job.job_id, False, msg)

    def _progress_callback(self, transferred: int, total: int) -> None:
        """Progress callback invoked by Paramiko put/get."""
        if self.cancel_event.is_set():
            raise InterruptedError("Transfer cancelled by user.")

        self.job.transferred_bytes = transferred
        if total > 0:
            self.job.total_bytes = total

        speed = self.speed_tracker.update(transferred)
        self.job.speed_bps = speed

        remaining = max(0, self.job.total_bytes - transferred)
        eta = self.speed_tracker.estimate_eta(remaining)
        self.job.eta_seconds = eta

        self.signals.job_progress.emit(
            self.job.job_id, transferred, self.job.total_bytes, speed, eta if eta is not None else -1.0
        )
        if self.lifecycle_signals:
            self.lifecycle_signals.file_transfer_progress.emit(
                self.job.job_id, transferred, self.job.total_bytes
            )

    def _execute_upload(self, sftp: paramiko.SFTPClient) -> None:
        """Upload file or directory recursively to remote host."""
        local_src = Path(self.job.source_path)
        remote_dest = self.sftp_manager.normalize_path(self.job.dest_path)

        if not local_src.exists():
            raise FileNotFoundError(f"Local source path does not exist: {local_src}")

        if local_src.is_dir():
            self._upload_dir_recursive(sftp, local_src, remote_dest)
        else:
            self.job.total_bytes = local_src.stat().st_size
            # Ensure destination parent exists
            parent = posixpath.dirname(remote_dest)
            self.sftp_manager.makedirs(parent)
            sftp.put(str(local_src), remote_dest, callback=self._progress_callback)
            # Invalidate cache for destination parent
            self.sftp_manager.clear_cache(parent)

    def _upload_dir_recursive(
        self, sftp: paramiko.SFTPClient, local_dir: Path, remote_dir: str
    ) -> None:
        """Recursively upload folder contents."""
        self.sftp_manager.makedirs(remote_dir)

        # Calculate total bytes if not already done
        if self.job.total_bytes <= 0:
            total_b = 0
            for root, _, files in os.walk(local_dir):
                for f in files:
                    try:
                        total_b += os.path.getsize(os.path.join(root, f))
                    except Exception:
                        pass
            self.job.total_bytes = total_b

        cumulative_transferred = 0
        base_path = str(local_dir)

        for root, dirs, files in os.walk(local_dir):
            if self.cancel_event.is_set():
                raise InterruptedError("Transfer cancelled by user.")

            rel_root = os.path.relpath(root, base_path)
            current_remote_root = (
                remote_dir if rel_root == "." else posixpath.join(remote_dir, rel_root.replace("\\", "/"))
            )

            for d in dirs:
                sub_remote = posixpath.join(current_remote_root, d)
                if not self.sftp_manager.exists(sub_remote):
                    self.sftp_manager.mkdir(sub_remote)

            for f in files:
                if self.cancel_event.is_set():
                    raise InterruptedError("Transfer cancelled by user.")

                file_local = os.path.join(root, f)
                file_remote = posixpath.join(current_remote_root, f)
                file_size = os.path.getsize(file_local)

                def file_callback(transferred_file: int, total_file: int) -> None:
                    total_done = cumulative_transferred + transferred_file
                    self._progress_callback(total_done, self.job.total_bytes)

                sftp.put(file_local, file_remote, callback=file_callback)
                cumulative_transferred += file_size

        self.sftp_manager.clear_cache(posixpath.dirname(remote_dir))

    def _execute_download(self, sftp: paramiko.SFTPClient) -> None:
        """Download file or directory recursively from remote host to local path."""
        remote_src = self.sftp_manager.normalize_path(self.job.source_path)
        local_dest = Path(self.job.dest_path)

        if not self.sftp_manager.exists(remote_src):
            raise FileNotFoundError(f"Remote source does not exist: {remote_src}")

        if local_dest.is_symlink():
            raise SFTPError(f"Destination path {local_dest} is an insecure symlink. Refusing to download.")

        if self.sftp_manager.is_dir(remote_src):
            self._download_dir_recursive(sftp, remote_src, local_dest)
        else:
            attr = self.sftp_manager.stat(remote_src)
            self.job.total_bytes = attr.size
            # Ensure local parent directory exists with secure permissions (0o700)
            local_dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if local_dest.parent.exists() and hasattr(os, "getuid") and local_dest.parent.stat().st_uid == os.getuid():
                try:
                    os.chmod(local_dest.parent, 0o700)
                except OSError:
                    pass

            sftp.get(remote_src, str(local_dest), callback=self._progress_callback)
            if local_dest.exists() and hasattr(os, "getuid") and local_dest.stat().st_uid == os.getuid():
                try:
                    os.chmod(local_dest, 0o600)
                except OSError:
                    pass

    def _download_dir_recursive(
        self, sftp: paramiko.SFTPClient, remote_dir: str, local_dir: Path
    ) -> None:
        """Recursively download remote directory contents with confinement enforcement."""
        if local_dir.is_symlink():
            raise SFTPError(f"Destination directory {local_dir} is an insecure symlink.")

        local_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        if local_dir.exists() and hasattr(os, "getuid") and local_dir.stat().st_uid == os.getuid():
            try:
                os.chmod(local_dir, 0o700)
            except OSError:
                pass

        canonical_base = local_dir.resolve()

        # Calculate remote tree total bytes
        def count_bytes(rem_path: str) -> int:
            b = 0
            items = self.sftp_manager.listdir_attr(rem_path, use_cache=False)
            for it in items:
                if it.is_dir:
                    b += count_bytes(it.path)
                else:
                    b += it.size
            return b

        if self.job.total_bytes <= 0:
            self.job.total_bytes = count_bytes(remote_dir)

        cumulative_transferred = 0

        def download_subtree(curr_rem: str, curr_loc: Path) -> None:
            nonlocal cumulative_transferred
            if curr_loc.is_symlink():
                raise SFTPError(f"Directory {curr_loc} is an insecure symlink.")

            curr_loc.mkdir(parents=True, exist_ok=True, mode=0o700)
            if curr_loc.exists() and hasattr(os, "getuid") and curr_loc.stat().st_uid == os.getuid():
                try:
                    os.chmod(curr_loc, 0o700)
                except OSError:
                    pass

            items = self.sftp_manager.listdir_attr(curr_rem, use_cache=False)

            for it in items:
                if self.cancel_event.is_set():
                    raise InterruptedError("Transfer cancelled by user.")

                # Security check: Validate filename and jail confinement (CWE-22)
                raw_name = it.name
                safe_name = posixpath.basename(raw_name.replace("\\", "/"))
                if not safe_name or safe_name in (".", "..") or "\x00" in raw_name:
                    logger.warning("Skipping malicious/invalid filename %r", raw_name)
                    continue

                target_local = (curr_loc / safe_name).resolve()

                # Enforce directory confinement (prevent traversal outside destination base)
                try:
                    target_local.relative_to(canonical_base)
                except ValueError:
                    raise SFTPError(
                        f"Path traversal detected: {it.name!r} attempts to escape target directory {canonical_base}"
                    )

                if target_local.is_symlink():
                    raise SFTPError(f"Refusing to write to symlink {target_local} during download.")

                if it.is_dir:
                    download_subtree(it.path, target_local)
                else:
                    def file_callback(transferred_file: int, total_file: int) -> None:
                        total_done = cumulative_transferred + transferred_file
                        self._progress_callback(total_done, self.job.total_bytes)

                    sftp.get(it.path, str(target_local), callback=file_callback)
                    if target_local.exists() and hasattr(os, "getuid") and target_local.stat().st_uid == os.getuid():
                        try:
                            os.chmod(target_local, 0o600)
                        except OSError:
                            pass
                    cumulative_transferred += it.size

        download_subtree(remote_dir, local_dir)



class TransferQueueManager(QObject):
    """Manages queueing, parallel execution, and lifecycle of SFTP file transfers."""

    # Qt signals
    job_enqueued = Signal(object)  # TransferJob
    job_started = Signal(str)  # job_id
    job_progress = Signal(str, int, int, float, float)  # job_id, bytes, total, speed, eta
    job_completed = Signal(str, bool, str)  # job_id, success, message
    queue_cleared = Signal()

    def __init__(
        self,
        sftp_manager: SFTPClientManager,
        max_concurrent_transfers: int = 2,
        lifecycle_signals: Optional[LifecycleSignals] = None,
        parent: Optional[Any] = None,
    ) -> None:
        super().__init__(parent)
        self.sftp_manager = sftp_manager
        self.lifecycle_signals = lifecycle_signals or get_signals()
        self._max_concurrent = max_concurrent_transfers

        self._jobs: Dict[str, TransferJob] = {}
        self._active_workers: Dict[str, TransferWorker] = {}
        self._cancel_events: Dict[str, threading.Event] = {}
        self._lock = threading.RLock()

        if PYSIDE_AVAILABLE:
            self._thread_pool = QThreadPool.globalInstance()
            self._thread_pool.setMaxThreadCount(max(4, max_concurrent_transfers + 2))
        else:
            self._thread_pool = None

    @property
    def jobs(self) -> List[TransferJob]:
        """Return snapshot of all registered transfer jobs."""
        with self._lock:
            return list(self._jobs.values())

    def get_job(self, job_id: str) -> Optional[TransferJob]:
        """Get TransferJob by ID."""
        with self._lock:
            return self._jobs.get(job_id)

    def enqueue_upload(
        self,
        local_path: str,
        remote_path: str,
        is_directory: Optional[bool] = None,
    ) -> TransferJob:
        """Enqueue a local-to-remote upload task."""
        p = Path(local_path)
        is_dir = p.is_dir() if is_directory is None and p.exists() else bool(is_directory)

        total_bytes = 0
        if not is_dir and p.is_file():
            try:
                total_bytes = p.stat().st_size
            except Exception:
                pass

        job = TransferJob(
            source_path=str(local_path),
            dest_path=str(remote_path),
            direction=TransferDirection.UPLOAD,
            total_bytes=total_bytes,
            is_directory=is_dir,
            status=TransferStatus.PENDING,
        )

        self._register_and_start(job)
        return job

    def enqueue_download(
        self,
        remote_path: str,
        local_path: str,
        is_directory: Optional[bool] = None,
    ) -> TransferJob:
        """Enqueue a remote-to-local download task."""
        total_bytes = 0
        is_dir = bool(is_directory)

        if not is_dir and self.sftp_manager.is_connected:
            try:
                st = self.sftp_manager.stat(remote_path)
                total_bytes = st.size
                is_dir = st.is_dir
            except Exception:
                pass

        job = TransferJob(
            source_path=str(remote_path),
            dest_path=str(local_path),
            direction=TransferDirection.DOWNLOAD,
            total_bytes=total_bytes,
            is_directory=is_dir,
            status=TransferStatus.PENDING,
        )

        self._register_and_start(job)
        return job

    def _register_and_start(self, job: TransferJob) -> None:
        """Register job in internal tracking and dispatch to thread pool."""
        cancel_event = threading.Event()
        with self._lock:
            self._jobs[job.job_id] = job
            self._cancel_events[job.job_id] = cancel_event

        worker_signals = TransferWorkerSignals()
        worker_signals.job_started.connect(self._on_worker_started)
        worker_signals.job_progress.connect(self._on_worker_progress)
        worker_signals.job_finished.connect(self._on_worker_finished)

        worker = TransferWorker(
            job=job,
            sftp_manager=self.sftp_manager,
            signals=worker_signals,
            lifecycle_signals=self.lifecycle_signals,
            cancel_event=cancel_event,
        )

        with self._lock:
            self._active_workers[job.job_id] = worker

        self.job_enqueued.emit(job)

        if self._thread_pool:
            self._thread_pool.start(worker)
        else:
            # Fallback pure python thread
            t = threading.Thread(target=worker.run, daemon=True)
            t.start()

    def cancel_job(self, job_id: str) -> bool:
        """Cancel an ongoing or pending transfer job."""
        with self._lock:
            cancel_event = self._cancel_events.get(job_id)
            job = self._jobs.get(job_id)

            if cancel_event:
                cancel_event.set()

            if job:
                if job.status in (TransferStatus.PENDING, TransferStatus.RUNNING):
                    job.status = TransferStatus.CANCELLED
                    job.completed_at = time.time()
                    return True
        return False

    def clear_completed(self) -> int:
        """Remove completed, failed, or cancelled jobs from memory."""
        with self._lock:
            to_remove = [
                jid
                for jid, j in self._jobs.items()
                if j.status in (TransferStatus.COMPLETED, TransferStatus.FAILED, TransferStatus.CANCELLED)
            ]
            for jid in to_remove:
                self._jobs.pop(jid, None)
                self._active_workers.pop(jid, None)
                self._cancel_events.pop(jid, None)

        self.queue_cleared.emit()
        return len(to_remove)

    def _on_worker_started(self, job_id: str) -> None:
        self.job_started.emit(job_id)

    def _on_worker_progress(
        self, job_id: str, transferred: int, total: int, speed: float, eta: float
    ) -> None:
        self.job_progress.emit(job_id, transferred, total, speed, eta)

    def _on_worker_finished(self, job_id: str, success: bool, message: str) -> None:
        with self._lock:
            self._active_workers.pop(job_id, None)
            self._cancel_events.pop(job_id, None)
        self.job_completed.emit(job_id, success, message)
