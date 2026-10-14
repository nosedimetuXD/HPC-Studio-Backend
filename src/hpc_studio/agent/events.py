"""Agentic event definitions and data models for HPC Studio Linux.

Zero-Emoji compliant representation of agent lifecycle, thoughts,
tool calls, streaming tokens, and completion states.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class AgentEventType(str, Enum):
    """Enumeration of agent event types."""
    AGENT_STARTED = "agent_started"
    THOUGHT_CHUNK = "thought_chunk"
    TOKEN = "token"
    TOOL_STARTED = "tool_started"
    TOOL_FINISHED = "tool_finished"
    AGENT_FINISHED = "agent_finished"
    AGENT_ERROR = "agent_error"
    SUBAGENT_SPAWNED = "subagent_spawned"
    SUBAGENT_STATE = "subagent_state"
    BACKGROUND_TASK = "background_task"
    ARTIFACT_CREATED = "artifact_created"


@dataclass
class AgentEvent:
    """Base event emitted during agent execution."""
    event_type: AgentEventType
    timestamp: datetime = field(default_factory=datetime.utcnow)
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ThoughtEvent(AgentEvent):
    """Event representing internal reasoning or thought chunks."""
    thought: str = ""

    def __init__(self, thought: str = "", timestamp: Optional[datetime] = None, data: Optional[Dict[str, Any]] = None):
        super().__init__(
            event_type=AgentEventType.THOUGHT_CHUNK,
            timestamp=timestamp or datetime.utcnow(),
            data=data or {"thought": thought},
        )
        self.thought = thought


@dataclass
class TokenEvent(AgentEvent):
    """Event representing a streaming text token emitted to the response."""
    token: str = ""

    def __init__(self, token: str = "", timestamp: Optional[datetime] = None, data: Optional[Dict[str, Any]] = None):
        super().__init__(
            event_type=AgentEventType.TOKEN,
            timestamp=timestamp or datetime.utcnow(),
            data=data or {"token": token},
        )
        self.token = token


@dataclass
class ToolCallEvent(AgentEvent):
    """Event representing tool invocation or completion."""
    tool_name: str = ""
    tool_args: Dict[str, Any] = field(default_factory=dict)
    tool_output: str = ""
    success: bool = True
    is_finished: bool = False

    def __init__(
        self,
        tool_name: str = "",
        tool_args: Optional[Dict[str, Any]] = None,
        tool_output: str = "",
        success: bool = True,
        is_finished: bool = False,
        timestamp: Optional[datetime] = None,
        data: Optional[Dict[str, Any]] = None,
    ):
        event_type = AgentEventType.TOOL_FINISHED if is_finished else AgentEventType.TOOL_STARTED
        payload = data or {
            "tool_name": tool_name,
            "tool_args": tool_args or {},
            "tool_output": tool_output,
            "success": success,
            "is_finished": is_finished,
        }
        super().__init__(
            event_type=event_type,
            timestamp=timestamp or datetime.utcnow(),
            data=payload,
        )
        self.tool_name = tool_name
        self.tool_args = tool_args or {}
        self.tool_output = tool_output
        self.success = success
        self.is_finished = is_finished


@dataclass
class CompleteEvent(AgentEvent):
    """Event representing successful or finished agent session."""
    total_tokens: int = 0
    duration_seconds: float = 0.0

    def __init__(
        self,
        total_tokens: int = 0,
        duration_seconds: float = 0.0,
        timestamp: Optional[datetime] = None,
        data: Optional[Dict[str, Any]] = None,
    ):
        payload = data or {
            "total_tokens": total_tokens,
            "duration_seconds": duration_seconds,
        }
        super().__init__(
            event_type=AgentEventType.AGENT_FINISHED,
            timestamp=timestamp or datetime.utcnow(),
            data=payload,
        )
        self.total_tokens = total_tokens
        self.duration_seconds = duration_seconds


@dataclass
class ErrorEvent(AgentEvent):
    """Event representing an agent error."""
    error_message: str = ""

    def __init__(
        self,
        error_message: str = "",
        timestamp: Optional[datetime] = None,
        data: Optional[Dict[str, Any]] = None,
    ):
        payload = data or {"error_message": error_message}
        super().__init__(
            event_type=AgentEventType.AGENT_ERROR,
            timestamp=timestamp or datetime.utcnow(),
            data=payload,
        )
        self.error_message = error_message


@dataclass
class SubagentSpawnEvent(AgentEvent):
    """Event representing the spawning of a child subagent."""
    subagent_id: str = ""
    role: str = ""
    type_name: str = ""
    task_description: str = ""
    subagent_record: Optional[Any] = None

    def __init__(
        self,
        subagent_id: str = "",
        role: str = "",
        type_name: str = "",
        task_description: str = "",
        subagent_record: Optional[Any] = None,
        timestamp: Optional[datetime] = None,
        data: Optional[Dict[str, Any]] = None,
    ):
        payload = data or {
            "subagent_id": subagent_id,
            "role": role,
            "type_name": type_name,
            "task_description": task_description,
            "subagent_record": subagent_record,
        }
        super().__init__(
            event_type=AgentEventType.SUBAGENT_SPAWNED,
            timestamp=timestamp or datetime.utcnow(),
            data=payload,
        )
        self.subagent_id = subagent_id
        self.role = role
        self.type_name = type_name
        self.task_description = task_description
        self.subagent_record = subagent_record


@dataclass
class SubagentStateEvent(AgentEvent):
    """Event representing a state update of a subagent."""
    subagent_id: str = ""
    state: str = ""
    error_message: Optional[str] = None

    def __init__(
        self,
        subagent_id: str = "",
        state: str = "",
        error_message: Optional[str] = None,
        timestamp: Optional[datetime] = None,
        data: Optional[Dict[str, Any]] = None,
    ):
        payload = data or {
            "subagent_id": subagent_id,
            "state": state,
            "error_message": error_message,
        }
        super().__init__(
            event_type=AgentEventType.SUBAGENT_STATE,
            timestamp=timestamp or datetime.utcnow(),
            data=payload,
        )
        self.subagent_id = subagent_id
        self.state = state
        self.error_message = error_message


@dataclass
class BackgroundTaskEvent(AgentEvent):
    """Event representing a background task launch, progress, or completion."""
    task_id: str = ""
    command_line: str = ""
    pid: int = 0
    status: str = "running"
    task_record: Optional[Any] = None

    def __init__(
        self,
        task_id: str = "",
        command_line: str = "",
        pid: int = 0,
        status: str = "running",
        task_record: Optional[Any] = None,
        timestamp: Optional[datetime] = None,
        data: Optional[Dict[str, Any]] = None,
    ):
        payload = data or {
            "task_id": task_id,
            "command_line": command_line,
            "pid": pid,
            "status": status,
            "task_record": task_record,
        }
        super().__init__(
            event_type=AgentEventType.BACKGROUND_TASK,
            timestamp=timestamp or datetime.utcnow(),
            data=payload,
        )
        self.task_id = task_id
        self.command_line = command_line
        self.pid = pid
        self.status = status
        self.task_record = task_record


@dataclass
class ArtifactCreatedEvent(AgentEvent):
    """Event representing artifact generation or modification."""
    artifact_id: str = ""
    title: str = ""
    file_path: str = ""
    summary: str = ""
    request_feedback: bool = False
    artifact_record: Optional[Any] = None

    def __init__(
        self,
        artifact_id: str = "",
        title: str = "",
        file_path: str = "",
        summary: str = "",
        request_feedback: bool = False,
        artifact_record: Optional[Any] = None,
        timestamp: Optional[datetime] = None,
        data: Optional[Dict[str, Any]] = None,
    ):
        payload = data or {
            "artifact_id": artifact_id,
            "title": title,
            "file_path": file_path,
            "summary": summary,
            "request_feedback": request_feedback,
            "artifact_record": artifact_record,
        }
        super().__init__(
            event_type=AgentEventType.ARTIFACT_CREATED,
            timestamp=timestamp or datetime.utcnow(),
            data=payload,
        )
        self.artifact_id = artifact_id
        self.title = title
        self.file_path = file_path
        self.summary = summary
        self.request_feedback = request_feedback
        self.artifact_record = artifact_record
