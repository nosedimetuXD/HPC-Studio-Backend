"""Unit tests for lifecycle signals hub in HPC Studio Linux."""

from __future__ import annotations

from hpc_studio.core.signals import LifecycleSignals, get_signals


def test_signals_singleton() -> None:
    """Test get_signals returns identical singleton instance."""
    sig1 = get_signals()
    sig2 = get_signals()
    assert sig1 is sig2


def test_theme_changed_signal() -> None:
    """Test emitting and receiving theme_changed signal."""
    signals = LifecycleSignals()
    received = []

    def handler(theme_name: str) -> None:
        received.append(theme_name)

    signals.theme_changed.connect(handler)
    signals.theme_changed.emit("light")

    assert received == ["light"]


def test_ssh_signals() -> None:
    """Test SSH connection lifecycle signal chain."""
    signals = LifecycleSignals()
    events = []

    signals.ssh_connecting.connect(lambda host: events.append(f"connecting:{host}"))
    signals.ssh_connected.connect(lambda host: events.append(f"connected:{host}"))
    signals.ssh_disconnected.connect(lambda host: events.append(f"disconnected:{host}"))
    signals.ssh_error.connect(lambda host, err: events.append(f"error:{host}:{err}"))

    signals.ssh_connecting.emit("login.cluster.hpc")
    signals.ssh_connected.emit("login.cluster.hpc")
    signals.ssh_disconnected.emit("login.cluster.hpc")
    signals.ssh_error.emit("login.cluster.hpc", "Connection refused")

    assert events == [
        "connecting:login.cluster.hpc",
        "connected:login.cluster.hpc",
        "disconnected:login.cluster.hpc",
        "error:login.cluster.hpc:Connection refused",
    ]


def test_slurm_signals() -> None:
    """Test Slurm queue and job event signals."""
    signals = LifecycleSignals()
    received_queue = []
    received_status = []

    signals.slurm_queue_refreshed.connect(lambda q: received_queue.append(q))
    signals.slurm_job_status_changed.connect(lambda jid, old, new: received_status.append((jid, old, new)))

    test_jobs = [{"job_id": "1001", "name": "qe_scf", "state": "RUNNING"}]
    signals.slurm_queue_refreshed.emit(test_jobs)
    signals.slurm_job_status_changed.emit("1001", "PENDING", "RUNNING")

    assert received_queue == [test_jobs]
    assert received_status == [("1001", "PENDING", "RUNNING")]


def test_file_transfer_signals() -> None:
    """Test SFTP file transfer progress and completion signals."""
    signals = LifecycleSignals()
    progress_updates = []
    completion = []

    signals.file_transfer_progress.connect(lambda tid, cur, tot: progress_updates.append((tid, cur, tot)))
    signals.file_transfer_completed.connect(lambda tid, ok, msg: completion.append((tid, ok, msg)))

    signals.file_transfer_progress.emit("task-1", 500, 1000)
    signals.file_transfer_progress.emit("task-1", 1000, 1000)
    signals.file_transfer_completed.emit("task-1", True, "Transfer complete")

    assert progress_updates == [("task-1", 500, 1000), ("task-1", 1000, 1000)]
    assert completion == [("task-1", True, "Transfer complete")]
