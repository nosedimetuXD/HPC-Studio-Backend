"""Exhaustive test suite for Agent Providers and Factory architecture.

Tests BaseAgentProvider contract, AgyCliProvider detection and streaming,
OpenRouterProvider SSE handling, SimulationProvider tool integration,
and provider factory get_provider() with automatic fallback.
Strict Zero-Emoji compliance.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from unittest.mock import MagicMock, patch
import pytest

from hpc_studio.agent.events import (
    CompleteEvent,
    ErrorEvent,
    ThoughtEvent,
    TokenEvent,
    ToolCallEvent,
)
from hpc_studio.agent.providers import (
    AgyCliProvider,
    BaseAgentProvider,
    OpenRouterProvider,
    SimulationProvider,
    get_provider,
)
from hpc_studio.agent.tools.registry import ToolRegistry


def test_provider_factory_resolution():
    """Verify provider factory returns appropriate provider types."""
    # Explicit simulation
    sim_p = get_provider("simulation")
    assert isinstance(sim_p, SimulationProvider)

    # Explicit openrouter
    open_p = get_provider("openrouter", {"api_key": "dummy"})
    assert isinstance(open_p, OpenRouterProvider)

    # Explicit agy
    agy_p = get_provider("agy")
    assert isinstance(agy_p, AgyCliProvider)

    # Unknown name falls back to simulation
    fallback_p = get_provider("non_existent_provider_xyz")
    assert isinstance(fallback_p, SimulationProvider)


def test_provider_factory_auto_resolution():
    """Verify auto resolution logic: agy -> openrouter -> simulation."""
    # 1. When agy is available in system
    with patch.object(AgyCliProvider, "is_available", return_value=True):
        auto_agy = get_provider("auto")
        assert isinstance(auto_agy, AgyCliProvider)

    # 2. When agy is absent, but API key or base_url is configured
    with patch.object(AgyCliProvider, "is_available", return_value=False):
        auto_http = get_provider("auto", {"api_key": "sk-1234"})
        assert isinstance(auto_http, OpenRouterProvider)

        auto_local = get_provider("auto", {"base_url": "http://localhost:11434/v1"})
        assert isinstance(auto_local, OpenRouterProvider)

    # 3. When neither is available, defaults to SimulationProvider
    with patch.object(AgyCliProvider, "is_available", return_value=False):
        auto_sim = get_provider("auto", {})
        assert isinstance(auto_sim, SimulationProvider)


def test_simulation_provider_streaming_and_tools():
    """Verify SimulationProvider stream_chat yields thoughts, tools and tokens."""
    sim = SimulationProvider()

    events = []
    for evt in sim.stream_chat("Revisa el estado de la cola Slurm en compute"):
        events.append(evt)

    thought_events = [e for e in events if isinstance(e, ThoughtEvent)]
    tool_events = [e for e in events if isinstance(e, ToolCallEvent)]
    token_events = [e for e in events if isinstance(e, TokenEvent)]
    comp_events = [e for e in events if isinstance(e, CompleteEvent)]

    assert len(thought_events) > 0
    assert any("Slurm" in t.thought or "Analizando" in t.thought for t in thought_events)

    assert len(tool_events) >= 2  # start and finished
    assert tool_events[0].tool_name == "slurm_query"
    assert not tool_events[0].is_finished
    assert tool_events[1].is_finished
    assert tool_events[1].success is True

    assert len(token_events) > 0
    full_text = "".join(t.token for t in token_events)
    assert "HPC" in full_text

    assert len(comp_events) == 1


def test_simulation_provider_cancel():
    """Verify cancellation interrupts SimulationProvider streaming."""
    sim = SimulationProvider()
    events = []

    def cancel_check():
        return len(events) >= 1

    for evt in sim.stream_chat("Consulta rapida", cancel_check=cancel_check):
        events.append(evt)

    # Should have stopped early without emitting all tokens or CompleteEvent
    assert len(events) <= 2
    assert not any(isinstance(e, CompleteEvent) for e in events)


def test_agy_cli_provider_not_found():
    """Verify AgyCliProvider yields ErrorEvent if CLI binary is missing."""
    provider = AgyCliProvider(config={"cli_path": "/nonexistent/agy/binary"})
    events = list(provider.stream_chat("Prueba"))

    assert len(events) == 1
    assert isinstance(events[0], ErrorEvent)
    assert "not found" in events[0].error_message


def test_agy_cli_provider_streaming_mock():
    """Verify AgyCliProvider parses stdout JSON events when binary runs."""
    fake_lines = [
        json.dumps({"type": "thought", "content": "Verificando particiones..."}) + "\n",
        json.dumps({"type": "tool_start", "tool_name": "sinfo", "args": {}}) + "\n",
        json.dumps({"type": "tool_finish", "tool_name": "sinfo", "output": "PARTITION UP", "success": True}) + "\n",
        json.dumps({"type": "token", "content": "Particion compute online."}) + "\n",
    ]

    mock_proc = MagicMock()
    mock_proc.stdout = iter(fake_lines)
    mock_proc.stderr = MagicMock()
    mock_proc.stderr.read.return_value = ""
    mock_proc.wait.return_value = None
    mock_proc.returncode = 0

    provider = AgyCliProvider(config={"cli_path": "agy"})

    with patch("shutil.which", return_value="/usr/local/bin/agy"):
        with patch("subprocess.Popen", return_value=mock_proc):
            events = list(provider.stream_chat("Estado del nodo"))

    thought_evts = [e for e in events if isinstance(e, ThoughtEvent)]
    tool_evts = [e for e in events if isinstance(e, ToolCallEvent)]
    token_evts = [e for e in events if isinstance(e, TokenEvent)]
    comp_evts = [e for e in events if isinstance(e, CompleteEvent)]

    assert len(thought_evts) == 1
    assert thought_evts[0].thought == "Verificando particiones..."
    assert len(tool_evts) == 2
    assert tool_evts[0].tool_name == "sinfo"
    assert tool_evts[1].tool_output == "PARTITION UP"
    assert len(token_evts) == 1
    assert token_evts[0].token == "Particion compute online."
    assert len(comp_evts) == 1


def test_openrouter_provider_streaming_mock():
    """Verify OpenRouterProvider parses SSE chunks correctly."""
    sse_data = (
        b"data: {\"choices\": [{\"delta\": {\"reasoning\": \"Pensando estrategia HPC...\"}}]}\n\n"
        b"data: {\"choices\": [{\"delta\": {\"content\": \"Hola, \"}}]}\n\n"
        b"data: {\"choices\": [{\"delta\": {\"content\": \"mundo HPC!\"}}]}\n\n"
        b"data: [DONE]\n\n"
    )

    mock_response = MagicMock()
    mock_response.__enter__.return_value = iter(sse_data.split(b"\n\n"))
    mock_response.__exit__.return_value = None

    provider = OpenRouterProvider(config={"api_key": "test_key", "model": "mock-model"})

    with patch("urllib.request.urlopen", return_value=mock_response):
        events = list(provider.stream_chat("Cuentame algo"))

    thought_evts = [e for e in events if isinstance(e, ThoughtEvent)]
    token_evts = [e for e in events if isinstance(e, TokenEvent)]
    comp_evts = [e for e in events if isinstance(e, CompleteEvent)]

    assert len(thought_evts) == 1
    assert thought_evts[0].thought == "Pensando estrategia HPC..."

    assert len(token_evts) == 2
    full_content = "".join(t.token for t in token_evts)
    assert full_content == "Hola, mundo HPC!"

    assert len(comp_evts) == 1
