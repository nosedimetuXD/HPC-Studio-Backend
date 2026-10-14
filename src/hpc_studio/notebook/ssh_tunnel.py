"""SSH Tunnel Manager for port forwarding remote Jupyter kernel ports."""

from __future__ import annotations

import logging
import socket
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import paramiko

logger = logging.getLogger(__name__)

CHANNEL_NAMES = ("shell", "iopub", "stdin", "control", "hb")


class PortForwardHandler:
    """Manages an active local listening port and bridges client connections to an SSH direct-tcpip channel."""

    def __init__(
        self,
        local_port: int,
        remote_port: int,
        transport: paramiko.Transport,
        remote_host: str = "127.0.0.1",
        bind_address: str = "127.0.0.1",
    ) -> None:
        self.local_port = local_port
        self.remote_port = remote_port
        self.transport = transport
        self.remote_host = remote_host
        self.bind_address = bind_address

        self._server_socket: Optional[socket.socket] = None
        self._is_active = threading.Event()
        self._listen_thread: Optional[threading.Thread] = None
        self._active_sockets: List[socket.socket] = []
        self._active_channels: List[paramiko.Channel] = []
        self._lock = threading.RLock()

    def start(self) -> int:
        """Bind server socket to local loopback port and start accepting connections."""
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.bind((self.bind_address, self.local_port))
        # If port 0 was passed, query the assigned OS port
        self.local_port = self._server_socket.getsockname()[1]
        self._server_socket.listen(10)
        self._server_socket.settimeout(0.5)

        self._is_active.set()
        self._listen_thread = threading.Thread(
            target=self._listen_loop,
            name=f"TunnelListener-{self.local_port}->{self.remote_port}",
            daemon=True,
        )
        self._listen_thread.start()
        return self.local_port

    def _listen_loop(self) -> None:
        while self._is_active.is_set():
            try:
                if self._server_socket is None:
                    break
                client_sock, client_addr = self._server_socket.accept()
            except (socket.timeout, TimeoutError):
                continue
            except OSError:
                break
            except Exception as e:
                logger.debug("Server accept error: %s", e)
                break

            if not self._is_active.is_set():
                try:
                    client_sock.close()
                except Exception:
                    pass
                break

            # Bridge client socket to SSH channel
            handler_thread = threading.Thread(
                target=self._handle_client,
                args=(client_sock, client_addr),
                name=f"TunnelBridge-{client_addr}->{self.remote_port}",
                daemon=True,
            )
            handler_thread.start()

    def _handle_client(self, client_sock: socket.socket, client_addr: Tuple[str, int]) -> None:
        channel: Optional[paramiko.Channel] = None
        try:
            channel = self.transport.open_channel(
                "direct-tcpip",
                (self.remote_host, self.remote_port),
                client_addr,
                timeout=10.0,
            )
            if channel is None:
                client_sock.close()
                return

            with self._lock:
                self._active_sockets.append(client_sock)
                self._active_channels.append(channel)

            # Bidirectional forwarding threads
            t1 = threading.Thread(
                target=self._forward_stream,
                args=(client_sock, channel, "sock->chan"),
                daemon=True,
            )
            t2 = threading.Thread(
                target=self._forward_stream,
                args=(channel, client_sock, "chan->sock"),
                daemon=True,
            )
            t1.start()
            t2.start()
            t1.join()
            t2.join()

        except Exception as e:
            logger.debug("Failed opening channel for %s: %s", client_addr, e)
        finally:
            with self._lock:
                if client_sock in self._active_sockets:
                    self._active_sockets.remove(client_sock)
                if channel and channel in self._active_channels:
                    self._active_channels.remove(channel)
            try:
                client_sock.close()
            except Exception:
                pass
            if channel is not None:
                try:
                    channel.close()
                except Exception:
                    pass

    def _forward_stream(self, source: Any, destination: Any, direction: str) -> None:
        while self._is_active.is_set():
            try:
                # Both socket and paramiko.Channel support .recv() and .sendall() / .send()
                data = source.recv(4096)
                if not data:
                    break
                if hasattr(destination, "sendall"):
                    destination.sendall(data)
                else:
                    total_sent = 0
                    while total_sent < len(data):
                        sent = destination.send(data[total_sent:])
                        if sent == 0:
                            break
                        total_sent += sent
            except Exception:
                break
        try:
            if hasattr(destination, "shutdown"):
                destination.shutdown(socket.SHUT_WR)
        except Exception:
            pass

    def close(self) -> None:
        """Tear down listener socket and active connections."""
        self._is_active.clear()

        # Connect a dummy client socket to wake accept() immediately if waiting
        if self._server_socket is not None:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as w:
                    w.settimeout(0.1)
                    w.connect((self.bind_address, self.local_port))
            except Exception:
                pass
            try:
                self._server_socket.close()
            except Exception:
                pass
            self._server_socket = None

        with self._lock:
            for ch in self._active_channels:
                try:
                    ch.close()
                except Exception:
                    pass
            self._active_channels.clear()

            for s in self._active_sockets:
                try:
                    s.close()
                except Exception:
                    pass
            self._active_sockets.clear()

        if self._listen_thread and self._listen_thread.is_alive():
            self._listen_thread.join(timeout=1.0)
            self._listen_thread = None


class SSHTunnelManager:
    """Manages SSH direct-tcpip local forwarding tunnels for the 5 Jupyter ZMQ channels."""

    def __init__(self, transport: paramiko.Transport, remote_host: str = "127.0.0.1") -> None:
        self.transport = transport
        self.remote_host = remote_host
        self.handlers: Dict[str, PortForwardHandler] = {}
        self.local_ports: Dict[str, int] = {}
        self._lock = threading.RLock()

    @property
    def is_active(self) -> bool:
        """Return True if tunnels are currently created and active."""
        return len(self.handlers) > 0 and all(h._is_active.is_set() for h in self.handlers.values())

    def start_kernel_tunnels(
        self,
        remote_ports: Dict[str, int],
        local_ports: Optional[Dict[str, int]] = None,
    ) -> Dict[str, int]:
        """Open 5 local forwarding tunnels for the Jupyter channels (shell, iopub, stdin, control, hb).

        Args:
            remote_ports: Mapping of channel names (or 'shell_port', etc.) to remote port integers.
            local_ports: Optional mapping of channel names to desired local port integers (0 for dynamic).

        Returns:
            Dictionary mapping channel keys (e.g. 'shell_port', 'iopub_port', ...) to bound local ports.
        """
        with self._lock:
            # Tear down any existing tunnels
            self.close()

            # Normalize keys: accept either 'shell' or 'shell_port'
            normalized_remote: Dict[str, int] = {}
            for name in CHANNEL_NAMES:
                if name in remote_ports:
                    normalized_remote[name] = remote_ports[name]
                elif f"{name}_port" in remote_ports:
                    normalized_remote[name] = remote_ports[f"{name}_port"]
                else:
                    raise ValueError(f"Missing required port for kernel channel: {name}")

            normalized_local: Dict[str, int] = {}
            if local_ports:
                for name in CHANNEL_NAMES:
                    if name in local_ports:
                        normalized_local[name] = local_ports[name]
                    elif f"{name}_port" in local_ports:
                        normalized_local[name] = local_ports[f"{name}_port"]
                    else:
                        normalized_local[name] = 0
            else:
                for name in CHANNEL_NAMES:
                    normalized_local[name] = 0

            # Bind each tunnel
            bound_ports: Dict[str, int] = {}
            try:
                for name in CHANNEL_NAMES:
                    rem_p = normalized_remote[name]
                    loc_p = normalized_local[name]
                    handler = PortForwardHandler(
                        local_port=loc_p,
                        remote_port=rem_p,
                        transport=self.transport,
                        remote_host=self.remote_host,
                    )
                    bound_loc = handler.start()
                    self.handlers[name] = handler
                    bound_ports[name] = bound_loc
                    bound_ports[f"{name}_port"] = bound_loc
            except Exception as e:
                logger.error("Failed creating SSH kernel tunnels: %s", e)
                self.close()
                raise

            self.local_ports = bound_ports
            return dict(bound_ports)

    def close(self) -> None:
        """Tear down all 5 tunnels and listening sockets."""
        with self._lock:
            for handler in self.handlers.values():
                try:
                    handler.close()
                except Exception as e:
                    logger.debug("Error closing handler: %s", e)
            self.handlers.clear()
            self.local_ports.clear()
