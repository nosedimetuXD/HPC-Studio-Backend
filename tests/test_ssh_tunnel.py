"""Unit tests for SSHTunnelManager and direct-tcpip port forwarding."""

import socket
import threading
import time
from unittest.mock import MagicMock

import paramiko
import pytest

from hpc_studio.notebook.ssh_tunnel import PortForwardHandler, SSHTunnelManager


class MockDirectChannel:
    """Simulates a Paramiko Channel created from open_channel('direct-tcpip', ...)."""

    def __init__(self, target_host: str, target_port: int) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((target_host, target_port))

    def recv(self, n: int) -> bytes:
        return self.sock.recv(n)

    def send(self, data: bytes) -> int:
        return self.sock.send(data)

    def sendall(self, data: bytes) -> None:
        self.sock.sendall(data)

    def close(self) -> None:
        try:
            self.sock.close()
        except Exception:
            pass

    def shutdown(self, how: int) -> None:
        try:
            self.sock.shutdown(how)
        except Exception:
            pass


def start_echo_server() -> tuple[socket.socket, int, threading.Thread]:
    """Start a TCP echo server on an ephemeral port."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    port = srv.getsockname()[1]

    stop_event = threading.Event()

    def run_echo():
        while not stop_event.is_set():
            try:
                srv.settimeout(0.2)
                conn, _ = srv.accept()
            except (socket.timeout, TimeoutError):
                continue
            except OSError:
                break

            def handle_client(c: socket.socket):
                try:
                    while not stop_event.is_set():
                        data = c.recv(4096)
                        if not data:
                            break
                        c.sendall(data)
                except Exception:
                    pass
                finally:
                    try:
                        c.close()
                    except Exception:
                        pass

            threading.Thread(target=handle_client, args=(conn,), daemon=True).start()

    t = threading.Thread(target=run_echo, daemon=True)
    t.start()
    return srv, port, t


def test_port_forward_handler_data_flow():
    """Test PortForwardHandler bridges local TCP traffic to Paramiko direct-tcpip channel."""
    echo_srv, echo_port, echo_thread = start_echo_server()

    mock_transport = MagicMock(spec=paramiko.Transport)

    def mock_open_channel(kind, dest_addr, src_addr, timeout=None):
        assert kind == "direct-tcpip"
        return MockDirectChannel(dest_addr[0], dest_addr[1])

    mock_transport.open_channel.side_effect = mock_open_channel

    handler = PortForwardHandler(
        local_port=0,
        remote_port=echo_port,
        transport=mock_transport,
    )
    bound_port = handler.start()
    assert bound_port > 0

    try:
        # Connect client to the local bound port
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect(("127.0.0.1", bound_port))
        client.settimeout(2.0)

        # Send test message
        msg = b"Hello through SSH tunnel!"
        client.sendall(msg)

        reply = client.recv(1024)
        assert reply == msg

        client.close()
    finally:
        handler.close()
        echo_srv.close()


def test_ssh_tunnel_manager_5_channels():
    """Test SSHTunnelManager starts 5 distinct forwarding channels and can close them cleanly."""
    echo_servers = [start_echo_server() for _ in range(5)]
    echo_ports = [srv[1] for srv in echo_servers]

    mock_transport = MagicMock(spec=paramiko.Transport)

    def mock_open_channel(kind, dest_addr, src_addr, timeout=None):
        assert kind == "direct-tcpip"
        return MockDirectChannel(dest_addr[0], dest_addr[1])

    mock_transport.open_channel.side_effect = mock_open_channel

    mgr = SSHTunnelManager(transport=mock_transport)

    remote_ports = {
        "shell_port": echo_ports[0],
        "iopub_port": echo_ports[1],
        "stdin_port": echo_ports[2],
        "control_port": echo_ports[3],
        "hb_port": echo_ports[4],
    }

    try:
        local_ports = mgr.start_kernel_tunnels(remote_ports)
        assert mgr.is_active is True
        assert len(mgr.handlers) == 5

        # Check all 5 channels are present in local_ports
        for name in ("shell", "iopub", "stdin", "control", "hb"):
            assert name in local_ports
            assert f"{name}_port" in local_ports
            assert local_ports[name] > 0

        # Verify communication over each channel
        for i, name in enumerate(("shell", "iopub", "stdin", "control", "hb")):
            c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            c.connect(("127.0.0.1", local_ports[f"{name}_port"]))
            c.settimeout(2.0)
            payload = f"ping-{name}".encode("utf-8")
            c.sendall(payload)
            resp = c.recv(1024)
            assert resp == payload
            c.close()

    finally:
        mgr.close()
        assert mgr.is_active is False
        for srv, _, _ in echo_servers:
            srv.close()


def test_ssh_tunnel_manager_invalid_ports():
    """Test SSHTunnelManager raises ValueError if any channel port is missing."""
    mock_transport = MagicMock(spec=paramiko.Transport)
    mgr = SSHTunnelManager(transport=mock_transport)

    incomplete_ports = {
        "shell_port": 1234,
        "iopub_port": 1235,
        # missing stdin, control, hb
    }

    with pytest.raises(ValueError, match="Missing required port for kernel channel"):
        mgr.start_kernel_tunnels(incomplete_ports)
