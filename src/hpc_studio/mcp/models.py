"""Pydantic and data models for Model Context Protocol (MCP) JSON-RPC 2.0.

Adheres strictly to the MCP specification (v2024-11-05).
Zero-Emoji compliant.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field


# Standard JSON-RPC 2.0 error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class JSONRPCError(BaseModel):
    """JSON-RPC 2.0 error payload."""

    code: int
    message: str
    data: Optional[Any] = None


class JSONRPCRequest(BaseModel):
    """Incoming JSON-RPC 2.0 request or notification."""

    jsonrpc: Literal["2.0"] = "2.0"
    method: str
    params: Optional[Dict[str, Any]] = None
    id: Optional[Union[str, int]] = None

    @property
    def is_notification(self) -> bool:
        """True if the message is a notification (no id provided)."""
        return self.id is None


class JSONRPCResponse(BaseModel):
    """Outgoing JSON-RPC 2.0 response."""

    jsonrpc: Literal["2.0"] = "2.0"
    id: Optional[Union[str, int]] = None
    result: Optional[Any] = None
    error: Optional[JSONRPCError] = None


# --- MCP Protocol Specific Models ---


class Implementation(BaseModel):
    """MCP Implementation information."""

    name: str
    version: str


class ServerInfo(BaseModel):
    """Server information returned during initialize."""

    name: str = "hpc-studio-mcp"
    version: str = "1.0.0"


class ToolsCapability(BaseModel):
    """Tools capability settings."""

    listChanged: Optional[bool] = False


class ServerCapabilities(BaseModel):
    """Capabilities supported by this MCP server."""

    tools: Dict[str, Any] = Field(default_factory=dict)
    logging: Optional[Dict[str, Any]] = None


class InitializeParams(BaseModel):
    """Parameters passed to the initialize method."""

    protocolVersion: str
    capabilities: Dict[str, Any] = Field(default_factory=dict)
    clientInfo: Optional[Implementation] = None


class InitializeResult(BaseModel):
    """Result returned by the initialize method."""

    protocolVersion: str = "2024-11-05"
    capabilities: ServerCapabilities = Field(default_factory=ServerCapabilities)
    serverInfo: ServerInfo = Field(default_factory=ServerInfo)


class ToolInputSchema(BaseModel):
    """JSON Schema definition for tool inputs."""

    type: Literal["object"] = "object"
    properties: Dict[str, Any] = Field(default_factory=dict)
    required: List[str] = Field(default_factory=list)


class Tool(BaseModel):
    """Definition of an MCP Tool."""

    name: str
    description: str
    inputSchema: ToolInputSchema


class ListToolsResult(BaseModel):
    """Result returned by tools/list."""

    tools: List[Tool]


class CallToolRequest(BaseModel):
    """Parameters for tools/call."""

    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


class TextContent(BaseModel):
    """Textual content returned by a tool."""

    type: Literal["text"] = "text"
    text: str


class ImageContent(BaseModel):
    """Image content returned by a tool."""

    type: Literal["image"] = "image"
    data: str
    mimeType: str


class EmbeddedResource(BaseModel):
    """Resource content returned by a tool."""

    type: Literal["resource"] = "resource"
    resource: Dict[str, Any]


ContentItem = Union[TextContent, ImageContent, EmbeddedResource]


class CallToolResult(BaseModel):
    """Result returned by tools/call."""

    content: List[TextContent] = Field(default_factory=list)
    isError: bool = False
