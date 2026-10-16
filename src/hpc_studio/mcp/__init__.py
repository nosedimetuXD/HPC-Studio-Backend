"""Model Context Protocol (MCP) implementation for HPC Studio.

Provides an official stdio MCP server exposing HPC cluster management,
SLURM job controls, Quantum ESPRESSO validation, crystallography parsing,
and SFTP filesystem operations to AI agents and Antigravity.
"""

from __future__ import annotations

from .models import (
    CallToolRequest,
    CallToolResult,
    InitializeResult,
    JSONRPCError,
    JSONRPCRequest,
    JSONRPCResponse,
    ServerCapabilities,
    ServerInfo,
    TextContent,
    Tool,
)
from .server import MCPServer
from .tools import register_all_tools

__all__ = [
    "CallToolRequest",
    "CallToolResult",
    "InitializeResult",
    "JSONRPCError",
    "JSONRPCRequest",
    "JSONRPCResponse",
    "MCPServer",
    "ServerCapabilities",
    "ServerInfo",
    "TextContent",
    "Tool",
    "register_all_tools",
]
