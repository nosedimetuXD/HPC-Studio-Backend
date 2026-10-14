"""Agent package for HPC Studio Linux.

Provides agent event modeling, Qt asynchronous bridges, and agentic workflows.
Zero-Emoji compliant.
"""

from .events import (
    AgentEvent,
    AgentEventType,
    CompleteEvent,
    ErrorEvent,
    ThoughtEvent,
    TokenEvent,
    ToolCallEvent,
)
try:
    from .bridge import AntigravityAgentBridge, AgentWorker
except ImportError:
    AntigravityAgentBridge = None  # type: ignore
    AgentWorker = None  # type: ignore
from .tools import (
    RiskLevel,
    ToolDefinition,
    ToolParameter,
    ToolRegistry,
    get_default_registry,
    hpc_tool,
)

__all__ = [
    "AgentEvent",
    "AgentEventType",
    "ThoughtEvent",
    "TokenEvent",
    "ToolCallEvent",
    "CompleteEvent",
    "ErrorEvent",
    "AntigravityAgentBridge",
    "AgentWorker",
    "RiskLevel",
    "ToolDefinition",
    "ToolParameter",
    "ToolRegistry",
    "get_default_registry",
    "hpc_tool",
]

