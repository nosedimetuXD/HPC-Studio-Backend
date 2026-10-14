"""Simulation Agent Provider for HPC Studio Linux.

Provides offline, realistic simulation for testing and offline environments.
Integrates directly with the native ToolRegistry for realistic HPC workflows.
Zero-Emoji compliant.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, Iterator, Optional

from ..events import (
    AgentEvent,
    CompleteEvent,
    ErrorEvent,
    ThoughtEvent,
    TokenEvent,
    ToolCallEvent,
)
from ..tools.registry import ToolRegistry, get_default_registry
from .base import BaseAgentProvider

logger = logging.getLogger(__name__)


class SimulationProvider(BaseAgentProvider):
    """Offline simulation provider invoking actual ToolRegistry tools for realistic responses."""

    def __init__(self, config: Optional[Dict[str, Any]] = None, tool_registry: Optional[ToolRegistry] = None) -> None:
        super().__init__(config)
        self.tool_registry = tool_registry or get_default_registry()
        self._is_cancelled = False

    def stream_chat(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
        callback: Optional[Callable[[AgentEvent], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Iterator[AgentEvent]:
        """Simulate reasoning, tool calls, and structured response streaming."""
        self._is_cancelled = False
        prompt_lower = prompt.lower()

        # 1. Thought phase
        thoughts = [
            f"Analizando prompt de usuario: '{prompt[:40]}...' y contexto de ejecucion HPC.",
            " Evaluando herramientas locales de cluster, Slurm y Quantum ESPRESSO.",
        ]
        for t in thoughts:
            if self._is_cancelled or (cancel_check and cancel_check()):
                return
            evt = ThoughtEvent(thought=t)
            if callback:
                callback(evt)
            yield evt
            time.sleep(0.01)

        # 2. Tool decision & execution phase
        tool_name = None
        tool_args: Dict[str, Any] = {}

        if "slurm" in prompt_lower or "queue" in prompt_lower or "squeue" in prompt_lower or "particion" in prompt_lower:
            tool_name = "slurm_query"
            tool_args = {"partition": "compute"}
        elif "submit" in prompt_lower or "sbatch" in prompt_lower or "enviar" in prompt_lower or "lanzar" in prompt_lower:
            tool_name = "slurm_submit"
            tool_args = {"script_path": "job_slurm.sh"}
        elif "qe" in prompt_lower or "espresso" in prompt_lower or "validar" in prompt_lower:
            tool_name = "qe_validate"
            tool_args = {"input_content": "&CONTROL calculation='scf' /\n&SYSTEM ibrav=1, celldm(1)=10.0, nat=1, ntyp=1 /\n&ELECTRONS /\nATOMIC_SPECIES\n Si 28.086 Si.pbe.UPF\nATOMIC_POSITIONS crystal\n Si 0.0 0.0 0.0\nK_POINTS automatic\n 4 4 4 0 0 0"}
        elif "read" in prompt_lower or "leer" in prompt_lower or "cat" in prompt_lower:
            tool_name = "read_file"
            tool_args = {"path": "job.sh"}
        elif "run" in prompt_lower or "comando" in prompt_lower:
            tool_name = "run_command"
            tool_args = {"command": "squeue"}

        if tool_name:
            if self._is_cancelled or (cancel_check and cancel_check()):
                return

            # Start tool event
            start_evt = ToolCallEvent(tool_name=tool_name, tool_args=tool_args, is_finished=False)
            if callback:
                callback(start_evt)
            yield start_evt
            time.sleep(0.01)

            # Tool execution
            out = ""
            success = True
            try:
                out = self.execute_tool(tool_name, tool_args, context)
            except Exception as exc:
                out = f"Error: {exc}"
                success = False

            if self._is_cancelled or (cancel_check and cancel_check()):
                return

            finish_evt = ToolCallEvent(
                tool_name=tool_name,
                tool_args=tool_args,
                tool_output=out,
                success=success,
                is_finished=True,
            )
            if callback:
                callback(finish_evt)
            yield finish_evt
            time.sleep(0.01)

        # 3. Final response streaming tokens
        tokens = [
            "Procesamiento ", "completado ", "con ", "exito. ",
            "Los ", "recursos ", "y ", "parametros ", "se ", "han ",
            "verificado ", "correctamente ", "en ", "el ", "entorno ", "HPC.",
        ]
        for tok in tokens:
            if self._is_cancelled or (cancel_check and cancel_check()):
                return
            evt = TokenEvent(token=tok)
            if callback:
                callback(evt)
            yield evt
            time.sleep(0.005)

        # 4. Finish
        if not self._is_cancelled:
            comp_evt = CompleteEvent()
            if callback:
                callback(comp_evt)
            yield comp_evt

    def execute_tool(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Execute a tool via the internal ToolRegistry."""
        try:
            res = self.tool_registry.execute(tool_name, args, remember_session_approval=False, context=context)
            return str(res)
        except Exception as exc:
            return f"Simulation tool error: {exc}"

    def cancel(self) -> None:
        """Cancel execution."""
        self._is_cancelled = True
