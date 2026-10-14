"""Agent Bridge and worker architecture for HPC Studio Linux.

Provides asynchronous, non-blocking execution of agentic workflows
using QThread and Qt signals, bridging UI components with LLM/CLI runtimes.
Zero-Emoji compliant.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from ..core.signals import QObject, QThread, Signal

from .events import (
    AgentEvent,
    AgentEventType,
    CompleteEvent,
    ErrorEvent,
    ThoughtEvent,
    TokenEvent,
    ToolCallEvent,
)
from .providers import BaseAgentProvider, get_provider
from .tools.registry import RiskLevel, ToolRegistry, get_default_registry

logger = logging.getLogger(__name__)


class AgentWorker(QThread):
    """Background worker executing the agent loop without blocking Qt GUI."""

    chunk_received = Signal(str)
    thought_chunk = Signal(str)
    tool_started = Signal(str, dict)
    tool_finished = Signal(str, str, bool)  # tool_name, output, success
    subagent_spawned = Signal(object)  # SubagentRecord
    subagent_updated = Signal(str, str)  # subagent_id, state
    task_started = Signal(object)  # BackgroundTaskRecord
    task_finished = Signal(str, str, bool)  # task_id, status, success
    artifact_created = Signal(object)  # ArtifactRecord
    agent_finished = Signal()
    agent_error = Signal(str)

    def __init__(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
        simulation_mode: bool = True,
        provider: Optional[BaseAgentProvider] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.prompt = prompt
        self.context = context or {}
        self.simulation_mode = simulation_mode
        self._is_cancelled = False
        if provider is not None:
            self.provider = provider
        else:
            self.provider = get_provider("simulation" if simulation_mode else "auto")

    def cancel(self) -> None:
        """Cancel worker execution gracefully."""
        self._is_cancelled = True
        if hasattr(self, "provider") and self.provider:
            self.provider.cancel()

    def run(self) -> None:
        """Run worker logic via agent provider."""
        if self._is_cancelled:
            return

        try:
            for event in self.provider.stream_chat(
                prompt=self.prompt,
                context=self.context,
                cancel_check=lambda: self._is_cancelled,
            ):
                if self._is_cancelled:
                    break

                if isinstance(event, ThoughtEvent):
                    self.thought_chunk.emit(event.thought)
                elif isinstance(event, TokenEvent):
                    self.chunk_received.emit(event.token)
                elif isinstance(event, ToolCallEvent):
                    if not event.is_finished:
                        self.tool_started.emit(event.tool_name, event.tool_args)
                    else:
                        self.tool_finished.emit(event.tool_name, event.tool_output, event.success)
                elif isinstance(event, CompleteEvent):
                    self.agent_finished.emit()
                    return
                elif isinstance(event, ErrorEvent):
                    self.agent_error.emit(event.error_message)
                    return

            if not self._is_cancelled:
                self.agent_finished.emit()
        except Exception as exc:
            logger.exception("AgentWorker encountered an error: %s", exc)
            self.agent_error.emit(str(exc))

    def _run_simulation(self) -> None:
        """Execute a simulated agent cycle with thoughts, tools, and response."""
        # 1. Thought phase
        thoughts = [
            "Analizando la solicitud del usuario y el contexto HPC...",
            " Evaluando particiones Slurm y recursos disponibles...",
        ]
        for t in thoughts:
            if self._is_cancelled:
                return
            self.thought_chunk.emit(t)
            time.sleep(0.01)

        # 2. Tool invocation phase
        if self._is_cancelled:
            return

        tool_name = "squeue"
        tool_args = {"partition": "compute", "format": "%i %u %T"}
        self.tool_started.emit(tool_name, tool_args)
        time.sleep(0.01)

        if self._is_cancelled:
            return

        tool_output = "JOBID USER STATE\n10489 user1 RUNNING\n10490 user2 PENDING"
        self.tool_finished.emit(tool_name, tool_output, True)
        time.sleep(0.01)

        # 3. Response token streaming phase
        response_tokens = [
            "Se ", "han ", "revisado ", "los ", "recursos ", "HPC. ",
            "El ", "cluster ", "cuenta ", "con ", "particiones ", "activas ",
            "y ", "el ", "nodo ", "compute ", "esta ", "disponible.",
        ]
        for tok in response_tokens:
            if self._is_cancelled:
                return
            self.chunk_received.emit(tok)
            time.sleep(0.005)

        # 4. Finished
        if not self._is_cancelled:
            self.agent_finished.emit()

    def _run_live(self) -> None:
        """Stub for live agent execution through local/remote CLI or HTTP."""
        self.thought_chunk.emit("Iniciando conexion con motor agentico...")
        self.chunk_received.emit("Procesando consulta...")
        self.agent_finished.emit()


class InlineEditWorker(QThread):
    """Background worker generating inline code edits/refactorings."""

    edit_started = Signal()
    edit_completed = Signal(str)  # new proposed code
    edit_error = Signal(str)

    def __init__(
        self,
        instruction: str,
        code: str,
        language: str = "python",
        simulation_mode: bool = True,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.instruction = instruction
        self.code = code
        self.language = language
        self.simulation_mode = simulation_mode
        self._is_cancelled = False

    def cancel(self) -> None:
        """Cancel worker execution gracefully."""
        self._is_cancelled = True

    def run(self) -> None:
        """Execute inline edit code generation."""
        if self._is_cancelled:
            return

        self.edit_started.emit()
        try:
            if self.simulation_mode:
                self._run_simulation()
            else:
                self._run_live()
        except Exception as exc:
            logger.exception("InlineEditWorker encountered an error: %s", exc)
            self.edit_error.emit(str(exc))

    def _run_simulation(self) -> None:
        """Generate simulated HPC refactoring/transformations based on instruction."""
        time.sleep(0.02)
        if self._is_cancelled:
            return

        inst = self.instruction.lower().strip()
        transformed = self.code

        # 1. OpenMP directives
        if "openmp" in inst or "omp" in inst or "paralel" in inst or "parallel" in inst:
            if self.language in ("c", "cpp", "fortran"):
                if "#pragma omp" not in transformed and "!$omp" not in transformed:
                    if self.language == "fortran":
                        transformed = "!$OMP PARALLEL DO DEFAULT(SHARED)\n" + transformed + "\n!$OMP END PARALLEL DO"
                    else:
                        transformed = "#pragma omp parallel for\n" + transformed
            elif self.language in ("python", "py"):
                if "numba" not in transformed and "prange" not in transformed:
                    transformed = "# [HPC-Agent] Directiva OpenMP / Paralelizacion Numba recomendada\nfrom numba import njit, prange\n\n" + transformed
            else:
                transformed = "#pragma omp parallel for\n" + transformed

        # 2. Quantum ESPRESSO calculation = 'scf' -> 'relax'
        elif "relax" in inst:
            if "calculation" in transformed or "scf" in transformed:
                import re
                transformed = re.sub(
                    r"calculation\s*=\s*['\"]scf['\"]",
                    "calculation = 'relax'",
                    transformed,
                    flags=re.IGNORECASE,
                )
                if "calculation = 'relax'" not in transformed and "calculation" not in transformed:
                    transformed = "calculation = 'relax'\n" + transformed

        # 3. Optimize / change k-points
        elif "k-point" in inst or "kpoint" in inst or "k_point" in inst or "k points" in inst:
            import re
            if "K_POINTS" in transformed.upper():
                transformed = re.sub(
                    r"(K_POINTS\s+(?:automatic)?\s*\n\s*)\d+\s+\d+\s+\d+(\s+\d+\s+\d+\s+\d+)",
                    r"\g<1>8 8 8\2",
                    transformed,
                    flags=re.IGNORECASE,
                )
                if "8 8 8" not in transformed:
                    transformed = transformed + "\n# K_POINTS optimizados para convergencia fina: 8 8 8 0 0 0"
            else:
                transformed = transformed + "\nK_POINTS automatic\n  8 8 8 1 1 1\n"

        # 4. Format / clean syntax
        elif "format" in inst or "formatear" in inst or "sintaxis" in inst or "clean" in inst or "limpiar" in inst:
            lines = [line.rstrip() for line in transformed.strip().splitlines()]
            transformed = "\n".join(lines) + "\n"

        # 5. Default generic transformation
        else:
            header = f"# [HPC-Agent Refactor: {self.instruction}]\n"
            transformed = header + transformed

        if not self._is_cancelled:
            self.edit_completed.emit(transformed)

    def _run_live(self) -> None:
        """Live inline edit execution stub."""
        time.sleep(0.01)
        self.edit_completed.emit(self.code)


class AntigravityAgentBridge(QObject):
    """Bridge connecting the HPC Studio UI with Agent engines.

    Exposes Qt signals for streaming chunks, thought chains,
    tool call telemetry, and completion/error states.
    """

    chunk_received = Signal(str)
    thought_chunk = Signal(str)
    tool_started = Signal(str, dict)
    tool_finished = Signal(str, str, bool)  # tool_name, output, success
    subagent_spawned = Signal(object)  # SubagentRecord
    subagent_updated = Signal(str, str)  # subagent_id, state
    task_started = Signal(object)  # BackgroundTaskRecord
    task_finished = Signal(str, str, bool)  # task_id, status, success
    artifact_created = Signal(object)  # ArtifactRecord
    agent_finished = Signal()
    agent_error = Signal(str)

    # Inline editing signals
    inline_edit_started = Signal()
    inline_edit_completed = Signal(str)  # nuevo código propuesto
    inline_edit_error = Signal(str)

    # Human-in-the-loop approval signal: tool_name, tool_args, risk_level
    approval_requested = Signal(str, dict, object)

    def __init__(
        self,
        parent: Optional[QObject] = None,
        simulation_mode: bool = True,
        provider_name: str = "auto",
        provider_config: Optional[Dict[str, Any]] = None,
        tool_registry: Optional[ToolRegistry] = None,
    ):
        super().__init__(parent)
        self.simulation_mode = simulation_mode
        self.provider_name = provider_name
        self.provider_config = provider_config or {}
        self.tool_registry = tool_registry or get_default_registry()
        self.approval_gate = self.tool_registry.approval_gate
        self.provider: BaseAgentProvider = get_provider(
            "simulation" if simulation_mode else provider_name,
            self.provider_config,
        )
        self._current_worker: Optional[AgentWorker] = None
        self._current_edit_worker: Optional[InlineEditWorker] = None
        self._is_busy = False
        self._subagents: Dict[str, Any] = {}
        self._tasks: Dict[str, Any] = {}
        self._artifacts: Dict[str, Any] = {}

        # Connect approval callback if not set
        if not self.approval_gate._interactive_callback:
            self.approval_gate.set_interactive_callback(self._on_approval_gate_check)

    def _on_approval_gate_check(self, tool_name: str, args: Dict[str, Any], risk_level: RiskLevel) -> bool:
        """Internal callback invoked by ToolRegistry when risk approval is needed."""
        self.approval_requested.emit(tool_name, args, risk_level)
        # If in interactive memory or whitelisted:
        return tool_name in self.approval_gate.session_approved_tools

    @property
    def is_busy(self) -> bool:
        """Return True if agent is actively running a prompt or inline edit."""
        return self._is_busy

    def set_provider(self, name: str, config: Optional[Dict[str, Any]] = None) -> None:
        """Dynamically switch the active agent provider."""
        self.provider_name = name
        if config is not None:
            self.provider_config = config
        self.provider = get_provider(name, self.provider_config)

    def send_prompt(self, prompt: str, context: Optional[Dict[str, Any]] = None) -> bool:
        """Send a prompt to the agent asynchronously.

        Args:
            prompt: User text prompt.
            context: Optional dictionary with editor state, files, active cluster.

        Returns:
            bool: True if task was dispatched, False if already busy or empty prompt.
        """
        clean_prompt = prompt.strip()
        if not clean_prompt:
            logger.warning("Empty prompt received; ignoring.")
            return False

        if self._is_busy and self._current_worker and self._current_worker.isRunning():
            logger.warning("Agent is currently busy with another prompt.")
            return False

        self._is_busy = True
        self._current_worker = AgentWorker(
            prompt=clean_prompt,
            context=context or {},
            simulation_mode=self.simulation_mode,
            provider=self.provider,
            parent=self,
        )

        # Wire worker signals to bridge signals
        self._current_worker.chunk_received.connect(self.chunk_received)
        self._current_worker.thought_chunk.connect(self.thought_chunk)
        self._current_worker.tool_started.connect(self.tool_started)
        self._current_worker.tool_finished.connect(self.tool_finished)
        self._current_worker.subagent_spawned.connect(self._on_subagent_spawned)
        self._current_worker.subagent_updated.connect(self._on_subagent_updated)
        self._current_worker.task_started.connect(self._on_task_started)
        self._current_worker.task_finished.connect(self._on_task_finished)
        self._current_worker.artifact_created.connect(self._on_artifact_created)
        self._current_worker.agent_finished.connect(self._on_worker_finished)
        self._current_worker.agent_error.connect(self._on_worker_error)

        self._current_worker.start()
        return True

    def request_inline_edit(
        self,
        instruction: str,
        code: str,
        language: str = "python",
    ) -> bool:
        """Request an inline code edit or refactor asynchronously.

        Args:
            instruction: User instruction (e.g. 'añadir directivas OpenMP', 'cambiar scf a relax').
            code: Original code snippet to transform.
            language: Language of the code ('python', 'fortran', 'c', 'qe', etc.).

        Returns:
            bool: True if edit request was dispatched, False if busy.
        """
        clean_instruction = instruction.strip()
        if not clean_instruction:
            logger.warning("Empty inline edit instruction received; ignoring.")
            return False

        if self._is_busy and self._current_edit_worker and self._current_edit_worker.isRunning():
            logger.warning("Agent is currently busy with another inline edit.")
            return False

        self._is_busy = True
        self._current_edit_worker = InlineEditWorker(
            instruction=clean_instruction,
            code=code,
            language=language,
            simulation_mode=self.simulation_mode,
            parent=self,
        )

        self._current_edit_worker.edit_started.connect(self._on_inline_edit_started)
        self._current_edit_worker.edit_completed.connect(self._on_inline_edit_completed)
        self._current_edit_worker.edit_error.connect(self._on_inline_edit_error)

        self._current_edit_worker.start()
        return True

    def _on_inline_edit_started(self) -> None:
        self.inline_edit_started.emit()

    def _on_inline_edit_completed(self, new_code: str) -> None:
        self._is_busy = False
        self.inline_edit_completed.emit(new_code)

    def _on_inline_edit_error(self, err: str) -> None:
        self._is_busy = False
        self.inline_edit_error.emit(err)

    def cancel(self) -> None:
        """Cancel current execution if running."""
        if self._current_worker and self._current_worker.isRunning():
            self._current_worker.cancel()
            self._current_worker.wait(500)
            self._is_busy = False

        if self._current_edit_worker and self._current_edit_worker.isRunning():
            self._current_edit_worker.cancel()
            self._current_edit_worker.wait(500)
            self._is_busy = False

    def kill_task(self, task_id: str) -> bool:
        """Kill or terminate a running background task by its identifier.

        Args:
            task_id: Unique background task identifier.

        Returns:
            bool: True if task was found and killed/updated.
        """
        logger.info("Solicitud para detener tarea: %s", task_id)
        if task_id in self._tasks:
            task = self._tasks[task_id]
            if hasattr(task, "status"):
                task.status = "terminated"
            self.task_finished.emit(task_id, "terminated", False)
            return True
        # Also emit signal if task was tracked externally
        self.task_finished.emit(task_id, "terminated", False)
        return True

    def kill_all_subagents(self) -> int:
        """Terminate all currently active subagents.

        Returns:
            int: Number of terminated subagents.
        """
        logger.info("Solicitud para cancelar todos los subagentes activos.")
        killed_count = 0
        for sub_id, record in list(self._subagents.items()):
            state = getattr(record, "state", "")
            if state in ("running", "idle"):
                if hasattr(record, "state"):
                    record.state = "completed"
                self.subagent_updated.emit(sub_id, "completed")
                killed_count += 1
        return killed_count

    def _on_subagent_spawned(self, record: Any) -> None:
        rec_id = getattr(record, "id", str(record))
        self._subagents[rec_id] = record
        self.subagent_spawned.emit(record)

    def _on_subagent_updated(self, subagent_id: str, state: str) -> None:
        if subagent_id in self._subagents:
            record = self._subagents[subagent_id]
            if hasattr(record, "state"):
                record.state = state
        self.subagent_updated.emit(subagent_id, state)

    def _on_task_started(self, record: Any) -> None:
        task_id = getattr(record, "task_id", str(record))
        self._tasks[task_id] = record
        self.task_started.emit(record)

    def _on_task_finished(self, task_id: str, status: str, success: bool) -> None:
        if task_id in self._tasks:
            task = self._tasks[task_id]
            if hasattr(task, "status"):
                task.status = status
        self.task_finished.emit(task_id, status, success)

    def _on_artifact_created(self, record: Any) -> None:
        art_id = getattr(record, "id", str(record))
        self._artifacts[art_id] = record
        self.artifact_created.emit(record)

    def _on_worker_finished(self) -> None:
        self._is_busy = False
        self.agent_finished.emit()

    def _on_worker_error(self, err: str) -> None:
        self._is_busy = False
        self.agent_error.emit(err)
