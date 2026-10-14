"""Local Jupyter Kernel execution engine using ZeroMQ and PySide6."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time
from typing import Any, Optional
import uuid

from ..core.signals import QObject, Signal, QThread
import zmq

from .kernel_spec import KernelSpec, get_kernel_spec
from .models import OutputData


def find_free_port() -> int:
    """Find and return an ephemeral free TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.setsockname = True
        return s.getsockname()[1]


def allocate_connection_ports(ip: str = "127.0.0.1") -> dict[str, int]:
    """Allocate 5 distinct free ports for Jupyter kernel channels."""
    ports: list[int] = []
    sockets: list[socket.socket] = []
    try:
        for _ in range(5):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind((ip, 0))
            sockets.append(s)
            ports.append(s.getsockname()[1])
    finally:
        for s in sockets:
            s.close()

    return {
        "shell_port": ports[0],
        "iopub_port": ports[1],
        "stdin_port": ports[2],
        "control_port": ports[3],
        "hb_port": ports[4],
    }


def create_connection_file(
    ports: dict[str, int],
    key: Optional[str] = None,
    ip: str = "127.0.0.1",
    signature_scheme: str = "hmac-sha256",
    transport: str = "tcp",
) -> tuple[dict[str, Any], Path]:
    """Generate temporary Jupyter connection file."""
    if key is None:
        key = str(uuid.uuid4())

    conn_info = {
        "ip": ip,
        "transport": transport,
        "control_port": ports["control_port"],
        "shell_port": ports["shell_port"],
        "stdin_port": ports["stdin_port"],
        "iopub_port": ports["iopub_port"],
        "hb_port": ports["hb_port"],
        "signature_scheme": signature_scheme,
        "key": key,
        "kernel_name": "python3",
    }

    import tempfile
    fd, path_str = tempfile.mkstemp(prefix="kernel-", suffix=".json")
    try:
        os.chmod(path_str, 0o600)
    except Exception:
        pass
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(conn_info, f, indent=2)

    return conn_info, Path(path_str)


def serialize_wire_msg(
    msg_type: str,
    content: dict[str, Any],
    key: str,
    session_id: str,
    parent_header: Optional[dict[str, Any]] = None,
    metadata: Optional[dict[str, Any]] = None,
    msg_id: Optional[str] = None,
) -> list[bytes]:
    """Serialize a message to Jupyter wire protocol multipart frames."""
    if msg_id is None:
        msg_id = str(uuid.uuid4())
    if parent_header is None:
        parent_header = {}
    if metadata is None:
        metadata = {}

    header = {
        "msg_id": msg_id,
        "msg_type": msg_type,
        "username": "hpc_studio",
        "session": session_id,
        "date": datetime.now(timezone.utc).isoformat(),
        "version": "5.3",
    }

    header_bytes = json.dumps(header).encode("utf-8")
    parent_bytes = json.dumps(parent_header).encode("utf-8")
    metadata_bytes = json.dumps(metadata).encode("utf-8")
    content_bytes = json.dumps(content).encode("utf-8")

    # Sign with HMAC-SHA256
    h = hmac.new(key.encode("utf-8"), digestmod=hashlib.sha256)
    h.update(header_bytes)
    h.update(parent_bytes)
    h.update(metadata_bytes)
    h.update(content_bytes)
    signature = h.hexdigest().encode("ascii")

    # Wire format: [b"<IDS|MSG>", signature, header, parent_header, metadata, content]
    return [b"<IDS|MSG>", signature, header_bytes, parent_bytes, metadata_bytes, content_bytes]


def deserialize_wire_msg(
    frames: list[bytes],
    key: Optional[str] = None,
) -> tuple[list[bytes], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Deserialize Jupyter wire protocol multipart frames into (idents, header, parent, metadata, content)."""
    idx = frames.index(b"<IDS|MSG>")
    idents = frames[:idx]
    # frames[idx] is delimiter
    sig_bytes = frames[idx + 1]
    header_bytes = frames[idx + 2]
    parent_bytes = frames[idx + 3]
    metadata_bytes = frames[idx + 4]
    content_bytes = frames[idx + 5]

    if key:
        if not sig_bytes:
            raise ValueError("HMAC signature verification failed: signature is missing on signed Jupyter message")
        h = hmac.new(key.encode("utf-8"), digestmod=hashlib.sha256)
        h.update(header_bytes)
        h.update(parent_bytes)
        h.update(metadata_bytes)
        h.update(content_bytes)
        expected_sig = h.hexdigest().encode("ascii")
        if not hmac.compare_digest(sig_bytes, expected_sig):
            raise ValueError("HMAC signature verification failed on Jupyter message")

    header = json.loads(header_bytes.decode("utf-8")) if header_bytes else {}
    parent = json.loads(parent_bytes.decode("utf-8")) if parent_bytes else {}
    metadata = json.loads(metadata_bytes.decode("utf-8")) if metadata_bytes else {}
    content = json.loads(content_bytes.decode("utf-8")) if content_bytes else {}

    return idents, header, parent, metadata, content


class LocalKernelManager(QObject):
    """Manages spawning, execution, messaging, and lifetime of a local Jupyter kernel."""

    status_changed = Signal(str)  # idle, busy, starting, dead, restarting
    output_received = Signal(str, object)  # cell_id: str, output: OutputData
    execution_completed = Signal(str, int)  # cell_id: str, execution_count: int
    error_occurred = Signal(str, str)  # error_name: str, error_value: str
    completion_received = Signal(str, list, int, int)  # cell_id: str, matches: list[str], cursor_start: int, cursor_end: int
    inspection_received = Signal(str, dict)  # cell_id: str, data: dict[str, Any]

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.session_id: str = str(uuid.uuid4())
        self.status: str = "dead"
        self.spec: Optional[KernelSpec] = None

        self._process: Optional[subprocess.Popen] = None
        self._conn_file: Optional[Path] = None
        self._conn_info: Optional[dict[str, Any]] = None

        # ZeroMQ context & sockets
        self._zmq_context: Optional[zmq.Context] = None
        self._shell_socket: Optional[zmq.Socket] = None
        self._iopub_socket: Optional[zmq.Socket] = None
        self._control_socket: Optional[zmq.Socket] = None
        self._hb_socket: Optional[zmq.Socket] = None

        # Tracking msg_id -> cell_id
        self._msg_to_cell: dict[str, str] = {}
        # Tracking msg_id -> (threading.Event, dict) for synchronous request/reply (complete, inspect)
        self._pending_replies: dict[str, tuple[threading.Event, dict[str, Any]]] = {}
        self._lock = threading.Lock()

        # Threads
        self._stop_event = threading.Event()
        self._iopub_thread: Optional[threading.Thread] = None
        self._shell_thread: Optional[threading.Thread] = None
        self._hb_thread: Optional[threading.Thread] = None

    def _set_status(self, new_status: str) -> None:
        if self.status != new_status:
            self.status = new_status
            self.status_changed.emit(new_status)

    def start(self, spec_name: str = "python3") -> bool:
        """Start a local kernel using the requested kernel spec."""
        if self._process is not None and self._process.poll() is None:
            # Kernel already running
            return True

        self._set_status("starting")
        spec = get_kernel_spec(spec_name)
        if not spec:
            self._set_status("dead")
            self.error_occurred.emit("KernelNotFound", f"Kernel spec '{spec_name}' could not be found.")
            return False

        self.spec = spec
        self._stop_event.clear()

        # 1. Allocate ports & generate connection file
        ports = allocate_connection_ports()
        conn_info, conn_file = create_connection_file(ports)
        self._conn_info = conn_info
        self._conn_file = conn_file

        # 2. Build command arguments
        conn_file_path = str(conn_file.resolve())
        cmd = [arg.replace("{connection_file}", conn_file_path) for arg in spec.argv]

        # Environment variables
        env = os.environ.copy()
        if spec.env:
            env.update(spec.env)
        # Ensure unbuffered python if python
        env["PYTHONUNBUFFERED"] = "1"

        # 3. Spawn kernel process
        try:
            self._process = subprocess.Popen(
                cmd,
                env=env,
                start_new_session=True,  # setsid for clean process group termination
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except Exception as e:
            self._set_status("dead")
            self.error_occurred.emit("LaunchError", str(e))
            self._cleanup_files()
            return False

        # 4. Initialize ZMQ context and sockets
        try:
            self._zmq_context = zmq.Context()

            # IOPub (SUB)
            self._iopub_socket = self._zmq_context.socket(zmq.SUB)
            self._iopub_socket.setsockopt(zmq.SUBSCRIBE, b"")
            self._iopub_socket.connect(f"tcp://127.0.0.1:{ports['iopub_port']}")

            # Shell (DEALER)
            self._shell_socket = self._zmq_context.socket(zmq.DEALER)
            self._shell_socket.connect(f"tcp://127.0.0.1:{ports['shell_port']}")

            # Control (DEALER)
            self._control_socket = self._zmq_context.socket(zmq.DEALER)
            self._control_socket.connect(f"tcp://127.0.0.1:{ports['control_port']}")

            # Heartbeat (REQ)
            self._hb_socket = self._zmq_context.socket(zmq.REQ)
            self._hb_socket.connect(f"tcp://127.0.0.1:{ports['hb_port']}")
        except Exception as e:
            self._set_status("dead")
            self.error_occurred.emit("ZMQError", str(e))
            self.shutdown()
            return False

        # 5. Start listener threads
        self._iopub_thread = threading.Thread(target=self._iopub_loop, daemon=True, name="IOPubListener")
        self._iopub_thread.start()

        self._shell_thread = threading.Thread(target=self._shell_loop, daemon=True, name="ShellListener")
        self._shell_thread.start()

        self._hb_thread = threading.Thread(target=self._heartbeat_loop, daemon=True, name="HeartbeatChecker")
        self._hb_thread.start()

        # Send kernel_info_request to verify readiness
        self._send_kernel_info_request()

        self._set_status("idle")
        return True

    def _send_kernel_info_request(self) -> None:
        """Send kernel_info_request over shell socket."""
        if not self._shell_socket or not self._conn_info:
            return
        frames = serialize_wire_msg(
            msg_type="kernel_info_request",
            content={},
            key=self._conn_info["key"],
            session_id=self.session_id,
        )
        try:
            with self._lock:
                self._shell_socket.send_multipart(frames)
        except Exception:
            pass

    def execute(self, code: str, cell_id: str) -> str:
        """Execute code in the kernel for the given cell_id. Returns msg_id."""
        if self._process is None or self._process.poll() is not None or not self._shell_socket:
            self.error_occurred.emit("KernelDead", "Cannot execute code because kernel is not running.")
            return ""

        msg_id = str(uuid.uuid4())
        with self._lock:
            self._msg_to_cell[msg_id] = cell_id

        content = {
            "code": code,
            "silent": False,
            "store_history": True,
            "user_expressions": {},
            "allow_stdin": False,
            "stop_on_error": True,
        }

        frames = serialize_wire_msg(
            msg_type="execute_request",
            content=content,
            key=self._conn_info["key"],
            session_id=self.session_id,
            msg_id=msg_id,
        )

        with self._lock:
            self._shell_socket.send_multipart(frames)

        self._set_status("busy")
        return msg_id

    def complete(self, code: str, cursor_pos: int, cell_id: str = "") -> dict:
        """Send complete_request over shell socket and return completion result dict."""
        if self._process is None or self._process.poll() is not None or not self._shell_socket or not self._conn_info:
            return {"status": "error", "matches": [], "cursor_start": cursor_pos, "cursor_end": cursor_pos, "metadata": {}}

        msg_id = str(uuid.uuid4())
        done_evt = threading.Event()
        result_box: dict[str, Any] = {}

        with self._lock:
            self._msg_to_cell[msg_id] = cell_id
            self._pending_replies[msg_id] = (done_evt, result_box)

        content = {
            "code": code,
            "cursor_pos": cursor_pos,
        }

        frames = serialize_wire_msg(
            msg_type="complete_request",
            content=content,
            key=self._conn_info["key"],
            session_id=self.session_id,
            msg_id=msg_id,
        )

        with self._lock:
            self._shell_socket.send_multipart(frames)

        # Wait synchronously up to 3 seconds for reply
        done_evt.wait(timeout=3.0)

        with self._lock:
            self._pending_replies.pop(msg_id, None)

        matches = result_box.get("matches", [])
        cursor_start = result_box.get("cursor_start", cursor_pos)
        cursor_end = result_box.get("cursor_end", cursor_pos)

        # Emit Qt signal
        self.completion_received.emit(cell_id, matches, cursor_start, cursor_end)

        return result_box

    def inspect(self, code: str, cursor_pos: int, detail_level: int = 0, cell_id: str = "") -> dict:
        """Send inspect_request over shell socket and return inspection result dict."""
        if self._process is None or self._process.poll() is not None or not self._shell_socket or not self._conn_info:
            return {"status": "error", "found": False, "data": {}, "metadata": {}}

        msg_id = str(uuid.uuid4())
        done_evt = threading.Event()
        result_box: dict[str, Any] = {}

        with self._lock:
            self._msg_to_cell[msg_id] = cell_id
            self._pending_replies[msg_id] = (done_evt, result_box)

        content = {
            "code": code,
            "cursor_pos": cursor_pos,
            "detail_level": detail_level,
        }

        frames = serialize_wire_msg(
            msg_type="inspect_request",
            content=content,
            key=self._conn_info["key"],
            session_id=self.session_id,
            msg_id=msg_id,
        )

        with self._lock:
            self._shell_socket.send_multipart(frames)

        # Wait synchronously up to 3 seconds for reply
        done_evt.wait(timeout=3.0)

        with self._lock:
            self._pending_replies.pop(msg_id, None)

        data = result_box.get("data", {})

        # Emit Qt signal
        self.inspection_received.emit(cell_id, data)

        return result_box

    def interrupt(self) -> None:
        """Interrupt current kernel execution via SIGINT or control socket."""
        if self._process and self._process.poll() is None:
            try:
                # Send SIGINT to process group
                os.killpg(os.getpgid(self._process.pid), signal.SIGINT)
            except Exception:
                try:
                    self._process.send_signal(signal.SIGINT)
                except Exception:
                    pass

        # Also attempt interrupt_request on control socket if supported
        if self._control_socket and self._conn_info:
            frames = serialize_wire_msg(
                msg_type="interrupt_request",
                content={},
                key=self._conn_info["key"],
                session_id=self.session_id,
            )
            try:
                with self._lock:
                    self._control_socket.send_multipart(frames)
            except Exception:
                pass

    def restart(self) -> bool:
        """Restart the running kernel."""
        self._set_status("restarting")
        spec_name = self.spec.name if self.spec else "python3"
        self.shutdown()
        # Brief pause to ensure OS frees ports
        time.sleep(0.2)
        return self.start(spec_name)

    def shutdown(self) -> None:
        """Gracefully shut down the kernel and cleanup resources."""
        self._stop_event.set()

        # Send shutdown_request over control socket if possible
        if self._control_socket and self._conn_info:
            try:
                frames = serialize_wire_msg(
                    msg_type="shutdown_request",
                    content={"restart": False},
                    key=self._conn_info["key"],
                    session_id=self.session_id,
                )
                with self._lock:
                    self._control_socket.send_multipart(frames)
            except Exception:
                pass

        # Terminate / Kill process
        if self._process is not None:
            try:
                if self._process.poll() is None:
                    try:
                        os.killpg(os.getpgid(self._process.pid), signal.SIGTERM)
                    except Exception:
                        self._process.terminate()

                    try:
                        self._process.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        try:
                            os.killpg(os.getpgid(self._process.pid), signal.SIGKILL)
                        except Exception:
                            self._process.kill()
                        self._process.wait(timeout=1.0)
            except Exception:
                pass
            finally:
                self._process = None

        # Close ZMQ sockets
        for sock in [self._shell_socket, self._iopub_socket, self._control_socket, self._hb_socket]:
            if sock is not None:
                try:
                    sock.close(linger=0)
                except Exception:
                    pass
        self._shell_socket = None
        self._iopub_socket = None
        self._control_socket = None
        self._hb_socket = None

        if self._zmq_context is not None:
            try:
                self._zmq_context.term()
            except Exception:
                pass
            self._zmq_context = None

        self._cleanup_files()
        self._set_status("dead")

    def _cleanup_files(self) -> None:
        """Remove temporary connection file."""
        if self._conn_file and self._conn_file.exists():
            try:
                self._conn_file.unlink()
            except Exception:
                pass
            self._conn_file = None
        self._conn_info = None

    def _iopub_loop(self) -> None:
        """Background thread reading and dispatching IOPub messages."""
        poller = zmq.Poller()
        if self._iopub_socket:
            poller.register(self._iopub_socket, zmq.POLLIN)

        while not self._stop_event.is_set():
            try:
                socks = dict(poller.poll(timeout=200))
                if self._iopub_socket in socks and socks[self._iopub_socket] == zmq.POLLIN:
                    frames = self._iopub_socket.recv_multipart(flags=zmq.NOBLOCK)
                    self._handle_iopub_msg(frames)
            except zmq.ZMQError:
                break
            except Exception:
                continue

    def _handle_iopub_msg(self, frames: list[bytes]) -> None:
        """Process a single IOPub message."""
        try:
            key = self._conn_info.get("key", "") if self._conn_info else None
            _, header, parent, metadata, content = deserialize_wire_msg(frames, key=key)
        except Exception:
            return

        msg_type = header.get("msg_type", "")
        parent_msg_id = parent.get("msg_id", "")

        with self._lock:
            cell_id = self._msg_to_cell.get(parent_msg_id, "")

        if msg_type == "status":
            execution_state = content.get("execution_state", "")
            if execution_state in ("busy", "idle"):
                self._set_status(execution_state)

        elif msg_type == "stream":
            name = content.get("name", "stdout")
            text = content.get("text", "")
            out = OutputData(output_type="stream", name=name, text=text)
            self.output_received.emit(cell_id, out)

        elif msg_type == "display_data":
            data = content.get("data", {})
            meta = content.get("metadata", {})
            out = OutputData(output_type="display_data", data=data, metadata=meta)
            self.output_received.emit(cell_id, out)

        elif msg_type == "execute_result":
            data = content.get("data", {})
            meta = content.get("metadata", {})
            exec_count = content.get("execution_count")
            out = OutputData(
                output_type="execute_result",
                data=data,
                metadata=meta,
                execution_count=exec_count,
            )
            self.output_received.emit(cell_id, out)

        elif msg_type == "error":
            ename = content.get("ename", "Error")
            evalue = content.get("evalue", "")
            traceback = content.get("traceback", [])
            out = OutputData(
                output_type="error",
                ename=ename,
                evalue=evalue,
                traceback=traceback,
            )
            self.output_received.emit(cell_id, out)
            self.error_occurred.emit(ename, evalue)

    def _shell_loop(self) -> None:
        """Background thread handling shell socket replies (e.g. execute_reply)."""
        poller = zmq.Poller()
        if self._shell_socket:
            poller.register(self._shell_socket, zmq.POLLIN)

        while not self._stop_event.is_set():
            try:
                socks = dict(poller.poll(timeout=200))
                if self._shell_socket in socks and socks[self._shell_socket] == zmq.POLLIN:
                    frames = self._shell_socket.recv_multipart(flags=zmq.NOBLOCK)
                    self._handle_shell_msg(frames)
            except zmq.ZMQError:
                break
            except Exception:
                continue

    def _handle_shell_msg(self, frames: list[bytes]) -> None:
        """Process shell reply message."""
        try:
            key = self._conn_info.get("key", "") if self._conn_info else None
            _, header, parent, metadata, content = deserialize_wire_msg(frames, key=key)
        except Exception:
            return

        msg_type = header.get("msg_type", "")
        parent_msg_id = parent.get("msg_id", "")

        with self._lock:
            cell_id = self._msg_to_cell.get(parent_msg_id, "")

        if msg_type == "execute_reply":
            status = content.get("status", "ok")
            execution_count = content.get("execution_count", 0) or 0
            if cell_id:
                self.execution_completed.emit(cell_id, execution_count)

        elif msg_type == "complete_reply":
            with self._lock:
                if parent_msg_id in self._pending_replies:
                    evt, res_dict = self._pending_replies[parent_msg_id]
                    res_dict.update(content)
                    evt.set()

        elif msg_type == "inspect_reply":
            with self._lock:
                if parent_msg_id in self._pending_replies:
                    evt, res_dict = self._pending_replies[parent_msg_id]
                    res_dict.update(content)
                    evt.set()

    def _heartbeat_loop(self) -> None:
        """Periodic heartbeat ping to ensure kernel is responsive and alive."""
        poller = zmq.Poller()
        if self._hb_socket:
            poller.register(self._hb_socket, zmq.POLLIN)

        fail_count = 0
        while not self._stop_event.is_set():
            # Check process state directly first
            if self._process is not None and self._process.poll() is not None:
                # Subprocess exited
                if not self._stop_event.is_set():
                    self._set_status("dead")
                break

            time.sleep(1.0)
            if self._stop_event.is_set() or not self._hb_socket:
                break

            try:
                # Send ping
                ping_payload = b"ping"
                with self._lock:
                    if self._hb_socket:
                        self._hb_socket.send(ping_payload, flags=zmq.NOBLOCK)

                socks = dict(poller.poll(timeout=1000))
                if self._hb_socket in socks and socks[self._hb_socket] == zmq.POLLIN:
                    with self._lock:
                        if self._hb_socket:
                            reply = self._hb_socket.recv(flags=zmq.NOBLOCK)
                            if reply == ping_payload:
                                fail_count = 0
                else:
                    fail_count += 1
                    # If socket timed out without response, REQ socket is in invalid state; reset it
                    if fail_count >= 5:
                        if self._process and self._process.poll() is not None:
                            self._set_status("dead")
                            break
            except Exception:
                fail_count += 1
                if fail_count >= 5:
                    if self._process and self._process.poll() is not None:
                        self._set_status("dead")
                        break
