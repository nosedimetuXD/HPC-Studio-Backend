"""Unit tests for HPC Studio Agent Tool Registry and native tools.

Zero-Emoji compliant.
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import pytest

from hpc_studio.agent.tools.registry import (
    RiskLevel,
    ToolDefinition,
    ToolParameter,
    ToolRegistry,
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


def test_tool_parameter_schema():
    param = ToolParameter(name="test_p", param_type="string", description="desc", required=True, default="def")
    d = param.to_dict()
    assert d["type"] == "string"
    assert d["description"] == "desc"
    assert d["required"] is True
    assert d["default"] == "def"


def test_tool_definition_to_schema():
    def dummy():
        pass

    tool_def = ToolDefinition(
        name="custom_tool",
        description="A test tool",
        risk_level=RiskLevel.MEDIUM,
        parameters=[ToolParameter(name="arg1", param_type="integer", description="arg1 desc", required=True)],
        handler=dummy,
    )
    schema = tool_def.to_schema()
    assert schema["name"] == "custom_tool"
    assert schema["risk_level"] == "MEDIUM"
    assert "arg1" in schema["parameters"]["properties"]
    assert "arg1" in schema["parameters"]["required"]


def test_tool_registry_registration_and_execution():
    reg = ToolRegistry()

    @hpc_tool("greet", "Greets person", risk_level=RiskLevel.LOW, registry=reg)
    def greet(name: str) -> str:
        return f"Hello, {name}!"

    assert reg.get_tool("greet") is not None
    assert len(reg.list_tools()) == 1

    res = reg.execute_tool("greet", {"name": "HPC"})
    assert res == "Hello, HPC!"


def test_tool_registry_context_injection():
    reg = ToolRegistry()

    @hpc_tool("check_ctx", "Context checker", risk_level=RiskLevel.LOW, registry=reg)
    def check_ctx(val: int, context: dict = None) -> dict:
        return {"val": val, "cluster": (context or {}).get("cluster")}

    res = reg.execute_tool("check_ctx", {"val": 42}, context={"cluster": "magerit"})
    assert res["val"] == 42
    assert res["cluster"] == "magerit"


def test_default_registry_contains_native_tools():
    default_reg = get_default_registry()
    tools = default_reg.list_tools()
    tool_names = [t.name for t in tools]

    assert "slurm_query" in tool_names
    assert "slurm_submit" in tool_names
    assert "qe_validate" in tool_names
    assert "read_file" in tool_names
    assert "edit_file" in tool_names
    assert "run_command" in tool_names

    sq = default_reg.get_tool("slurm_query")
    assert sq.risk_level == RiskLevel.LOW

    ss = default_reg.get_tool("slurm_submit")
    assert ss.risk_level == RiskLevel.HIGH

    rc = default_reg.get_tool("run_command")
    assert rc.risk_level == RiskLevel.CRITICAL


def test_read_and_edit_file_tools():
    with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".txt") as tf:
        tf.write("line 1\nline 2\nline 3\nline 4\n")
        temp_path = tf.name

    try:
        # Test read_file
        read_res = read_file(path=temp_path, offset=2, limit=2)
        assert read_res["success"] is True
        assert read_res["start_line"] == 2
        assert read_res["end_line"] == 3
        assert "2: line 2" in read_res["content"]

        # Test edit_file
        edit_res = edit_file(path=temp_path, target_content="line 2", replacement_content="line 2 modified")
        assert edit_res["success"] is True

        # Verify edited content
        verify_res = read_file(path=temp_path, offset=1, limit=10)
        assert "line 2 modified" in verify_res["content"]

        # Test edit non-existing target
        bad_edit = edit_file(path=temp_path, target_content="nonexistent", replacement_content="abc")
        assert bad_edit["success"] is False
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def test_qe_validate_tool():
    valid_qe_deck = """&CONTROL
  calculation = 'scf'
  pseudo_dir = './'
  outdir = './tmp'
/
&SYSTEM
  ibrav = 2
  celldm(1) = 10.2
  nat = 2
  ntyp = 1
  ecutwfc = 30.0
/
&ELECTRONS
  conv_thr = 1.0d-8
/
ATOMIC_SPECIES
  Si 28.0855 Si.pbe.UPF
ATOMIC_POSITIONS crystal
  Si 0.00 0.00 0.00
  Si 0.25 0.25 0.25
K_POINTS automatic
  4 4 4 0 0 0
"""
    res = qe_validate(input_content=valid_qe_deck)
    assert res["valid"] is True
    assert res["nat"] == 2
    assert res["ntyp"] == 1

    # Invalid deck with missing positions
    invalid_qe_deck = """&CONTROL
  calculation = 'scf'
/
&SYSTEM
  ibrav = 1
  nat = 5
  ntyp = 1
/
&ELECTRONS
/
ATOMIC_SPECIES
  Si 28.0855 Si.UPF
ATOMIC_POSITIONS crystal
  Si 0.0 0.0 0.0
"""
    bad_res = qe_validate(input_content=invalid_qe_deck)
    assert bad_res["valid"] is False
    assert len(bad_res["errors"]) > 0


def test_slurm_submit_validation():
    # Missing shebang
    bad_submit = slurm_submit(script_content="#SBATCH --job-name=test\necho 'hello'")
    assert bad_submit["success"] is False
    assert "Missing shebang" in bad_submit["error"]

    # Valid script structure fallback
    good_script = """#!/bin/bash
#SBATCH --job-name=test_job
#SBATCH --partition=gpu
#SBATCH --nodes=1
echo "Running computation"
"""
    submit_res = slurm_submit(script_content=good_script)
    # Even if sbatch is not on dev host, validation succeeded
    assert "directives_found" in submit_res or submit_res["success"] is True


def test_run_command_tool():
    res = run_command("echo 'HPC Agent Tool'")
    assert res["success"] is True
    assert "HPC Agent Tool" in res["stdout"]

    empty_res = run_command("")
    assert empty_res["success"] is False
