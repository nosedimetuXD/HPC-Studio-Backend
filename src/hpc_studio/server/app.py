"""FastAPI application factory for HPC Studio sidecar server."""

import logging
from typing import Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from hpc_studio.server.auth import TokenVerifier
from hpc_studio.server.config import ServerConfig
from hpc_studio.server.event_manager import ConnectionManager
from hpc_studio.server.routes.clusters import create_clusters_router
from hpc_studio.server.routes.events import create_events_router
from hpc_studio.server.routes.health import create_health_router
from hpc_studio.server.routes.sftp import create_sftp_router
from hpc_studio.server.routes.slurm import create_slurm_router
from hpc_studio.server.routes.workspace import create_workspace_router

logger = logging.getLogger("hpc_studio.server")


def create_app(config: Optional[ServerConfig] = None) -> FastAPI:
    """Create and configure the FastAPI server application."""
    if config is None:
        config = ServerConfig()

    app = FastAPI(
        title="HPC Studio Backend",
        version=config.version,
        description="Low-latency sidecar server for HPC Studio Electron workbench",
        docs_url="/docs" if config.debug else None,
        redoc_url=None,
    )

    # Attach shared state
    event_manager = ConnectionManager()
    verifier = TokenVerifier(config)

    app.state.config = config
    app.state.event_manager = event_manager
    app.state.token_verifier = verifier
    app.state.ssh_manager = None
    app.state.slurm_client = None
    app.state.sftp_manager = None

    # Configure CORS for local Electron communication
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
    app.include_router(create_health_router(config, verifier))
    app.include_router(create_workspace_router(config, verifier))
    app.include_router(create_events_router(config, event_manager))
    app.include_router(create_clusters_router(config, verifier))
    app.include_router(create_slurm_router(config, verifier))
    app.include_router(create_sftp_router(config, verifier))

    @app.on_event("startup")
    async def on_startup():
        logger.info(
            "HPC Studio backend started on %s:%d (pid=%d, workspace=%s)",
            config.host,
            config.port,
            config.start_time,
            config.workspace_dir,
        )

    @app.on_event("shutdown")
    async def on_shutdown():
        logger.info("HPC Studio backend shutting down.")

    return app
