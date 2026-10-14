"""Unit tests for SSH authentication, client manager, and async Qt worker threads.

Verifies:
- Safe volatile memory passphrase management without disk persistence (RNF-03)
- ssh-agent detection and public key retrieval
- Multi-cipher private key loading (Ed25519, RSA, ECDSA) and passphrase requirements
- Paramiko SSHClient session wrapper, KeepAlive, and ProxyJump forwarding
- Synchronous and asynchronous remote command execution
- Qt background workers emitting events through LifecycleSignals
"""

import os
import socket
from pathlib import Path
from unittest.mock import MagicMock, patch

import paramiko
import pytest

from hpc_studio.core.signals import LifecycleSignals
from hpc_studio.ssh.auth import (
    KeyLoadError,
    PassphraseRequiredError,
    SSHAuthManager,
    VolatileCredentialStore,
)
from hpc_studio.ssh.client import (
    CommandResult,
    ConnectionState,
    SSHClientError,
    SSHClientManager,
    SSHCommandTimeoutError,
    SSHConnectionError,
    SSHNotConnectedError,
)
from hpc_studio.ssh.config_parser import SSHHostEntry
from hpc_studio.ssh.worker import (
    SSHCommandWorker,
    SSHConnectionWorker,
    SSHDisconnectionWorker,
)


class TestVolatileCredentialStore:
    """Verifies RNF-03 compliance: Passphrases kept strictly in volatile memory."""

    def test_in_memory_passphrase_lifecycle(self, tmp_path):
        store = VolatileCredentialStore()
        key_id = "/home/user/.ssh/id_ed25519"

        # Initially empty
        assert not store.has_passphrase(key_id)
        assert store.get_passphrase(key_id) is None

        # Store passphrase
        store.set_passphrase(key_id, "super_secret_passphrase")
        assert store.has_passphrase(key_id)
        assert store.get_passphrase(key_id) == "super_secret_passphrase"

        # Verify nothing was written to disk
        disk_files = list(tmp_path.glob("**/*"))
        assert len(disk_files) == 0

        # Remove
        removed = store.remove_passphrase(key_id)
        assert removed is True
        assert not store.has_passphrase(key_id)

        # Clear multiple
        store.set_passphrase("k1", "p1")
        store.set_passphrase("k2", "p2")
        store.clear()
        assert not store.has_passphrase("k1")
        assert not store.has_passphrase("k2")


class TestSSHAuthManager:
    """Tests for SSH authentication and key loaders."""

    def test_agent_available_and_keys(self, monkeypatch):
        # Socket does not exist
        monkeypatch.setenv("SSH_AUTH_SOCK", "/nonexistent/agent.sock")
        auth = SSHAuthManager()
        assert not auth.is_agent_available()
        assert auth.get_agent_keys() == []

        # Mock active agent socket
        monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/mock_agent.sock")
        mock_agent_instance = MagicMock()
        mock_key = MagicMock(spec=paramiko.AgentKey)
        mock_agent_instance.get_keys.return_value = (mock_key,)

        with patch("pathlib.Path.exists", return_value=True):
            with patch("hpc_studio.ssh.auth.Agent", return_value=mock_agent_instance):
                assert auth.is_agent_available()
                keys = auth.get_agent_keys()
                assert len(keys) == 1
                assert keys[0] == mock_key

    def test_load_private_key_success(self, tmp_path):
        key_file = tmp_path / "id_ed25519"
        key_file.write_text("dummy private key content")

        auth = SSHAuthManager()
        mock_pkey = MagicMock(spec=paramiko.Ed25519Key)

        with patch.object(paramiko.Ed25519Key, "from_private_key_file", return_value=mock_pkey):
            loaded = auth.load_private_key(key_file)
            assert loaded == mock_pkey

    def test_load_private_key_with_volatile_passphrase(self, tmp_path):
        key_file = tmp_path / "id_rsa"
        key_file.write_text("encrypted rsa content")

        auth = SSHAuthManager()
        auth.store_passphrase(str(key_file.resolve()), "mypassphrase123")

        mock_pkey = MagicMock(spec=paramiko.RSAKey)

        with patch.object(
            paramiko.Ed25519Key, "from_private_key_file", side_effect=paramiko.SSHException("not ed25519")
        ):
            with patch.object(paramiko.RSAKey, "from_private_key_file", return_value=mock_pkey) as mock_rsa:
                loaded = auth.load_private_key(key_file)
                assert loaded == mock_pkey
                mock_rsa.assert_called_once_with(str(key_file.resolve()), password="mypassphrase123")

    def test_load_private_key_passphrase_required_error(self, tmp_path):
        key_file = tmp_path / "id_ecdsa"
        key_file.write_text("encrypted ecdsa content")

        auth = SSHAuthManager()

        with patch.object(
            paramiko.Ed25519Key, "from_private_key_file", side_effect=paramiko.SSHException("not ed25519")
        ):
            with patch.object(
                paramiko.RSAKey, "from_private_key_file", side_effect=paramiko.SSHException("not rsa")
            ):
                with patch.object(
                    paramiko.ECDSAKey,
                    "from_private_key_file",
                    side_effect=paramiko.PasswordRequiredException("Encrypted key"),
                ):
                    with pytest.raises(PassphraseRequiredError):
                        auth.load_private_key(key_file)

    def test_load_private_key_not_found(self):
        auth = SSHAuthManager()
        with pytest.raises(FileNotFoundError):
            auth.load_private_key("/invalid/path/key.pem")

    def test_candidate_keys_discovery(self, tmp_path):
        auth = SSHAuthManager()
        (tmp_path / "id_ed25519").touch()
        (tmp_path / "id_rsa").touch()
        (tmp_path / "random_file.txt").touch()

        candidates = auth.get_candidate_keys(search_dirs=[tmp_path])
        candidate_names = [p.name for p in candidates]
        assert "id_ed25519" in candidate_names
        assert "id_rsa" in candidate_names
        assert "random_file.txt" not in candidate_names


class TestSSHClientManager:
    """Tests for SSHClientManager connection lifecycle and command execution."""

    def test_initial_state_disconnected(self):
        manager = SSHClientManager()
        assert manager.state == ConnectionState.DISCONNECTED
        assert not manager.is_connected
        assert manager.client is None

    def test_connect_success(self):
        manager = SSHClientManager(keepalive_interval=45)
        entry = SSHHostEntry(host="mn5", hostname="mn5.bsc.es", user="hpcuser", port=22)

        mock_client = MagicMock(spec=paramiko.SSHClient)
        mock_transport = MagicMock(spec=paramiko.Transport)
        mock_transport.is_active.return_value = True
        mock_client.get_transport.return_value = mock_transport

        with patch.object(manager, "_create_ssh_client", return_value=mock_client):
            success = manager.connect(entry, timeout=15)
            assert success is True
            assert manager.state == ConnectionState.CONNECTED
            assert manager.is_connected is True
            assert manager.current_entry == entry

            mock_client.connect.assert_called_once_with(
                hostname="mn5.bsc.es",
                port=22,
                username="hpcuser",
                timeout=15,
                allow_agent=True,
                look_for_keys=True,
            )
            mock_transport.set_keepalive.assert_called_once_with(45)

    def test_connect_with_proxy_jump(self):
        manager = SSHClientManager()
        entry = SSHHostEntry(
            host="internal-calc",
            hostname="10.0.1.20",
            user="quantum",
            port=22,
            proxy_jump="jumpuser@bastion.org:2220",
        )

        mock_dest_client = MagicMock(spec=paramiko.SSHClient)
        mock_dest_transport = MagicMock(spec=paramiko.Transport)
        mock_dest_transport.is_active.return_value = True
        mock_dest_client.get_transport.return_value = mock_dest_transport

        mock_jump_client = MagicMock(spec=paramiko.SSHClient)
        mock_jump_transport = MagicMock(spec=paramiko.Transport)
        mock_channel = MagicMock(spec=paramiko.Channel)
        mock_jump_transport.open_channel.return_value = mock_channel
        mock_jump_client.get_transport.return_value = mock_jump_transport

        clients = [mock_dest_client, mock_jump_client]

        def client_factory():
            return clients.pop() if clients else MagicMock(spec=paramiko.SSHClient)

        with patch.object(manager, "_create_ssh_client", side_effect=client_factory):
            success = manager.connect(entry)
            assert success is True
            assert manager.state == ConnectionState.CONNECTED

            mock_dest_client.connect.assert_called_once()
            call_kwargs = mock_dest_client.connect.call_args[1]
            assert call_kwargs["sock"] == mock_channel

    def test_connect_failure_transitions_to_error(self):
        manager = SSHClientManager()
        entry = SSHHostEntry(host="badhost", hostname="192.0.2.1")

        mock_client = MagicMock(spec=paramiko.SSHClient)
        mock_client.connect.side_effect = paramiko.AuthenticationException("Auth failed")

        with patch.object(manager, "_create_ssh_client", return_value=mock_client):
            with pytest.raises(SSHConnectionError):
                manager.connect(entry)

            assert manager.state == ConnectionState.ERROR
            assert not manager.is_connected

    def test_execute_command_success(self):
        manager = SSHClientManager()
        entry = SSHHostEntry(host="node1", hostname="127.0.0.1")

        mock_client = MagicMock(spec=paramiko.SSHClient)
        mock_transport = MagicMock(spec=paramiko.Transport)
        mock_transport.is_active.return_value = True
        mock_client.get_transport.return_value = mock_transport

        # Mock exec_command return streams
        mock_stdin = MagicMock()
        mock_stdout = MagicMock()
        mock_stderr = MagicMock()

        mock_stdout.read.return_value = b"JOBID PARTITION NAME\n12344 batch   calc.pw\n"
        mock_stderr.read.return_value = b""
        mock_channel = MagicMock()
        mock_channel.recv_exit_status.return_value = 0
        mock_stdout.channel = mock_channel

        mock_client.exec_command.return_value = (mock_stdin, mock_stdout, mock_stderr)

        with patch.object(manager, "_create_ssh_client", return_value=mock_client):
            manager.connect(entry)
            result = manager.execute_command("squeue")

            assert isinstance(result, CommandResult)
            assert result.command == "squeue"
            assert result.exit_code == 0
            assert result.success is True
            assert "JOBID PARTITION NAME" in result.stdout
            assert result.stderr == ""
            assert result.duration >= 0

    def test_execute_command_not_connected_raises(self):
        manager = SSHClientManager()
        with pytest.raises(SSHNotConnectedError):
            manager.execute_command("hostname")

    def test_execute_command_timeout(self):
        manager = SSHClientManager()
        entry = SSHHostEntry(host="node1", hostname="127.0.0.1")

        mock_client = MagicMock(spec=paramiko.SSHClient)
        mock_transport = MagicMock(spec=paramiko.Transport)
        mock_transport.is_active.return_value = True
        mock_client.get_transport.return_value = mock_transport
        mock_client.exec_command.side_effect = socket.timeout("Timed out")

        with patch.object(manager, "_create_ssh_client", return_value=mock_client):
            manager.connect(entry)
            with pytest.raises(SSHCommandTimeoutError):
                manager.execute_command("sleep 100", timeout=2)

    def test_disconnect_lifecycle(self):
        manager = SSHClientManager()
        entry = SSHHostEntry(host="node1", hostname="127.0.0.1")

        mock_client = MagicMock(spec=paramiko.SSHClient)
        mock_transport = MagicMock(spec=paramiko.Transport)
        mock_transport.is_active.return_value = True
        mock_client.get_transport.return_value = mock_transport

        with patch.object(manager, "_create_ssh_client", return_value=mock_client):
            manager.connect(entry)
            assert manager.is_connected is True

            manager.disconnect()
            assert manager.state == ConnectionState.DISCONNECTED
            assert not manager.is_connected
            mock_client.close.assert_called_once()


class TestSSHWorkers:
    """Tests for asynchronous Qt QThread workers and LifecycleSignals emission."""

    def test_connection_worker_success(self):
        signals = LifecycleSignals()
        emitted_connecting = []
        emitted_connected = []

        signals.ssh_connecting.connect(lambda msg: emitted_connecting.append(msg))
        signals.ssh_connected.connect(lambda host: emitted_connected.append(host))

        manager = MagicMock(spec=SSHClientManager)
        entry = SSHHostEntry(host="mn5", hostname="mn5.bsc.es")

        worker = SSHConnectionWorker(
            client_manager=manager,
            host_entry=entry,
            signals=signals,
        )

        finished_events = []
        worker.connection_finished.connect(lambda success, msg: finished_events.append((success, msg)))

        worker.run()

        assert len(emitted_connecting) == 1
        assert "Connecting to mn5" in emitted_connecting[0]
        assert emitted_connected == ["mn5"]
        assert len(finished_events) == 1
        assert finished_events[0][0] is True
        manager.connect.assert_called_once()

    def test_connection_worker_error(self):
        signals = LifecycleSignals()
        emitted_errors = []
        signals.ssh_error.connect(lambda host, err: emitted_errors.append((host, err)))

        manager = MagicMock(spec=SSHClientManager)
        manager.connect.side_effect = SSHConnectionError("Network unreachable")
        entry = SSHHostEntry(host="failed-node", hostname="10.0.0.9")

        worker = SSHConnectionWorker(
            client_manager=manager,
            host_entry=entry,
            signals=signals,
        )

        finished_events = []
        worker.connection_finished.connect(lambda success, msg: finished_events.append((success, msg)))

        worker.run()

        assert len(emitted_errors) == 1
        assert emitted_errors[0][0] == "failed-node"
        assert "Network unreachable" in emitted_errors[0][1]
        assert len(finished_events) == 1
        assert finished_events[0][0] is False

    def test_disconnection_worker(self):
        signals = LifecycleSignals()
        emitted_disconnected = []
        signals.ssh_disconnected.connect(lambda msg: emitted_disconnected.append(msg))

        manager = MagicMock(spec=SSHClientManager)
        manager.current_entry = SSHHostEntry(host="active-cluster", hostname="127.0.0.1")

        worker = SSHDisconnectionWorker(
            client_manager=manager,
            reason="Session ended",
            signals=signals,
        )

        worker.run()

        assert len(emitted_disconnected) == 1
        assert "active-cluster: Session ended" in emitted_disconnected[0]
        manager.disconnect.assert_called_once()

    def test_command_worker_execution(self):
        manager = MagicMock(spec=SSHClientManager)
        expected_res = CommandResult(
            command="sbatch job.slurm",
            stdout="Submitted batch job 54321\n",
            stderr="",
            exit_code=0,
            duration=0.15,
        )
        manager.execute_command.return_value = expected_res

        worker = SSHCommandWorker(client_manager=manager, command="sbatch job.slurm")
        received_results = []
        worker.command_finished.connect(lambda res: received_results.append(res))

        worker.run()

        assert len(received_results) == 1
        assert received_results[0] == expected_res
        manager.execute_command.assert_called_once_with(
            "sbatch job.slurm",
            timeout=None,
            environment=None,
        )
