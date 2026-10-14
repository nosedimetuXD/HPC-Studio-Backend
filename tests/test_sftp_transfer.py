"""Unit tests for asynchronous SFTP TransferQueueManager and TransferWorker.

Verifies:
- Sliding-window SpeedTracker calculations and ETA estimation.
- Enqueueing uploads and downloads.
- Real-time progress updates, speed calculation, and completion.
- Recursive directory upload and download traversal.
- Job cancellation and clearing completed jobs.
- Integration and signal emission via LifecycleSignals.
"""

import os
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from hpc_studio.core.signals import LifecycleSignals
from hpc_studio.sftp.client import SFTPClientManager
from hpc_studio.sftp.models import (
    RemoteFileInfo,
    TransferDirection,
    TransferJob,
    TransferStatus,
)
from hpc_studio.sftp.transfer_queue import (
    SpeedTracker,
    TransferQueueManager,
    TransferWorker,
    TransferWorkerSignals,
)


class TestSpeedTracker:
    """Verifies speed and ETA calculation with sliding window."""

    def test_speed_calculation(self):
        tracker = SpeedTracker(window_seconds=1.0)
        now = 100.0

        # Initial point
        tracker.update(0, now=now)
        # 0.5s later: 1 MB transferred
        speed = tracker.update(1024 * 1024, now=now + 0.5)
        # Speed ~ 2 MB/s
        assert 1.9 * 1024 * 1024 <= speed <= 2.1 * 1024 * 1024

        # 1.0s later: 2 MB total transferred
        speed2 = tracker.update(2 * 1024 * 1024, now=now + 1.0)
        assert 1.9 * 1024 * 1024 <= speed2 <= 2.1 * 1024 * 1024

        # ETA estimation
        rem_bytes = 4 * 1024 * 1024  # 4 MB remaining
        eta = tracker.estimate_eta(rem_bytes)
        assert eta is not None
        assert 1.8 <= eta <= 2.2

    def test_speed_tracker_edge_cases(self):
        tracker = SpeedTracker()
        assert tracker.estimate_eta(0) == 0.0
        assert tracker.estimate_eta(1000) is None  # Speed is 0


class TestTransferWorker:
    """Verifies worker execution, callbacks, and directory recursion."""

    @pytest.fixture
    def mock_sftp_client(self):
        sftp = MagicMock()
        return sftp

    @pytest.fixture
    def mock_sftp_mgr(self, mock_sftp_client):
        mgr = MagicMock(spec=SFTPClientManager)
        mgr.raw_client = mock_sftp_client
        mgr.normalize_path.side_effect = lambda p: p
        mgr.exists.return_value = True
        return mgr

    def test_upload_single_file(self, tmp_path, mock_sftp_mgr, mock_sftp_client):
        test_file = tmp_path / "test_upload.txt"
        test_file.write_text("Hello HPC Cluster")
        file_size = test_file.stat().st_size

        job = TransferJob(
            source_path=str(test_file),
            dest_path="/remote/test_upload.txt",
            direction=TransferDirection.UPLOAD,
            total_bytes=file_size,
        )

        lifecycle_signals = LifecycleSignals()
        signals = TransferWorkerSignals()

        started_events = []
        progress_events = []
        finished_events = []

        signals.job_started.connect(lambda jid: started_events.append(jid))
        signals.job_progress.connect(
            lambda jid, cur, tot, sp, eta: progress_events.append((cur, tot))
        )
        signals.job_finished.connect(
            lambda jid, succ, msg: finished_events.append((succ, msg))
        )

        # Simulate put invoking callback
        def mock_put(local_p, remote_p, callback=None):
            if callback:
                callback(file_size // 2, file_size)
                callback(file_size, file_size)

        mock_sftp_client.put.side_effect = mock_put

        worker = TransferWorker(
            job=job,
            sftp_manager=mock_sftp_mgr,
            signals=signals,
            lifecycle_signals=lifecycle_signals,
        )

        worker.run()

        assert len(started_events) == 1
        assert len(finished_events) == 1
        assert finished_events[0][0] is True  # Success
        assert job.status == TransferStatus.COMPLETED
        assert job.transferred_bytes == file_size

        mock_sftp_client.put.assert_called_once()
        mock_sftp_mgr.makedirs.assert_called_once_with("/remote")

    def test_download_single_file(self, tmp_path, mock_sftp_mgr, mock_sftp_client):
        dest_file = tmp_path / "downloaded.dat"
        mock_sftp_mgr.stat.return_value = RemoteFileInfo(
            name="data.dat", path="/remote/data.dat", size=5000, is_dir=False
        )
        mock_sftp_mgr.is_dir.return_value = False

        job = TransferJob(
            source_path="/remote/data.dat",
            dest_path=str(dest_file),
            direction=TransferDirection.DOWNLOAD,
            total_bytes=5000,
        )

        signals = TransferWorkerSignals()
        finished = []
        signals.job_finished.connect(lambda jid, s, m: finished.append((s, m)))

        worker = TransferWorker(
            job=job,
            sftp_manager=mock_sftp_mgr,
            signals=signals,
        )

        worker.run()

        assert len(finished) == 1
        assert finished[0][0] is True
        assert job.status == TransferStatus.COMPLETED
        mock_sftp_client.get.assert_called_once_with(
            "/remote/data.dat", str(dest_file), callback=worker._progress_callback
        )

    def test_worker_cancellation(self, tmp_path, mock_sftp_mgr, mock_sftp_client):
        test_file = tmp_path / "cancel.txt"
        test_file.write_text("Data")

        job = TransferJob(
            source_path=str(test_file),
            dest_path="/remote/cancel.txt",
            direction=TransferDirection.UPLOAD,
            total_bytes=4,
        )

        cancel_ev = threading.Event()
        worker = TransferWorker(
            job=job,
            sftp_manager=mock_sftp_mgr,
            cancel_event=cancel_ev,
        )

        # Cancel prior to run
        worker.cancel()
        worker.run()

        assert job.status == TransferStatus.CANCELLED
        mock_sftp_client.put.assert_not_called()

    def test_recursive_upload_directory(self, tmp_path, mock_sftp_mgr, mock_sftp_client):
        dir_to_upload = tmp_path / "run_folder"
        dir_to_upload.mkdir()
        (dir_to_upload / "f1.txt").write_text("AAA")
        (dir_to_upload / "sub").mkdir()
        (dir_to_upload / "sub" / "f2.txt").write_text("BBBBBB")

        job = TransferJob(
            source_path=str(dir_to_upload),
            dest_path="/remote/run_folder",
            direction=TransferDirection.UPLOAD,
            is_directory=True,
        )

        mock_sftp_mgr.exists.return_value = False

        worker = TransferWorker(
            job=job,
            sftp_manager=mock_sftp_mgr,
        )

        worker.run()

        assert job.status == TransferStatus.COMPLETED
        assert mock_sftp_client.put.call_count == 2
        assert job.total_bytes == 9


class TestTransferQueueManager:
    """Verifies queue manager lifecycle, job retrieval, and cancellation."""

    @pytest.fixture
    def queue_mgr(self):
        sftp_mgr = MagicMock(spec=SFTPClientManager)
        sftp_mgr.is_connected = True
        sftp_mgr.normalize_path.side_effect = lambda p: p
        signals = LifecycleSignals()
        mgr = TransferQueueManager(
            sftp_manager=sftp_mgr,
            max_concurrent_transfers=2,
            lifecycle_signals=signals,
        )
        return mgr

    def test_enqueue_upload(self, queue_mgr, tmp_path):
        f = tmp_path / "calc.in"
        f.write_text("test")

        job = queue_mgr.enqueue_upload(str(f), "/remote/calc.in")
        assert job.job_id in [j.job_id for j in queue_mgr.jobs]
        assert queue_mgr.get_job(job.job_id) is job
        assert job.direction == TransferDirection.UPLOAD

    def test_enqueue_download(self, queue_mgr):
        job = queue_mgr.enqueue_download("/remote/output.out", "/local/output.out")
        assert job.direction == TransferDirection.DOWNLOAD
        assert job.dest_path == "/local/output.out"

    def test_cancel_job(self, queue_mgr, tmp_path):
        f = tmp_path / "to_cancel.txt"
        f.write_text("abc")

        queue_mgr.sftp_manager.raw_client.put.side_effect = lambda *a, **k: time.sleep(0.2)
        job = queue_mgr.enqueue_upload(str(f), "/remote/to_cancel.txt")
        cancelled = queue_mgr.cancel_job(job.job_id)
        assert cancelled
        assert job.status == TransferStatus.CANCELLED

    def test_clear_completed(self, queue_mgr):
        # Manually create jobs in various states
        job1 = TransferJob("/a", "/b", TransferDirection.UPLOAD, status=TransferStatus.COMPLETED)
        job2 = TransferJob("/c", "/d", TransferDirection.UPLOAD, status=TransferStatus.FAILED)
        job3 = TransferJob("/e", "/f", TransferDirection.UPLOAD, status=TransferStatus.RUNNING)

        queue_mgr._jobs[job1.job_id] = job1
        queue_mgr._jobs[job2.job_id] = job2
        queue_mgr._jobs[job3.job_id] = job3

        cleared_count = queue_mgr.clear_completed()
        assert cleared_count == 2
        assert len(queue_mgr.jobs) == 1
        assert queue_mgr.jobs[0].job_id == job3.job_id
