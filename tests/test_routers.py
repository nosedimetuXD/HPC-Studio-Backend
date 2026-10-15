"""Comprehensive tests for clusters, slurm, and sftp routers."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from starlette.testclient import TestClient

from hpc_studio.server.app import create_app
from hpc_studio.server.config import ServerConfig
from hpc_studio.slurm.models import JobState, SlurmJob
from hpc_studio.ssh.client import CommandResult, ConnectionState
from hpc_studio.ssh.config_parser import SSHHostEntry


@pytest.fixture
def server_config(tmp_path: Path) -> ServerConfig:
    return ServerConfig(
        host="127.0.0.1",
        port=8000,
        token="test-secret-token-xyz",
        workspace_dir=tmp_path,
        version="0.1.0",
        debug=True,
    )


@pytest.fixture
def test_client(server_config: ServerConfig) -> TestClient:
    app = create_app(server_config)
    return TestClient(app)


def test_clusters_list_unauthorized(test_client: TestClient):
    response = test_client.get("/api/clusters")
    assert response.status_code == 401


def test_clusters_list_authorized(test_client: TestClient, server_config: ServerConfig):
    response = test_client.get("/api/clusters", headers={"X-HPC-Token": server_config.token})
    assert response.status_code == 200
    data = response.json()
    assert "clusters" in data
    assert "active_cluster" in data
    assert "is_connected" in data
    assert data["is_connected"] is False


def test_clusters_ping(test_client: TestClient, server_config: ServerConfig):
    response = test_client.post(
        "/api/clusters/ping",
        json={"host": "127.0.0.1", "port": 65530, "timeout": 1.0},
        headers={"X-HPC-Token": server_config.token},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["host"] == "127.0.0.1"
    assert data["port"] == 65530
    assert "reachable" in data


def test_clusters_connect_and_disconnect(test_client: TestClient, server_config: ServerConfig):
    with patch("hpc_studio.server.routes.clusters.SSHClientManager") as mock_mgr_cls:
        mock_mgr = MagicMock()
        mock_mgr.is_connected = True
        mock_mgr.current_entry = SSHHostEntry(host="mock-cluster", hostname="cluster.example.edu", user="hpcteam", port=22)
        mock_mgr.open_sftp.return_value = MagicMock()
        mock_mgr_cls.return_value = mock_mgr

        # Connect
        conn_resp = test_client.post(
            "/api/clusters/connect",
            json={"host": "mock-cluster", "user": "hpcteam", "port": 22},
            headers={"X-HPC-Token": server_config.token},
        )
        assert conn_resp.status_code == 200
        assert conn_resp.json()["status"] == "connected"

        # List should reflect active connection
        list_resp = test_client.get("/api/clusters", headers={"X-HPC-Token": server_config.token})
        assert list_resp.status_code == 200
        assert list_resp.json()["is_connected"] is True
        assert list_resp.json()["active_cluster"]["host"] == "mock-cluster"

        # Disconnect
        disc_resp = test_client.post("/api/clusters/disconnect", headers={"X-HPC-Token": server_config.token})
        assert disc_resp.status_code == 200
        assert disc_resp.json()["status"] == "disconnected"

        # List after disconnect
        list_resp2 = test_client.get("/api/clusters", headers={"X-HPC-Token": server_config.token})
        assert list_resp2.json()["is_connected"] is False


def test_slurm_jobs_empty_when_disconnected(test_client: TestClient, server_config: ServerConfig):
    # Without connection or local squeue, returns []
    with patch("shutil.which", return_value=None):
        resp = test_client.get("/api/slurm/jobs", headers={"X-HPC-Token": server_config.token})
        assert resp.status_code == 200
        assert resp.json() == []


def test_slurm_jobs_with_connected_mock(test_client: TestClient, server_config: ServerConfig):
    mock_ssh = MagicMock()
    mock_ssh.is_connected = True
    # Mock squeue execution
    squeue_output = "1001|my_calc|user1|RUNNING|01:23:45|04:00:00|2|64|None|/home/user1|node[01-02]\n"
    mock_ssh.execute_command.return_value = CommandResult(
        command="squeue",
        stdout=squeue_output,
        stderr="",
        exit_code=0,
        duration=0.1,
    )

    test_client.app.state.ssh_manager = mock_ssh

    resp = test_client.get("/api/slurm/jobs", headers={"X-HPC-Token": server_config.token})
    assert resp.status_code == 200
    jobs = resp.json()
    assert len(jobs) == 1
    assert jobs[0]["job_id"] == "1001"
    assert jobs[0]["name"] == "my_calc"
    assert jobs[0]["state"] == "RUNNING"
    assert jobs[0]["nodes"] == 2
    assert jobs[0]["cpus"] == 64


def test_slurm_submit_job(test_client: TestClient, server_config: ServerConfig):
    mock_ssh = MagicMock()
    mock_ssh.is_connected = True
    mock_ssh.execute_command.return_value = CommandResult(
        command="sbatch",
        stdout="Submitted batch job 54321\n",
        stderr="",
        exit_code=0,
        duration=0.2,
    )
    test_client.app.state.ssh_manager = mock_ssh

    resp = test_client.post(
        "/api/slurm/submit",
        json={"script_content": "#!/bin/bash\n#SBATCH -J test\nsrun hostname\n"},
        headers={"X-HPC-Token": server_config.token},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "submitted"
    assert data["job_id"] == "54321"


def test_slurm_cancel_job(test_client: TestClient, server_config: ServerConfig):
    mock_ssh = MagicMock()
    mock_ssh.is_connected = True
    mock_ssh.execute_command.return_value = CommandResult(
        command="scancel 54321",
        stdout="",
        stderr="",
        exit_code=0,
        duration=0.1,
    )
    test_client.app.state.ssh_manager = mock_ssh

    resp = test_client.post(
        "/api/slurm/jobs/54321/cancel",
        headers={"X-HPC-Token": server_config.token},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"
    assert resp.json()["job_id"] == "54321"


def test_slurm_get_job_log(test_client: TestClient, server_config: ServerConfig):
    mock_ssh = MagicMock()
    mock_ssh.is_connected = True
    # First call: scontrol show job (details), Second call: tail -n 50
    mock_ssh.execute_command.side_effect = [
        CommandResult(command="scontrol", stdout="JobId=54321 StdOut=/scratch/run.log\n", stderr="", exit_code=0, duration=0.1),
        CommandResult(command="tail", stdout="Step 100 finished\nAll converged!\n", stderr="", exit_code=0, duration=0.1),
    ]
    test_client.app.state.ssh_manager = mock_ssh

    resp = test_client.get(
        "/api/slurm/jobs/54321/log?lines=50",
        headers={"X-HPC-Token": server_config.token},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == "54321"
    assert data["log_path"] == "/scratch/run.log"
    assert "All converged!" in data["content"]


def test_sftp_list_and_transfers(test_client: TestClient, server_config: ServerConfig, tmp_path: Path):
    mock_ssh = MagicMock()
    mock_ssh.is_connected = True
    mock_sftp = MagicMock()
    mock_ssh.open_sftp.return_value = mock_sftp

    # Mock listdir_attr
    attr_dir = MagicMock()
    attr_dir.filename = "scratch"
    attr_dir.st_mode = 0o040755
    attr_dir.st_size = 4096
    attr_dir.st_mtime = 1700000000

    attr_file = MagicMock()
    attr_file.filename = "input.in"
    attr_file.st_mode = 0o100644
    attr_file.st_size = 1024
    attr_file.st_mtime = 1700000100

    mock_sftp.listdir_attr.return_value = [attr_dir, attr_file]
    test_client.app.state.ssh_manager = mock_ssh

    # GET /api/sftp/list
    resp = test_client.get("/api/sftp/list?path=/home/user", headers={"X-HPC-Token": server_config.token})
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 2
    assert items[0]["name"] == "scratch"
    assert items[0]["is_dir"] is True
    assert items[1]["name"] == "input.in"
    assert items[1]["is_dir"] is False

    # POST /api/sftp/upload with content
    upload_resp = test_client.post(
        "/api/sftp/upload",
        json={"remote_path": "/home/user/test.txt", "content": "Hello remote cluster"},
        headers={"X-HPC-Token": server_config.token},
    )
    assert upload_resp.status_code == 200
    assert upload_resp.json()["status"] == "uploaded"

    # POST /api/sftp/download
    local_target = tmp_path / "downloaded.txt"
    # Ensure remote file stat works
    mock_stat = MagicMock()
    mock_stat.st_size = 12
    mock_stat.st_mode = 0o100644
    mock_sftp.stat.return_value = mock_stat

    dl_resp = test_client.post(
        "/api/sftp/download",
        json={"remote_path": "/home/user/test.txt", "local_path": str(local_target)},
        headers={"X-HPC-Token": server_config.token},
    )
    assert dl_resp.status_code == 200
    assert dl_resp.json()["status"] == "downloaded"
