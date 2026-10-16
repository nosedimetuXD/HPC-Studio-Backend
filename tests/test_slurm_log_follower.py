"""Tests for RemoteLogStreamer."""

import time
from unittest.mock import MagicMock

import pytest

from hpc_studio.slurm.log_follower import RemoteLogStreamer
from hpc_studio.ssh.client import ConnectionState


class MockChannel:
    """Mock Paramiko channel that simulates interactive streaming chunks."""

    def __init__(self, data_chunks=None, auto_exit=True):
        self._chunks = list(data_chunks or [])
        self._closed = False
        self._auto_exit = auto_exit
        self._exit_ready = False
        self.cmd_executed = None
        self.timeout = None

    def settimeout(self, timeout):
        self.timeout = timeout

    def exec_command(self, cmd):
        self.cmd_executed = cmd

    def recv(self, nbytes):
        if self._chunks:
            return self._chunks.pop(0)
        if self._auto_exit:
            self._exit_ready = True
        return b""

    def recv_ready(self):
        return bool(self._chunks)

    def exit_status_ready(self):
        return self._exit_ready

    @property
    def closed(self):
        return self._closed

    def close(self):
        self._closed = True


@pytest.fixture
def mock_ssh_manager():
    manager = MagicMock()
    manager.is_connected = True
    manager.state = ConnectionState.CONNECTED

    client = MagicMock()
    transport = MagicMock()
    transport.is_active.return_value = True

    channel = MockChannel([b"line 1\nline 2\n", b"line 3\n"], auto_exit=False)
    transport.open_session.return_value = channel

    client.get_transport.return_value = transport
    manager.client = client
    manager.mock_channel = channel
    return manager


def test_streamer_initial_state():
    streamer = RemoteLogStreamer()
    assert not streamer.is_streaming
    assert not streamer.is_paused
    assert streamer.current_path == ""


def test_start_streaming_empty_path(mock_ssh_manager):
    streamer = RemoteLogStreamer(ssh_manager=mock_ssh_manager)
    errors = []
    streamer.stream_error.connect(errors.append)

    assert not streamer.start_streaming("")
    assert len(errors) == 1
    assert "empty" in errors[0].lower()


def test_start_streaming_not_connected():
    disconnected_manager = MagicMock()
    disconnected_manager.is_connected = False
    streamer = RemoteLogStreamer(ssh_manager=disconnected_manager)

    errors = []
    streamer.stream_error.connect(errors.append)

    assert not streamer.start_streaming("/var/log/slurm.out")
    assert len(errors) == 1
    assert "not connected" in errors[0].lower()


def test_stream_lines_received(qtbot, mock_ssh_manager):
    streamer = RemoteLogStreamer(ssh_manager=mock_ssh_manager)
    received_lines = []
    started_paths = []
    stopped_reasons = []

    streamer.line_received.connect(received_lines.append)
    streamer.stream_started.connect(started_paths.append)
    streamer.stream_stopped.connect(stopped_reasons.append)

    success = streamer.start_streaming("/scratch/calc.out", lines_history=50)
    assert success
    assert streamer.is_streaming
    assert streamer.current_path == "/scratch/calc.out"
    assert started_paths == ["/scratch/calc.out"]

    # Wait until all 3 lines are received and processed by Qt event loop
    qtbot.waitUntil(lambda: len(received_lines) == 3, timeout=3000)

    assert received_lines == ["line 1", "line 2", "line 3"]
    assert "tail -n 50 -f" in mock_ssh_manager.mock_channel.cmd_executed
    streamer.stop_streaming()


def test_pause_and_resume_streaming():
    # Long-running channel that stays open
    channel = MockChannel([], auto_exit=False)
    manager = MagicMock()
    manager.is_connected = True
    manager.state = ConnectionState.CONNECTED
    client = MagicMock()
    transport = MagicMock()
    transport.is_active.return_value = True
    transport.open_session.return_value = channel
    client.get_transport.return_value = transport
    manager.client = client

    streamer = RemoteLogStreamer(ssh_manager=manager)
    streamer.start_streaming("/scratch/job.out")

    assert streamer.is_streaming
    assert not streamer.is_paused

    streamer.pause_streaming()
    assert streamer.is_paused

    streamer.resume_streaming()
    assert not streamer.is_paused

    streamer.stop_streaming()
    assert not streamer.is_streaming


def test_stop_streaming(qtbot, mock_ssh_manager):
    # Use continuous channel (does not auto exit immediately)
    mock_ssh_manager.client.get_transport().open_session.return_value = MockChannel(
        [b"first line\n"], auto_exit=False
    )
    mock_ssh_manager.mock_channel = mock_ssh_manager.client.get_transport().open_session.return_value

    streamer = RemoteLogStreamer(ssh_manager=mock_ssh_manager)
    stopped = []
    streamer.stream_stopped.connect(stopped.append)

    streamer.start_streaming("/scratch/job.out")
    streamer.stop_streaming()

    qtbot.waitUntil(lambda: len(stopped) > 0, timeout=2000)
    assert not streamer.is_streaming
    assert mock_ssh_manager.mock_channel.closed
    assert "user_stopped" in stopped


