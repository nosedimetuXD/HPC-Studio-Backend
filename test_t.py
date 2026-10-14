from tests.test_ssh_tunnel import start_echo_server, MockDirectChannel
from hpc_studio.notebook.ssh_tunnel import SSHTunnelManager
from unittest.mock import MagicMock
import paramiko, socket, time

echo_servers = [start_echo_server() for _ in range(5)]
echo_ports = [srv[1] for srv in echo_servers]
mock_transport = MagicMock(spec=paramiko.Transport)
def mock_open_channel(kind, dest_addr, src_addr, timeout=None):
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
local_ports = mgr.start_kernel_tunnels(remote_ports)
print("Tunnels started:", local_ports)

for i, name in enumerate(("shell", "iopub", "stdin", "control", "hb")):
    c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    c.connect(("127.0.0.1", local_ports[f"{name}_port"]))
    c.sendall(f"ping-{name}".encode("utf-8"))
    resp = c.recv(1024)
    print(name, "got", resp)
    c.close()

import threading
print("Active threads before close:")
for t in threading.enumerate():
    print("  Thread:", t.name, t.is_alive())

print("Closing mgr...")
t0 = time.time()
mgr.close()
print("Mgr closed in", time.time() - t0)

print("Active threads after close:")
for t in threading.enumerate():
    print("  Thread:", t.name, t.is_alive())

for srv, _, _ in echo_servers:
    srv.close()
print("Done!")
