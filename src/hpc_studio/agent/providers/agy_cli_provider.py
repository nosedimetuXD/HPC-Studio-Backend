"""Google Antigravity Native CLI Provider for HPC Studio Linux.

Interfaces with the system `agy` CLI binary for streaming agent execution.
Zero-Emoji compliant.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from typing import Any, Callable, Dict, Iterator, Optional

from ..events import (
    AgentEvent,
    CompleteEvent,
    ErrorEvent,
    ThoughtEvent,
    TokenEvent,
    ToolCallEvent,
)
from .base import BaseAgentProvider

logger = logging.getLogger(__name__)


class AgyCliProvider(BaseAgentProvider):
    """Provider executing tasks via local Antigravity CLI (`agy`)."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        self.cli_path = self.config.get("cli_path") or shutil.which("agy") or "agy"
        self._current_process: Optional[subprocess.Popen] = None

    @classmethod
    def is_available(cls) -> bool:
        """Check if `agy` binary is found in system PATH."""
        return shutil.which("agy") is not None

    def build_command(self, prompt: str, context: Optional[Dict[str, Any]] = None) -> list[str]:
        """Build agy CLI command arguments."""
        cmd = [self.cli_path, "--output-format", "stream-json"]
        workspace_path = (context or {}).get("workspace_path")
        if workspace_path:
            cmd.extend(["--add-dir", str(workspace_path)])
        cmd.extend(["--print", prompt])
        return cmd

    def stream_chat(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
        callback: Optional[Callable[[AgentEvent], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Iterator[AgentEvent]:
        """Stream events from `agy` CLI invocation."""
        if not shutil.which(self.cli_path):
            err = ErrorEvent(error_message=f"Antigravity CLI binary '{self.cli_path}' not found in PATH.")
            if callback:
                callback(err)
            yield err
            return

        cmd = self.build_command(prompt, context)
        cwd = (context or {}).get("cwd") or (context or {}).get("workspace_path") or os.getcwd()

        try:
            self._current_process = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )

            # Stream stdout line by line
            if self._current_process.stdout:
                stdout_iter = (
                    self._current_process.stdout
                    if hasattr(self._current_process.stdout, "__iter__")
                    else iter(self._current_process.stdout.readline, "")
                )
                for line in stdout_iter:
                    if cancel_check and cancel_check():
                        self.cancel()
                        break

                    line_clean = line.strip()
                    if not line_clean:
                        continue

                    event = self._parse_agy_output_line(line_clean)
                    if event:
                        if callback:
                            callback(event)
                        yield event

            self._current_process.wait()
            ret_code = self._current_process.returncode
            if ret_code != 0:
                err_text = ""
                if self._current_process.stderr:
                    err_text = self._current_process.stderr.read().strip()
                err_evt = ErrorEvent(error_message=f"agy exited with code {ret_code}: {err_text}")
                if callback:
                    callback(err_evt)
                yield err_evt
            else:
                comp_evt = CompleteEvent()
                if callback:
                    callback(comp_evt)
                yield comp_evt

        except Exception as exc:
            logger.exception("Error executing agy CLI: %s", exc)
            err_evt = ErrorEvent(error_message=str(exc))
            if callback:
                callback(err_evt)
            yield err_evt
        finally:
            self._current_process = None

    def execute_tool(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Execute a tool via agy tool runner."""
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]*$", tool_name):
            return "Error: Invalid tool name format."

        if not shutil.which(self.cli_path):
            return f"Error: agy binary '{self.cli_path}' not available."

        cmd = [self.cli_path, "tool", tool_name, "--args", json.dumps(args)]
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return res.stdout if res.returncode == 0 else f"Error: {res.stderr}"
        except Exception as exc:
            return f"Tool execution failed: {exc}"

    def cancel(self) -> None:
        """Terminate running `agy` process."""
        if self._current_process:
            try:
                self._current_process.terminate()
            except Exception:
                pass

    def _parse_agy_output_line(self, line: str) -> Optional[AgentEvent]:
        """Parse structured JSON or plain text event from `agy` stdout."""
        try:
            data = json.loads(line)
            if not isinstance(data, dict):
                return TokenEvent(token=line)

            event_type = data.get("type")
            if event_type == "thought":
                return ThoughtEvent(thought=data.get("content") or data.get("thought") or "")
            elif event_type in ("token", "content", "chunk"):
                return TokenEvent(token=data.get("content") or data.get("token") or data.get("chunk") or "")
            elif event_type == "tool_start":
                return ToolCallEvent(
                    tool_name=data.get("tool_name", ""),
                    tool_args=data.get("args", {}),
                    is_finished=False,
                )
            elif event_type == "tool_finish":
                return ToolCallEvent(
                    tool_name=data.get("tool_name", ""),
                    tool_output=data.get("output", ""),
                    success=data.get("success", True),
                    is_finished=True,
                )
            elif event_type == "error":
                return ErrorEvent(error_message=data.get("message") or data.get("error") or "Error in agy")

            # Native agy CLI stream-json format support
            evt = data.get("event")
            if evt == "step_update":
                step_update = data.get("step_update", {})
                step_type = step_update.get("step_type")
                if step_type == "agent_response":
                    delta = step_update.get("text_delta")
                    if delta:
                        return TokenEvent(token=delta)
                elif step_type == "thought":
                    thought = step_update.get("text_delta") or step_update.get("thought_delta") or ""
                    if thought:
                        return ThoughtEvent(thought=thought)
            elif evt == "error":
                return ErrorEvent(error_message=data.get("error") or "Error in agy")
            elif evt in ("init", "result"):
                return None

        except (json.JSONDecodeError, AttributeError):
            # Fallback to plain token stream
            return TokenEvent(token=line)
        return None
