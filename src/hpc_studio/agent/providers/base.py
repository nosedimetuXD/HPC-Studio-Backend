"""Base Agent Provider interface for HPC Studio Linux.

Zero-Emoji compliant. Defines the contract for streaming LLM/CLI agent providers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Iterator, Optional

from ..events import AgentEvent


class BaseAgentProvider(ABC):
    """Abstract base class for agent runtime providers."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config: Dict[str, Any] = config or {}

    @abstractmethod
    def stream_chat(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
        callback: Optional[Callable[[AgentEvent], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Iterator[AgentEvent]:
        """Stream events (thoughts, tokens, tool calls, completion) from the agent."""
        pass

    @abstractmethod
    def execute_tool(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Execute a tool or return tool result."""
        pass

    def cancel(self) -> None:
        """Cancel ongoing operations if applicable."""
        pass
