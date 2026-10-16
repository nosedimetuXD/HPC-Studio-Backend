"""CLI Entrypoint for HPC Studio Model Context Protocol (MCP) stdio server.

Supports --debug and --log-file options.
Zero-Emoji compliant.
"""

from __future__ import annotations

import argparse
import logging
import sys

from .server import MCPServer
from .tools import register_all_tools


def main() -> None:
    """Parse CLI arguments and launch the MCP stdio server."""
    parser = argparse.ArgumentParser(
        prog="hpc-studio-mcp",
        description="Official Model Context Protocol (MCP) stdio server for HPC Studio Linux.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging level.",
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default="",
        help="Path to redirect log outputs (avoids corrupting stdio transport).",
    )
    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    log_handlers = []
    if args.log_file:
        log_handlers.append(logging.FileHandler(args.log_file, encoding="utf-8"))
    else:
        # If no log-file is given, write to stderr so stdout remains clean JSON-RPC
        log_handlers.append(logging.StreamHandler(sys.stderr))

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=log_handlers,
    )

    registry = register_all_tools()
    server = MCPServer(registry=registry)
    try:
        server.run_stdio()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
