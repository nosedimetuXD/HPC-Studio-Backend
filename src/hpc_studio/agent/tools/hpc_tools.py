"""Native HPC Studio agent tools implementation.

Provides SLURM monitoring and submission, Quantum ESPRESSO validation,
file manipulation (read/edit), and command execution.
Zero-Emoji compliant.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Dict, Optional

from .registry import RiskLevel, ToolParameter, get_default_registry, hpc_tool

logger = logging.getLogger(__name__)


@hpc_tool(
    name="slurm_query",
    description="Queries Slurm queue status, jobs and cluster nodes.",
    risk_level=RiskLevel.LOW,
    parameters=[
        ToolParameter("partition", "string", "Partition name to filter by (optional)", required=False, default=""),
        ToolParameter("user", "string", "Username to filter jobs by (optional)", required=False, default=""),
    ],
)
def slurm_query(
    partition: str = "",
    user: str = "",
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Query queue or node states from Slurm via SlurmClient, SSHManager or local CLI fallback."""
    ctx = context or {}
    slurm_client = ctx.get("slurm_client")
    ssh_manager = ctx.get("ssh_manager")

    # If SlurmClient is injected in context
    if slurm_client is not None and getattr(slurm_client, "is_connected", False):
        try:
            jobs = slurm_client.get_jobs(
                user=user if user else None,
                partition=partition if partition else None,
            )
            partitions = slurm_client.get_partitions()
            return {
                "success": True,
                "jobs": [
                    {
                        "job_id": j.job_id,
                        "name": j.name,
                        "user": j.user,
                        "state": j.state.value if hasattr(j.state, "value") else str(j.state),
                        "partition": j.partition,
                        "time_used": j.time_used,
                        "nodes": j.nodes,
                    }
                    for j in jobs
                ],
                "partitions": [
                    {
                        "name": p.name,
                        "state": p.state,
                        "total_nodes": p.total_nodes,
                        "idle_nodes": p.idle_nodes,
                        "busy_nodes": p.busy_nodes,
                    }
                    for p in partitions
                ],
            }
        except Exception as exc:
            return {"success": False, "error": f"Failed querying SlurmClient: {exc}"}

    # If SSHClientManager is provided directly
    if ssh_manager is not None and getattr(ssh_manager, "is_connected", False):
        cmd = 'squeue -o "%i|%j|%u|%T|%M|%l|%D|%C|%R|%Z|%N" --noheader'
        if user:
            cmd += f" -u {user}"
        if partition:
            cmd += f" -p {partition}"
        try:
            res = ssh_manager.execute_command(cmd)
            return {
                "success": res.success,
                "stdout": res.stdout,
                "stderr": res.stderr,
                "exit_code": res.exit_code,
            }
        except Exception as exc:
            return {"success": False, "error": f"Failed executing squeue over SSH: {exc}"}

    # Fallback to local squeue command if available on host system
    try:
        cmd_args = ["squeue"]
        if user:
            cmd_args.extend(["-u", user])
        if partition:
            cmd_args.extend(["-p", partition])
        res = subprocess.run(cmd_args, capture_output=True, text=True, timeout=10)
        return {
            "success": res.returncode == 0,
            "stdout": res.stdout,
            "stderr": res.stderr,
            "exit_code": res.returncode,
            "source": "local_slurm",
        }
    except FileNotFoundError:
        return {
            "success": False,
            "error": "Slurm is not accessible locally and no connected SSH/Slurm session is active.",
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@hpc_tool(
    name="slurm_submit",
    description="Validates and submits a Slurm batch script to the cluster queue.",
    risk_level=RiskLevel.HIGH,
    parameters=[
        ToolParameter("script_path", "string", "Path to .sbatch or .sh script file (optional)", required=False, default=""),
        ToolParameter("script_content", "string", "Direct text content of the sbatch script (optional)", required=False, default=""),
    ],
)
def slurm_submit(
    script_path: str = "",
    script_content: str = "",
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Validate and submit an sbatch job script to Slurm."""
    content = script_content
    if not content and script_path:
        p = Path(script_path)
        if not p.is_file():
            return {"success": False, "error": f"Script file not found: {script_path}"}
        try:
            content = p.read_text(encoding="utf-8")
        except Exception as exc:
            return {"success": False, "error": f"Failed reading script file: {exc}"}

    if not content.strip():
        return {"success": False, "error": "Both script_path and script_content are empty."}

    # Validate presence of #SBATCH or #!/bin/bash
    lines = content.strip().splitlines()
    has_shebang = any(line.startswith("#!") for line in lines[:3])
    sbatch_directives = [line for line in lines if line.startswith("#SBATCH")]

    if not has_shebang:
        return {
            "success": False,
            "error": "Validation failed: Missing shebang (e.g. #!/bin/bash) in job script header.",
        }

    ctx = context or {}
    sandbox = ctx.get("sandbox")
    if sandbox is not None and script_path:
        try:
            script_path = sandbox.validate_path(script_path, for_write=False)
        except Exception as exc:
            return {"success": False, "error": f"SecurityPolicyError: {exc}"}

    ssh_manager = ctx.get("ssh_manager")

    if ssh_manager is not None and getattr(ssh_manager, "is_connected", False):
        import base64
        import uuid
        remote_script_name = f"agent_submit_{uuid.uuid4().hex[:8]}.sbatch"
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        upload_cmd = f"echo '{encoded}' | base64 -d > {remote_script_name}"
        try:
            write_res = ssh_manager.execute_command(upload_cmd)
            if not write_res.success:
                return {
                    "success": False,
                    "error": f"Could not write remote script: {write_res.stderr}",
                }

            submit_res = ssh_manager.execute_command(f"sbatch {remote_script_name}")
            if submit_res.success:
                out = submit_res.stdout.strip()
                job_id_match = re.search(r"Submitted batch job (\d+)", out)
                job_id = job_id_match.group(1) if job_id_match else out
                return {
                    "success": True,
                    "job_id": job_id,
                    "output": out,
                    "directives_count": len(sbatch_directives),
                }
            return {
                "success": False,
                "error": submit_res.stderr.strip() or f"sbatch exited with code {submit_res.exit_code}",
            }
        except Exception as exc:
            return {"success": False, "error": f"SSH submission failed: {exc}"}

    # Local fallback submission
    try:
        res = subprocess.run(["sbatch"], input=content, text=True, capture_output=True, timeout=15)
        if res.returncode == 0:
            out = res.stdout.strip()
            job_id_match = re.search(r"Submitted batch job (\d+)", out)
            job_id = job_id_match.group(1) if job_id_match else out
            return {
                "success": True,
                "job_id": job_id,
                "output": out,
                "directives_count": len(sbatch_directives),
                "source": "local_slurm",
            }
        return {
            "success": False,
            "error": res.stderr.strip() or f"sbatch exit code {res.returncode}",
        }
    except FileNotFoundError:
        return {
            "success": False,
            "error": "Slurm (sbatch) is not available locally and no connected SSH session was found in context.",
            "validated": True,
            "directives_found": len(sbatch_directives),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@hpc_tool(
    name="qe_validate",
    description="Validates syntactic and semantic correctness of Quantum ESPRESSO input cards and namelists.",
    risk_level=RiskLevel.LOW,
    parameters=[
        ToolParameter("input_path", "string", "Path to Quantum ESPRESSO .in or .pwi file (optional)", required=False, default=""),
        ToolParameter("input_content", "string", "Direct text content of the QE input file (optional)", required=False, default=""),
    ],
)
def qe_validate(
    input_path: str = "",
    input_content: str = "",
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Validate Quantum ESPRESSO inputs using AST parser and semantic QEValidator."""
    content = input_content
    if not content and input_path:
        p = Path(input_path)
        if not p.is_file():
            return {"valid": False, "errors": [f"File not found: {input_path}"]}
        try:
            content = p.read_text(encoding="utf-8")
        except Exception as exc:
            return {"valid": False, "errors": [f"Cannot read file: {exc}"]}

    if not content.strip():
        return {"valid": False, "errors": ["Input content and file path are both empty."]}

    # Check basic namelists presence
    upper = content.upper()
    mandatory_namelists = ["&CONTROL", "&SYSTEM", "&ELECTRONS"]
    missing = [nl for nl in mandatory_namelists if nl not in upper]

    from ...qe.parser import parse_qe_input
    from ...qe.validator import QEValidator

    try:
        qe_input = parse_qe_input(content)
        issues = QEValidator.validate(qe_input)

        errors = [str(i) for i in issues if i.is_error()]
        warnings = [str(i) for i in issues if i.is_warning()]

        # Include missing namelists warnings/errors if any
        for m in missing:
            errors.append(f"[ERROR] Namelist: Missing mandatory namelist {m}")

        is_valid = len(errors) == 0
        return {
            "valid": is_valid,
            "errors": errors,
            "warnings": warnings,
            "nat": qe_input.system.nat,
            "ntyp": qe_input.system.ntyp,
            "ibrav": qe_input.system.ibrav,
            "calculation": qe_input.control.calculation,
        }
    except Exception as exc:
        # Fallback error formatting
        return {
            "valid": False,
            "errors": [f"Syntax/Parser error: {exc}"],
            "warnings": [],
        }


@hpc_tool(
    name="read_file",
    description="Reads safely up to limit lines from a file in the workspace.",
    risk_level=RiskLevel.LOW,
    parameters=[
        ToolParameter("path", "string", "Path of the file to read", required=True),
        ToolParameter("offset", "integer", "1-based starting line number", required=False, default=1),
        ToolParameter("limit", "integer", "Maximum number of lines to return", required=False, default=200),
    ],
)
def read_file(
    path: str,
    offset: int = 1,
    limit: int = 200,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Safely read lines from a file with pagination."""
    sandbox = (context or {}).get("sandbox")
    if sandbox is not None:
        try:
            path = sandbox.validate_path(path, for_write=False)
        except Exception as exc:
            return {"success": False, "error": f"SecurityPolicyError: {exc}"}

    target = Path(path).resolve()
    if not target.exists():
        return {"success": False, "error": f"File does not exist: {path}"}
    if not target.is_file():
        return {"success": False, "error": f"Path is not a regular file: {path}"}

    try:
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        total_lines = len(lines)
        start_idx = max(0, offset - 1)
        end_idx = min(total_lines, start_idx + limit)

        selected_lines = lines[start_idx:end_idx]
        numbered_content = [
            f"{i + 1}: {line.rstrip()}"
            for i, line in enumerate(selected_lines, start=start_idx)
        ]

        return {
            "success": True,
            "path": str(target),
            "total_lines": total_lines,
            "start_line": start_idx + 1,
            "end_line": end_idx,
            "content": "\n".join(numbered_content),
        }
    except Exception as exc:
        return {"success": False, "error": f"Failed reading file: {exc}"}


@hpc_tool(
    name="edit_file",
    description="Surgically replaces a target content chunk with replacement content in a file.",
    risk_level=RiskLevel.HIGH,
    parameters=[
        ToolParameter("path", "string", "Path of the file to edit", required=True),
        ToolParameter("target_content", "string", "Exact string chunk to search and replace", required=True),
        ToolParameter("replacement_content", "string", "Replacement content to insert", required=True),
    ],
)
def edit_file(
    path: str,
    target_content: str,
    replacement_content: str,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Surgically edit file content by replacing an exact block."""
    sandbox = (context or {}).get("sandbox")
    if sandbox is not None:
        try:
            path = sandbox.validate_path(path, for_write=True)
        except Exception as exc:
            return {"success": False, "error": f"SecurityPolicyError: {exc}"}

    target = Path(path).resolve()
    if not target.exists():
        return {"success": False, "error": f"File does not exist: {path}"}
    if not target.is_file():
        return {"success": False, "error": f"Path is not a regular file: {path}"}

    try:
        content = target.read_text(encoding="utf-8")
        occurrences = content.count(target_content)

        if occurrences == 0:
            return {
                "success": False,
                "error": "Target content not found in file.",
            }
        if occurrences > 1:
            return {
                "success": False,
                "error": f"Target content occurs {occurrences} times. Specify a more unique chunk.",
            }

        new_content = content.replace(target_content, replacement_content, 1)
        target.write_text(new_content, encoding="utf-8")

        return {
            "success": True,
            "path": str(target),
            "replaced_bytes": len(target_content),
            "new_bytes": len(replacement_content),
        }
    except Exception as exc:
        return {"success": False, "error": f"Failed editing file: {exc}"}


@hpc_tool(
    name="run_command",
    description="Executes a shell command in the local environment or remote session.",
    risk_level=RiskLevel.CRITICAL,
    parameters=[
        ToolParameter("command", "string", "Shell command string to execute", required=True),
        ToolParameter("cwd", "string", "Working directory for execution (optional)", required=False, default=""),
    ],
)
def run_command(
    command: str,
    cwd: str = "",
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Execute shell command with environment context."""
    if not command.strip():
        return {"success": False, "error": "Command string cannot be empty."}

    if "\x00" in command:
        return {"success": False, "error": "SecurityPolicyError: Null bytes in command string."}

    ctx = context or {}
    sandbox = ctx.get("sandbox")
    if sandbox is not None:
        try:
            sandbox.validate_command(command)
            if cwd:
                sandbox.validate_path(cwd, for_write=False)
        except Exception as exc:
            return {"success": False, "error": f"SecurityPolicyError: {exc}"}

    ssh_manager = ctx.get("ssh_manager")

    # If execution requested in remote HPC cluster over SSH
    if ctx.get("remote", False) and ssh_manager is not None and getattr(ssh_manager, "is_connected", False):
        try:
            import shlex
            cmd_to_run = f"cd {shlex.quote(cwd)} && {command}" if cwd else command
            res = ssh_manager.execute_command(cmd_to_run)
            return {
                "success": res.success,
                "stdout": res.stdout,
                "stderr": res.stderr,
                "exit_code": res.exit_code,
                "execution_target": "remote_ssh",
            }
        except Exception as exc:
            return {"success": False, "error": f"Remote execution failed: {exc}"}

    # Local execution
    work_dir = cwd if cwd and os.path.isdir(cwd) else None
    try:
        res = subprocess.run(
            command,
            shell=True,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return {
            "success": res.returncode == 0,
            "stdout": res.stdout,
            "stderr": res.stderr,
            "exit_code": res.returncode,
            "execution_target": "local",
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Command execution timed out after 60 seconds."}
    except Exception as exc:
        return {"success": False, "error": f"Execution failed: {exc}"}
