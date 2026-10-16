"""MCP Standard Stdio Server implementation for HPC Studio.

Implements JSON-RPC 2.0 streaming over stdin/stdout conforming to
the Model Context Protocol specification (v2024-11-05).
Zero-Emoji compliant.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any, Dict, Optional, TextIO

from .models import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    CallToolResult,
    InitializeResult,
    JSONRPCError,
    JSONRPCRequest,
    JSONRPCResponse,
    ServerCapabilities,
    ServerInfo,
    TextContent,
)
from .tools import ToolRegistry, register_all_tools

logger = logging.getLogger(__name__)


class MCPServer:
    """Standard Model Context Protocol stdio server."""

    def __init__(
        self,
        registry: Optional[ToolRegistry] = None,
        name: str = "hpc-studio-mcp",
        version: str = "1.0.0",
        stdin: Optional[TextIO] = None,
        stdout: Optional[TextIO] = None,
    ) -> None:
        self.registry = registry or register_all_tools()
        self.server_info = ServerInfo(name=name, version=version)
        self.stdin = stdin or sys.stdin
        self.stdout = stdout or sys.stdout
        self._initialized = False

    def handle_message(self, raw_line: str) -> Optional[str]:
        """Process a single JSON-RPC 2.0 line and return the response JSON string (if not notification)."""
        stripped = raw_line.strip()
        if not stripped:
            return None

        # 1. Parse JSON
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as exc:
            err_resp = JSONRPCResponse(
                id=None,
                error=JSONRPCError(
                    code=PARSE_ERROR,
                    message=f"Parse error: {exc}",
                ),
            )
            return err_resp.model_dump_json(exclude_none=True)

        if not isinstance(data, dict):
            err_resp = JSONRPCResponse(
                id=None,
                error=JSONRPCError(
                    code=INVALID_REQUEST,
                    message="Invalid Request: payload must be a JSON object",
                ),
            )
            return err_resp.model_dump_json(exclude_none=True)

        # 2. Parse request model
        try:
            req = JSONRPCRequest.model_validate(data)
        except Exception as exc:
            req_id = data.get("id")
            err_resp = JSONRPCResponse(
                id=req_id,
                error=JSONRPCError(
                    code=INVALID_REQUEST,
                    message=f"Invalid Request: {exc}",
                ),
            )
            return err_resp.model_dump_json(exclude_none=True)

        # 3. Route method
        resp = self._dispatch(req)
        if resp is None:
            # Notification: no response required
            return None

        return resp.model_dump_json(exclude_none=True)

    def _dispatch(self, req: JSONRPCRequest) -> Optional[JSONRPCResponse]:
        """Route JSON-RPC method call."""
        method = req.method
        params = req.params or {}

        # Handle notifications
        if req.is_notification:
            if method in ("notifications/initialized", "initialized"):
                self._initialized = True
                logger.info("MCP client acknowledged initialization.")
            return None

        # Handle requests
        if method == "initialize":
            return self._handle_initialize(req)
        elif method == "ping":
            return JSONRPCResponse(id=req.id, result={})
        elif method == "tools/list":
            return self._handle_tools_list(req)
        elif method == "tools/call":
            return self._handle_tools_call(req, params)
        else:
            return JSONRPCResponse(
                id=req.id,
                error=JSONRPCError(
                    code=METHOD_NOT_FOUND,
                    message=f"Method not found: '{method}'",
                ),
            )

    def _handle_initialize(self, req: JSONRPCRequest) -> JSONRPCResponse:
        """Handle initialize request."""
        result = InitializeResult(
            protocolVersion="2024-11-05",
            capabilities=ServerCapabilities(tools={}),
            serverInfo=self.server_info,
        )
        return JSONRPCResponse(id=req.id, result=result.model_dump())

    def _handle_tools_list(self, req: JSONRPCRequest) -> JSONRPCResponse:
        """Handle tools/list request."""
        tools = self.registry.list_tools()
        result = {
            "tools": [t.model_dump() for t in tools],
        }
        return JSONRPCResponse(id=req.id, result=result)

    def _handle_tools_call(
        self, req: JSONRPCRequest, params: Dict[str, Any]
    ) -> JSONRPCResponse:
        """Handle tools/call request."""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if not tool_name or not isinstance(tool_name, str):
            return JSONRPCResponse(
                id=req.id,
                error=JSONRPCError(
                    code=INVALID_PARAMS,
                    message="Missing or invalid parameter 'name' for tools/call",
                ),
            )

        if not isinstance(arguments, dict):
            arguments = {}

        try:
            tool_result: CallToolResult = self.registry.call(tool_name, arguments)
            return JSONRPCResponse(id=req.id, result=tool_result.model_dump())
        except Exception as exc:
            logger.exception("Unexpected error in tools/call for %s: %s", tool_name, exc)
            return JSONRPCResponse(
                id=req.id,
                error=JSONRPCError(
                    code=INTERNAL_ERROR,
                    message=f"Internal error executing tool '{tool_name}': {exc}",
                ),
            )

    def run_stdio(self) -> None:
        """Start the stdio streaming server loop."""
        logger.info("Starting HPC Studio MCP server stdio loop...")
        for line in self.stdin:
            if not line:
                break
            try:
                response = self.handle_message(line)
                if response:
                    self.stdout.write(response + "\n")
                    self.stdout.flush()
            except Exception as exc:
                logger.exception("Fatal loop exception: %s", exc)
