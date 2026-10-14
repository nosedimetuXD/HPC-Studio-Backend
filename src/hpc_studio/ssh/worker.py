"""Asynchronous background worker threads for non-blocking SSH operations.

Integrates with PySide6 QThread to ensure responsive desktop UI while
executing network connections, command execution, and session tear-down,
emitting events through LifecycleSignals.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from ..core.signals import LifecycleSignals, get_signals
from .client import CommandResult, ConnectionState, SSHClientManager
from .config_parser import SSHHostEntry

logger = logging.getLogger(__name__)

try:
    from PySide6.QtCore import QObject, QThread, Signal
    PYSIDE6_AVAILABLE = True
except ImportError:
    PYSIDE6_AVAILABLE = False


if not PYSIDE6_AVAILABLE:
    import threading

    class _MockSignal:
        def __init__(self, *types: Any) -> None:
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
                    logger.error("Error executing worker callback: %s", err)

    def Signal(*types: Any) -> Any:  # type: ignore[no-redef]
        return _MockSignal(*types)

    class QObject:  # type: ignore[no-redef]
        def __init__(self, parent: Optional[Any] = None) -> None:
            pass

    class QThread(threading.Thread):  # type: ignore[no-redef]
        def __init__(self, parent: Optional[Any] = None) -> None:
            super().__init__()
            self.daemon = True

        def start(self) -> None:
            super().start()

        def wait(self, timeout_ms: Optional[int] = None) -> None:
            timeout_sec = (timeout_ms / 1000.0) if timeout_ms else None
            self.join(timeout=timeout_sec)


class SSHConnectionWorker(QThread):
    """Background worker for non-blocking SSH session establishment."""

    connection_finished = Signal(bool, str)  # (success, message)
    progress_status = Signal(str)            # status text

    def __init__(
        self,
        client_manager: SSHClientManager,
        host_entry: SSHHostEntry,
        passphrase: Optional[str] = None,
        password: Optional[str] = None,
        timeout: int = 10,
        signals: Optional[LifecycleSignals] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.client_manager = client_manager
        self.host_entry = host_entry
        self.passphrase = passphrase
        self.password = password
        self.timeout = timeout
        self.signals = signals if signals is not None else get_signals()
        self._is_cancelled = False

    def __repr__(self) -> str:
        host_label = getattr(self.host_entry, "host", "unknown")
        return f"<SSHConnectionWorker host={host_label!r}>"

    def cancel(self) -> None:
        """Flag the pending worker for cancellation."""
        self._is_cancelled = True

    def run(self) -> None:
        """Run the connection attempt on the background thread."""
        host_label = self.host_entry.host or self.host_entry.hostname
        try:
            status_msg = f"Connecting to {host_label}..."
            self.signals.ssh_connecting.emit(status_msg)
            self.progress_status.emit(status_msg)

            if self._is_cancelled:
                return

            self.client_manager.connect(
                host_entry=self.host_entry,
                passphrase=self.passphrase,
                password=self.password,
                timeout=self.timeout,
            )

            if self._is_cancelled:
                self.client_manager.disconnect()
                return

            self.signals.ssh_connected.emit(host_label)
            self.connection_finished.emit(True, f"Connected to {host_label}")

        except Exception as exc:
            err_msg = str(exc)
            logger.error("SSH connection error for %s: %s", host_label, err_msg)
            self.signals.ssh_error.emit(host_label, err_msg)
            self.connection_finished.emit(False, err_msg)
        finally:
            # Securely wipe in-memory credential references after attempt
            self.passphrase = None
            self.password = None



class SSHDisconnectionWorker(QThread):
    """Background worker for non-blocking SSH session teardown."""

    disconnection_finished = Signal(bool, str)

    def __init__(
        self,
        client_manager: SSHClientManager,
        reason: str = "User requested disconnect",
        signals: Optional[LifecycleSignals] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.client_manager = client_manager
        self.reason = reason
        self.signals = signals if signals is not None else get_signals()

    def run(self) -> None:
        """Disconnect and notify lifecycle bus."""
        host_label = (
            self.client_manager.current_entry.host
            if self.client_manager.current_entry
            else "session"
        )
        try:
            self.client_manager.disconnect()
            self.signals.ssh_disconnected.emit(f"{host_label}: {self.reason}")
            self.disconnection_finished.emit(True, f"Disconnected from {host_label}")
        except Exception as exc:
            err_msg = str(exc)
            self.disconnection_finished.emit(False, err_msg)


class SSHCommandWorker(QThread):
    """Background worker for non-blocking execution of remote shell commands."""

    command_finished = Signal(object)  # CommandResult
    command_error = Signal(str)

    def __init__(
        self,
        client_manager: SSHClientManager,
        command: str,
        timeout: Optional[int] = None,
        environment: Optional[Dict[str, str]] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.client_manager = client_manager
        self.command = command
        self.timeout = timeout
        self.environment = environment

    def run(self) -> None:
        """Execute remote command on background thread."""
        try:
            result = self.client_manager.execute_command(
                self.command,
                timeout=self.timeout,
                environment=self.environment,
            )
            self.command_finished.emit(result)
        except Exception as exc:
            self.command_error.emit(str(exc))
