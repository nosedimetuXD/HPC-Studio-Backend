"""Real-time remote log streaming via SSH for Slurm job outputs.

Supports tailing remote output and error files with pause, resume, and stop controls.
Emits Qt signals as lines arrive from the remote compute node/cluster.
"""

from __future__ import annotations

import logging
import shlex
import threading
import time
from typing import Optional

from ..core.signals import QObject, Signal

from ..ssh.client import SSHClientManager

logger = logging.getLogger(__name__)


class RemoteLogStreamer(QObject):
    """Streams remote log files continuously over an SSH connection using tail -f."""

    line_received = Signal(str)
    stream_started = Signal(str)
    stream_stopped = Signal(str)
    stream_error = Signal(str)

    def __init__(
        self,
        ssh_manager: Optional[SSHClientManager] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.ssh_manager = ssh_manager
        self._current_path: str = ""
        self._is_streaming: bool = False
        self._is_paused: bool = False
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._active_channel = None
        self._lock = threading.RLock()

    @property
    def is_streaming(self) -> bool:
        """True if the background log streaming thread is active."""
        with self._lock:
            return self._is_streaming

    @property
    def is_paused(self) -> bool:
        """True if streaming is currently paused."""
        with self._lock:
            return self._is_paused

    @property
    def current_path(self) -> str:
        """Current remote log file path being streamed."""
        with self._lock:
            return self._current_path

    def start_streaming(self, remote_path: str, lines_history: int = 100) -> bool:
        """Start streaming the specified remote file using tail -n <lines> -f.

        Args:
            remote_path: Absolute or relative path to remote log file.
            lines_history: Number of existing lines to retrieve before following new lines.

        Returns:
            bool: True if streaming thread started successfully, False otherwise.
        """
        if not remote_path or not remote_path.strip():
            err_msg = "Remote path cannot be empty."
            logger.warning(err_msg)
            self.stream_error.emit(err_msg)
            return False

        with self._lock:
            if self._is_streaming:
                self._stop_streaming_internal(reason="restarted")

            if self.ssh_manager is None or not self.ssh_manager.is_connected:
                err_msg = "SSH client is not connected."
                logger.warning(err_msg)
                self.stream_error.emit(err_msg)
                return False

            self._current_path = remote_path.strip()
            self._is_streaming = True
            self._is_paused = False
            self._stop_event.clear()
            self._pause_event.clear()

            self._worker_thread = threading.Thread(
                target=self._stream_worker,
                args=(self._current_path, max(0, lines_history)),
                name=f"RemoteLogStreamer-{self._current_path}",
                daemon=True,
            )
            self._worker_thread.start()

        self.stream_started.emit(self._current_path)
        return True

    def stop_streaming(self) -> None:
        """Stop streaming and close the remote channel."""
        with self._lock:
            if not self._is_streaming:
                return
            self._stop_streaming_internal(reason="user_stopped")

        if self._worker_thread and self._worker_thread.is_alive():
            if threading.current_thread() != self._worker_thread:
                self._worker_thread.join(timeout=1.0)

    def pause_streaming(self) -> None:
        """Temporarily stop forwarding received lines while keeping the connection."""
        with self._lock:
            if self._is_streaming and not self._is_paused:
                self._is_paused = True
                self._pause_event.set()

    def resume_streaming(self) -> None:
        """Resume forwarding received lines."""
        with self._lock:
            if self._is_streaming and self._is_paused:
                self._is_paused = False
                self._pause_event.clear()

    def _stop_streaming_internal(self, reason: str = "stopped") -> None:
        """Internal helper to signal stop and close channels under lock."""
        self._stop_event.set()
        self._is_streaming = False
        self._is_paused = False

        channel = self._active_channel
        self._active_channel = None

        if channel is not None:
            try:
                channel.close()
            except Exception as exc:
                logger.debug("Error closing streaming channel: %s", exc)

        self.stream_stopped.emit(reason)

    def _stream_worker(self, remote_path: str, lines_history: int) -> None:
        """Background thread target that invokes remote tail and reads lines."""
        channel = None
        cmd = f"tail -n {lines_history} -f {shlex.quote(remote_path)}"

        try:
            client = self.ssh_manager.client if self.ssh_manager else None
            if client is None:
                raise RuntimeError("SSH client is not available.")

            transport = client.get_transport()
            if transport is None or not transport.is_active():
                raise RuntimeError("SSH transport is not active.")

            channel = transport.open_session()
            channel.settimeout(1.0)
            with self._lock:
                if self._stop_event.is_set():
                    channel.close()
                    return
                self._active_channel = channel

            channel.exec_command(cmd)

            buffer = ""
            while not self._stop_event.is_set():
                if channel.closed or (channel.exit_status_ready() and not channel.recv_ready()):
                    break

                try:
                    data = channel.recv(4096)
                    if not data:
                        if channel.exit_status_ready():
                            break
                        time.sleep(0.05)
                        continue

                    chunk = data.decode("utf-8", errors="replace")
                    buffer += chunk

                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        clean_line = line.rstrip("\r")
                        if not self._pause_event.is_set() and not self._stop_event.is_set():
                            self.line_received.emit(clean_line)

                except TimeoutError:
                    continue
                except Exception as read_exc:
                    if self._stop_event.is_set():
                        break
                    # Socket timeout on paramiko channels is socket.timeout
                    if "timed out" in str(read_exc).lower():
                        continue
                    raise

            # Flush remaining buffer on termination if any
            if buffer and not self._stop_event.is_set() and not self._pause_event.is_set():
                self.line_received.emit(buffer.rstrip("\r\n"))

        except Exception as exc:
            if not self._stop_event.is_set():
                err_msg = f"Log streaming error: {exc}"
                logger.error(err_msg, exc_info=True)
                self.stream_error.emit(err_msg)
                with self._lock:
                    self._stop_streaming_internal(reason="error")
                return

        finally:
            if channel is not None:
                try:
                    channel.close()
                except Exception:
                    pass
            with self._lock:
                if self._is_streaming and not self._stop_event.is_set():
                    self._is_streaming = False
                    self.stream_stopped.emit("completed")
