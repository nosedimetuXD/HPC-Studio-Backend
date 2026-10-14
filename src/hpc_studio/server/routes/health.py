"""Health check route for HPC Studio server."""

import os
import platform
import sys
import time
from typing import Any, Dict
from fastapi import APIRouter, Depends

from hpc_studio.server.auth import TokenVerifier
from hpc_studio.server.config import ServerConfig

router = APIRouter()


def create_health_router(config: ServerConfig, verifier: TokenVerifier) -> APIRouter:
    """Create health router with injected configuration and token verifier."""
    r = APIRouter()

    @r.get("/api/health")
    async def get_health(_: str = Depends(verifier)) -> Dict[str, Any]:
        """Return service health, uptime, version and host environment details."""
        return {
            "status": "healthy",
            "version": config.version,
            "uptime_seconds": round(config.uptime, 2),
            "pid": os.getpid(),
            "started_at": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(config.start_time)
            ),
            "system": {
                "platform": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
                "python": sys.version.split()[0],
            },
        }

    return r
