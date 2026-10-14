"""Terminal backend abstraction and execution engines for HPC Studio Linux.

Sprint 1.4 terminal subsystem component. Provides abstract TerminalBackend,
native Linux LocalPTYBackend (using pty.openpty, termios, and fcntl), and
remote interactive SSHPtyBackend wrapping Paramiko channels.
"""

from __future__ import annotations

import fcntl
import logging
import os
import pty
import re
import select
import shlex
import signal
import socket
import struct
import subprocess
import termios
import threading
from abc import ABC, ABCMeta, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from hpc_studio.ssh.client import SSHClientManager

logger = logging.getLogger(__name__)

try:
    from PySide6.QtCore import QObject, Signal
    PYSIDE6_AVAILABLE = True
except ImportError:
    PYSIDE6_AVAILABLE = False
    from hpc_studio.core.signals import QObject, Signal  # type: ignore[assignment]


# Regex for detecting OSC 0 / 1 / 2 terminal title change escape sequences in raw byte stream
OSC_TITLE_RE = re.compile(rb"\x1b\](?:0|1|2);([^\x07\x1b]*)(?:\x07|\x1b\\)")


def _resolve_safe_shell(custom_shell: Optional[str] = None) -> str:
    """Resolve and validate a secure system shell executable.

    Validates that the shell is an absolute path, exists, and has execute permissions.
    Falls back safely to /bin/bash or /bin/sh if $SHELL contains an invalid or non-executable binary.
    """
    candidate = custom_shell or os.environ.get("SHELL")
    if candidate:
        candidate = candidate.strip()
        if os.path.isabs(candidate) and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate

    for fallback in ("/bin/bash", "/bin/sh", "/usr/bin/bash", "/usr/bin/sh"):
        if os.path.isfile(fallback) and os.access(fallback, os.X_OK):
            return fallback

    return "/bin/sh"


def _sanitize_terminal_title(title: str, max_length: int = 128) -> str:
    """Sanitize terminal window title to prevent ANSI/control sequence injection and DoS.

    Strips non-printable control characters, newlines, carriage returns,
    and truncates to max_length.
    """
    if not title:
        return ""
    # Strip non-printable ASCII and control characters
    cleaned = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", title)
    # Collapse consecutive spaces
    cleaned = " ".join(cleaned.split()).strip()
    return cleaned[:max_length]


def _set_terminal_size(fd: int, rows: int, cols: int) -> None:
    """Configure terminal window dimensions (TIOCSWINSZ) on a file descriptor."""
    try:
        winsize = struct.pack("HHHH", max(1, int(rows)), max(1, int(cols)), 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)
    except OSError as err:
        logger.debug("Failed to set terminal size on fd %d: %s", fd, err)


if type(QObject) is type:
    _QABCMeta = ABCMeta
else:
    class _QABCMeta(type(QObject), ABCMeta):  # type: ignore[misc]
        """Metaclass resolving conflict between Qt's ObjectType and Python's ABCMeta."""



class TerminalBackend(QObject, metaclass=_QABCMeta):
    """Abstract base class for terminal communication backends (Local PTY, Remote SSH).

    Exposes Qt signals for streaming terminal output, session termination, and
    window title updates.
    """

    # Qt Signals for terminal events
    data_received = Signal(bytes)
    finished = Signal(int)
    title_changed = Signal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._cols: int = 80
        self._rows: int = 24

    @property
    def cols(self) -> int:
        """Current terminal column width."""
        return self._cols

    @property
    def rows(self) -> int:
        """Current terminal row height."""
        return self._rows

    @abstractmethod
    def start(self, cols: int = 80, rows: int = 24) -> None:
        """Initialize and start the interactive terminal session."""

    @abstractmethod
    def write(self, data: bytes) -> None:
        """Send raw input bytes to the terminal."""

    def write_str(self, text: str, encoding: str = "utf-8") -> None:
        """Convenience method to write an encoded string to the terminal."""
        self.write(text.encode(encoding))

    @abstractmethod
    def resize(self, cols: int, rows: int) -> None:
        """Resize the pseudo-terminal window dimensions."""

    @abstractmethod
    def close(self) -> None:
        """Terminate the terminal session and release associated resources."""

    @abstractmethod
    def is_alive(self) -> bool:
        """Return True if the underlying terminal session is active and responsive."""

    def _detect_and_emit_title(self, data: bytes) -> None:
        """Scan received byte stream for OSC title escape sequences and emit sanitized title_changed."""
        match = OSC_TITLE_RE.search(data)
        if match:
            try:
                raw_title = match.group(1).decode("utf-8", errors="replace")
                clean_title = _sanitize_terminal_title(raw_title)
                if clean_title:
                    self.title_changed.emit(clean_title)
            except Exception as err:
                logger.debug("Error decoding terminal title: %s", err)


class LocalPTYBackend(TerminalBackend):
    """Native Linux PTY interactive terminal backend.

    Creates a master/slave pseudo-terminal pair via pty.openpty(), sets window
    size geometry with termios/fcntl, executes an interactive shell process,
    and streams terminal I/O asynchronously via a background reader thread.
    """

    def __init__(
        self,
        command: Optional[Union[str, List[str]]] = None,
        cwd: Optional[Union[str, Path]] = None,
        env: Optional[Dict[str, str]] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._command = command
        self._cwd = Path(cwd) if cwd else None
        self._custom_env = env or {}

        self._master_fd: Optional[int] = None
        self._process: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def start(self, cols: int = 80, rows: int = 24) -> None:
        """Start the local pseudo-terminal shell session."""
        with self._lock:
            if self.is_alive():
                raise RuntimeError("Local PTY session is already running.")

            self._cols = max(1, cols)
            self._rows = max(1, rows)
            self._stop_event.clear()

            # Open master and slave pseudo-terminal file descriptors
            self._master_fd, slave_fd = pty.openpty()

            # Security: Set FD_CLOEXEC on master PTY to prevent descriptor leak across exec
            try:
                flags = fcntl.fcntl(self._master_fd, fcntl.F_GETFD)
                fcntl.fcntl(self._master_fd, fcntl.F_SETFD, flags | fcntl.FD_CLOEXEC)
            except OSError as err:
                logger.debug("Failed to set FD_CLOEXEC on master PTY fd %d: %s", self._master_fd, err)

            # Apply initial terminal window dimensions
            _set_terminal_size(self._master_fd, self._rows, self._cols)
            _set_terminal_size(slave_fd, self._rows, self._cols)

            # Build command argument list with secure shell validation
            if self._command is None:
                shell = _resolve_safe_shell()
                cmd_list = [shell]
            elif isinstance(self._command, str):
                cmd_list = shlex.split(self._command)
                if not cmd_list:
                    raise ValueError("Provided command string is empty.")
            else:
                cmd_list = list(self._command)
                if not cmd_list:
                    raise ValueError("Provided command list is empty.")

            # Build execution environment with proper terminal variables
            cmd_env = dict(os.environ)
            cmd_env.update({
                "TERM": "xterm-256color",
                "COLORTERM": "truecolor",
                "COLUMNS": str(self._cols),
                "LINES": str(self._rows),
            })
            cmd_env.update(self._custom_env)

            # Pre-exec hook to establish controlling terminal and process group for the child
            def _preexec() -> None:
                os.setsid()
                try:
                    fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
                except Exception:
                    pass

            try:
                self._process = subprocess.Popen(
                    cmd_list,
                    stdin=slave_fd,
                    stdout=slave_fd,
                    stderr=slave_fd,
                    cwd=str(self._cwd) if self._cwd else None,
                    env=cmd_env,
                    close_fds=True,
                    preexec_fn=_preexec,
                )
            finally:
                # Slave FD must be closed in parent immediately so EOF / EIO occurs when child exits
                try:
                    os.close(slave_fd)
                except OSError:
                    pass

            # Start asynchronous background reader thread
            self._reader_thread = threading.Thread(
                target=self._reader_loop,
                daemon=True,
                name="LocalPTYReader",
            )
            self._reader_thread.start()

    def _terminate_process_group(self) -> None:
        """Terminate child process and its entire process group cleanly (SIGHUP -> SIGTERM -> SIGKILL)."""
        if self._process is None or self._process.poll() is not None:
            return

        pid = self._process.pid
        try:
            # 1. Send SIGHUP to process group (standard UNIX terminal disconnection)
            try:
                os.killpg(pid, signal.SIGHUP)
            except (ProcessLookupError, PermissionError):
                pass

            try:
                self._process.wait(timeout=0.2)
                return
            except subprocess.TimeoutExpired:
                pass

            # 2. Escalate to SIGTERM
            try:
                os.killpg(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass

            try:
                self._process.wait(timeout=0.3)
                return
            except subprocess.TimeoutExpired:
                pass

            # 3. Hard kill with SIGKILL to avoid hung/orphaned processes
            try:
                os.killpg(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

            try:
                self._process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                pass
        except (ProcessLookupError, OSError) as err:
            logger.debug("Error while terminating process group %d: %s", pid, err)

    def _reader_loop(self) -> None:
        """Background thread reading master PTY fd and emitting data_received signals."""
        while not self._stop_event.is_set():
            master_fd = self._master_fd
            if master_fd is None:
                break

            try:
                # Non-blocking poll with 50ms timeout to permit clean thread termination
                r, _, _ = select.select([master_fd], [], [], 0.05)
                if not r:
                    continue

                data = os.read(master_fd, 4096)
                if not data:
                    break

                self._detect_and_emit_title(data)
                self.data_received.emit(data)

            except (OSError, ValueError):
                # Standard Linux PTY EOF condition raises OSError(EIO) when slave exits
                break
            except Exception as err:
                logger.debug("Unexpected error in Local PTY reader loop: %s", err)
                break

        # Process has exited or PTY was closed; ensure clean process reaping
        exit_code = 0
        if self._process:
            try:
                exit_code = self._process.wait(timeout=0.5)
            except (subprocess.TimeoutExpired, Exception):
                # Ensure hung process group is cleaned up and reaped
                self._terminate_process_group()
                exit_code = self._process.poll() if self._process else 0

        self._cleanup_master_fd()
        self.finished.emit(exit_code or 0)

    def write(self, data: bytes) -> None:
        """Write bytes to the master PTY descriptor."""
        with self._lock:
            if not self.is_alive() or self._master_fd is None:
                raise RuntimeError("Cannot write to inactive or closed Local PTY session.")
            try:
                os.write(self._master_fd, data)
            except OSError as err:
                logger.debug("Local PTY write failed: %s", err)
                raise

    def resize(self, cols: int, rows: int) -> None:
        """Update terminal dimensions and notify child process via SIGWINCH."""
        self._cols = max(1, cols)
        self._rows = max(1, rows)

        with self._lock:
            if self._master_fd is not None:
                _set_terminal_size(self._master_fd, self._rows, self._cols)

            if self._process and self._process.poll() is None:
                try:
                    os.killpg(self._process.pid, signal.SIGWINCH)
                except (ProcessLookupError, OSError):
                    try:
                        self._process.send_signal(signal.SIGWINCH)
                    except (ProcessLookupError, OSError):
                        pass

    def close(self) -> None:
        """Terminate child process group, reap zombie process, and close PTY file descriptors."""
        self._stop_event.set()

        with self._lock:
            self._terminate_process_group()
            self._cleanup_master_fd()

        if self._reader_thread and self._reader_thread.is_alive():
            if threading.current_thread() != self._reader_thread:
                self._reader_thread.join(timeout=1.0)

    def is_alive(self) -> bool:
        """Return True if the child process is active."""
        return self._process is not None and self._process.poll() is None

    def _cleanup_master_fd(self) -> None:
        """Close master file descriptor safely."""
        if self._master_fd is not None:
            fd = self._master_fd
            self._master_fd = None
            try:
                os.close(fd)
            except OSError:
                pass


class SSHPtyBackend(TerminalBackend):
    """Remote interactive SSH PTY terminal backend.

    Invokes an interactive pseudo-terminal shell channel via Paramiko
    (term='xterm-256color'), streams stdin/stdout asynchronously, and supports
    dynamic PTY dimension resizing.
    """

    def __init__(
        self,
        client: Any,
        term: str = "xterm-256color",
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._term = term

        self._channel: Optional[Any] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def start(self, cols: int = 80, rows: int = 24) -> None:
        """Establish the remote interactive SSH shell session."""
        with self._lock:
            if self.is_alive() or self._channel is not None:
                raise RuntimeError("SSH PTY session is already running.")

            self._cols = max(1, cols)
            self._rows = max(1, rows)
            self._stop_event.clear()

            # Resolve Paramiko SSHClient from raw client or SSHClientManager
            raw_client = self._resolve_ssh_client()
            if raw_client is None:
                raise RuntimeError("SSH client is not connected or invalid.")

            # Invoke remote interactive shell with PTY
            self._channel = raw_client.invoke_shell(
                term=self._term,
                width=self._cols,
                height=self._rows,
            )

            # Set short timeout so recv() does not block indefinitely
            self._channel.settimeout(0.05)

            # Start reader thread
            self._reader_thread = threading.Thread(
                target=self._reader_loop,
                daemon=True,
                name="SSHPtyReader",
            )
            self._reader_thread.start()

    def _resolve_ssh_client(self) -> Any:
        """Extract active Paramiko SSHClient from manager or instance."""
        # Support SSHClientManager instance or mock typed as SSHClientManager
        if isinstance(self._client, SSHClientManager):
            if not self._client.is_connected:
                raise RuntimeError("SSHClientManager is not currently connected.")
            return self._client.client

        # Direct paramiko.SSHClient instance
        transport = getattr(self._client, "get_transport", lambda: None)()
        if transport is None or not transport.is_active():
            raise RuntimeError("SSHClient transport is not active.")
        return self._client

    def _reader_loop(self) -> None:
        """Background thread reading remote SSH channel and emitting signals."""
        while not self._stop_event.is_set():
            channel = self._channel
            if channel is None or channel.closed:
                break

            try:
                data = channel.recv(4096)
                if not data:
                    # Remote end closed connection
                    break

                self._detect_and_emit_title(data)
                self.data_received.emit(data)

            except socket.timeout:
                continue
            except (OSError, EOFError):
                break
            except Exception as err:
                if not self._stop_event.is_set():
                    logger.debug("Error in SSH PTY reader loop: %s", err)
                break

        exit_code = 0
        channel = self._channel
        if channel is not None:
            try:
                if channel.exit_status_ready():
                    exit_code = channel.recv_exit_status()
            except Exception:
                pass
            try:
                channel.close()
            except Exception:
                pass

        self.finished.emit(exit_code)

    def write(self, data: bytes) -> None:
        """Send keyboard input bytes to the remote SSH channel."""
        with self._lock:
            if not self.is_alive() or self._channel is None:
                raise RuntimeError("Cannot write to inactive or closed SSH PTY session.")
            try:
                self._channel.sendall(data)
            except Exception as err:
                logger.debug("SSH PTY write failed: %s", err)
                raise

    def resize(self, cols: int, rows: int) -> None:
        """Request remote PTY window dimension resize."""
        self._cols = max(1, cols)
        self._rows = max(1, rows)

        with self._lock:
            if self._channel and not self._channel.closed:
                try:
                    self._channel.resize_pty(width=self._cols, height=self._rows)
                except Exception as err:
                    logger.debug("Failed to resize SSH PTY: %s", err)

    def close(self) -> None:
        """Close SSH channel and stop reader thread."""
        self._stop_event.set()

        with self._lock:
            if self._channel is not None:
                try:
                    if not self._channel.closed:
                        self._channel.close()
                except Exception:
                    pass
                self._channel = None

        if self._reader_thread and self._reader_thread.is_alive():
            if threading.current_thread() != self._reader_thread:
                self._reader_thread.join(timeout=1.0)

    def is_alive(self) -> bool:
        """Return True if the remote SSH channel is open and active."""
        channel = self._channel
        if channel is None:
            return False
        try:
            return not channel.closed and not channel.exit_status_ready()
        except Exception:
            return False
