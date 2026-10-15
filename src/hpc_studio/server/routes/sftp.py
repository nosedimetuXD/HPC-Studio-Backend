"""FastAPI router for SFTP remote file navigation, uploads, and downloads."""

from __future__ import annotations

import logging
import os
import posixpath
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from hpc_studio.server.auth import TokenVerifier
from hpc_studio.server.config import ServerConfig
from hpc_studio.sftp.client import (
    SFTPClientManager,
    SFTPError,
    SFTPFileNotFoundError,
)
from hpc_studio.sftp.models import RemoteFileInfo
from hpc_studio.ssh.client import SSHClientManager

logger = logging.getLogger("hpc_studio.server.sftp")


class DownloadRequest(BaseModel):
    """Payload to download remote file to local path."""

    remote_path: str = Field(..., description="Path of file on remote cluster")
    local_path: str = Field(..., description="Destination path on local filesystem")


class UploadRequest(BaseModel):
    """Payload to upload local file or content to remote path."""

    local_path: Optional[str] = Field(None, description="Source path on local filesystem")
    remote_path: str = Field(..., description="Destination path on remote cluster")
    content: Optional[str] = Field(None, description="Optional raw string/text content to write directly")


def _get_or_init_sftp_manager(request: Request) -> SFTPClientManager:
    """Retrieve existing SFTPClientManager or create one from the active SSH connection."""
    sftp_mgr: Optional[SFTPClientManager] = getattr(request.app.state, "sftp_manager", None)
    if sftp_mgr and sftp_mgr.is_connected:
        return sftp_mgr

    ssh_mgr: Optional[SSHClientManager] = getattr(request.app.state, "ssh_manager", None)
    if not ssh_mgr or not ssh_mgr.is_connected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SSH client is not connected. Connect to a cluster first.",
        )

    try:
        raw_sftp = ssh_mgr.open_sftp()
        username = ssh_mgr.current_entry.user if ssh_mgr.current_entry else None
        sftp_mgr = SFTPClientManager(sftp_client=raw_sftp, cluster_username=username)
        request.app.state.sftp_manager = sftp_mgr
        return sftp_mgr
    except Exception as exc:
        logger.error("Failed to initialize SFTP session: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not open SFTP session over SSH: {exc}",
        )


def create_sftp_router(config: ServerConfig, verifier: TokenVerifier) -> APIRouter:
    """Create SFTP router with injected configuration and token verifier."""
    router = APIRouter(prefix="/api/sftp", tags=["sftp"])

    @router.get("/list", response_model=List[Dict[str, Any]])
    async def list_files(
        request: Request,
        path: str = Query("/", description="Remote path to list"),
        refresh: bool = Query(False, description="Bypass in-memory directory cache"),
        _: str = Depends(verifier),
    ) -> List[Dict[str, Any]]:
        """List files and directories at remote path with sizes, permissions and mtime."""
        sftp_mgr = _get_or_init_sftp_manager(request)
        try:
            items: List[RemoteFileInfo] = sftp_mgr.listdir_attr(path=path, use_cache=not refresh)
            result: List[Dict[str, Any]] = []
            for item in items:
                d = asdict(item)
                d["permissions_str"] = item.permissions_str
                result.append(d)
            return result
        except SFTPFileNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
        except (SFTPError, Exception) as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to list remote path {path!r}: {exc}",
            )

    @router.post("/upload")
    async def upload_file(
        payload: UploadRequest,
        request: Request,
        _: str = Depends(verifier),
    ) -> Dict[str, Any]:
        """Upload a local file or string content to remote path."""
        sftp_mgr = _get_or_init_sftp_manager(request)
        raw_sftp = sftp_mgr.raw_client
        if not raw_sftp:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="SFTP client is not active.",
            )

        target_remote = sftp_mgr.normalize_path(payload.remote_path)
        parent = posixpath.dirname(target_remote)
        if parent and not sftp_mgr.exists(parent):
            sftp_mgr.makedirs(parent)

        # Handle direct content upload
        if payload.content is not None:
            try:
                data_bytes = payload.content.encode("utf-8")
                with raw_sftp.open(target_remote, "wb") as remote_f:
                    remote_f.write(data_bytes)
                sftp_mgr.clear_cache(parent)
                return {
                    "status": "uploaded",
                    "remote_path": target_remote,
                    "bytes_written": len(data_bytes),
                }
            except Exception as exc:
                logger.error("Failed to write content to %s: %s", target_remote, exc)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Upload failed: {exc}",
                )

        # Handle local filesystem path upload
        if payload.local_path:
            p_local = Path(payload.local_path).resolve()
            if not p_local.is_file():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Local file does not exist: {payload.local_path}",
                )

            try:
                raw_sftp.put(str(p_local), target_remote)
                sftp_mgr.clear_cache(parent)
                return {
                    "status": "uploaded",
                    "local_path": str(p_local),
                    "remote_path": target_remote,
                    "size": p_local.stat().st_size,
                }
            except Exception as exc:
                logger.error("Failed to put %s to %s: %s", p_local, target_remote, exc)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Upload failed: {exc}",
                )

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either 'local_path' or 'content' must be provided.",
        )

    @router.post("/download")
    async def download_file(
        payload: DownloadRequest,
        request: Request,
        _: str = Depends(verifier),
    ) -> Dict[str, Any]:
        """Download remote file to local destination path."""
        sftp_mgr = _get_or_init_sftp_manager(request)
        raw_sftp = sftp_mgr.raw_client
        if not raw_sftp:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="SFTP client is not active.",
            )

        norm_remote = sftp_mgr.normalize_path(payload.remote_path)
        if not sftp_mgr.exists(norm_remote):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Remote path does not exist: {norm_remote}",
            )

        local_p = Path(payload.local_path).resolve()
        if local_p.is_symlink():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Destination path is an insecure symlink.",
            )

        # Create parent directories
        local_p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

        try:
            raw_sftp.get(norm_remote, str(local_p))
            if hasattr(os, "chmod") and local_p.exists():
                try:
                    os.chmod(str(local_p), 0o600)
                except OSError:
                    pass
            return {
                "status": "downloaded",
                "remote_path": norm_remote,
                "local_path": str(local_p),
                "size": local_p.stat().st_size if local_p.exists() else 0,
            }
        except Exception as exc:
            logger.error("Failed to download %s to %s: %s", norm_remote, local_p, exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Download failed: {exc}",
            )

    return router
