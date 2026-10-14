"""Remote Jupyter Kernel execution engine over SSH with port forwarding and latency measurement."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
import shlex
import socket
import threading
import time
from typing import Any, Dict, List, Optional, Tuple, Union
import uuid

from ..core.signals import QObject, Signal
import zmq

from .local_kernel import deserialize_wire_msg, serialize_wire_msg
from .models import OutputData
from .ssh_tunnel import SSHTunnelManager
from ..ssh.client import ConnectionState, SSHClientManager

logger = logging.getLogger(__name__)


class RemoteKernelManager(QObject):
    """Manages starting, executing, and monitoring an ipykernel process on a remote SSH host."""

    status_changed = Signal(str)            # idle, busy, starting, dead, restarting, disconnected
    output_received = Signal(str, object)   # cell_id: str, output: OutputData
    execution_completed = Signal(str, int)  # cell_id: str, execution_count: int
    error_occurred = Signal(str, str)       # error_name: str, error_value: str
    latency_measured = Signal(int)          # round-trip ping latency in milliseconds
    connection_lost = Signal(str)           # reason: str
    completion_received = Signal(str, list, int, int)  # cell_id: str, matches: list[str], cursor_start: int, cursor_end: int
    inspection_received = Signal(str, dict)  # cell_id: str, data: dict[str, Any]

    def __init__(
        self,
        ssh_manager: Optional[SSHClientManager] = None,
        ssh_client_manager: Optional[SSHClientManager] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.ssh_manager: SSHClientManager = ssh_manager or ssh_client_manager or SSHClientManager()
        # Alias for compatibility
        self.ssh_client_manager = self.ssh_manager

        self.session_id: str = str(uuid.uuid4())
        self.status: str = "dead"
        self.host_name: str = ""
        self.kernel_name: str = "python3"
        self.env_setup: str = ""
        self.latency_ms: int = 0

        # Remote process tracking
        self.remote_pid: Optional[int] = None
        self.remote_conn_file: Optional[str] = None
        self.remote_conn_info: Optional[Dict[str, Any]] = None

        # SSH Tunnel manager
        self.tunnel_manager: Optional[SSHTunnelManager] = None
        self.local_ports: Optional[Dict[str, int]] = None

        # ZeroMQ context & sockets
        self._zmq_context: Optional[zmq.Context] = None
        self._shell_socket: Optional[zmq.Socket] = None
        self._iopub_socket: Optional[zmq.Socket] = None
        self._control_socket: Optional[zmq.Socket] = None
        self._hb_socket: Optional[zmq.Socket] = None

        # Tracking msg_id -> cell_id
        self._msg_to_cell: Dict[str, str] = {}
        # Tracking msg_id -> (threading.Event, dict) for synchronous request/reply (complete, inspect)
        self._pending_replies: Dict[str, Tuple[threading.Event, Dict[str, Any]]] = {}
        self._lock = threading.RLock()

        # Threads
        self._stop_event = threading.Event()
        self._iopub_thread: Optional[threading.Thread] = None
        self._shell_thread: Optional[threading.Thread] = None
        self._hb_thread: Optional[threading.Thread] = None

        # Remote execution options
        self.command_prefix: str = ""

    @property
    def _remote_conn_info(self) -> Optional[Dict[str, Any]]:
        return self.remote_conn_info

    @_remote_conn_info.setter
    def _remote_conn_info(self, val: Optional[Dict[str, Any]]) -> None:
        self.remote_conn_info = val

    @property
    def _local_ports(self) -> Optional[Dict[str, int]]:
        return self.local_ports

    @_local_ports.setter
    def _local_ports(self, val: Optional[Dict[str, int]]) -> None:
        self.local_ports = val

    def _set_status(self, new_status: str) -> None:
        if self.status != new_status:
            self.status = new_status
            self.status_changed.emit(new_status)

    def start(
        self,
        host_name: Optional[str] = None,
        kernel_cmd: str = "python3 -m ipykernel",
        kernel_name: Optional[str] = None,
        env_prefix: str = "",
        env_setup: Optional[str] = None,
        timeout: int = 20,
        ssh_params: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Launch ipykernel on remote host, extract connection info, tunnel ports, and connect ZMQ."""
        self._set_status("starting")
        self._stop_event.clear()

        if host_name:
            self.host_name = host_name
        if kernel_name:
            self.kernel_name = kernel_name
        self.command_prefix = (env_setup or env_prefix or "").strip()
        self.env_setup = self.command_prefix

        # 1. Ensure SSH connection is established
        if not self.ssh_manager.is_connected:
            if ssh_params:
                try:
                    self.ssh_manager.connect(**ssh_params)
                except Exception as exc:
                    self._set_status("dead")
                    self.error_occurred.emit("SSHConnectionError", f"Failed to connect SSH: {exc}")
                    return False
            elif getattr(self.ssh_manager, "config_parser", None) and host_name:
                try:
                    entry = self.ssh_manager.config_parser.get_host(host_name)
                    self.ssh_manager.connect(entry)
                except Exception as exc:
                    self._set_status("dead")
                    self.error_occurred.emit("SSHConnectionError", f"Failed to connect SSH: {exc}")
                    return False
            else:
                self._set_status("dead")
                self.error_occurred.emit("SSHNotConnected", "Cannot start remote kernel: SSH is not connected.")
                return False

        if self.status in ("busy", "idle") and self.remote_pid is not None and self.is_alive():
            return True

        # 2. Launch ipykernel remotely via SSH exec_command
        try:
            conn_info, pid, conn_file_path = self._launch_remote_kernel_process(
                kernel_cmd=kernel_cmd,
                env_prefix=self.command_prefix,
                timeout=timeout,
            )
            self.remote_conn_info = conn_info
            self.remote_pid = pid
            self.remote_conn_file = conn_file_path
        except Exception as e:
            logger.error("Failed to launch remote kernel process: %s", e)
            self._set_status("dead")
            self.error_occurred.emit("RemoteLaunchError", str(e))
            self.shutdown()
            return False

        # 3. Establish SSH direct-tcpip tunnels using SSHTunnelManager
        transport = self.ssh_manager.transport
        if transport is None or not transport.is_active():
            self._set_status("dead")
            self.error_occurred.emit("SSHTransportError", "SSH transport is not active.")
            self.shutdown()
            return False

        try:
            self.tunnel_manager = SSHTunnelManager(transport)
            self.local_ports = self.tunnel_manager.start_kernel_tunnels(self.remote_conn_info)
        except Exception as e:
            logger.error("Failed opening SSH tunnels for kernel: %s", e)
            self._set_status("dead")
            self.error_occurred.emit("TunnelError", str(e))
            self.shutdown()
            return False

        # 4. Connect local ZeroMQ sockets through local tunnel endpoints
        try:
            self._zmq_context = zmq.Context()

            # IOPub (SUB)
            self._iopub_socket = self._zmq_context.socket(zmq.SUB)
            self._iopub_socket.setsockopt(zmq.SUBSCRIBE, b"")
            self._iopub_socket.connect(f"tcp://127.0.0.1:{self.local_ports['iopub_port']}")

            # Shell (DEALER)
            self._shell_socket = self._zmq_context.socket(zmq.DEALER)
            self._shell_socket.connect(f"tcp://127.0.0.1:{self.local_ports['shell_port']}")

            # Control (DEALER)
            self._control_socket = self._zmq_context.socket(zmq.DEALER)
            self._control_socket.connect(f"tcp://127.0.0.1:{self.local_ports['control_port']}")

            # Heartbeat (REQ)
            self._hb_socket = self._zmq_context.socket(zmq.REQ)
            self._hb_socket.connect(f"tcp://127.0.0.1:{self.local_ports['hb_port']}")
        except Exception as e:
            logger.error("Failed connecting local ZMQ sockets: %s", e)
            self._set_status("dead")
            self.error_occurred.emit("ZMQError", str(e))
            self.shutdown()
            return False

        # 5. Start listener threads
        self._iopub_thread = threading.Thread(
            target=self._iopub_loop,
            daemon=True,
            name="RemoteIOPubListener",
        )
        self._iopub_thread.start()

        self._shell_thread = threading.Thread(
            target=self._shell_loop,
            daemon=True,
            name="RemoteShellListener",
        )
        self._shell_thread.start()

        self._hb_thread = threading.Thread(
            target=self._heartbeat_loop,
            daemon=True,
            name="RemoteHeartbeatChecker",
        )
        self._hb_thread.start()

        # Send kernel_info_request to verify readiness
        self._send_kernel_info_request()

        self._set_status("idle")
        return True

    def _launch_remote_kernel_process(
        self,
        kernel_cmd: str,
        env_prefix: str,
        timeout: int = 20,
    ) -> Tuple[Dict[str, Any], int, str]:
        """Start the remote ipykernel, write connection JSON, and retrieve its PID and parameters."""
        token = str(uuid.uuid4())[:8]
        remote_conn_file = f"~/.cache/hpc_studio/kernels/kernel-{token}.json"

        prefix = f"{env_prefix} && " if env_prefix else ""
        remote_script = (
            f'mkdir -p ~/.cache/hpc_studio/kernels && chmod 700 ~/.cache/hpc_studio/kernels && '
            f'{prefix}{kernel_cmd} --IPKernelApp.connection_file={remote_conn_file} --ip=127.0.0.1 > /dev/null 2>&1 & '
            f'KPID=$!; '
            f'for i in $(seq 1 50); do '
            f'  if [ -s {remote_conn_file} ]; then '
            f'    chmod 600 {remote_conn_file} 2>/dev/null; '
            f'    echo "---KERNEL_PID_START---"; '
            f'    echo "$KPID"; '
            f'    echo "---KERNEL_CONN_START---"; '
            f'    cat {remote_conn_file}; '
            f'    echo "---KERNEL_CONN_END---"; '
            f'    exit 0; '
            f'  fi; '
            f'  sleep 0.2; '
            f'done; '
            f'kill -9 $KPID 2>/dev/null; '
            f'echo "Failed to start kernel within timeout" >&2; '
            f'exit 1'
        )

        full_cmd = f"bash -c {shlex.quote(remote_script)}"
        result = self.ssh_manager.execute_command(full_cmd, timeout=timeout)
        if not result.success:
            err = result.stderr or result.stdout or "Command failed with exit code non-zero"
            raise RuntimeError(f"Remote kernel start error: {err}")

        stdout = result.stdout
        pid_match = re.search(r"---KERNEL_PID_START---\s*\n(\d+)", stdout)
        conn_match = re.search(r"---KERNEL_CONN_START---\s*\n(.*?)\n---KERNEL_CONN_END---", stdout, re.DOTALL)

        if not pid_match or not conn_match:
            # Fallback check if JSON exists anywhere in output
            json_search = re.search(r"\{[\s\S]*\"shell_port\"[\s\S]*\}", stdout)
            if json_search:
                conn_data = json.loads(json_search.group(0))
                pid = int(pid_match.group(1)) if pid_match else -1
                return conn_data, pid, remote_conn_file
            raise RuntimeError(f"Could not parse kernel connection info from remote output:\n{stdout}")

        pid = int(pid_match.group(1))
        conn_json_str = conn_match.group(1).strip()
        conn_data = json.loads(conn_json_str)

        return conn_data, pid, remote_conn_file

    def is_alive(self) -> bool:
        """Check if remote kernel process is currently alive via remote kill -0 PID."""
        if self.remote_pid is None or not self.ssh_manager or not self.ssh_manager.is_connected:
            return False
        try:
            res = self.ssh_manager.execute_command(f"kill -0 {self.remote_pid}", timeout=5)
            return res.exit_code == 0
        except Exception:
            return False

    def _send_kernel_info_request(self) -> None:
        """Send kernel_info_request over shell socket."""
        if not self._shell_socket or not self.remote_conn_info:
            return
        frames = serialize_wire_msg(
            msg_type="kernel_info_request",
            content={},
            key=self.remote_conn_info.get("key", ""),
            session_id=self.session_id,
        )
        try:
            with self._lock:
                self._shell_socket.send_multipart(frames)
        except Exception:
            pass

    def execute(self, code: str, cell_id: str) -> str:
        """Execute code in the remote kernel for the given cell_id. Returns msg_id."""
        if self.status in ("dead", "disconnected") or not self._shell_socket or not self.remote_conn_info:
            self.error_occurred.emit("KernelDead", "Cannot execute code because remote kernel is not running.")
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
            key=self.remote_conn_info.get("key", ""),
            session_id=self.session_id,
            msg_id=msg_id,
        )

        try:
            with self._lock:
                self._shell_socket.send_multipart(frames)
            self._set_status("busy")
            return msg_id
        except Exception as e:
            self._set_status("disconnected")
            self.connection_lost.emit(f"Failed to send execute_request: {e}")
            return ""

    def complete(self, code: str, cursor_pos: int, cell_id: str = "") -> dict:
        """Send complete_request over shell socket and return completion result dict."""
        if self.status in ("dead", "disconnected") or not self._shell_socket or not self.remote_conn_info:
            return {"status": "error", "matches": [], "cursor_start": cursor_pos, "cursor_end": cursor_pos, "metadata": {}}

        msg_id = str(uuid.uuid4())
        done_evt = threading.Event()
        result_box: Dict[str, Any] = {}

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
            key=self.remote_conn_info.get("key", ""),
            session_id=self.session_id,
            msg_id=msg_id,
        )

        try:
            with self._lock:
                self._shell_socket.send_multipart(frames)
        except Exception as e:
            with self._lock:
                self._pending_replies.pop(msg_id, None)
            self._set_status("disconnected")
            self.connection_lost.emit(f"Failed to send complete_request: {e}")
            return {"status": "error", "matches": [], "cursor_start": cursor_pos, "cursor_end": cursor_pos, "metadata": {}}

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
        if self.status in ("dead", "disconnected") or not self._shell_socket or not self.remote_conn_info:
            return {"status": "error", "found": False, "data": {}, "metadata": {}}

        msg_id = str(uuid.uuid4())
        done_evt = threading.Event()
        result_box: Dict[str, Any] = {}

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
            key=self.remote_conn_info.get("key", ""),
            session_id=self.session_id,
            msg_id=msg_id,
        )

        try:
            with self._lock:
                self._shell_socket.send_multipart(frames)
        except Exception as e:
            with self._lock:
                self._pending_replies.pop(msg_id, None)
            self._set_status("disconnected")
            self.connection_lost.emit(f"Failed to send inspect_request: {e}")
            return {"status": "error", "found": False, "data": {}, "metadata": {}}

        # Wait synchronously up to 3 seconds for reply
        done_evt.wait(timeout=3.0)

        with self._lock:
            self._pending_replies.pop(msg_id, None)

        data = result_box.get("data", {})

        # Emit Qt signal
        self.inspection_received.emit(cell_id, data)

        return result_box

    def interrupt(self) -> None:
        """Interrupt current kernel execution on remote host."""
        # 1. Send interrupt_request on control socket
        if self._control_socket and self.remote_conn_info:
            frames = serialize_wire_msg(
                msg_type="interrupt_request",
                content={},
                key=self.remote_conn_info.get("key", ""),
                session_id=self.session_id,
            )
            try:
                with self._lock:
                    self._control_socket.send_multipart(frames)
            except Exception:
                pass

        # 2. Send SIGINT to remote PID via SSH
        if self.remote_pid and self.ssh_manager and self.ssh_manager.is_connected:
            try:
                self.ssh_manager.execute_command(f"kill -INT {self.remote_pid}", timeout=5)
            except Exception:
                pass

    def restart(self) -> bool:
        """Restart the remote kernel."""
        self._set_status("restarting")
        self.shutdown()
        time.sleep(0.3)
        return self.start(
            host_name=self.host_name,
            kernel_cmd=f"python3 -m {self.kernel_name}",
            env_prefix=self.command_prefix,
        )

    def shutdown(self) -> None:
        """Gracefully shut down the remote kernel and tear down tunnels and sockets."""
        self._stop_event.set()

        # 1. Send shutdown_request over control socket if possible
        if self._control_socket and self.remote_conn_info:
            try:
                frames = serialize_wire_msg(
                    msg_type="shutdown_request",
                    content={"restart": False},
                    key=self.remote_conn_info.get("key", ""),
                    session_id=self.session_id,
                )
                with self._lock:
                    self._control_socket.send_multipart(frames)
                time.sleep(0.1)
            except Exception:
                pass

        # 2. Terminate / Kill remote process via SSH if still alive
        if self.remote_pid is not None and self.ssh_manager and self.ssh_manager.is_connected:
            try:
                self.ssh_manager.execute_command(
                    f"kill -TERM {self.remote_pid} 2>/dev/null || true",
                    timeout=5,
                )
                time.sleep(0.2)
                self.ssh_manager.execute_command(
                    f"kill -9 {self.remote_pid} 2>/dev/null || true",
                    timeout=5,
                )
            except Exception:
                pass

        # Clean up remote connection file if present
        if self.remote_conn_file and self.ssh_manager and self.ssh_manager.is_connected:
            try:
                rm_target = shlex.quote(str(self.remote_conn_file))
                self.ssh_manager.execute_command(
                    f"rm -f {rm_target} 2>/dev/null || true",
                    timeout=5,
                )
            except Exception:
                pass

        self.remote_pid = None
        self.remote_conn_file = None
        self.remote_conn_info = None

        # 3. Close local ZMQ sockets
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

        # 4. Tear down SSH tunnels
        if self.tunnel_manager is not None:
            try:
                self.tunnel_manager.close()
            except Exception:
                pass
            self.tunnel_manager = None
        self.local_ports = None

        self._set_status("dead")

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

    def _handle_iopub_msg(self, frames: List[bytes]) -> None:
        """Process a single IOPub message."""
        try:
            key = self.remote_conn_info.get("key", "") if self.remote_conn_info else None
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

    def _handle_shell_msg(self, frames: List[bytes]) -> None:
        """Process shell reply message."""
        try:
            key = self.remote_conn_info.get("key", "") if self.remote_conn_info else None
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
        """Periodic heartbeat ping measuring round-trip latency and detecting dead remote kernels."""
        poller = zmq.Poller()
        if self._hb_socket:
            poller.register(self._hb_socket, zmq.POLLIN)

        fail_count = 0
        while not self._stop_event.is_set():
            time.sleep(1.0)
            if self._stop_event.is_set() or not self._hb_socket:
                break

            if not self.ssh_manager.is_connected:
                self._set_status("disconnected")
                self.connection_lost.emit("SSH connection dropped")
                break

            ping_payload = b"ping"
            t0 = time.monotonic()
            try:
                with self._lock:
                    if self._hb_socket:
                        self._hb_socket.send(ping_payload, flags=zmq.NOBLOCK)

                socks = dict(poller.poll(timeout=1500))
                if self._hb_socket in socks and socks[self._hb_socket] == zmq.POLLIN:
                    with self._lock:
                        if self._hb_socket:
                            reply = self._hb_socket.recv(flags=zmq.NOBLOCK)
                            if reply == ping_payload:
                                latency_ms = int((time.monotonic() - t0) * 1000)
                                self.latency_ms = latency_ms
                                fail_count = 0
                                self.latency_measured.emit(latency_ms)
                else:
                    fail_count += 1
                    if fail_count >= 5:
                        if not self.is_alive():
                            self._set_status("dead")
                            self.connection_lost.emit("Remote kernel heartbeat timeout")
                            break
            except Exception:
                fail_count += 1
                if fail_count >= 5:
                    if not self.is_alive():
                        self._set_status("dead")
                        self.connection_lost.emit("Heartbeat exception failure")
                        break
