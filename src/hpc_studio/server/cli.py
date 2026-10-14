"""Command line interface for starting HPC Studio backend server."""

import argparse
import json
import logging
import os
import socket
import sys
from pathlib import Path
from typing import Optional

import uvicorn

from hpc_studio.server.app import create_app
from hpc_studio.server.config import ServerConfig


def find_free_port(host: str = "127.0.0.1") -> int:
    """Find an available port by binding to port 0."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def build_parser() -> argparse.ArgumentParser:
    """Build argument parser for HPC Studio server."""
    parser = argparse.ArgumentParser(
        description="HPC Studio Python Backend Sidecar Server"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host address to bind to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port number to listen on (default: 8000, use 0 for dynamic port)",
    )
    parser.add_argument(
        "--token",
        type=str,
        default=None,
        help="Ephemeral security token (auto-generated if omitted)",
    )
    parser.add_argument(
        "--workspace",
        type=str,
        default=None,
        help="Working directory path for HPC Studio workspace",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode and Swagger documentation",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="info",
        choices=["debug", "info", "warning", "error"],
        help="Logging verbosity level",
    )
    return parser


def main(args_list: Optional[list] = None) -> int:
    """Main entrypoint for CLI server launcher."""
    parser = build_parser()
    args = parser.parse_args(args_list)

    # Configure logging
    log_level = getattr(logging, args.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    port = args.port
    if port == 0:
        port = find_free_port(args.host)

    workspace_dir = Path(args.workspace).resolve() if args.workspace else Path.cwd()

    config = ServerConfig(
        host=args.host,
        port=port,
        token=args.token or "",
        workspace_dir=workspace_dir,
        debug=args.debug,
    )

    app = create_app(config)

    # Output structured startup announcement on stdout for Electron supervisor
    announcement = {
        "status": "ready",
        "host": config.host,
        "port": config.port,
        "token": config.token,
        "workspace": str(config.workspace_dir),
        "pid": os.getpid(),
        "version": config.version,
    }
    sys.stdout.write(f"[HPC_SIDECAR_READY] {json.dumps(announcement)}\n")
    sys.stdout.flush()

    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level=args.log_level,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
