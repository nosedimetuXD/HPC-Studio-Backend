"""Slurm and Quantum ESPRESSO calculation convergence and anomaly watchdog.

Monitors output stream lines for:
- Iteration counts, total energies, and SCF accuracy steps.
- Completion signals ('JOB DONE.').
- Convergence failure alerts ('convergence NOT achieved').
- Critical execution aborts and system faults (OOM, segmentation faults, timeouts).
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from ..core.signals import QObject, Signal

logger = logging.getLogger(__name__)

# Regular expressions for Quantum ESPRESSO output metrics
RE_ITERATION = re.compile(r"iteration\s*#\s*(\d+)", re.IGNORECASE)
RE_ENERGY = re.compile(r"total\s+energy\s*=\s*([-\d\.]+)\s*Ry", re.IGNORECASE)
RE_ACCURACY = re.compile(r"estimated\s+scf\s+accuracy\s*<\s*([-\d\.eE\+]+)\s*Ry", re.IGNORECASE)

# Termination patterns
PATTERN_JOB_DONE = "JOB DONE."
PATTERN_CONVERGENCE_NOT_ACHIEVED = "convergence NOT achieved"

# Critical system error signatures
CRASH_KEYWORDS = [
    ("OOM", "OUT OF MEMORY"),
    ("OOM", "oom-kill"),
    ("TIMEOUT", "DUE TO TIME LIMIT"),
    ("SIGSEGV", "SIGSEGV"),
    ("SIGSEGV", "segmentation fault"),
    ("ROUTINE_ERROR", "Error in routine"),
]


class ConvergenceWatchdog(QObject):
    """Watches calculation logs line by line, detecting SCF progress, completion, and failures."""

    scf_step_detected = Signal(int, float, float)  # (iteration_number, energy_ry, accuracy_ry)
    job_completed = Signal(str)  # message
    convergence_failed = Signal(str)  # message
    system_error_detected = Signal(str, str)  # (error_type, error_line)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.current_iteration: int = 0
        self.current_energy: Optional[float] = None
        self.current_accuracy: Optional[float] = None
        self.status_text: str = "Esperando cálculo..."
        self.is_done: bool = False
        self.has_error: bool = False

    def reset(self) -> None:
        """Reset all counters, metrics, and watchdog status."""
        self.current_iteration = 0
        self.current_energy = None
        self.current_accuracy = None
        self.status_text = "Esperando cálculo..."
        self.is_done = False
        self.has_error = False

    def process_line(self, line: str) -> None:
        """Analyze a single log line, updating state and emitting relevant signals.

        Args:
            line: Log line to process.
        """
        if not line:
            return

        clean_line = line.strip()

        # 1. Parse iteration number
        iter_match = RE_ITERATION.search(clean_line)
        if iter_match:
            try:
                self.current_iteration = int(iter_match.group(1))
                self.status_text = f"Iteración {self.current_iteration}"
            except ValueError:
                pass

        # 2. Parse total energy
        energy_match = RE_ENERGY.search(clean_line)
        if energy_match:
            try:
                self.current_energy = float(energy_match.group(1))
            except ValueError:
                pass

        # 3. Parse estimated SCF accuracy
        accuracy_match = RE_ACCURACY.search(clean_line)
        if accuracy_match:
            try:
                self.current_accuracy = float(accuracy_match.group(1))
                energy_val = self.current_energy if self.current_energy is not None else 0.0
                self.scf_step_detected.emit(
                    self.current_iteration,
                    energy_val,
                    self.current_accuracy,
                )
            except ValueError:
                pass

        # 4. Check for job completion
        if PATTERN_JOB_DONE in clean_line:
            self.is_done = True
            self.status_text = "Cálculo finalizado exitosamente"
            self.job_completed.emit("JOB DONE.")

        # 5. Check for convergence failure
        if PATTERN_CONVERGENCE_NOT_ACHIEVED.lower() in clean_line.lower():
            self.has_error = True
            self.status_text = "Fallo de convergencia SCF"
            self.convergence_failed.emit(clean_line)

        # 6. Check for crash keywords and system faults
        clean_lower = clean_line.lower()
        for error_type, keyword in CRASH_KEYWORDS:
            if keyword.lower() in clean_lower:
                self.has_error = True
                self.status_text = f"Error crítico: {error_type}"
                self.system_error_detected.emit(error_type, clean_line)
                break
