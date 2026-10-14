"""Global lifecycle and event bus signals for HPC Studio Linux.

Provides a centralized hub of signals for cross-component communication
between UI panels, background SSH threads, Slurm watchdog, and system events.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

class _BoundSignal:
    def __init__(self, name: str = "") -> None:
        self.name = name
        self._callbacks: List[Callable[..., Any]] = []

    def connect(self, callback: Callable[..., Any]) -> None:
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def disconnect(self, callback: Optional[Callable[..., Any]] = None) -> None:
        if callback is None:
            self._callbacks.clear()
        elif callback in self._callbacks:
            self._callbacks.remove(callback)

    def emit(self, *args: Any, **kwargs: Any) -> None:
        for cb in list(self._callbacks):
            try:
                cb(*args, **kwargs)
            except Exception as err:
                logger.error("Error executing signal callback %s: %s", cb, err)


class Signal:
    """Descriptor-based Signal implementation compatible with Qt Signal."""

    def __init__(self, *types: Any) -> None:
        self._types = types
        self._fallback = _BoundSignal()

    def __set_name__(self, owner: Any, name: str) -> None:
        self._name = name

    def __get__(self, instance: Any, owner: Any = None) -> Any:
        if instance is None:
            return self
        if not hasattr(instance, "_instance_signals"):
            instance._instance_signals = {}
        attr_name = getattr(self, "_name", id(self))
        if attr_name not in instance._instance_signals:
            instance._instance_signals[attr_name] = _BoundSignal(str(attr_name))
        return instance._instance_signals[attr_name]

    def connect(self, callback: Callable[..., Any]) -> None:
        self._fallback.connect(callback)

    def disconnect(self, callback: Optional[Callable[..., Any]] = None) -> None:
        self._fallback.disconnect(callback)

    def emit(self, *args: Any, **kwargs: Any) -> None:
        self._fallback.emit(*args, **kwargs)


class QObject:
    """Lightweight QObject base for non-GUI backend environments."""

    def __init__(self, parent: Optional[Any] = None) -> None:
        self._parent = parent


class QMutex:
    """Thread-safe mutex compatible with QMutex."""

    def __init__(self) -> None:
        self._lock = threading.RLock()

    def lock(self) -> None:
        self._lock.acquire()

    def unlock(self) -> None:
        try:
            self._lock.release()
        except RuntimeError:
            pass

    def tryLock(self, timeout_ms: int = 0) -> bool:
        return self._lock.acquire(timeout=timeout_ms / 1000.0)

    def __enter__(self) -> bool:
        return self._lock.acquire()

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.unlock()


class QMutexLocker:
    """RAII context manager compatible with QMutexLocker."""

    def __init__(self, mutex: Any) -> None:
        self._mutex = mutex

    def __enter__(self) -> Any:
        if hasattr(self._mutex, "lock"):
            self._mutex.lock()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if hasattr(self._mutex, "unlock"):
            self._mutex.unlock()


class QThread(threading.Thread, QObject):
    """Background worker thread compatible with QThread."""

    def __init__(self, parent: Optional[Any] = None) -> None:
        threading.Thread.__init__(self, daemon=True)
        QObject.__init__(self, parent)
        self._running = False

    def isRunning(self) -> bool:
        return self.is_alive()

    def quit(self) -> None:
        self._running = False

    def wait(self, timeout_ms: Optional[int] = None) -> bool:
        timeout_s = timeout_ms / 1000.0 if timeout_ms is not None else None
        self.join(timeout=timeout_s)
        return not self.is_alive()

    @staticmethod
    def msleep(ms: int) -> None:
        import time
        time.sleep(ms / 1000.0)



class LifecycleSignals(QObject):
    """Global lifecycle signal hub and event bus.

    Thread-safe Qt signal hub for publishing and subscribing to events
    across the IDE lifecycle without tight coupling between components.
    """

    # --- Application & Theme Lifecycle ---
    app_started = Signal()
    app_about_to_quit = Signal()
    theme_changed = Signal(str)  # 'dark', 'light', 'system'

    # --- Configuration & State ---
    config_changed = Signal(str, object)  # (key, new_value)
    config_reloaded = Signal()
    layout_reset_requested = Signal()

    # --- SSH Connection Lifecycle ---
    ssh_connect_requested = Signal(str)  # profile_name or host
    ssh_connecting = Signal(str)  # host / status message
    ssh_connected = Signal(str)  # host or session_id
    ssh_disconnected = Signal(str)  # reason / session_id
    ssh_error = Signal(str, str)  # (host, error_message)

    # --- Remote File Explorer (SFTP) ---
    sftp_path_changed = Signal(str)  # new remote working directory
    file_transfer_started = Signal(str, str)  # (source_path, target_path)
    file_transfer_progress = Signal(str, int, int)  # (task_id, bytes_transferred, total_bytes)
    file_transfer_completed = Signal(str, bool, str)  # (task_id, success, message)

    # --- Slurm Orchestration & Jobs ---
    slurm_queue_refreshed = Signal(list)  # list of job dictionaries
    slurm_job_submitted = Signal(str)  # job_id
    slurm_job_status_changed = Signal(str, str, str)  # (job_id, old_status, new_status)
    slurm_job_finished = Signal(str, int)  # (job_id, exit_code)

    # --- Quantum ESPRESSO & Workbench ---
    structure_loaded = Signal(str)  # structure file path
    input_generated = Signal(str)  # module name, e.g. 'pw.x'
    scf_convergence_alert = Signal(str, bool, str)  # (job_id, converged, message)

    # --- System Notifications & Status Bar ---
    notification_dispatched = Signal(str, str, str)  # (title, message, severity: info/warning/error)
    status_message_updated = Signal(str, int)  # (message, timeout_ms)

    def __init__(self, parent: Optional[Any] = None) -> None:
        super().__init__(parent)
        self._history: Dict[str, List[Any]] = {}

    def log_event(self, event_name: str, payload: Any) -> None:
        """Utility for debugging and recording event occurrences."""
        if event_name not in self._history:
            self._history[event_name] = []
        self._history[event_name].append(payload)


# Global singleton instance
_global_signals: Optional[LifecycleSignals] = None
_signals_lock = threading.Lock()


def get_signals() -> LifecycleSignals:
    """Return the global LifecycleSignals singleton."""
    global _global_signals
    with _signals_lock:
        if _global_signals is None:
            _global_signals = LifecycleSignals()
        return _global_signals
