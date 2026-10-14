"""Exhaustive test suite for native agent tools, ToolSandbox and ApprovalGate.

Tests registration, search and validation of native tools (slurm_query, slurm_submit,
qe_validate, read_file, edit_file, run_command), RiskLevel classifications,
ApprovalGate simulation (approval, rejection, session persistent memory),
ToolSandbox path traversal mitigation, and command injection prevention.
Strict Zero-Emoji compliance.
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import pytest

from hpc_studio.agent.tools.registry import (
    ApprovalGate,
    RiskLevel,
    SecurityPolicyError,
    ToolDefinition,
    ToolParameter,
    ToolRegistry,
    ToolSandbox,
    get_default_registry,
    hpc_tool,
)
from hpc_studio.agent.tools.hpc_tools import (
    edit_file,
    qe_validate,
    read_file,
    run_command,
    slurm_query,
    slurm_submit,
)


def test_tool_definitions_and_schema():
    """Verify tool parameter definitions and JSON schemas."""
    param = ToolParameter(
        name="workspace",
        param_type="string",
        description="Workspace directory",
        required=True,
        default="/tmp",
    )
    d = param.to_dict()
    assert d["type"] == "string"
    assert d["required"] is True
    assert d["default"] == "/tmp"

    tool_def = ToolDefinition(
        name="test_tool",
        description="Testing schema generator",
        risk_level=RiskLevel.MEDIUM,
        parameters=[param],
        handler=lambda workspace: workspace,
    )
    schema = tool_def.to_schema()
    assert schema["name"] == "test_tool"
    assert schema["risk_level"] == "MEDIUM"
    assert "workspace" in schema["parameters"]["properties"]
    assert "workspace" in schema["parameters"]["required"]


def test_native_tools_registered_in_default_registry():
    """Verify all required tools are present in default registry."""
    reg = get_default_registry()
    expected_tools = [
        "slurm_query",
        "slurm_submit",
        "qe_validate",
        "read_file",
        "edit_file",
        "run_command",
    ]
    all_names = [t.name for t in reg.list_tools()]
    for expected in expected_tools:
        assert expected in all_names, f"Tool {expected} must be registered"

    # Verify risk levels
    assert reg.get_tool("slurm_query").risk_level in (RiskLevel.LOW, RiskLevel.READ_ONLY)
    assert reg.get_tool("read_file").risk_level in (RiskLevel.LOW, RiskLevel.READ_ONLY)
    assert reg.get_tool("qe_validate").risk_level in (RiskLevel.LOW, RiskLevel.READ_ONLY)
    assert reg.get_tool("edit_file").risk_level in (RiskLevel.MEDIUM, RiskLevel.MODERATE, RiskLevel.HIGH)
    assert reg.get_tool("slurm_submit").risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
    assert reg.get_tool("run_command").risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)


def test_sandbox_path_validation_and_traversal_mitigation():
    """Verify ToolSandbox strictly blocks path traversal outside workspace root."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        sandbox = ToolSandbox(workspace_root=tmp_dir)

        # Valid relative and absolute paths within workspace
        safe_rel = "subfolder/test.txt"
        validated_write = sandbox.validate_path(safe_rel, for_write=True)
        assert validated_write.startswith(os.path.abspath(tmp_dir))

        # Path traversal attack attempting to write to /etc or ../outside
        traversal_attempts = [
            "../outside.txt",
            "../../escape.sh",
            "/etc/passwd",
            "subfolder/../../../../etc/shadow",
        ]
        for bad_path in traversal_attempts:
            with pytest.raises(SecurityPolicyError):
                sandbox.validate_path(bad_path, for_write=True)

        # Empty path raises SecurityPolicyError
        with pytest.raises(SecurityPolicyError):
            sandbox.validate_path("", for_write=True)


def test_sandbox_command_validation_and_injection_mitigation():
    """Verify ToolSandbox detects command injection and unwhitelisted binaries."""
    sandbox = ToolSandbox(workspace_root="/tmp", allowed_command_prefixes=["squeue", "ls", "echo"])

    # Permitted simple commands
    parsed = sandbox.validate_command("squeue -u user1")
    assert parsed == ["squeue", "-u", "user1"]

    parsed_echo = sandbox.validate_command("echo hello")
    assert parsed_echo == ["echo", "hello"]

    # Malicious injection patterns
    injection_commands = [
        "squeue; rm -rf /",
        "echo test && cat /etc/passwd",
        "ls || whoami",
        "echo `id`",
        "echo $(whoami)",
        "squeue > /tmp/out.txt",
        "squeue < /tmp/in.txt",
        "squeue | grep user",
    ]
    for bad_cmd in injection_commands:
        with pytest.raises(SecurityPolicyError):
            sandbox.validate_command(bad_cmd)

    # Unwhitelisted binary
    with pytest.raises(SecurityPolicyError):
        sandbox.validate_command("nc -lvp 4444")


def test_approval_gate_policy_and_session_memory():
    """Verify ApprovalGate approval, rejection, and session persistence."""
    gate = ApprovalGate()

    # Read-only / Low risk requires no approval
    assert gate.request_approval("slurm_query", {}, RiskLevel.LOW) is True
    assert gate.request_approval("read_file", {}, RiskLevel.READ_ONLY) is True

    # High risk without callback defaults to rejected
    assert gate.request_approval("slurm_submit", {"script_path": "run.sh"}, RiskLevel.HIGH) is False

    # Simulate interactive dialog callback
    dialog_responses = []

    def mock_approval_dialog(tool_name: str, args: dict, risk: RiskLevel) -> bool:
        return dialog_responses.pop(0) if dialog_responses else False

    gate.set_interactive_callback(mock_approval_dialog)

    # 1. User rejects execution
    dialog_responses.append(False)
    rejected = gate.request_approval("run_command", {"command": "rm -f foo"}, RiskLevel.HIGH)
    assert rejected is False

    # 2. User approves once without remembering session
    dialog_responses.append(True)
    approved_once = gate.request_approval(
        "run_command", {"command": "sbatch run.sh"}, RiskLevel.HIGH, remember_for_session=False
    )
    assert approved_once is True
    assert "run_command" not in gate.session_approved_tools

    # 3. User approves and remembers for session
    dialog_responses.append(True)
    approved_session = gate.request_approval(
        "edit_file", {"path": "job.sh"}, RiskLevel.MEDIUM, remember_for_session=True
    )
    assert approved_session is True
    assert "edit_file" in gate.session_approved_tools

    # 4. Subsequent call for session-approved tool does not invoke dialog callback
    # dialog_responses is empty; if dialog was called it would return False or error
    session_cached = gate.request_approval("edit_file", {"path": "another.sh"}, RiskLevel.MEDIUM)
    assert session_cached is True


def test_tool_registry_execution_with_approval_gate():
    """Verify ToolRegistry enforcing ApprovalGate during execute()."""
    gate = ApprovalGate()
    reg = ToolRegistry(approval_gate=gate)

    @hpc_tool("clean_scratch", "Cleans scratch", risk_level=RiskLevel.HIGH, registry=reg)
    def clean_scratch(target: str) -> str:
        return f"Cleaned {target}"

    # High risk tool without approval raises SecurityPolicyError
    with pytest.raises(SecurityPolicyError) as exc_info:
        reg.execute("clean_scratch", {"target": "/tmp/scratch"})
    assert "rejected by user approval policy" in str(exc_info.value)

    # Authorize with callback and remember session
    gate.set_interactive_callback(lambda name, args, risk: True)
    res = reg.execute("clean_scratch", {"target": "/tmp/scratch"}, remember_session_approval=True)
    assert res == "Cleaned /tmp/scratch"
    assert "clean_scratch" in gate.session_approved_tools

    # Next execution succeeds directly
    res2 = reg.execute("clean_scratch", {"target": "/tmp/scratch2"})
    assert res2 == "Cleaned /tmp/scratch2"


def test_qe_validate_execution():
    """Verify qe_validate tool returns meaningful semantic diagnostics."""
    valid_deck = (
        "&CONTROL\n  calculation = 'scf'\n/\n"
        "&SYSTEM\n  ibrav = 1\n  celldm(1) = 10.0\n  nat = 1\n  ntyp = 1\n/\n"
        "&ELECTRONS\n/\n"
        "ATOMIC_SPECIES\n  Si 28.086 Si.pbe.UPF\n"
        "ATOMIC_POSITIONS crystal\n  Si 0.0 0.0 0.0\n"
        "K_POINTS automatic\n  4 4 4 0 0 0\n"
    )
    result = qe_validate(input_content=valid_deck)
    assert result["valid"] is True
    assert result["nat"] == 1
    assert result["ntyp"] == 1

    invalid_deck = "&CONTROL\n  calculation = 'scf'\n/\n&SYSTEM\n  nat = 4\n  ntyp = 1\n/\n"
    bad_result = qe_validate(input_content=invalid_deck)
    assert bad_result["valid"] is False
    assert len(bad_result["errors"]) > 0


def test_slurm_query_and_submit_execution():
    """Verify slurm_query and slurm_submit native tools."""
    from unittest.mock import MagicMock
    mock_slurm_client = MagicMock()
    mock_slurm_client.is_connected = True
    job_mock = MagicMock(job_id=10489, name="qe_job", user="user1", state="RUNNING", partition="compute", time_used="01:00", nodes=2)
    mock_slurm_client.get_jobs.return_value = [job_mock]
    mock_slurm_client.get_partitions.return_value = []

    query_res = slurm_query(context={"slurm_client": mock_slurm_client})
    assert query_res["success"] is True
    assert "jobs" in query_res
    assert len(query_res["jobs"]) == 1

    # slurm_submit with invalid script (no shebang)
    res_bad = slurm_submit(script_content="echo test")
    assert res_bad["success"] is False
    assert "Missing shebang" in res_bad["error"]

    # slurm_submit with valid script structure
    res_good = slurm_submit(script_content="#!/bin/bash\n#SBATCH --job-name=sprint_a4\necho 123")
    assert res_good["success"] is True or "directives_found" in res_good
