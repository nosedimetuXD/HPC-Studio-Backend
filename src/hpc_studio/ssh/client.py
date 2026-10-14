"""High-level SSH client manager wrapping Paramiko SSHClient.

Features configurable host key verification policies, KeepAlive mechanisms,
robust command execution, connection state tracking, and ProxyJump forwarding.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import paramiko

from .auth import PassphraseRequiredError, SSHAuthManager
from .config_parser import SSHConfigParser, SSHHostEntry

logger = logging.getLogger(__name__)


class ConnectionState(str, Enum):
    """Lifecycle states of the SSH connection."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class CommandResult:
    """Outcome of an executed remote shell command."""

    command: str
    stdout: str
    stderr: str
    exit_code: int
    duration: float

    @property
    def success(self) -> bool:
        """True if the remote process exited with status 0."""
        return self.exit_code == 0


class SSHClientError(Exception):
    """Base exception for SSH client operations."""


class SSHNotConnectedError(SSHClientError):
    """Raised when an operation requiring an active SSH session is called on a disconnected client."""


class SSHConnectionError(SSHClientError):
    """Raised when establishing an SSH session fails."""


class SSHCommandTimeoutError(SSHClientError):
    """Raised when command execution exceeds the specified timeout."""


def _parse_jump_target(target: str) -> Tuple[Optional[str], str, int]:
    """Parse jump host target string: [user@]host[:port]."""
    user = None
    port = 22
    host_str = target.strip()

    if "@" in host_str:
        user, host_str = host_str.split("@", 1)

    if ":" in host_str:
        parts = host_str.split(":", 1)
        host_str = parts[0]
        try:
            port = int(parts[1])
        except ValueError:
            port = 22

    return user, host_str, port


class SSHClientManager:
    """Manages Paramiko SSHClient sessions, authentication, and execution."""

    def __init__(
        self,
        auth_manager: Optional[SSHAuthManager] = None,
        config_parser: Optional[SSHConfigParser] = None,
        missing_host_key_policy: Optional[paramiko.MissingHostKeyPolicy] = None,
        keepalive_interval: int = 30,
    ) -> None:
        self.auth_manager = auth_manager or SSHAuthManager()
        self.config_parser = config_parser
        self._missing_host_key_policy = (
            missing_host_key_policy if missing_host_key_policy is not None else paramiko.AutoAddPolicy()
        )
        self._keepalive_interval = keepalive_interval
        self._state = ConnectionState.DISCONNECTED
        self._client: Optional[paramiko.SSHClient] = None
        self._jump_client: Optional[paramiko.SSHClient] = None
        self._current_entry: Optional[SSHHostEntry] = None
        self._lock = threading.RLock()

    @property
    def state(self) -> ConnectionState:
        """Current lifecycle state of the SSH session."""
        return self._state

    @property
    def is_connected(self) -> bool:
        """True if the SSH client and transport are active and connected."""
        with self._lock:
            if self._state != ConnectionState.CONNECTED or self._client is None:
                return False
            transport = self._client.get_transport()
            return transport is not None and transport.is_active()

    @property
    def client(self) -> Optional[paramiko.SSHClient]:
        """Underlying Paramiko SSHClient instance."""
        return self._client

    @property
    def current_entry(self) -> Optional[SSHHostEntry]:
        """Host entry currently connected to, if any."""
        return self._current_entry

    @property
    def transport(self) -> Optional[paramiko.Transport]:
        """Underlying Paramiko Transport instance."""
        return self._client.get_transport() if self._client else None

    def set_missing_host_key_policy(
        self, policy: paramiko.MissingHostKeyPolicy
    ) -> None:
        """Configure the host key verification policy (e.g. AutoAddPolicy, RejectPolicy)."""
        self._missing_host_key_policy = policy
        if self._client:
            self._client.set_missing_host_key_policy(policy)

    def set_keepalive(self, interval: int) -> None:
        """Configure TCP KeepAlive interval in seconds."""
        self._keepalive_interval = interval
        with self._lock:
            if self.is_connected and self._client:
                transport = self._client.get_transport()
                if transport:
                    transport.set_keepalive(interval)

    def _create_ssh_client(self) -> paramiko.SSHClient:
        """Factory for pre-configured paramiko.SSHClient."""
        client = paramiko.SSHClient()
        # Load system known_hosts if available
        known_hosts_file = Path.home() / ".ssh" / "known_hosts"
        if known_hosts_file.exists():
            try:
                client.load_host_keys(str(known_hosts_file))
            except Exception as exc:
                logger.debug("Could not load known_hosts: %s", exc)

        client.set_missing_host_key_policy(self._missing_host_key_policy)
        return client

    def connect(
        self,
        host_entry: SSHHostEntry,
        passphrase: Optional[str] = None,
        password: Optional[str] = None,
        timeout: int = 10,
        look_for_keys: bool = True,
        allow_agent: bool = True,
        sock: Optional[Any] = None,
    ) -> bool:
        """Establish an SSH connection according to host configuration.

        Supports Jump Hosts (ProxyJump), encrypted keys with passphrase,
        ssh-agent keys, and standard password authentication.
        """
        with self._lock:
            self._state = ConnectionState.CONNECTING
            self._current_entry = host_entry
            target_sock = sock

            try:
                # Handle ProxyJump if specified and no socket provided
                if host_entry.proxy_jump and target_sock is None:
                    target_sock = self._setup_proxy_jump(host_entry, timeout=timeout)

                # Prepare client
                self._client = self._create_ssh_client()

                # Attempt to resolve private key objects
                loaded_pkey: Optional[paramiko.PKey] = None
                key_filenames: List[str] = []

                candidate_identity_files = (
                    host_entry.identity_files
                    if host_entry.identity_files
                    else ([host_entry.identity_file] if host_entry.identity_file else [])
                )
                for id_file in candidate_identity_files:
                    p = Path(id_file).expanduser().resolve()
                    if p.is_file():
                        try:
                            # Try loading key directly with auth manager
                            loaded_pkey = self.auth_manager.load_private_key(
                                p, passphrase=passphrase
                            )
                            break
                        except PassphraseRequiredError:
                            # Propagate passphrase required error up
                            raise
                        except Exception:
                            # Fallback to passing file name to paramiko
                            key_filenames.append(str(p))

                # Connect underlying client
                connect_kwargs: Dict[str, Any] = {
                    "hostname": host_entry.hostname,
                    "port": host_entry.port,
                    "username": host_entry.user,
                    "timeout": timeout,
                    "allow_agent": allow_agent,
                    "look_for_keys": look_for_keys,
                }

                if target_sock is not None:
                    connect_kwargs["sock"] = target_sock

                if loaded_pkey is not None:
                    connect_kwargs["pkey"] = loaded_pkey
                elif key_filenames:
                    connect_kwargs["key_filename"] = key_filenames

                if passphrase is not None and loaded_pkey is None:
                    connect_kwargs["passphrase"] = passphrase

                if password is not None:
                    connect_kwargs["password"] = password

                self._client.connect(**connect_kwargs)

                # Setup KeepAlive if requested
                if self._keepalive_interval > 0:
                    transport = self._client.get_transport()
                    if transport:
                        transport.set_keepalive(self._keepalive_interval)

                self._state = ConnectionState.CONNECTED
                logger.info("Successfully connected to SSH host %s", host_entry.display_name)
                return True

            except PassphraseRequiredError:
                self._close_clients()
                self._state = ConnectionState.ERROR
                raise

            except Exception as exc:
                self._close_clients()
                self._state = ConnectionState.ERROR
                err_msg = f"Failed to connect to {host_entry.display_name}: {exc}"
                logger.error(err_msg)
                raise SSHConnectionError(err_msg) from exc

    def _setup_proxy_jump(self, host_entry: SSHHostEntry, timeout: int = 10) -> Any:
        """Establish connection to jump host and open direct-tcpip channel."""
        jump_spec = host_entry.proxy_jump or ""
        jump_user, jump_host, jump_port = _parse_jump_target(jump_spec)

        # If we have a config parser, look up configured options for the jump host
        if self.config_parser:
            jump_entry = self.config_parser.get_host(jump_host)
            if jump_user:
                jump_entry.user = jump_user
            if jump_port != 22:
                jump_entry.port = jump_port
        else:
            jump_entry = SSHHostEntry(
                host=jump_host,
                hostname=jump_host,
                user=jump_user,
                port=jump_port,
            )

        logger.info("Connecting to jump host: %s", jump_entry.display_name)
        self._jump_client = self._create_ssh_client()

        jump_key_files: List[str] = []
        jump_candidates = (
            jump_entry.identity_files
            if jump_entry.identity_files
            else ([jump_entry.identity_file] if jump_entry.identity_file else [])
        )
        for id_f in jump_candidates:
            jp = Path(id_f).expanduser().resolve()
            if jp.is_file():
                jump_key_files.append(str(jp))

        self._jump_client.connect(
            hostname=jump_entry.hostname,
            port=jump_entry.port,
            username=jump_entry.user,
            key_filename=jump_key_files if jump_key_files else None,
            timeout=timeout,
        )

        jump_transport = self._jump_client.get_transport()
        if not jump_transport:
            raise SSHConnectionError(f"Could not get transport from jump host {jump_entry.host}")

        # Open direct-tcpip tunnel to final destination
        dest_addr = (host_entry.hostname, host_entry.port)
        src_addr = ("127.0.0.1", 0)
        channel = jump_transport.open_channel("direct-tcpip", dest_addr, src_addr)
        return channel

    def execute_command(
        self,
        command: str,
        timeout: Optional[int] = None,
        environment: Optional[Dict[str, str]] = None,
    ) -> CommandResult:
        """Execute a remote shell command synchronously, returning output and exit status."""
        if not isinstance(command, str) or not command.strip():
            raise ValueError("Command must be a non-empty string.")
        if "\x00" in command:
            raise ValueError("Command contains invalid null bytes.")
        if timeout is not None and timeout < 0:
            raise ValueError("Timeout must be non-negative.")
        if environment is not None:
            for k, v in environment.items():
                if not isinstance(k, str) or not isinstance(v, str) or "=" in k or "\x00" in k or "\x00" in v:
                    raise ValueError(f"Invalid environment variable: {k!r}")

        with self._lock:
            if not self.is_connected or self._client is None:
                raise SSHNotConnectedError("Cannot execute command: SSH client is not connected.")

            start_time = time.monotonic()
            stdin = stdout = stderr = None
            try:
                stdin, stdout, stderr = self._client.exec_command(
                    command,
                    timeout=timeout,
                    environment=environment,
                )

                # Read output buffers
                out_bytes = stdout.read()
                err_bytes = stderr.read()
                exit_status = stdout.channel.recv_exit_status()
                duration = time.monotonic() - start_time

                stdout_text = out_bytes.decode("utf-8", errors="replace")
                stderr_text = err_bytes.decode("utf-8", errors="replace")

                return CommandResult(
                    command=command,
                    stdout=stdout_text,
                    stderr=stderr_text,
                    exit_code=exit_status,
                    duration=duration,
                )

            except socket.timeout as exc:
                raise SSHCommandTimeoutError(
                    f"Command '{command}' timed out after {timeout} seconds."
                ) from exc
            except Exception as exc:
                if isinstance(exc, (SSHNotConnectedError, SSHCommandTimeoutError, ValueError)):
                    raise
                raise SSHClientError(f"Error executing command '{command}': {exc}") from exc
            finally:
                if stdin is not None:
                    try:
                        stdin.close()
                    except Exception:
                        pass
                if stdout is not None:
                    try:
                        stdout.close()
                    except Exception:
                        pass
                    try:
                        if hasattr(stdout, "channel") and stdout.channel:
                            stdout.channel.close()
                    except Exception:
                        pass
                if stderr is not None:
                    try:
                        stderr.close()
                    except Exception:
                        pass


    def open_sftp(self) -> paramiko.SFTPClient:
        """Create and return an active SFTP client over the SSH transport."""
        with self._lock:
            if not self.is_connected or self._client is None:
                raise SSHNotConnectedError("Cannot open SFTP: SSH client is not connected.")
            return self._client.open_sftp()

    def _close_clients(self) -> None:
        """Close active sockets without altering connection state."""
        if self._client:
            try:
                self._client.close()
            except Exception as exc:
                logger.debug("Error closing client: %s", exc)
            self._client = None

        if self._jump_client:
            try:
                self._jump_client.close()
            except Exception as exc:
                logger.debug("Error closing jump client: %s", exc)
            self._jump_client = None

    def disconnect(self) -> None:
        """Cleanly close active SSH session, SFTP channels, and jump hosts."""
        with self._lock:
            self._close_clients()
            self._state = ConnectionState.DISCONNECTED
            self._current_entry = None
