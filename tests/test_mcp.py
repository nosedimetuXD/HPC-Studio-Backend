"""Unit and integration tests for HPC Studio Model Context Protocol (MCP) server and tools.

Zero-Emoji compliant.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hpc_studio.mcp.models import (
    CallToolResult,
    InitializeResult,
    JSONRPCRequest,
    JSONRPCResponse,
)
from hpc_studio.mcp.server import MCPServer
from hpc_studio.mcp.tools import (
    ToolRegistry,
    _tool_inspect_structure,
    _tool_list_clusters,
    _tool_sftp_list,
    _tool_sftp_read,
    _tool_slurm_cancel,
    _tool_slurm_log,
    _tool_slurm_queue,
    _tool_slurm_submit,
    _tool_validate_qe,
    register_all_tools,
)


@pytest.fixture
def mcp_server() -> MCPServer:
    """Fixture providing initialized MCPServer instance."""
    registry = register_all_tools()
    return MCPServer(registry=registry)


# --- Test MCP Server Protocol Methods ---


def test_mcp_initialize(mcp_server: MCPServer):
    """Test initialize method returns serverInfo and capabilities."""
    req_json = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"},
        },
    })
    resp_str = mcp_server.handle_message(req_json)
    assert resp_str is not None
    resp = json.loads(resp_str)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 1
    assert "result" in resp
    result = resp["result"]
    assert result["serverInfo"]["name"] == "hpc-studio-mcp"
    assert result["serverInfo"]["version"] == "1.0.0"
    assert result["protocolVersion"] == "2024-11-05"
    assert "tools" in result["capabilities"]


def test_mcp_notifications_initialized(mcp_server: MCPServer):
    """Test notifications/initialized acknowledge without response."""
    notif_json = json.dumps({
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
        "params": {},
    })
    resp_str = mcp_server.handle_message(notif_json)
    assert resp_str is None
    assert mcp_server._initialized is True


def test_mcp_ping(mcp_server: MCPServer):
    """Test ping returns empty dict."""
    req_json = json.dumps({
        "jsonrpc": "2.0",
        "id": "ping-123",
        "method": "ping",
    })
    resp_str = mcp_server.handle_message(req_json)
    assert resp_str is not None
    resp = json.loads(resp_str)
    assert resp["id"] == "ping-123"
    assert resp["result"] == {}


def test_mcp_tools_list(mcp_server: MCPServer):
    """Test tools/list returns all 9 registered tools with valid schemas."""
    req_json = json.dumps({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
    })
    resp_str = mcp_server.handle_message(req_json)
    assert resp_str is not None
    resp = json.loads(resp_str)
    tools = resp["result"]["tools"]
    tool_names = {t["name"] for t in tools}
    expected_tools = {
        "hpc_slurm_queue",
        "hpc_slurm_submit",
        "hpc_slurm_cancel",
        "hpc_slurm_log",
        "hpc_validate_qe",
        "hpc_inspect_structure",
        "hpc_list_clusters",
        "hpc_sftp_list",
        "hpc_sftp_read",
    }
    assert expected_tools.issubset(tool_names)
    assert len(tools) == 9
    for tool in tools:
        assert "name" in tool
        assert "description" in tool
        assert "inputSchema" in tool
        assert tool["inputSchema"]["type"] == "object"


def test_mcp_tools_call_unknown(mcp_server: MCPServer):
    """Test calling an unknown tool returns isError=True."""
    req_json = json.dumps({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "non_existent_tool",
            "arguments": {},
        },
    })
    resp_str = mcp_server.handle_message(req_json)
    assert resp_str is not None
    resp = json.loads(resp_str)
    assert resp["id"] == 3
    result = resp["result"]
    assert result["isError"] is True
    assert "not found" in result["content"][0]["text"].lower()


def test_mcp_invalid_json(mcp_server: MCPServer):
    """Test parse error on invalid JSON."""
    resp_str = mcp_server.handle_message("NOT VALID JSON {{{{")
    assert resp_str is not None
    resp = json.loads(resp_str)
    assert "error" in resp
    assert resp["error"]["code"] == -32700


def test_mcp_method_not_found(mcp_server: MCPServer):
    """Test method not found error."""
    req_json = json.dumps({
        "jsonrpc": "2.0",
        "id": 4,
        "method": "unknown/method",
    })
    resp_str = mcp_server.handle_message(req_json)
    resp = json.loads(resp_str)
    assert resp["error"]["code"] == -32601


# --- Test Tool Handlers ---


def test_tool_slurm_queue_mocked():
    """Test hpc_slurm_queue parses squeue output."""
    mock_stdout = "101|calc_si|alice|RUNNING|01:23:45|02:00:00|2|32|(None)|/scratch/alice|node01,node02\n"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=mock_stdout, stderr="")
        res = _tool_slurm_queue({"user": "alice", "partition": "standard"})
        assert res.isError is False
        assert len(res.content) == 1
        data = json.loads(res.content[0].text)
        assert data["total_jobs"] == 1
        assert data["jobs"][0]["job_id"] == "101"
        assert data["jobs"][0]["state"] == "RUNNING"
        assert data["jobs"][0]["user"] == "alice"


def test_tool_slurm_queue_error_sanitization():
    """Test hpc_slurm_queue rejects malicious user arguments."""
    res = _tool_slurm_queue({"user": "alice; rm -rf /"})
    assert res.isError is True
    assert "Invalid username" in res.content[0].text


def test_tool_slurm_submit_content():
    """Test hpc_slurm_submit with valid script content."""
    script = "#!/bin/bash\n#SBATCH -J test\n#SBATCH -N 1\nsrun hostname\n"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="Submitted batch job 88990\n", stderr="")
        res = _tool_slurm_submit({"script_content": script})
        assert res.isError is False
        data = json.loads(res.content[0].text)
        assert data["success"] is True
        assert data["job_id"] == "88990"
        assert data["sbatch_directives_count"] == 2


def test_tool_slurm_submit_missing_shebang():
    """Test hpc_slurm_submit rejects script without shebang."""
    script = "#SBATCH -J test\nsrun hostname\n"
    res = _tool_slurm_submit({"script_content": script})
    assert res.isError is True
    assert "Missing shebang" in res.content[0].text


def test_tool_slurm_cancel_mocked():
    """Test hpc_slurm_cancel executes scancel with valid id."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        res = _tool_slurm_cancel({"job_id": "88990", "signal": "SIGTERM"})
        assert res.isError is False
        data = json.loads(res.content[0].text)
        assert data["success"] is True
        assert data["job_id"] == "88990"


def test_tool_slurm_cancel_invalid_id():
    """Test hpc_slurm_cancel rejects invalid job ID."""
    res = _tool_slurm_cancel({"job_id": "88990; rm -rf /"})
    assert res.isError is True
    assert "Invalid Slurm job ID" in res.content[0].text


def test_tool_slurm_log(tmp_path: Path):
    """Test hpc_slurm_log reads lines from log file."""
    log_file = tmp_path / "slurm-123.out"
    log_file.write_text("line 1\nline 2\nline 3\nline 4\nline 5\n", encoding="utf-8")

    res = _tool_slurm_log({"log_path": str(log_file), "lines": 3})
    assert res.isError is False
    data = json.loads(res.content[0].text)
    assert data["lines_returned"] == 3
    assert "line 3\nline 4\nline 5\n" in data["content"]


def test_tool_validate_qe_with_sample():
    """Test hpc_validate_qe on sample silicon_scf.in."""
    sample_path = Path("samples/silicon_scf.in").resolve()
    assert sample_path.is_file()

    res = _tool_validate_qe({"input_path": str(sample_path)})
    assert res.isError is False
    data = json.loads(res.content[0].text)
    assert data["valid"] is True
    assert data["summary"]["calculation"] == "scf"
    assert data["summary"]["nat"] == 2
    assert data["summary"]["ntyp"] == 1
    assert data["summary"]["ibrav"] == 2


def test_tool_validate_qe_missing_namelist():
    """Test hpc_validate_qe detects missing namelist."""
    incomplete = "&CONTROL\n calculation='scf'\n/\n"
    res = _tool_validate_qe({"input_content": incomplete})
    assert res.isError is False
    data = json.loads(res.content[0].text)
    assert data["valid"] is False
    assert any("Missing mandatory namelist &SYSTEM" in err for err in data["errors"])


def test_tool_inspect_structure_cif():
    """Test hpc_inspect_structure on samples/silicon_diamond.cif."""
    sample_path = Path("samples/silicon_diamond.cif").resolve()
    assert sample_path.is_file()

    res = _tool_inspect_structure({"file_path": str(sample_path)})
    assert res.isError is False
    data = json.loads(res.content[0].text)
    assert data["format"] == "cif"
    assert "Si" in data["elements"]
    assert data["lattice"] is not None
    assert data["lattice"]["a"] > 0.0


def test_tool_inspect_structure_xyz():
    """Test hpc_inspect_structure on samples/caffeine.xyz."""
    sample_path = Path("samples/caffeine.xyz").resolve()
    assert sample_path.is_file()

    res = _tool_inspect_structure({"file_path": str(sample_path)})
    assert res.isError is False
    data = json.loads(res.content[0].text)
    assert data["format"] == "xyz"
    assert data["total_atoms"] == 24
    assert "C" in data["elements"]
    assert "H" in data["elements"]
    assert "N" in data["elements"]
    assert "O" in data["elements"]


def test_tool_list_clusters():
    """Test hpc_list_clusters includes Quantum Mobile preset."""
    res = _tool_list_clusters({})
    assert res.isError is False
    data = json.loads(res.content[0].text)
    assert data["total_clusters"] >= 1
    qm = next(c for c in data["clusters"] if c.get("alias") == "quantum-mobile")
    assert qm["hostname"] == "127.0.0.1"
    assert qm["port"] == 2222
    assert qm["user"] == "max"


def test_tool_sftp_list_and_read(tmp_path: Path):
    """Test hpc_sftp_list and hpc_sftp_read."""
    test_dir = tmp_path / "remote_mock"
    test_dir.mkdir()
    f1 = test_dir / "calc.in"
    f1.write_text("line A\nline B\nline C\n", encoding="utf-8")
    d1 = test_dir / "subdir"
    d1.mkdir()

    list_res = _tool_sftp_list({"path": str(test_dir)})
    assert list_res.isError is False
    list_data = json.loads(list_res.content[0].text)
    assert list_data["total_entries"] == 2
    names = [e["name"] for e in list_data["entries"]]
    assert "subdir" in names
    assert "calc.in" in names

    read_res = _tool_sftp_read({"path": str(f1), "offset": 2, "limit": 2})
    assert read_res.isError is False
    read_data = json.loads(read_res.content[0].text)
    assert read_data["lines_read"] == 2
    assert read_data["content"] == "line B\nline C\n"


def test_mcp_server_run_stdio_stream():
    """Test MCPServer.run_stdio processes lines via in-memory stream."""
    in_stream = io.StringIO(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"}) + "\n"
    )
    out_stream = io.StringIO()
    server = MCPServer(stdin=in_stream, stdout=out_stream)
    server.run_stdio()

    out_lines = [json.loads(line) for line in out_stream.getvalue().strip().splitlines() if line.strip()]
    assert len(out_lines) == 2
    assert out_lines[0]["id"] == 1
    assert "serverInfo" in out_lines[0]["result"]
    assert out_lines[1]["id"] == 2
    assert out_lines[1]["result"] == {}
