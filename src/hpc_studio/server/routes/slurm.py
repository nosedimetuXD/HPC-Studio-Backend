"""FastAPI router for Slurm workload management and job lifecycle."""

from __future__ import annotations

import logging
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from hpc_studio.server.auth import TokenVerifier
from hpc_studio.server.config import ServerConfig
from hpc_studio.slurm.client import SlurmClient
from hpc_studio.slurm.models import SlurmJob
from hpc_studio.ssh.client import SSHClientManager

logger = logging.getLogger("hpc_studio.server.slurm")


class SubmitJobRequest(BaseModel):
    """Payload to submit a batch job to Slurm."""

    script_path: Optional[str] = Field(None, description="Path to batch script file (remote or local)")
    script_content: Optional[str] = Field(None, description="Batch script content string")
    work_dir: Optional[str] = Field(None, description="Optional working directory for execution")


def _run_local_command(args: List[str], timeout: int = 15) -> tuple[int, str, str]:
    """Execute local command safely returning (exit_code, stdout, stderr)."""
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"Command timed out after {timeout} seconds"
    except Exception as exc:
        return -1, "", str(exc)


def create_slurm_router(config: ServerConfig, verifier: TokenVerifier) -> APIRouter:
    """Create Slurm router with injected configuration and token verifier."""
    router = APIRouter(prefix="/api/slurm", tags=["slurm"])

    @router.get("/jobs", response_model=List[Dict[str, Any]])
    async def list_jobs(
        request: Request,
        user: Optional[str] = Query(None, description="Filter by Slurm user"),
        partition: Optional[str] = Query(None, description="Filter by partition"),
        _: str = Depends(verifier),
    ) -> List[Dict[str, Any]]:
        """List Slurm jobs via connected SSH cluster or local squeue if available."""
        ssh_mgr: Optional[SSHClientManager] = getattr(request.app.state, "ssh_manager", None)

        if ssh_mgr and ssh_mgr.is_connected:
            client = SlurmClient(ssh_manager=ssh_mgr)
            jobs: List[SlurmJob] = client.get_jobs(user=user, partition=partition)
            return [asdict(j) for j in jobs]

        # Check local squeue if not connected via SSH
        if shutil.which("squeue") is not None:
            cmd = ["squeue", '-o', "%i|%j|%u|%T|%M|%l|%D|%C|%R|%Z|%N", "--noheader"]
            if user:
                clean_user = user.strip()
                if re.match(r"^[A-Za-z0-9_.-]+$", clean_user):
                    cmd.extend(["-u", clean_user])
            if partition:
                clean_part = partition.strip()
                if re.match(r"^[A-Za-z0-9_.-]+$", clean_part):
                    cmd.extend(["-p", clean_part])

            code, stdout, stderr = _run_local_command(cmd)
            if code == 0:
                jobs = []
                from hpc_studio.slurm.models import JobState
                for line in stdout.strip().splitlines():
                    parts = line.strip().split("|")
                    if len(parts) < 11:
                        parts = parts + [""] * (11 - len(parts))
                    try:
                        nodes = int(parts[6].strip())
                    except Exception:
                        nodes = 1
                    try:
                        cpus = int(parts[7].strip())
                    except Exception:
                        cpus = 1
                    raw_st = parts[3].strip()
                    job = SlurmJob(
                        job_id=parts[0].strip(),
                        name=parts[1].strip(),
                        user=parts[2].strip(),
                        partition=partition or "",
                        state=JobState.from_string(raw_st),
                        time_used=parts[4].strip() or "00:00",
                        time_limit=parts[5].strip() or "UNLIMITED",
                        nodes=nodes,
                        cpus=cpus,
                        reason=parts[8].strip(),
                        work_dir=parts[9].strip(),
                        nodelist=parts[10].strip(),
                        raw_state=raw_st,
                    )
                    jobs.append(asdict(job))
                return jobs

        return []

    @router.post("/submit")
    async def submit_job(
        payload: SubmitJobRequest,
        request: Request,
        _: str = Depends(verifier),
    ) -> Dict[str, Any]:
        """Submit a batch job script using sbatch via SSH or locally."""
        if not payload.script_path and not payload.script_content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Either script_path or script_content must be provided.",
            )

        ssh_mgr: Optional[SSHClientManager] = getattr(request.app.state, "ssh_manager", None)
        is_ssh = bool(ssh_mgr and ssh_mgr.is_connected)
        has_local_sbatch = shutil.which("sbatch") is not None

        if not is_ssh and not has_local_sbatch:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No active SSH connection and local 'sbatch' command is not available.",
            )

        # Execute submission
        job_id: Optional[str] = None
        output_msg: str = ""

        if is_ssh and ssh_mgr:
            # Build sbatch command on remote host
            if payload.script_content:
                # Pipe script content to sbatch
                # Prevent shell escaping problems by writing to remote tmp or piping with EOF
                escaped_script = payload.script_content.replace("'", "'\"'\"'")
                cd_cmd = f"cd {shlex.quote(payload.work_dir)} && " if payload.work_dir else ""
                cmd = f"{cd_cmd}echo '{escaped_script}' | sbatch"
            else:
                cd_cmd = f"cd {shlex.quote(payload.work_dir)} && " if payload.work_dir else ""
                cmd = f"{cd_cmd}sbatch {shlex.quote(payload.script_path)}"

            result = ssh_mgr.execute_command(cmd, timeout=30)
            if not result.success:
                logger.error("sbatch failed: %s", result.stderr)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"sbatch submission failed: {result.stderr or result.stdout}",
                )
            output_msg = result.stdout.strip()

        else:
            # Local submission
            if payload.script_content:
                proc = subprocess.Popen(
                    ["sbatch"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    cwd=payload.work_dir,
                )
                stdout, stderr = proc.communicate(input=payload.script_content, timeout=30)
                if proc.returncode != 0:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"sbatch submission failed: {stderr or stdout}",
                    )
                output_msg = stdout.strip()
            else:
                code, stdout, stderr = _run_local_command(
                    ["sbatch", payload.script_path], timeout=30
                )
                if code != 0:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"sbatch submission failed: {stderr or stdout}",
                    )
                output_msg = stdout.strip()

        # Parse job id from output: "Submitted batch job 12345"
        match = re.search(r"Submitted\s+batch\s+job\s+([0-9]+)", output_msg, re.IGNORECASE)
        if match:
            job_id = match.group(1)

        return {
            "status": "submitted",
            "job_id": job_id,
            "message": output_msg,
        }

    @router.post("/jobs/{job_id}/cancel")
    async def cancel_job(
        job_id: str,
        request: Request,
        signal: Optional[str] = Query(None, description="Optional signal to send"),
        _: str = Depends(verifier),
    ) -> Dict[str, Any]:
        """Cancel a running or queued Slurm job using scancel."""
        try:
            clean_id = SlurmClient._validate_job_id(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

        ssh_mgr: Optional[SSHClientManager] = getattr(request.app.state, "ssh_manager", None)
        if ssh_mgr and ssh_mgr.is_connected:
            client = SlurmClient(ssh_manager=ssh_mgr)
            success, msg = client.cancel_job(clean_id, signal=signal)
            if not success:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Failed to cancel job {clean_id}: {msg}",
                )
            return {"status": "cancelled", "job_id": clean_id, "message": msg}

        # Check local scancel
        if shutil.which("scancel") is not None:
            cmd = ["scancel"]
            if signal:
                if not re.match(r"^[A-Za-z0-9]+$", signal):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Invalid signal name.",
                    )
                cmd.extend(["-s", signal])
            cmd.append(clean_id)
            code, stdout, stderr = _run_local_command(cmd)
            if code != 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Failed to cancel job {clean_id}: {stderr or stdout}",
                )
            return {"status": "cancelled", "job_id": clean_id, "message": stdout.strip()}

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No active SSH connection and local 'scancel' command is not available.",
        )

    @router.get("/jobs/{job_id}/log")
    async def get_job_log(
        job_id: str,
        request: Request,
        lines: int = Query(100, ge=1, le=5000, description="Number of tail lines to retrieve"),
        log_path: Optional[str] = Query(None, description="Explicit log path if known"),
        _: str = Depends(verifier),
    ) -> Dict[str, Any]:
        """Fetch the latest output log lines for a Slurm job."""
        try:
            clean_id = SlurmClient._validate_job_id(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

        ssh_mgr: Optional[SSHClientManager] = getattr(request.app.state, "ssh_manager", None)
        is_ssh = bool(ssh_mgr and ssh_mgr.is_connected)

        target_file = log_path
        # If target_file is not specified, attempt to inspect job via scontrol
        if not target_file:
            details: Dict[str, str] = {}
            if is_ssh and ssh_mgr:
                client = SlurmClient(ssh_manager=ssh_mgr)
                details = client.get_job_details(clean_id)
            elif shutil.which("scontrol") is not None:
                code, stdout, _ = _run_local_command(["scontrol", "show", "job", "-d", clean_id])
                if code == 0:
                    pattern = re.compile(r'(\b[A-Za-z0-9_]+)=([^\s=]+(?:\s+(?![A-Za-z0-9_]+=)[^\s=]+)*)')
                    for line in stdout.splitlines():
                        for match in pattern.finditer(line):
                            k, v = match.groups()
                            details[k] = v.strip()

            target_file = details.get("StdOut") or details.get("StdErr")

            # Default fallback convention: slurm-<job_id>.out
            if not target_file or target_file.lower() == "none":
                work_dir = details.get("WorkDir", ".")
                target_file = f"{work_dir}/slurm-{clean_id}.out"

        # Read the file
        if is_ssh and ssh_mgr:
            cmd = f"tail -n {lines} {shlex.quote(target_file)}"
            res = ssh_mgr.execute_command(cmd, timeout=10)
            if not res.success:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Could not read log file '{target_file}': {res.stderr or 'File not found'}",
                )
            return {
                "job_id": clean_id,
                "log_path": target_file,
                "lines": lines,
                "content": res.stdout,
            }
        else:
            p = Path(target_file)
            if not p.is_file():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Log file not found: {target_file}",
                )
            code, stdout, stderr = _run_local_command(["tail", "-n", str(lines), str(p)])
            if code != 0:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to read log: {stderr}",
                )
            return {
                "job_id": clean_id,
                "log_path": target_file,
                "lines": lines,
                "content": stdout,
            }

    return router
