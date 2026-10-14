"""Workspace and environment status route for HPC Studio server."""

import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List
from fastapi import APIRouter, Depends

from hpc_studio.server.auth import TokenVerifier
from hpc_studio.server.config import ServerConfig


def create_workspace_router(config: ServerConfig, verifier: TokenVerifier) -> APIRouter:
    """Create workspace router with injected configuration and token verifier."""
    r = APIRouter()

    @r.get("/api/workspace")
    async def get_workspace(_: str = Depends(verifier)) -> Dict[str, Any]:
        """Return workspace directory details, file counts and environment status."""
        workspace_path = config.workspace_dir
        exists = workspace_path.exists()
        is_dir = workspace_path.is_dir() if exists else False

        entries: List[Dict[str, Any]] = []
        file_count = 0
        dir_count = 0

        if exists and is_dir:
            try:
                # Scan top-level items for responsiveness
                with os.scandir(workspace_path) as it:
                    for entry in it:
                        try:
                            is_entry_dir = entry.is_dir(follow_symlinks=False)
                            if is_entry_dir:
                                dir_count += 1
                            else:
                                file_count += 1

                            if len(entries) < 50:
                                stat = entry.stat(follow_symlinks=False)
                                entries.append(
                                    {
                                        "name": entry.name,
                                        "is_dir": is_entry_dir,
                                        "size": stat.st_size if not is_entry_dir else 0,
                                        "modified_at": stat.st_mtime,
                                    }
                                )
                        except (OSError, PermissionError):
                            continue
            except (OSError, PermissionError):
                pass

        return {
            "workspace_path": str(workspace_path),
            "exists": exists,
            "is_directory": is_dir,
            "stats": {
                "top_level_files": file_count,
                "top_level_directories": dir_count,
                "listed_entries": len(entries),
            },
            "environment": {
                "python_executable": sys.executable,
                "is_virtual_env": sys.prefix != getattr(sys, "base_prefix", sys.prefix),
                "slurm_available": shutil.which("sbatch") is not None,
                "ssh_available": shutil.which("ssh") is not None,
                "git_repo": (workspace_path / ".git").exists() if exists else False,
                "cwd": str(Path.cwd()),
            },
            "entries": entries,
        }

    return r
