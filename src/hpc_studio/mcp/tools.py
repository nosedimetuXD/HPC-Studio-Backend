"""MCP Tools implementation for HPC Studio.

Contains tool registrations and handlers for:
- hpc_slurm_queue
- hpc_slurm_submit
- hpc_slurm_cancel
- hpc_slurm_log
- hpc_validate_qe
- hpc_inspect_structure
- hpc_list_clusters
- hpc_sftp_list
- hpc_sftp_read

Zero-Emoji compliant.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Callable, Dict, List, Optional

from .models import CallToolResult, TextContent, Tool, ToolInputSchema

logger = logging.getLogger(__name__)

ToolHandler = Callable[[Dict[str, Any]], CallToolResult]


class ToolRegistry:
    """Registry holding MCP tool definitions and their execution handlers."""

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}
        self._handlers: Dict[str, ToolHandler] = {}

    def register(self, tool: Tool, handler: ToolHandler) -> None:
        """Register a tool definition and its handler."""
        self._tools[tool.name] = tool
        self._handlers[tool.name] = handler

    def list_tools(self) -> List[Tool]:
        """Return list of all registered tools."""
        return list(self._tools.values())

    def get_tool(self, name: str) -> Optional[Tool]:
        """Get tool definition by name."""
        return self._tools.get(name)

    def call(self, name: str, arguments: Dict[str, Any]) -> CallToolResult:
        """Execute a tool by name with arguments."""
        handler = self._handlers.get(name)
        if not handler:
            return CallToolResult(
                content=[TextContent(text=f"Error: Tool '{name}' not found.")],
                isError=True,
            )
        try:
            return handler(arguments)
        except Exception as exc:
            logger.exception("Error executing tool %s: %s", name, exc)
            return CallToolResult(
                content=[TextContent(text=f"Execution error in '{name}': {exc}")],
                isError=True,
            )


# --- Tool Implementations ---


def _tool_slurm_queue(arguments: Dict[str, Any]) -> CallToolResult:
    """Handler for hpc_slurm_queue."""
    partition = str(arguments.get("partition", "") or "").strip()
    user = str(arguments.get("user", "") or "").strip()

    # Sanitization
    if user and not re.match(r"^[A-Za-z0-9_.-]+$", user):
        return CallToolResult(
            content=[TextContent(text=f"Error: Invalid username format: {user}")],
            isError=True,
        )
    if partition and not re.match(r"^[A-Za-z0-9_.-]+$", partition):
        return CallToolResult(
            content=[TextContent(text=f"Error: Invalid partition format: {partition}")],
            isError=True,
        )

    cmd = ["squeue", '-o', '%i|%j|%u|%T|%M|%l|%D|%C|%R|%Z|%N', "--noheader"]
    if user:
        cmd.extend(["-u", user])
    if partition:
        cmd.extend(["-p", partition])

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if res.returncode != 0:
            err_msg = res.stderr.strip() or f"squeue failed with exit code {res.returncode}"
            return CallToolResult(
                content=[TextContent(text=f"Error querying Slurm queue: {err_msg}")],
                isError=True,
            )

        jobs = []
        for line in res.stdout.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split("|")
            if len(parts) < 11:
                parts += [""] * (11 - len(parts))
            jobs.append({
                "job_id": parts[0].strip(),
                "name": parts[1].strip(),
                "user": parts[2].strip(),
                "state": parts[3].strip(),
                "time_used": parts[4].strip(),
                "time_limit": parts[5].strip(),
                "nodes": parts[6].strip(),
                "cpus": parts[7].strip(),
                "reason": parts[8].strip(),
                "work_dir": parts[9].strip(),
                "nodelist": parts[10].strip(),
            })

        output_data = {
            "total_jobs": len(jobs),
            "jobs": jobs,
            "filter": {
                "user": user or None,
                "partition": partition or None,
            },
        }
        return CallToolResult(
            content=[TextContent(text=json.dumps(output_data, indent=2))]
        )
    except FileNotFoundError:
        # Slurm not installed locally
        return CallToolResult(
            content=[
                TextContent(
                    text="Error: Slurm command 'squeue' is not available in local PATH. "
                    "Ensure Slurm client is installed or connect to an HPC cluster via SSH."
                )
            ],
            isError=True,
        )
    except Exception as exc:
        return CallToolResult(
            content=[TextContent(text=f"Error querying Slurm queue: {exc}")],
            isError=True,
        )


def _tool_slurm_submit(arguments: Dict[str, Any]) -> CallToolResult:
    """Handler for hpc_slurm_submit."""
    script_path = str(arguments.get("script_path", "") or "").strip()
    script_content = str(arguments.get("script_content", "") or "")

    content = script_content
    if not content and script_path:
        p = Path(script_path).resolve()
        if not p.is_file():
            return CallToolResult(
                content=[TextContent(text=f"Error: Script file not found: {script_path}")],
                isError=True,
            )
        try:
            content = p.read_text(encoding="utf-8")
        except Exception as exc:
            return CallToolResult(
                content=[TextContent(text=f"Error reading script file {script_path}: {exc}")],
                isError=True,
            )

    if not content.strip():
        return CallToolResult(
            content=[TextContent(text="Error: Neither script_path nor script_content was provided.")],
            isError=True,
        )

    # Validate header
    lines = content.strip().splitlines()
    has_shebang = any(line.startswith("#!") for line in lines[:3])
    if not has_shebang:
        return CallToolResult(
            content=[
                TextContent(
                    text="Error: Validation failed: Missing shebang (e.g. #!/bin/bash) in job script header."
                )
            ],
            isError=True,
        )

    directives = [line for line in lines if line.startswith("#SBATCH")]

    try:
        res = subprocess.run(
            ["sbatch"],
            input=content,
            text=True,
            capture_output=True,
            timeout=15,
        )
        if res.returncode == 0:
            out = res.stdout.strip()
            match = re.search(r"Submitted batch job (\d+)", out)
            job_id = match.group(1) if match else out
            result_data = {
                "success": True,
                "job_id": job_id,
                "output": out,
                "sbatch_directives_count": len(directives),
            }
            return CallToolResult(
                content=[TextContent(text=json.dumps(result_data, indent=2))]
            )
        err = res.stderr.strip() or f"sbatch exit code {res.returncode}"
        return CallToolResult(
            content=[TextContent(text=f"Error submitting batch job: {err}")],
            isError=True,
        )
    except FileNotFoundError:
        return CallToolResult(
            content=[
                TextContent(
                    text="Error: 'sbatch' command not found on local system. "
                    "Cannot submit Slurm batch job directly without Slurm installation or active cluster session."
                )
            ],
            isError=True,
        )
    except Exception as exc:
        return CallToolResult(
            content=[TextContent(text=f"Error during sbatch execution: {exc}")],
            isError=True,
        )


def _tool_slurm_cancel(arguments: Dict[str, Any]) -> CallToolResult:
    """Handler for hpc_slurm_cancel."""
    raw_job_id = str(arguments.get("job_id", "") or "").strip()
    signal = str(arguments.get("signal", "") or "").strip()

    if not raw_job_id:
        return CallToolResult(
            content=[TextContent(text="Error: 'job_id' is required.")],
            isError=True,
        )

    if not re.match(r"^[0-9]+(?:_[0-9]+)?$", raw_job_id):
        return CallToolResult(
            content=[TextContent(text=f"Error: Invalid Slurm job ID: {raw_job_id!r}")],
            isError=True,
        )

    cmd = ["scancel"]
    if signal:
        if not re.match(r"^[A-Za-z0-9]+$", signal):
            return CallToolResult(
                content=[TextContent(text=f"Error: Invalid signal: {signal!r}")],
                isError=True,
            )
        cmd.extend(["-s", signal])
    cmd.append(raw_job_id)

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            result_data = {
                "success": True,
                "job_id": raw_job_id,
                "signal": signal or None,
                "message": f"Job {raw_job_id} cancellation signal sent successfully.",
            }
            return CallToolResult(
                content=[TextContent(text=json.dumps(result_data, indent=2))]
            )
        err = res.stderr.strip() or f"scancel exited with code {res.returncode}"
        return CallToolResult(
            content=[TextContent(text=f"Error cancelling job {raw_job_id}: {err}")],
            isError=True,
        )
    except FileNotFoundError:
        return CallToolResult(
            content=[
                TextContent(
                    text="Error: 'scancel' command not found on local system. "
                    "Ensure Slurm is installed or configure an SSH connection."
                )
            ],
            isError=True,
        )
    except Exception as exc:
        return CallToolResult(
            content=[TextContent(text=f"Error executing scancel: {exc}")],
            isError=True,
        )


def _tool_slurm_log(arguments: Dict[str, Any]) -> CallToolResult:
    """Handler for hpc_slurm_log."""
    log_path = str(arguments.get("log_path", "") or "").strip()
    lines_count = int(arguments.get("lines", 50) or 50)

    if not log_path:
        return CallToolResult(
            content=[TextContent(text="Error: 'log_path' argument is required.")],
            isError=True,
        )

    if lines_count <= 0:
        lines_count = 50

    target = Path(log_path).resolve()
    if not target.exists():
        return CallToolResult(
            content=[TextContent(text=f"Error: Log file not found: {log_path}")],
            isError=True,
        )
    if not target.is_file():
        return CallToolResult(
            content=[TextContent(text=f"Error: Path is not a regular file: {log_path}")],
            isError=True,
        )

    try:
        # Read the last N lines
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        tail_lines = all_lines[-lines_count:] if len(all_lines) > lines_count else all_lines
        log_text = "".join(tail_lines)

        result_data = {
            "path": str(target),
            "total_lines": len(all_lines),
            "lines_returned": len(tail_lines),
            "content": log_text,
        }
        return CallToolResult(
            content=[TextContent(text=json.dumps(result_data, indent=2))]
        )
    except Exception as exc:
        return CallToolResult(
            content=[TextContent(text=f"Error reading log file {log_path}: {exc}")],
            isError=True,
        )


def _tool_validate_qe(arguments: Dict[str, Any]) -> CallToolResult:
    """Handler for hpc_validate_qe."""
    input_path = str(arguments.get("input_path", "") or "").strip()
    input_content = str(arguments.get("input_content", "") or "")

    content = input_content
    if not content and input_path:
        p = Path(input_path).resolve()
        if not p.is_file():
            return CallToolResult(
                content=[TextContent(text=f"Error: Input file not found: {input_path}")],
                isError=True,
            )
        try:
            content = p.read_text(encoding="utf-8")
        except Exception as exc:
            return CallToolResult(
                content=[TextContent(text=f"Error reading file {input_path}: {exc}")],
                isError=True,
            )

    if not content.strip():
        return CallToolResult(
            content=[TextContent(text="Error: Both input_path and input_content are empty.")],
            isError=True,
        )

    # Check mandatory namelists
    upper = content.upper()
    mandatory_namelists = ["&CONTROL", "&SYSTEM", "&ELECTRONS"]
    missing = [nl for nl in mandatory_namelists if nl not in upper]

    from hpc_studio.qe.parser import parse_qe_input
    from hpc_studio.qe.validator import QEValidator

    try:
        qe_input = parse_qe_input(content)
        issues = QEValidator.validate(qe_input)

        errors = [str(i) for i in issues if i.is_error()]
        warnings = [str(i) for i in issues if i.is_warning()]

        for m in missing:
            errors.append(f"[ERROR] Namelist: Missing mandatory namelist {m}")

        is_valid = len(errors) == 0

        # Check ecutwfc and k-points specifically
        ecutwfc = getattr(qe_input.system, "ecutwfc", None)
        k_points_mode = getattr(qe_input.k_points, "mode", None) if qe_input.k_points else None

        result_data = {
            "valid": is_valid,
            "errors": errors,
            "warnings": warnings,
            "summary": {
                "calculation": getattr(qe_input.control, "calculation", None),
                "ecutwfc": ecutwfc,
                "nat": getattr(qe_input.system, "nat", None),
                "ntyp": getattr(qe_input.system, "ntyp", None),
                "ibrav": getattr(qe_input.system, "ibrav", None),
                "k_points_mode": k_points_mode,
            },
        }
        return CallToolResult(
            content=[TextContent(text=json.dumps(result_data, indent=2))]
        )
    except Exception as exc:
        return CallToolResult(
            content=[TextContent(text=f"Error parsing Quantum ESPRESSO input: {exc}")],
            isError=True,
        )


def _tool_inspect_structure(arguments: Dict[str, Any]) -> CallToolResult:
    """Handler for hpc_inspect_structure."""
    file_path = str(arguments.get("file_path", "") or "").strip()
    file_content = str(arguments.get("file_content", "") or "")
    format_type = str(arguments.get("format", "") or "").lower().strip()

    content = file_content
    path_obj = None
    if file_path:
        path_obj = Path(file_path).resolve()
        if not path_obj.is_file():
            return CallToolResult(
                content=[TextContent(text=f"Error: Structure file not found: {file_path}")],
                isError=True,
            )
        if not content:
            try:
                content = path_obj.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:
                return CallToolResult(
                    content=[TextContent(text=f"Error reading file {file_path}: {exc}")],
                    isError=True,
                )

    if not content.strip():
        return CallToolResult(
            content=[TextContent(text="Error: Both file_path and file_content are empty.")],
            isError=True,
        )

    # Determine format
    if not format_type:
        if path_obj:
            ext = path_obj.suffix.lower()
            if ext in (".cif",):
                format_type = "cif"
            elif ext in (".xyz",):
                format_type = "xyz"
        if not format_type:
            if "data_" in content or "_cell_length" in content:
                format_type = "cif"
            else:
                format_type = "xyz"

    try:
        from hpc_studio.crystallography.parsers.cif import read_cif
        from hpc_studio.crystallography.parsers.xyz import read_xyz

        if format_type == "cif":
            structure = read_cif(content)
        elif format_type == "xyz":
            structure = read_xyz(content)
        else:
            return CallToolResult(
                content=[
                    TextContent(
                        text=f"Error: Unsupported format '{format_type}'. Supported formats are 'cif' and 'xyz'."
                    )
                ],
                isError=True,
            )

        lattice_data = None
        if structure.lattice is not None:
            lat = structure.lattice
            lattice_data = {
                "a": round(float(lat.a), 6),
                "b": round(float(lat.b), 6),
                "c": round(float(lat.c), 6),
                "alpha": round(float(lat.alpha), 4),
                "beta": round(float(lat.beta), 4),
                "gamma": round(float(lat.gamma), 4),
                "volume": round(float(lat.volume), 4),
                "matrix": [
                    [round(float(v), 6) for v in row]
                    for row in lat.matrix.tolist()
                ],
            }

        # Atom count and element breakdown
        counts: Dict[str, int] = {}
        for atom in structure.atoms:
            counts[atom.symbol] = counts.get(atom.symbol, 0) + 1

        result_data = {
            "format": format_type,
            "formula": structure.formula(),
            "total_atoms": len(structure.atoms),
            "elements": counts,
            "lattice": lattice_data,
        }
        return CallToolResult(
            content=[TextContent(text=json.dumps(result_data, indent=2))]
        )
    except Exception as exc:
        return CallToolResult(
            content=[TextContent(text=f"Error parsing crystallographic structure: {exc}")],
            isError=True,
        )


def _tool_list_clusters(arguments: Dict[str, Any]) -> CallToolResult:
    """Handler for hpc_list_clusters."""
    from hpc_studio.ssh.config_parser import SSHConfigParser

    clusters: List[Dict[str, Any]] = []

    # Preset: Quantum Mobile
    qm_preset = {
        "name": "Quantum Mobile",
        "alias": "quantum-mobile",
        "hostname": "127.0.0.1",
        "port": 2222,
        "user": "max",
        "description": "Quantum Mobile VM simulation environment (Quantum ESPRESSO, AiiDA, Slurm)",
        "source": "preset",
    }
    clusters.append(qm_preset)

    # Read ~/.ssh/config
    ssh_config_path = Path.home() / ".ssh" / "config"
    if ssh_config_path.is_file():
        try:
            parser = SSHConfigParser()
            entries = parser.load_file(ssh_config_path)
            for entry in entries:
                clusters.append({
                    "name": entry.display_name,
                    "alias": entry.host,
                    "hostname": entry.hostname,
                    "port": entry.port,
                    "user": entry.user,
                    "identity_file": entry.identity_file,
                    "source": "ssh_config",
                })
        except Exception as exc:
            logger.warning("Error reading SSH config in hpc_list_clusters: %s", exc)

    return CallToolResult(
        content=[TextContent(text=json.dumps({"total_clusters": len(clusters), "clusters": clusters}, indent=2))]
    )


def _tool_sftp_list(arguments: Dict[str, Any]) -> CallToolResult:
    """Handler for hpc_sftp_list."""
    remote_path = str(arguments.get("path", ".") or ".").strip()
    limit = int(arguments.get("limit", 100) or 100)

    # Fallback to local filesystem if no active SFTP session
    norm_path = Path(remote_path).expanduser().resolve()
    if not norm_path.exists():
        return CallToolResult(
            content=[TextContent(text=f"Error: Path does not exist: {remote_path}")],
            isError=True,
        )

    if not norm_path.is_dir():
        return CallToolResult(
            content=[TextContent(text=f"Error: Path is not a directory: {remote_path}")],
            isError=True,
        )

    try:
        entries = []
        for p in list(norm_path.iterdir())[:limit]:
            is_directory = p.is_dir()
            size = p.stat().st_size if not is_directory else 0
            mtime = int(p.stat().st_mtime)
            entries.append({
                "name": p.name,
                "path": str(p),
                "is_dir": is_directory,
                "size_bytes": size,
                "mtime": mtime,
            })

        # Sort dirs first then files
        entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))

        result_data = {
            "path": str(norm_path),
            "total_entries": len(entries),
            "entries": entries,
        }
        return CallToolResult(
            content=[TextContent(text=json.dumps(result_data, indent=2))]
        )
    except Exception as exc:
        return CallToolResult(
            content=[TextContent(text=f"Error listing directory {remote_path}: {exc}")],
            isError=True,
        )


def _tool_sftp_read(arguments: Dict[str, Any]) -> CallToolResult:
    """Handler for hpc_sftp_read."""
    remote_path = str(arguments.get("path", "") or "").strip()
    offset = int(arguments.get("offset", 1) or 1)
    limit = int(arguments.get("limit", 200) or 200)

    if not remote_path:
        return CallToolResult(
            content=[TextContent(text="Error: 'path' argument is required.")],
            isError=True,
        )

    target = Path(remote_path).expanduser().resolve()
    if not target.exists():
        return CallToolResult(
            content=[TextContent(text=f"Error: Remote file not found: {remote_path}")],
            isError=True,
        )
    if not target.is_file():
        return CallToolResult(
            content=[TextContent(text=f"Error: Path is not a regular file: {remote_path}")],
            isError=True,
        )

    try:
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        total_lines = len(lines)
        start_idx = max(0, offset - 1)
        end_idx = min(total_lines, start_idx + limit)

        selected_lines = lines[start_idx:end_idx]
        content_text = "".join(selected_lines)

        result_data = {
            "path": str(target),
            "total_lines": total_lines,
            "offset": start_idx + 1,
            "lines_read": len(selected_lines),
            "content": content_text,
        }
        return CallToolResult(
            content=[TextContent(text=json.dumps(result_data, indent=2))]
        )
    except Exception as exc:
        return CallToolResult(
            content=[TextContent(text=f"Error reading remote file {remote_path}: {exc}")],
            isError=True,
        )


# --- Registration Helper ---


def register_all_tools(registry: Optional[ToolRegistry] = None) -> ToolRegistry:
    """Register all 9 HPC Studio MCP tools with the registry."""
    reg = registry or ToolRegistry()

    # 1. hpc_slurm_queue
    reg.register(
        Tool(
            name="hpc_slurm_queue",
            description="Query the Slurm workload manager job queue with optional partition and user filtering.",
            inputSchema=ToolInputSchema(
                properties={
                    "partition": {
                        "type": "string",
                        "description": "Optional partition name to filter jobs.",
                    },
                    "user": {
                        "type": "string",
                        "description": "Optional username to filter jobs.",
                    },
                },
                required=[],
            ),
        ),
        _tool_slurm_queue,
    )

    # 2. hpc_slurm_submit
    reg.register(
        Tool(
            name="hpc_slurm_submit",
            description="Validate and submit a Slurm batch job script to the cluster queue via sbatch.",
            inputSchema=ToolInputSchema(
                properties={
                    "script_path": {
                        "type": "string",
                        "description": "Path to the .sbatch or .sh job script file.",
                    },
                    "script_content": {
                        "type": "string",
                        "description": "Direct text content of the batch job script.",
                    },
                },
                required=[],
            ),
        ),
        _tool_slurm_submit,
    )

    # 3. hpc_slurm_cancel
    reg.register(
        Tool(
            name="hpc_slurm_cancel",
            description="Cancel a running or pending Slurm job using scancel with optional POSIX signal.",
            inputSchema=ToolInputSchema(
                properties={
                    "job_id": {
                        "type": "string",
                        "description": "Slurm job ID to cancel (e.g. '12345' or '12345_1').",
                    },
                    "signal": {
                        "type": "string",
                        "description": "Optional signal name or number to send (e.g. 'SIGTERM', '9').",
                    },
                },
                required=["job_id"],
            ),
        ),
        _tool_slurm_cancel,
    )

    # 4. hpc_slurm_log
    reg.register(
        Tool(
            name="hpc_slurm_log",
            description="Read execution output or error log files for a Slurm calculation job.",
            inputSchema=ToolInputSchema(
                properties={
                    "log_path": {
                        "type": "string",
                        "description": "Absolute or relative path to the Slurm stdout/stderr log file.",
                    },
                    "lines": {
                        "type": "integer",
                        "description": "Number of tail lines to retrieve (default: 50).",
                    },
                },
                required=["log_path"],
            ),
        ),
        _tool_slurm_log,
    )

    # 5. hpc_validate_qe
    reg.register(
        Tool(
            name="hpc_validate_qe",
            description="Strict syntax and semantic validation of Quantum ESPRESSO pw.x input cards and namelists (&CONTROL, &SYSTEM, &ELECTRONS, ecutwfc, k-points).",
            inputSchema=ToolInputSchema(
                properties={
                    "input_path": {
                        "type": "string",
                        "description": "Path to Quantum ESPRESSO input file (.in, .pwi).",
                    },
                    "input_content": {
                        "type": "string",
                        "description": "Direct string content of Quantum ESPRESSO input deck.",
                    },
                },
                required=[],
            ),
        ),
        _tool_validate_qe,
    )

    # 6. hpc_inspect_structure
    reg.register(
        Tool(
            name="hpc_inspect_structure",
            description="Crystallographic analysis of .cif and .xyz structure files (extracts lattice vectors, a,b,c, alpha,beta,gamma, volume, atom counts, chemical formula).",
            inputSchema=ToolInputSchema(
                properties={
                    "file_path": {
                        "type": "string",
                        "description": "Path to structure file (.cif or .xyz).",
                    },
                    "file_content": {
                        "type": "string",
                        "description": "Direct text content of CIF or XYZ file.",
                    },
                    "format": {
                        "type": "string",
                        "enum": ["cif", "xyz"],
                        "description": "Optional explicit file format ('cif' or 'xyz').",
                    },
                },
                required=[],
            ),
        ),
        _tool_inspect_structure,
    )

    # 7. hpc_list_clusters
    reg.register(
        Tool(
            name="hpc_list_clusters",
            description="List configured HPC clusters from ~/.ssh/config and presets like Quantum Mobile (127.0.0.1:2222).",
            inputSchema=ToolInputSchema(
                properties={},
                required=[],
            ),
        ),
        _tool_list_clusters,
    )

    # 8. hpc_sftp_list
    reg.register(
        Tool(
            name="hpc_sftp_list",
            description="Navigate and list files and directories in remote HPC cluster filesystems.",
            inputSchema=ToolInputSchema(
                properties={
                    "path": {
                        "type": "string",
                        "description": "Remote directory path to list (default: '.').",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of directory entries to return (default: 100).",
                    },
                },
                required=[],
            ),
        ),
        _tool_sftp_list,
    )

    # 9. hpc_sftp_read
    reg.register(
        Tool(
            name="hpc_sftp_read",
            description="Read file contents from remote cluster workspace with line pagination.",
            inputSchema=ToolInputSchema(
                properties={
                    "path": {
                        "type": "string",
                        "description": "Remote file path to read.",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "1-based starting line number (default: 1).",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of lines to read (default: 200).",
                    },
                },
                required=["path"],
            ),
        ),
        _tool_sftp_read,
    )

    return reg
