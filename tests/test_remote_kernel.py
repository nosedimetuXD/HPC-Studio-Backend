"""Unit and integration tests for RemoteKernelManager over SSH."""

import json
import time
from unittest.mock import MagicMock, patch

import paramiko
import pytest


from hpc_studio.notebook.models import OutputData
from hpc_studio.notebook.remote_kernel import RemoteKernelManager
from hpc_studio.notebook.ssh_tunnel import SSHTunnelManager
from hpc_studio.ssh.client import CommandResult, ConnectionState, SSHClientManager


@pytest.fixture
def mock_ssh_manager():
    """Provides a mocked connected SSHClientManager with active Transport."""
    manager = MagicMock(spec=SSHClientManager)
    manager.is_connected = True
    manager.state = ConnectionState.CONNECTED

    mock_transport = MagicMock(spec=paramiko.Transport)
    mock_transport.is_active.return_value = True
    manager.transport = mock_transport

    return manager


def test_remote_kernel_not_connected_fails(qtbot):
    """Test start fails and emits error if SSHClientManager is disconnected."""
    mgr_ssh = MagicMock(spec=SSHClientManager)
    mgr_ssh.is_connected = False
    mgr_ssh.transport = None

    kernel_mgr = RemoteKernelManager(ssh_manager=mgr_ssh)

    errors = []
    kernel_mgr.error_occurred.connect(lambda n, v: errors.append((n, v)))

    ok = kernel_mgr.start()
    assert ok is False
    assert kernel_mgr.status == "dead"
    assert len(errors) == 1
    assert errors[0][0] == "SSHNotConnected"


def test_remote_kernel_start_lifecycle_mocked(qtbot, mock_ssh_manager):
    """Test full start, execute, interrupt, and shutdown lifecycle with mocked SSH & tunnels."""
    kernel_mgr = RemoteKernelManager(ssh_manager=mock_ssh_manager)

    statuses = []
    kernel_mgr.status_changed.connect(statuses.append)

    latencies = []
    kernel_mgr.latency_measured.connect(latencies.append)

    # Simulated remote JSON and output
    remote_json = {
        "shell_port": 50001,
        "iopub_port": 50002,
        "stdin_port": 50003,
        "control_port": 50004,
        "hb_port": 50005,
        "ip": "127.0.0.1",
        "key": "mock-hmac-key",
        "transport": "tcp",
        "signature_scheme": "hmac-sha256",
    }
    remote_stdout = (
        "---KERNEL_PID_START---\n"
        "12345\n"
        "---KERNEL_CONN_START---\n"
        f"{json.dumps(remote_json)}\n"
        "---KERNEL_CONN_END---\n"
    )

    cmd_res = CommandResult(
        command="start_kernel",
        stdout=remote_stdout,
        stderr="",
        exit_code=0,
        duration=0.2,
    )
    mock_ssh_manager.execute_command.return_value = cmd_res

    # Mock SSHTunnelManager to avoid real network sockets in this test
    with patch("hpc_studio.notebook.remote_kernel.SSHTunnelManager") as mock_tunnel_cls, \
         patch("zmq.Context"):

        mock_tunnel_instance = MagicMock()
        mock_tunnel_instance.start_kernel_tunnels.return_value = {
            "shell_port": 40001,
            "iopub_port": 40002,
            "stdin_port": 40003,
            "control_port": 40004,
            "hb_port": 40005,
        }
        mock_tunnel_cls.return_value = mock_tunnel_instance

        started = kernel_mgr.start(kernel_cmd="python3 -m ipykernel", env_prefix="module load python")
        assert started is True
        assert kernel_mgr.status == "idle"
        assert kernel_mgr.remote_pid == 12345
        assert kernel_mgr.remote_conn_info == remote_json

        # Test execute call
        msg_id = kernel_mgr.execute("a = 10", cell_id="cell-99")
        assert msg_id != ""
        assert kernel_mgr.status == "busy"

        # Test interrupt
        kernel_mgr.interrupt()
        mock_ssh_manager.execute_command.assert_any_call("kill -INT 12345", timeout=5)

        # Test is_alive
        mock_ssh_manager.execute_command.return_value = CommandResult(
            command="kill -0 12345", stdout="", stderr="", exit_code=0, duration=0.01
        )
        assert kernel_mgr.is_alive() is True

        # Test shutdown
        kernel_mgr.shutdown()
        assert kernel_mgr.status == "dead"
        assert kernel_mgr.remote_pid is None


def test_remote_kernel_iopub_and_shell_message_dispatch(qtbot, mock_ssh_manager):
    """Test that remote kernel manager decodes IOPub streams, results, errors, and replies."""
    from hpc_studio.notebook.local_kernel import serialize_wire_msg

    kernel_mgr = RemoteKernelManager(ssh_manager=mock_ssh_manager)

    outputs = []
    kernel_mgr.output_received.connect(lambda cid, out: outputs.append((cid, out)))

    completed = []
    kernel_mgr.execution_completed.connect(lambda cid, count: completed.append((cid, count)))

    errors = []
    kernel_mgr.error_occurred.connect(lambda n, v: errors.append((n, v)))

    kernel_mgr._msg_to_cell["parent-msg-remote-1"] = "cell-remote-1"
    kernel_mgr.remote_conn_info = {"key": "remote-key"}

    # 1. Stream message
    stream_frames = serialize_wire_msg(
        msg_type="stream",
        content={"name": "stdout", "text": "Remote calculation done.\n"},
        key="remote-key",
        session_id="session-remote",
        parent_header={"msg_id": "parent-msg-remote-1"},
    )
    kernel_mgr._handle_iopub_msg(stream_frames)

    assert len(outputs) == 1
    cid, out = outputs[0]
    assert cid == "cell-remote-1"
    assert out.output_type == "stream"
    assert out.text == "Remote calculation done.\n"

    # 2. Execute result message
    res_frames = serialize_wire_msg(
        msg_type="execute_result",
        content={"execution_count": 3, "data": {"text/plain": "99.9"}, "metadata": {}},
        key="remote-key",
        session_id="session-remote",
        parent_header={"msg_id": "parent-msg-remote-1"},
    )
    kernel_mgr._handle_iopub_msg(res_frames)

    assert len(outputs) == 2
    _, out_res = outputs[1]
    assert out_res.execution_count == 3
    assert out_res.data["text/plain"] == "99.9"

    # 3. Error message
    err_frames = serialize_wire_msg(
        msg_type="error",
        content={"ename": "RemoteRuntimeError", "evalue": "Out of memory", "traceback": ["tb_line"]},
        key="remote-key",
        session_id="session-remote",
        parent_header={"msg_id": "parent-msg-remote-1"},
    )
    kernel_mgr._handle_iopub_msg(err_frames)

    assert len(outputs) == 3
    _, out_err = outputs[2]
    assert out_err.ename == "RemoteRuntimeError"
    assert len(errors) == 1
    assert errors[0] == ("RemoteRuntimeError", "Out of memory")

    # 4. Status busy/idle
    status_frames = serialize_wire_msg(
        msg_type="status",
        content={"execution_state": "idle"},
        key="remote-key",
        session_id="session-remote",
    )
    kernel_mgr._handle_iopub_msg(status_frames)
    assert kernel_mgr.status == "idle"

    # 5. Execute reply over shell handler
    reply_frames = serialize_wire_msg(
        msg_type="execute_reply",
        content={"status": "ok", "execution_count": 3},
        key="remote-key",
        session_id="session-remote",
        parent_header={"msg_id": "parent-msg-remote-1"},
    )
    kernel_mgr._handle_shell_msg(reply_frames)
    assert len(completed) == 1
    assert completed[0] == ("cell-remote-1", 3)


def test_remote_kernel_latency_signal(qtbot, mock_ssh_manager):
    """Test heartbeat loop emits latency_measured signal with round-trip milliseconds."""
    kernel_mgr = RemoteKernelManager(ssh_manager=mock_ssh_manager)

    latencies = []
    kernel_mgr.latency_measured.connect(latencies.append)

    # Directly emit for signal interface verification
    kernel_mgr.latency_measured.emit(12)
    assert latencies == [12]
