"""Unit tests for kernel intellisense (completion and inspection) in Local and Remote Kernel Managers."""

from pathlib import Path
import threading
import time
from unittest.mock import MagicMock, patch

import pytest


from hpc_studio.notebook.kernel_spec import KernelSpec
from hpc_studio.notebook.local_kernel import LocalKernelManager, serialize_wire_msg
from hpc_studio.notebook.remote_kernel import RemoteKernelManager
from hpc_studio.ssh.client import ConnectionState, SSHClientManager


def test_local_kernel_complete_mocked(qtbot):
    """Test LocalKernelManager complete request sending and reply handling."""
    mgr = LocalKernelManager()
    mgr._conn_info = {"key": "test-key"}
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mgr._process = mock_proc

    mock_shell = MagicMock()
    mgr._shell_socket = mock_shell

    received_signals = []
    mgr.completion_received.connect(
        lambda cell_id, matches, c_start, c_end: received_signals.append((cell_id, matches, c_start, c_end))
    )

    # In a background thread or hook, simulate kernel replying with complete_reply
    def fake_send(frames):
        # Decode frames to get msg_id
        from hpc_studio.notebook.local_kernel import deserialize_wire_msg
        _, header, _, _, _ = deserialize_wire_msg(frames)
        parent_msg_id = header["msg_id"]

        reply_content = {
            "status": "ok",
            "matches": ["numpy", "numbers"],
            "cursor_start": 3,
            "cursor_end": 5,
            "metadata": {},
        }
        reply_frames = serialize_wire_msg(
            msg_type="complete_reply",
            content=reply_content,
            key="test-key",
            session_id=mgr.session_id,
            parent_header={"msg_id": parent_msg_id},
        )
        # Deliver in a thread after short delay
        def deliver():
            time.sleep(0.05)
            mgr._handle_shell_msg(reply_frames)

        t = threading.Thread(target=deliver)
        t.start()

    mock_shell.send_multipart.side_effect = fake_send

    res = mgr.complete("import num", cursor_pos=10, cell_id="cell-42")

    assert res["status"] == "ok"
    assert res["matches"] == ["numpy", "numbers"]
    assert res["cursor_start"] == 3
    assert res["cursor_end"] == 5

    # Check signal emission
    assert len(received_signals) == 1
    assert received_signals[0] == ("cell-42", ["numpy", "numbers"], 3, 5)


def test_local_kernel_inspect_mocked(qtbot):
    """Test LocalKernelManager inspect request sending and reply handling."""
    mgr = LocalKernelManager()
    mgr._conn_info = {"key": "test-key"}
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mgr._process = mock_proc

    mock_shell = MagicMock()
    mgr._shell_socket = mock_shell

    received_signals = []
    mgr.inspection_received.connect(lambda cell_id, data: received_signals.append((cell_id, data)))

    def fake_send(frames):
        from hpc_studio.notebook.local_kernel import deserialize_wire_msg
        _, header, _, _, _ = deserialize_wire_msg(frames)
        parent_msg_id = header["msg_id"]

        reply_content = {
            "status": "ok",
            "found": True,
            "data": {"text/plain": "Signature: print(*args)\nDocstring: Prints values to stream."},
            "metadata": {},
        }
        reply_frames = serialize_wire_msg(
            msg_type="inspect_reply",
            content=reply_content,
            key="test-key",
            session_id=mgr.session_id,
            parent_header={"msg_id": parent_msg_id},
        )
        def deliver():
            time.sleep(0.05)
            mgr._handle_shell_msg(reply_frames)

        t = threading.Thread(target=deliver)
        t.start()

    mock_shell.send_multipart.side_effect = fake_send

    res = mgr.inspect("print", cursor_pos=5, cell_id="cell-99")

    assert res["status"] == "ok"
    assert res["found"] is True
    assert "Docstring" in res["data"]["text/plain"]

    assert len(received_signals) == 1
    assert received_signals[0][0] == "cell-99"
    assert "Signature" in received_signals[0][1]["text/plain"]


def test_remote_kernel_complete_and_inspect_mocked(qtbot):
    """Test RemoteKernelManager complete and inspect requests and signals."""
    mock_ssh = MagicMock(spec=SSHClientManager)
    mock_ssh.is_connected = True

    mgr = RemoteKernelManager(ssh_manager=mock_ssh)
    mgr.status = "idle"
    mgr.remote_conn_info = {"key": "remote-secret"}

    mock_shell = MagicMock()
    mgr._shell_socket = mock_shell

    completion_sigs = []
    inspection_sigs = []
    mgr.completion_received.connect(
        lambda cell_id, matches, c_start, c_end: completion_sigs.append((cell_id, matches, c_start, c_end))
    )
    mgr.inspection_received.connect(lambda cell_id, data: inspection_sigs.append((cell_id, data)))

    def fake_send(frames):
        from hpc_studio.notebook.local_kernel import deserialize_wire_msg
        _, header, _, _, content = deserialize_wire_msg(frames)
        msg_type = header["msg_type"]
        parent_msg_id = header["msg_id"]

        if msg_type == "complete_request":
            reply_content = {
                "status": "ok",
                "matches": ["scipy", "scikit-learn"],
                "cursor_start": 2,
                "cursor_end": 4,
                "metadata": {},
            }
            reply_type = "complete_reply"
        else:
            reply_content = {
                "status": "ok",
                "found": True,
                "data": {"text/plain": "Docstring for remote function"},
                "metadata": {},
            }
            reply_type = "inspect_reply"

        reply_frames = serialize_wire_msg(
            msg_type=reply_type,
            content=reply_content,
            key="remote-secret",
            session_id=mgr.session_id,
            parent_header={"msg_id": parent_msg_id},
        )
        def deliver():
            time.sleep(0.05)
            mgr._handle_shell_msg(reply_frames)

        t = threading.Thread(target=deliver)
        t.start()

    mock_shell.send_multipart.side_effect = fake_send

    # 1. Test complete
    comp_res = mgr.complete("sci", cursor_pos=3, cell_id="rem-cell-1")
    assert comp_res["status"] == "ok"
    assert comp_res["matches"] == ["scipy", "scikit-learn"]
    assert len(completion_sigs) == 1
    assert completion_sigs[0] == ("rem-cell-1", ["scipy", "scikit-learn"], 2, 4)

    # 2. Test inspect
    insp_res = mgr.inspect("scipy.optimize", cursor_pos=14, cell_id="rem-cell-2")
    assert insp_res["status"] == "ok"
    assert insp_res["found"] is True
    assert len(inspection_sigs) == 1
    assert inspection_sigs[0][0] == "rem-cell-2"
    assert "Docstring for remote function" in inspection_sigs[0][1]["text/plain"]


@pytest.mark.skipif(
    not any(Path(p).exists() for p in ["/home/nosedimetuxd/.cache/hpc_studio_venv/bin/python", "/usr/bin/python3"]),
    reason="Python executable not found",
)
def test_real_python3_kernel_complete_and_inspect(qtbot):
    """Test actual LocalKernelManager complete and inspect requests against real python3 ipykernel."""
    mgr = LocalKernelManager()
    ok = mgr.start("python3")
    assert ok is True

    # Brief delay for kernel socket initialization
    time.sleep(0.5)

    try:
        # Pre-execute import
        mgr.execute("import math", cell_id="c0")
        time.sleep(0.5)

        # 1. Test real autocompletion on math.sq -> math.sqrt
        comp_res = mgr.complete("math.sq", cursor_pos=7, cell_id="c1")
        assert comp_res["status"] == "ok"
        assert "sqrt" in comp_res["matches"] or any("sqrt" in m for m in comp_res["matches"])

        # 2. Test real inspection on math.sqrt
        insp_res = mgr.inspect("math.sqrt", cursor_pos=9, cell_id="c2")
        assert insp_res["status"] == "ok"
        assert insp_res.get("found", False) is True
        data = insp_res.get("data", {})
        assert "text/plain" in data
        assert "sqrt" in data["text/plain"] or "square root" in data["text/plain"].lower()
    finally:
        mgr.shutdown()
