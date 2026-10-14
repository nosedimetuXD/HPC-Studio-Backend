"""OpenRouter and Local OpenAI/Ollama Compatible Provider for HPC Studio Linux.

Provides streaming SSE chat completions over HTTP/REST using standard urllib.
Zero-Emoji compliant.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
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


class OpenRouterProvider(BaseAgentProvider):
    """Streaming provider for OpenRouter and Ollama/v1 endpoints."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        self.api_key: str = self.config.get("api_key") or ""
        self.base_url: str = self.config.get("base_url") or "https://openrouter.ai/api/v1"
        self.model: str = self.config.get("model") or "meta-llama/llama-3.3-70b-instruct"
        self._is_cancelled = False

    def __repr__(self) -> str:
        masked = f"{self.api_key[:4]}***{self.api_key[-2:]}" if len(self.api_key) > 6 else "***"
        return f"OpenRouterProvider(model='{self.model}', base_url='{self.base_url}', api_key='{masked}')"

    def stream_chat(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
        callback: Optional[Callable[[AgentEvent], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Iterator[AgentEvent]:
        """Send chat completion request with SSE streaming."""
        self._is_cancelled = False
        url = f"{self.base_url.rstrip('/')}/chat/completions"

        messages = []
        system_prompt = (
            "Eres el asistente cientifico y de computacion de alto rendimiento (HPC) para HPC Studio Linux. "
            "Sigue una estricta politica Zero-Emoji."
        )
        messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
        }
        data_bytes = json.dumps(payload).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "HPC-Studio-Agent/1.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                for raw_line in resp:
                    if self._is_cancelled or (cancel_check and cancel_check()):
                        break

                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue

                    if line.startswith("data: "):
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break

                        try:
                            chunk = json.loads(data_str)
                            choices = chunk.get("choices", [])
                            if not choices:
                                continue
                            delta = choices[0].get("delta", {})

                            # Reasoning / thought chunk
                            reasoning = delta.get("reasoning") or delta.get("thinking")
                            if reasoning:
                                evt = ThoughtEvent(thought=reasoning)
                                if callback:
                                    callback(evt)
                                yield evt

                            # Content chunk
                            content = delta.get("content")
                            if content:
                                evt = TokenEvent(token=content)
                                if callback:
                                    callback(evt)
                                yield evt

                        except json.JSONDecodeError:
                            continue

            if not self._is_cancelled:
                comp_evt = CompleteEvent()
                if callback:
                    callback(comp_evt)
                yield comp_evt

        except urllib.error.HTTPError as http_err:
            body = ""
            try:
                body = http_err.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            msg = f"HTTP Error {http_err.code}: {http_err.reason} - {body}"
            if self.api_key and self.api_key in msg:
                msg = msg.replace(self.api_key, "[REDACTED_API_KEY]")
            logger.error("OpenRouterProvider HTTP error: %s", msg)
            err_evt = ErrorEvent(error_message=msg)
            if callback:
                callback(err_evt)
            yield err_evt

        except Exception as exc:
            logger.exception("OpenRouterProvider connection error: %s", exc)
            err_evt = ErrorEvent(error_message=str(exc))
            if callback:
                callback(err_evt)
            yield err_evt

    def execute_tool(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Fallback tool execution stub for HTTP provider."""
        return f"[OpenRouterProvider] Tool {tool_name} executed with args {args}"

    def cancel(self) -> None:
        """Mark provider as cancelled to interrupt reading loop."""
        self._is_cancelled = True
