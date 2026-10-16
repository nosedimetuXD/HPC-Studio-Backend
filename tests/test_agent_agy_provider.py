"""Tests for AgyCliProvider and agent integration with local agy CLI.

Validates:
- AgyCliProvider.is_available() detection.
- get_provider('auto') resolution to AgyCliProvider.
- CLI command construction (--output-format stream-json, --print, --add-dir).
- NDJSON output parsing (content, token, thought, error, real agy events).
- Mocked subprocess streaming yielding proper AgentEvent instances.
- Strict ZERO-EMOJI compliance.
"""

from io import StringIO
import json
from pathlib import Path
import re
import shutil
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from hpc_studio.agent.events import (
    CompleteEvent,
    ErrorEvent,
    ThoughtEvent,
    TokenEvent,
)
from hpc_studio.agent.providers import AgyCliProvider, get_provider


EMOJI_PATTERN = re.compile(r"[\U00010000-\U0010ffff\u2600-\u26ff\u2700-\u27bf]")


class TestAgyCliProvider:
    """Test suite for AgyCliProvider."""

    def test_is_available_system(self):
        """Verify is_available() accurately reflects binary availability."""
        has_agy = shutil.which("agy") is not None
        assert AgyCliProvider.is_available() is has_agy

    def test_is_available_mocked(self):
        """Verify is_available() with mocked PATH lookup."""
        with patch("shutil.which", return_value="/usr/local/bin/agy"):
            assert AgyCliProvider.is_available() is True

        with patch("shutil.which", return_value=None):
            assert AgyCliProvider.is_available() is False

    def test_get_provider_auto_resolves_agy(self):
        """Verify factory get_provider('auto') selects AgyCliProvider when available."""
        with patch("shutil.which", return_value="/fake/bin/agy"):
            provider = get_provider("auto")
            assert isinstance(provider, AgyCliProvider)

    def test_command_construction_basic(self):
        """Verify correct CLI flags for standalone prompt."""
        provider = AgyCliProvider()
        cmd = provider.build_command("Describe Quantum ESPRESSO")

        assert cmd[0] == provider.cli_path
        assert "--output-format" in cmd
        assert "stream-json" in cmd
        assert "--print" in cmd
        assert "Describe Quantum ESPRESSO" in cmd
        assert "--add-dir" not in cmd

    def test_command_construction_with_workspace(self, tmp_path):
        """Verify --add-dir is appended when workspace_path is in context."""
        provider = AgyCliProvider()
        ws = str(tmp_path / "qe_project")
        cmd = provider.build_command("Check convergence", context={"workspace_path": ws})

        assert "--add-dir" in cmd
        assert ws in cmd
        assert "--print" in cmd
        assert "Check convergence" in cmd

    def test_parse_ndjson_token_events(self):
        """Verify parsing of various token/content NDJSON events."""
        provider = AgyCliProvider()

        # Type: content
        ev1 = provider._parse_agy_output_line('{"type": "content", "content": "PWscf started"}')
        assert isinstance(ev1, TokenEvent)
        assert ev1.token == "PWscf started"

        # Type: token
        ev2 = provider._parse_agy_output_line('{"type": "token", "token": "energy="}')
        assert isinstance(ev2, TokenEvent)
        assert ev2.token == "energy="

        # Type: chunk
        ev3 = provider._parse_agy_output_line('{"type": "chunk", "chunk": " -42.0 Ry"}')
        assert isinstance(ev3, TokenEvent)
        assert ev3.token == " -42.0 Ry"

    def test_parse_ndjson_thought_events(self):
        """Verify parsing of thought events."""
        provider = AgyCliProvider()
        ev = provider._parse_agy_output_line('{"type": "thought", "thought": "Analyzing k-points..."}')
        assert isinstance(ev, ThoughtEvent)
        assert ev.thought == "Analyzing k-points..."

    def test_parse_ndjson_error_events(self):
        """Verify parsing of error events."""
        provider = AgyCliProvider()
        ev = provider._parse_agy_output_line('{"type": "error", "message": "SCF failed to converge"}')
        assert isinstance(ev, ErrorEvent)
        assert "SCF failed to converge" in ev.error_message

    def test_parse_native_agy_step_updates(self):
        """Verify parsing of real agy stream-json format."""
        provider = AgyCliProvider()

        # agent_response step
        native_line = json.dumps({
            "event": "step_update",
            "step_update": {
                "step_index": 1,
                "step_type": "agent_response",
                "text_delta": "Calculo completado con exito.",
            },
        })
        ev = provider._parse_agy_output_line(native_line)
        assert isinstance(ev, TokenEvent)
        assert ev.token == "Calculo completado con exito."

        # thought step
        thought_line = json.dumps({
            "event": "step_update",
            "step_update": {
                "step_index": 1,
                "step_type": "thought",
                "text_delta": "Evaluando pseudopotenciales...",
            },
        })
        ev_th = provider._parse_agy_output_line(thought_line)
        assert isinstance(ev_th, ThoughtEvent)
        assert ev_th.thought == "Evaluando pseudopotenciales..."

        # administrative events ignored
        init_line = json.dumps({"event": "init", "conversation_id": "c123"})
        assert provider._parse_agy_output_line(init_line) is None

    def test_parse_plain_text_fallback(self):
        """Verify non-JSON lines are yielded as TokenEvent."""
        provider = AgyCliProvider()
        ev = provider._parse_agy_output_line("Non-JSON log line from HPC cluster")
        assert isinstance(ev, TokenEvent)
        assert ev.token == "Non-JSON log line from HPC cluster"

    def test_stream_chat_lifecycle_success(self):
        """Verify stream_chat yields tokens and finishes with CompleteEvent."""
        provider = AgyCliProvider()

        simulated_stdout = (
            '{"event": "step_update", "step_update": {"step_type": "agent_response", "text_delta": "Paso 1"}}\n'
            '{"event": "step_update", "step_update": {"step_type": "agent_response", "text_delta": "Paso 2"}}\n'
        )

        mock_proc = MagicMock()
        mock_proc.stdout = StringIO(simulated_stdout)
        mock_proc.stderr = StringIO("")
        mock_proc.returncode = 0
        mock_proc.wait.return_value = 0

        with patch("shutil.which", return_value="/usr/bin/agy"), patch("subprocess.Popen", return_value=mock_proc):
            events = list(provider.stream_chat("Prueba"))

        assert len(events) == 3
        assert isinstance(events[0], TokenEvent) and events[0].token == "Paso 1"
        assert isinstance(events[1], TokenEvent) and events[1].token == "Paso 2"
        assert isinstance(events[2], CompleteEvent)

    def test_stream_chat_lifecycle_error(self):
        """Verify stream_chat emits ErrorEvent on non-zero exit code."""
        provider = AgyCliProvider()

        mock_proc = MagicMock()
        mock_proc.stdout = StringIO("")
        mock_proc.stderr = StringIO("Binary auth error")
        mock_proc.returncode = 1
        mock_proc.wait.return_value = 1

        with patch("shutil.which", return_value="/usr/bin/agy"), patch("subprocess.Popen", return_value=mock_proc):
            events = list(provider.stream_chat("Prueba"))

        assert len(events) == 1
        assert isinstance(events[0], ErrorEvent)
        assert "code 1" in events[0].error_message
        assert "Binary auth error" in events[0].error_message

    def test_stream_chat_binary_not_found(self):
        """Verify stream_chat emits ErrorEvent when agy is not in PATH."""
        provider = AgyCliProvider()
        with patch("shutil.which", return_value=None):
            events = list(provider.stream_chat("Prueba"))
        assert len(events) == 1
        assert isinstance(events[0], ErrorEvent)
        assert "not found in PATH" in events[0].error_message

    def test_zero_emoji_compliance(self):
        """Ensure test file and provider have zero emojis."""
        test_file = Path(__file__)
        provider_file = Path("src/hpc_studio/agent/providers/agy_cli_provider.py")

        assert not EMOJI_PATTERN.search(test_file.read_text(encoding="utf-8"))
        assert not EMOJI_PATTERN.search(provider_file.read_text(encoding="utf-8"))
