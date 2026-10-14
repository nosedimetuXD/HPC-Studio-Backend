"""Unit tests for LocalKernelManager and Jupyter protocol handling."""

from pathlib import Path
import time
from unittest.mock import MagicMock, patch

import pytest


from hpc_studio.notebook.kernel_spec import KernelSpec
from hpc_studio.notebook.local_kernel import (
    LocalKernelManager,
    allocate_connection_ports,
    create_connection_file,
    serialize_wire_msg,
    deserialize_wire_msg,
)
from hpc_studio.notebook.models import OutputData


def test_allocate_ports():
    ports = allocate_connection_ports()
    assert len(ports) == 5
    assert "shell_port" in ports
    assert "iopub_port" in ports
    assert "stdin_port" in ports
    assert "control_port" in ports
    assert "hb_port" in ports

    # Ensure all 5 ports are unique and valid positive integers
    unique_ports = set(ports.values())
    assert len(unique_ports) == 5
    for p in unique_ports:
        assert isinstance(p, int) and p > 1024


def test_create_connection_file():
    ports = allocate_connection_ports()
    conn_info, conn_file = create_connection_file(ports, key="secret-123")

    assert conn_file.exists()
    assert conn_info["key"] == "secret-123"
    assert conn_info["shell_port"] == ports["shell_port"]
    assert conn_info["signature_scheme"] == "hmac-sha256"

    # Clean up
    conn_file.unlink()
    assert not conn_file.exists()


def test_wire_serialization_roundtrip():
    key = "test-hmac-key-xyz"
    session_id = "session-abc-456"
    content = {"code": "print('hello')", "silent": False}

    frames = serialize_wire_msg(
        msg_type="execute_request",
        content=content,
        key=key,
        session_id=session_id,
        msg_id="msg-123",
    )

    # Roundtrip without key verification
    idents, header, parent, metadata, res_content = deserialize_wire_msg(frames)
    assert header["msg_type"] == "execute_request"
    assert header["msg_id"] == "msg-123"
    assert header["session"] == session_id
    assert res_content == content

    # Roundtrip with key verification
    idents, header, parent, metadata, res_content = deserialize_wire_msg(frames, key=key)
    assert header["msg_type"] == "execute_request"

    # Mismatched key raises ValueError
    with pytest.raises(ValueError, match="HMAC signature verification failed"):
        deserialize_wire_msg(frames, key="wrong-key")

    # Tampered content raises ValueError
    tampered_frames = list(frames)
    tampered_frames[5] = b'{"tampered": true}'
    with pytest.raises(ValueError, match="HMAC signature verification failed"):
        deserialize_wire_msg(tampered_frames, key=key)


def test_create_connection_file_permissions():
    """Verify connection files are created with 0600 permissions."""
    ports = allocate_connection_ports()
    conn_info, conn_file = create_connection_file(ports, key="secret-key")
    try:
        import stat
        file_mode = stat.S_IMODE(conn_file.stat().st_mode)
        assert file_mode == 0o600
    finally:
        if conn_file.exists():
            conn_file.unlink()


def test_local_kernel_lifecycle_mocked(qtbot):
    """Test LocalKernelManager state transitions, signals, and mock execution."""
    mgr = LocalKernelManager()

    statuses = []
    mgr.status_changed.connect(statuses.append)

    errors = []
    mgr.error_occurred.connect(lambda name, val: errors.append((name, val)))

    # Attempt start with invalid kernel name
    success = mgr.start("invalid_kernel_name_404")
    assert not success
    assert mgr.status == "dead"
    assert len(errors) == 1
    assert errors[0][0] == "KernelNotFound"

    # Mock successful process launch
    mock_spec = KernelSpec(
        name="mock_py",
        display_name="Mock Python",
        language="python",
        argv=["mock_python", "-f", "{connection_file}"],
    )

    with patch("hpc_studio.notebook.local_kernel.get_kernel_spec", return_value=mock_spec), \
         patch("subprocess.Popen") as mock_popen, \
         patch("zmq.Context"):

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 99999
        mock_popen.return_value = mock_proc

        started = mgr.start("mock_py")
        assert started is True
        assert mgr.status == "idle"

        # Test execute call
        msg_id = mgr.execute("x = 1 + 1", cell_id="cell-42")
        assert msg_id != ""
        assert mgr.status == "busy"

        # Mock interrupt
        mgr.interrupt()

        # Mock shutdown
        mgr.shutdown()
        assert mgr.status == "dead"


def test_iopub_message_dispatch(qtbot):
    """Test handling of IOPub messages (stream, execute_result, error, status)."""
    mgr = LocalKernelManager()

    received_outputs = []
    mgr.output_received.connect(lambda cid, out: received_outputs.append((cid, out)))

    completed = []
    mgr.execution_completed.connect(lambda cid, count: completed.append((cid, count)))

    errors = []
    mgr.error_occurred.connect(lambda n, v: errors.append((n, v)))

    # Set internal mapping for msg_id -> cell_id
    mgr._msg_to_cell["parent-msg-1"] = "cell-1"
    mgr._conn_info = {"key": "test"}

    # 1. Test stream output
    stream_frames = serialize_wire_msg(
        msg_type="stream",
        content={"name": "stdout", "text": "Hello, world!\n"},
        key="test",
        session_id="session1",
        parent_header={"msg_id": "parent-msg-1"},
    )
    mgr._handle_iopub_msg(stream_frames)

    assert len(received_outputs) == 1
    cell_id, out = received_outputs[0]
    assert cell_id == "cell-1"
    assert out.output_type == "stream"
    assert out.name == "stdout"
    assert out.text == "Hello, world!\n"

    # 2. Test execute_result
    result_frames = serialize_wire_msg(
        msg_type="execute_result",
        content={"execution_count": 5, "data": {"text/plain": "42"}, "metadata": {}},
        key="test",
        session_id="session1",
        parent_header={"msg_id": "parent-msg-1"},
    )
    mgr._handle_iopub_msg(result_frames)

    assert len(received_outputs) == 2
    _, out_res = received_outputs[1]
    assert out_res.output_type == "execute_result"
    assert out_res.execution_count == 5
    assert out_res.data["text/plain"] == "42"

    # 3. Test error output
    error_frames = serialize_wire_msg(
        msg_type="error",
        content={"ename": "ZeroDivisionError", "evalue": "division by zero", "traceback": ["tb1", "tb2"]},
        key="test",
        session_id="session1",
        parent_header={"msg_id": "parent-msg-1"},
    )
    mgr._handle_iopub_msg(error_frames)

    assert len(received_outputs) == 3
    _, out_err = received_outputs[2]
    assert out_err.output_type == "error"
    assert out_err.ename == "ZeroDivisionError"
    assert len(errors) == 1
    assert errors[0][0] == "ZeroDivisionError"

    # 4. Test status changes
    status_idle_frames = serialize_wire_msg(
        msg_type="status",
        content={"execution_state": "idle"},
        key="test",
        session_id="session1",
    )
    mgr._handle_iopub_msg(status_idle_frames)
    assert mgr.status == "idle"

    # 5. Test execute_reply via shell handler
    shell_reply_frames = serialize_wire_msg(
        msg_type="execute_reply",
        content={"status": "ok", "execution_count": 5},
        key="test",
        session_id="session1",
        parent_header={"msg_id": "parent-msg-1"},
    )
    mgr._handle_shell_msg(shell_reply_frames)
    assert len(completed) == 1
    assert completed[0] == ("cell-1", 5)


def test_real_python3_kernel_execution(qtbot):
    """Test actual spawning and execution of Python code using local ipykernel."""
    mgr = LocalKernelManager()

    outputs: list[tuple[str, OutputData]] = []
    mgr.output_received.connect(lambda cid, out: outputs.append((cid, out)))

    completed: list[tuple[str, int]] = []
    mgr.execution_completed.connect(lambda cid, count: completed.append((cid, count)))

    status_history: list[str] = []
    mgr.status_changed.connect(status_history.append)

    # Start the kernel
    ok = mgr.start("python3")
    assert ok is True

    # Give the kernel a brief moment to initialize
    time.sleep(0.5)

    # Execute a simple calculation & print
    code = "x = 10 * 3\nprint(f'Computed {x}')\nx"
    cell_id = "test-cell-001"
    msg_id = mgr.execute(code, cell_id=cell_id)
    assert msg_id != ""

    # Wait for execution completed signal or timeout
    start_wait = time.time()
    while not completed and (time.time() - start_wait < 8.0):
        qtbot.wait(100)

    assert len(completed) >= 1
    assert completed[0][0] == cell_id
    assert completed[0][1] >= 1

    # Verify stream output received
    stream_outs = [out for cid, out in outputs if out.output_type == "stream"]
    assert any("Computed 30" in (s.text or "") for s in stream_outs)

    # Verify execute_result received
    exec_results = [out for cid, out in outputs if out.output_type == "execute_result"]
    assert any("30" in str(r.data.get("text/plain", "")) for r in exec_results)

    # Clean shutdown
    mgr.shutdown()
    assert mgr.status == "dead"
