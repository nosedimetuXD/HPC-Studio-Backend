"""Unit tests for HPC Studio backend server and authentication."""

import json
from pathlib import Path
import pytest
from starlette.testclient import TestClient

from hpc_studio.server.app import create_app
from hpc_studio.server.cli import build_parser, find_free_port
from hpc_studio.server.config import ServerConfig


@pytest.fixture
def test_config(tmp_path: Path) -> ServerConfig:
    """Fixture providing a known server configuration."""
    return ServerConfig(
        host="127.0.0.1",
        port=8000,
        token="test-secret-token-12345",
        workspace_dir=tmp_path,
        version="0.1.0",
        debug=True,
    )


@pytest.fixture
def client(test_config: ServerConfig) -> TestClient:
    """Fixture providing FastAPI TestClient."""
    app = create_app(test_config)
    return TestClient(app)


def test_health_endpoint_unauthorized_without_token(client: TestClient):
    """Health check must reject requests lacking authentication token."""
    response = client.get("/api/health")
    assert response.status_code == 401
    assert "detail" in response.json()


def test_health_endpoint_unauthorized_with_wrong_token(client: TestClient):
    """Health check must reject requests with wrong token."""
    response = client.get("/api/health", headers={"X-HPC-Token": "invalid-token"})
    assert response.status_code == 401


def test_health_endpoint_authorized_via_header(client: TestClient, test_config: ServerConfig):
    """Health check must succeed when valid token is supplied via X-HPC-Token header."""
    response = client.get("/api/health", headers={"X-HPC-Token": test_config.token})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["version"] == test_config.version
    assert "uptime_seconds" in data
    assert data["uptime_seconds"] >= 0.0
    assert "pid" in data
    assert "system" in data
    assert "python" in data["system"]


def test_health_endpoint_authorized_via_query_param(client: TestClient, test_config: ServerConfig):
    """Health check must succeed when token is passed as query parameter."""
    response = client.get(f"/api/health?token={test_config.token}")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

    response_alias = client.get(f"/api/health?X-HPC-Token={test_config.token}")
    assert response_alias.status_code == 200
    assert response_alias.json()["status"] == "healthy"


def test_workspace_endpoint_unauthorized(client: TestClient):
    """Workspace endpoint must reject unauthorized requests."""
    response = client.get("/api/workspace")
    assert response.status_code == 401


def test_workspace_endpoint_authorized(client: TestClient, test_config: ServerConfig):
    """Workspace endpoint must return folder structure and environment status."""
    # Create sample files in temporary workspace
    (test_config.workspace_dir / "sample.py").write_text("print('test')")
    (test_config.workspace_dir / "subdir").mkdir()

    response = client.get("/api/workspace", headers={"X-HPC-Token": test_config.token})
    assert response.status_code == 200
    data = response.json()
    assert data["workspace_path"] == str(test_config.workspace_dir)
    assert data["exists"] is True
    assert data["is_directory"] is True
    assert data["stats"]["top_level_files"] >= 1
    assert data["stats"]["top_level_directories"] >= 1
    assert "environment" in data
    assert "python_executable" in data["environment"]


def test_websocket_unauthorized_rejected(client: TestClient):
    """WebSocket connection without valid token must be rejected."""
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/events?token=wrong_token") as ws:
            pass


def test_websocket_connected_and_ping_pong(client: TestClient, test_config: ServerConfig):
    """WebSocket connection with valid token must authenticate and reply to ping."""
    with client.websocket_connect(f"/ws/events?token={test_config.token}") as ws:
        # Initial greeting from server
        msg = ws.receive_json()
        assert msg["type"] == "system:connected"
        assert msg["payload"]["version"] == test_config.version

        # Send ping
        ws.send_json({"type": "ping", "payload": {"timestamp": 12345}})
        reply = ws.receive_json()
        assert reply["type"] == "pong"
        assert reply["payload"]["client_timestamp"] == 12345
        assert "server_timestamp" in reply["payload"]


def test_cli_parser_defaults_and_flags():
    """Verify CLI parser parses port, token and custom workspace directory."""
    parser = build_parser()
    args = parser.parse_args(["--port", "9090", "--token", "custom-token-xyz", "--debug"])
    assert args.port == 9090
    assert args.token == "custom-token-xyz"
    assert args.debug is True


def test_find_free_port():
    """Verify free port finder returns a valid integer port."""
    port = find_free_port("127.0.0.1")
    assert isinstance(port, int)
    assert 1024 < port < 65535
