"""FastAPI router for SSH cluster connections and configuration."""

from __future__ import annotations

import logging
import socket
import time
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from hpc_studio.server.auth import TokenVerifier
from hpc_studio.server.config import ServerConfig
from hpc_studio.ssh.client import SSHClientError, SSHClientManager
from hpc_studio.ssh.config_parser import SSHConfigParser, SSHHostEntry
from hpc_studio.slurm.client import SlurmClient
from hpc_studio.sftp.client import SFTPClientManager

logger = logging.getLogger("hpc_studio.server.clusters")


class ConnectClusterRequest(BaseModel):
    """Payload to initiate a cluster SSH connection."""

    host: str = Field(..., description="Target hostname or SSH alias")
    user: Optional[str] = Field(None, description="SSH username")
    port: int = Field(22, ge=1, le=65535, description="SSH port")
    identity_file: Optional[str] = Field(None, description="Path to private key identity file")
    password: Optional[str] = Field(None, description="Optional SSH password")
    passphrase: Optional[str] = Field(None, description="Optional key passphrase")
    timeout: int = Field(10, ge=1, le=60, description="Connection timeout in seconds")


class PingClusterRequest(BaseModel):
    """Payload to measure latency to a remote cluster host."""

    host: str = Field(..., description="Target host to test")
    port: int = Field(22, ge=1, le=65535, description="Target TCP port")
    timeout: float = Field(5.0, ge=0.5, le=30.0, description="TCP timeout in seconds")


def create_clusters_router(config: ServerConfig, verifier: TokenVerifier) -> APIRouter:
    """Create clusters router with injected configuration and token verifier."""
    router = APIRouter(prefix="/api/clusters", tags=["clusters"])

    @router.get("", response_model=Dict[str, Any])
    async def list_clusters(request: Request, _: str = Depends(verifier)) -> Dict[str, Any]:
        """List configured clusters from ~/.ssh/config and report the currently active cluster."""
        parser = SSHConfigParser()
        clusters: List[Dict[str, Any]] = []

        try:
            hosts = parser.get_all_entries()
            for entry in hosts:
                clusters.append(entry.to_dict())
        except Exception as exc:
            logger.warning("Error reading SSH configuration: %s", exc)

        active_cluster: Optional[Dict[str, Any]] = None
        ssh_manager: Optional[SSHClientManager] = getattr(request.app.state, "ssh_manager", None)
        if ssh_manager and ssh_manager.is_connected:
            current_entry = ssh_manager.current_entry
            active_cluster = current_entry.to_dict() if current_entry else {"status": "connected"}

        presets = [
            {
                "name": "Quantum Mobile (VirtualBox)",
                "hostname": "127.0.0.1",
                "port": 2222,
                "user": "max",
                "description": "Local simulation VM for materials science (Quantum ESPRESSO, AiiDA, Slurm)",
            }
        ]

        return {
            "clusters": clusters,
            "presets": presets,
            "active_cluster": active_cluster,
            "is_connected": bool(ssh_manager and ssh_manager.is_connected),
        }

    @router.post("/connect")
    async def connect_cluster(
        payload: ConnectClusterRequest,
        request: Request,
        _: str = Depends(verifier),
    ) -> Dict[str, Any]:
        """Establish an SSH connection and configure Slurm and SFTP managers."""
        # Check ~/.ssh/config to resolve defaults or jump hosts if alias matches
        parser = SSHConfigParser()
        entry = parser.get_host(payload.host)

        # Detect Quantum Mobile preset defaults
        is_quantum_mobile = (
            payload.host in ("127.0.0.1", "localhost", "quantum-mobile")
            and (payload.port == 2222 or payload.host == "quantum-mobile")
        )

        user = payload.user
        port = payload.port
        if is_quantum_mobile:
            if not user:
                user = "max"
            if port == 22 and payload.host == "quantum-mobile":
                port = 2222

        if entry is None:
            entry = SSHHostEntry(
                host=payload.host,
                hostname="127.0.0.1" if payload.host == "quantum-mobile" else payload.host,
                user=user or ("max" if is_quantum_mobile else None),
                port=port,
                identity_file=payload.identity_file,
            )
        else:
            # Override with explicit values provided by caller if given
            if user:
                entry.user = user
            if port != 22 or is_quantum_mobile:
                entry.port = port
            if payload.identity_file:
                entry.identity_file = payload.identity_file
                if payload.identity_file not in entry.identity_files:
                    entry.identity_files.insert(0, payload.identity_file)

        # Quantum Mobile default password fallback if no password or key is provided
        password = payload.password
        if is_quantum_mobile and not password and not payload.identity_file:
            password = "moritz"

        # Disconnect existing connection cleanly if any
        existing_mgr: Optional[SSHClientManager] = getattr(request.app.state, "ssh_manager", None)
        if existing_mgr:
            try:
                existing_mgr.disconnect()
            except Exception as exc:
                logger.debug("Error disconnecting previous SSH session: %s", exc)

        mgr = SSHClientManager(config_parser=parser)
        try:
            mgr.connect(
                host_entry=entry,
                passphrase=payload.passphrase,
                password=password,
                timeout=payload.timeout,
            )
        except Exception as exc:
            logger.error("Failed to connect to %s: %s", entry.host, exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"SSH connection failed: {exc}",
            )

        # Update app.state with new active managers
        request.app.state.ssh_manager = mgr
        request.app.state.slurm_client = SlurmClient(ssh_manager=mgr)

        try:
            raw_sftp = mgr.open_sftp()
            sftp_mgr = SFTPClientManager(sftp_client=raw_sftp, cluster_username=entry.user)
            request.app.state.sftp_manager = sftp_mgr
        except Exception as exc:
            logger.warning("Could not automatically initialize SFTP channel: %s", exc)
            request.app.state.sftp_manager = None

        return {
            "status": "connected",
            "cluster": entry.to_dict(),
            "connection_summary": entry.connection_summary,
        }

    @router.post("/disconnect")
    async def disconnect_cluster(request: Request, _: str = Depends(verifier)) -> Dict[str, Any]:
        """Close active SSH session and reset associated Slurm and SFTP managers."""
        sftp_mgr: Optional[SFTPClientManager] = getattr(request.app.state, "sftp_manager", None)
        if sftp_mgr:
            try:
                sftp_mgr.close()
            except Exception as exc:
                logger.debug("Error closing SFTP client: %s", exc)
        request.app.state.sftp_manager = None

        ssh_mgr: Optional[SSHClientManager] = getattr(request.app.state, "ssh_manager", None)
        if ssh_mgr:
            try:
                ssh_mgr.disconnect()
            except Exception as exc:
                logger.debug("Error disconnecting SSH manager: %s", exc)
        request.app.state.ssh_manager = None
        request.app.state.slurm_client = None

        return {"status": "disconnected"}

    @router.post("/ping")
    async def ping_cluster(
        payload: PingClusterRequest,
        _: str = Depends(verifier),
    ) -> Dict[str, Any]:
        """Measure TCP connection latency to the specified host and port."""
        target_host = "127.0.0.1" if payload.host == "quantum-mobile" else payload.host
        target_port = 2222 if (payload.host == "quantum-mobile" and payload.port == 22) else payload.port
        start_time = time.monotonic()
        try:
            with socket.create_connection((target_host, target_port), timeout=payload.timeout):
                latency_ms = (time.monotonic() - start_time) * 1000.0
            return {
                "host": payload.host,
                "port": target_port,
                "reachable": True,
                "latency_ms": round(latency_ms, 2),
            }
        except socket.timeout:
            return {
                "host": payload.host,
                "port": payload.port,
                "reachable": False,
                "error": "Connection timed out",
                "latency_ms": None,
            }
        except Exception as exc:
            return {
                "host": payload.host,
                "port": payload.port,
                "reachable": False,
                "error": str(exc),
                "latency_ms": None,
            }

    return router
