"""Unit tests for TerminalBackend, LocalPTYBackend, and SSHPtyBackend.

Sprint 1.4 test suite for HPC Studio Linux.
"""

from __future__ import annotations

import os
import socket
import time
from unittest.mock import MagicMock, patch

import pytest

from hpc_studio.terminal import (
    LocalPTYBackend,
    SSHPtyBackend,
    TerminalBackend,
)




# ==============================================================================
# Tests for LocalPTYBackend
# ==============================================================================


def test_local_pty_lifecycle_echo(qapp):
    """Verify LocalPTYBackend starts, captures output, and signals process completion."""
    received_data = []
    finished_codes = []

    backend = LocalPTYBackend(command=["/bin/echo", "HPC_STUDIO_PTY_OK"])
    backend.data_received.connect(lambda d: received_data.append(d))
    backend.finished.connect(lambda c: finished_codes.append(c))

    assert not backend.is_alive()
    backend.start(cols=80, rows=24)

    # Allow event loop and background thread to process process output
    deadline = time.time() + 2.0
    while time.time() < deadline:
        qapp.processEvents()
        if finished_codes:
            break
        time.sleep(0.02)

    backend.close()

    assert not backend.is_alive()
    output = b"".join(received_data)
    assert b"HPC_STUDIO_PTY_OK" in output
    assert finished_codes == [0]


def test_local_pty_interactive_write_and_eof(qapp):
    """Verify writing stdin bytes to a running process and clean exit on EOF."""
    received_data = []
    finished_codes = []

    backend = LocalPTYBackend(command=["cat"])
    backend.data_received.connect(lambda d: received_data.append(d))
    backend.finished.connect(lambda c: finished_codes.append(c))

    backend.start(cols=80, rows=24)
    assert backend.is_alive()

    # Write text to cat, then send EOF (Ctrl+D / \x04)
    backend.write(b"interactivity_test_line\n")
    time.sleep(0.05)
    backend.write(b"\x04")

    deadline = time.time() + 2.0
    while time.time() < deadline:
        qapp.processEvents()
        if finished_codes:
            break
        time.sleep(0.02)

    backend.close()

    output = b"".join(received_data)
    assert b"interactivity_test_line" in output
    assert finished_codes == [0]


def test_local_pty_write_str_helper(qapp):
    """Verify write_str helper writes encoded string."""
    backend = LocalPTYBackend(command=["cat"])
    backend.start(cols=80, rows=24)

    with patch.object(backend, "write") as mock_write:
        backend.write_str("echo $SLURM_JOB_ID\n")
        mock_write.assert_called_once_with(b"echo $SLURM_JOB_ID\n")

    backend.close()


def test_local_pty_resize(qapp):
    """Verify terminal geometry resize updates dimensions and triggers TIOCSWINSZ."""
    backend = LocalPTYBackend(command=["cat"])
    backend.start(cols=80, rows=24)
    assert backend.cols == 80
    assert backend.rows == 24

    backend.resize(cols=132, rows=43)
    assert backend.cols == 132
    assert backend.rows == 43

    backend.close()


def test_local_pty_title_changed_signal(qapp):
    """Verify OSC 0 title sequence in stream triggers title_changed Qt signal."""
    titles = []
    # Bash script printing OSC 0 escape sequence
    backend = LocalPTYBackend(command=["/bin/bash", "-c", 'printf "\033]0;HPC_Cluster_Node_4\007"'])
    backend.title_changed.connect(lambda t: titles.append(t))

    backend.start(cols=80, rows=24)

    deadline = time.time() + 2.0
    while time.time() < deadline:
        qapp.processEvents()
        if titles:
            break
        time.sleep(0.02)

    backend.close()
    assert "HPC_Cluster_Node_4" in titles


def test_local_pty_double_start_error():
    """Verify starting an already running session raises RuntimeError."""
    backend = LocalPTYBackend(command=["cat"])
    backend.start()
    try:
        with pytest.raises(RuntimeError):
            backend.start()
    finally:
        backend.close()


def test_local_pty_write_when_closed_error():
    """Verify writing to an inactive session raises RuntimeError."""
    backend = LocalPTYBackend(command=["cat"])
    with pytest.raises(RuntimeError):
        backend.write(b"data")


def test_local_pty_custom_cwd_and_env(qapp, tmp_path):
    """Verify LocalPTYBackend respects custom cwd and environment variables."""
    received = []
    custom_dir = tmp_path / "hpc_work"
    custom_dir.mkdir()

    backend = LocalPTYBackend(
        command=["/bin/bash", "-c", "echo WORK=$HPC_WORK_VAR; pwd"],
        cwd=custom_dir,
        env={"HPC_WORK_VAR": "QUANTUM_SIM_01"},
    )
    backend.data_received.connect(lambda d: received.append(d))
    backend.start()

    deadline = time.time() + 2.0
    while time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.02)

    backend.close()
    output = b"".join(received).decode("utf-8")
    assert "WORK=QUANTUM_SIM_01" in output
    assert str(custom_dir) in output


# ==============================================================================
# Tests for SSHPtyBackend
# ==============================================================================


@pytest.fixture
def mock_ssh_channel():
    """Provide a mock Paramiko Channel with buffer simulation."""
    channel = MagicMock()
    channel.closed = False
    channel._recv_queue = [
        b"Welcome to HPC Cluster\r\n",
        b"\x1b]0;cn01.hpc.local\x07",
        b"cn01:~$ ",
        b"",  # EOF
    ]

    def mock_recv(n):
        if not channel._recv_queue:
            return b""
        item = channel._recv_queue.pop(0)
        if item is None:
            raise socket.timeout()
        return item

    channel.recv.side_effect = mock_recv
    channel.exit_status_ready.side_effect = lambda: len(channel._recv_queue) == 0
    channel.recv_exit_status.return_value = 0
    return channel


@pytest.fixture
def mock_ssh_client(mock_ssh_channel):
    """Provide a mock Paramiko SSHClient."""
    client = MagicMock()
    transport = MagicMock()
    transport.is_active.return_value = True
    client.get_transport.return_value = transport
    client.invoke_shell.return_value = mock_ssh_channel
    return client


def test_ssh_pty_start_and_receive_data(mock_ssh_client, mock_ssh_channel, qapp):
    """Verify SSHPtyBackend invokes shell, reads stream, and detects title."""
    received_data = []
    titles = []
    finished_codes = []

    backend = SSHPtyBackend(client=mock_ssh_client, term="xterm-256color")
    backend.data_received.connect(lambda d: received_data.append(d))
    backend.title_changed.connect(lambda t: titles.append(t))
    backend.finished.connect(lambda c: finished_codes.append(c))

    assert not backend.is_alive()
    backend.start(cols=100, rows=30)

    # Verify invoke_shell parameters
    mock_ssh_client.invoke_shell.assert_called_once_with(
        term="xterm-256color",
        width=100,
        height=30,
    )
    mock_ssh_channel.settimeout.assert_called_once_with(0.05)

    deadline = time.time() + 2.0
    while time.time() < deadline:
        qapp.processEvents()
        if finished_codes:
            break
        time.sleep(0.02)

    backend.close()

    output = b"".join(received_data)
    assert b"Welcome to HPC Cluster" in output
    assert "cn01.hpc.local" in titles
    assert finished_codes == [0]


def test_ssh_pty_write_and_resize(mock_ssh_client):
    """Verify write sends bytes to channel and resize invokes resize_pty."""
    channel = MagicMock()
    channel.closed = False
    channel.exit_status_ready.return_value = False
    channel.recv.side_effect = socket.timeout()
    mock_ssh_client.invoke_shell.return_value = channel

    backend = SSHPtyBackend(client=mock_ssh_client)
    backend.start(cols=80, rows=24)

    assert backend.is_alive()

    # Write data
    backend.write(b"squeue -u user\n")
    channel.sendall.assert_called_once_with(b"squeue -u user\n")

    # Write str
    backend.write_str("sinfo\n")
    channel.sendall.assert_called_with(b"sinfo\n")

    # Resize
    backend.resize(cols=120, rows=40)
    channel.resize_pty.assert_called_once_with(width=120, height=40)
    assert backend.cols == 120
    assert backend.rows == 40

    backend.close()


def test_ssh_pty_with_ssh_client_manager(mock_ssh_client):
    """Verify SSHPtyBackend extracts client from SSHClientManager."""
    channel = MagicMock()
    channel.closed = False
    channel.exit_status_ready.return_value = False
    channel.recv.side_effect = socket.timeout()
    mock_ssh_client.invoke_shell.return_value = channel

    from hpc_studio.ssh.client import SSHClientManager

    manager = MagicMock(spec=SSHClientManager)
    manager.is_connected = True
    manager.client = mock_ssh_client

    backend = SSHPtyBackend(client=manager)
    backend.start(cols=80, rows=24)
    assert backend.is_alive()
    backend.close()


def test_ssh_pty_disconnected_manager_error():
    """Verify starting with a disconnected SSHClientManager raises RuntimeError."""
    from hpc_studio.ssh.client import SSHClientManager

    manager = MagicMock(spec=SSHClientManager)
    manager.is_connected = False
    manager.client = None

    backend = SSHPtyBackend(client=manager)
    with pytest.raises(RuntimeError, match="SSHClientManager is not currently connected"):
        backend.start()


def test_ssh_pty_inactive_transport_error():
    """Verify starting with an inactive transport raises RuntimeError."""
    client = MagicMock()
    transport = MagicMock()
    transport.is_active.return_value = False
    client.get_transport.return_value = transport

    backend = SSHPtyBackend(client=client)
    with pytest.raises(RuntimeError, match="transport is not active"):
        backend.start()


def test_ssh_pty_write_when_closed_error(mock_ssh_client):
    """Verify writing to closed SSH session raises RuntimeError."""
    backend = SSHPtyBackend(client=mock_ssh_client)
    with pytest.raises(RuntimeError, match="Cannot write"):
        backend.write(b"test")


def test_ssh_pty_double_start_error(mock_ssh_client):
    """Verify double start on SSH session raises RuntimeError."""
    channel = MagicMock()
    channel.closed = False
    channel.exit_status_ready.return_value = False
    channel.recv.side_effect = socket.timeout()
    mock_ssh_client.invoke_shell.return_value = channel

    backend = SSHPtyBackend(client=mock_ssh_client)
    backend.start()
    try:
        with pytest.raises(RuntimeError, match="already running"):
            backend.start()
    finally:
        backend.close()
