"""Data models and state representations for Slurm workload manager.

Defines JobState enum, SlurmJob dataclass, SlurmPartition dataclass, and SlurmNode dataclass.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class JobState(str, Enum):
    """Slurm job execution states."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    NODE_FAIL = "NODE_FAIL"
    PREEMPTED = "PREEMPTED"
    BOOT_FAIL = "BOOT_FAIL"
    DEADLINE = "DEADLINE"
    OUT_OF_MEMORY = "OUT_OF_MEMORY"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def from_string(cls, val: str) -> JobState:
        """Parse standard Slurm abbreviations and state names into a JobState enum member.

        Slurm states can contain flags/suffixes like '+', '*', or state modifiers.
        Handles PD, R, CG, CD, CA, F, TO, NF, PR, BF, DL, OOM, and full names.
        """
        if not val or not isinstance(val, str):
            return cls.UNKNOWN

        clean = val.strip().upper()
        # Remove trailing flags such as '+' or '*'
        clean = clean.rstrip("+*")

        # Map common abbreviations
        abbreviation_map = {
            "PD": cls.PENDING,
            "R": cls.RUNNING,
            "CG": cls.COMPLETED,  # Completing -> maps to COMPLETED
            "CD": cls.COMPLETED,  # Completed
            "CA": cls.CANCELLED,
            "F": cls.FAILED,
            "TO": cls.TIMEOUT,
            "NF": cls.NODE_FAIL,
            "PR": cls.PREEMPTED,
            "BF": cls.BOOT_FAIL,
            "DL": cls.DEADLINE,
            "OOM": cls.OUT_OF_MEMORY,
            "S": cls.SUSPENDED,
        }

        if clean in abbreviation_map:
            return abbreviation_map[clean]

        # Match exact enum member name
        for state in cls:
            if state.value == clean:
                return state

        # Also handle common variants
        variant_map = {
            "COMPLETING": cls.COMPLETED,
            "CANCELED": cls.CANCELLED,
            "PREEMPTING": cls.PREEMPTED,
            "TIMEOUTS": cls.TIMEOUT,
            "OUTOFMEMORY": cls.OUT_OF_MEMORY,
        }
        if clean in variant_map:
            return variant_map[clean]

        return cls.UNKNOWN


@dataclass
class SlurmJob:
    """Represents a workload job queued or executed in Slurm."""

    job_id: str
    name: str
    user: str
    partition: str
    state: JobState
    time_used: str = "00:00"
    time_limit: str = "UNLIMITED"
    nodes: int = 1
    cpus: int = 1
    work_dir: str = ""
    reason: str = ""
    nodelist: str = ""
    raw_state: str = ""

    @property
    def is_active(self) -> bool:
        """True if the job is active in the queue (RUNNING, PENDING, or SUSPENDED)."""
        return self.state in (JobState.RUNNING, JobState.PENDING, JobState.SUSPENDED)

    @property
    def is_done(self) -> bool:
        """True if the job has finished execution (terminal state)."""
        return not self.is_active and self.state != JobState.UNKNOWN

    @property
    def state_badge_color(self) -> str:
        """Hex color code representing the status badge."""
        if self.state == JobState.RUNNING:
            return "#98c379"  # Green
        if self.state == JobState.PENDING:
            return "#e5c07b"  # Yellow
        if self.state in (JobState.FAILED, JobState.TIMEOUT, JobState.NODE_FAIL, JobState.BOOT_FAIL, JobState.OUT_OF_MEMORY):
            return "#e06c75"  # Red
        if self.state in (JobState.COMPLETED, JobState.CANCELLED):
            return "#abb2bf"  # Gray / Slate
        return "#abb2bf"


@dataclass
class SlurmPartition:
    """Represents a cluster partition/queue in Slurm."""

    name: str
    state: str
    total_nodes: int
    idle_nodes: int
    busy_nodes: int
    other_nodes: int
    max_time: str
    cpus_per_node: str
    gpus: str = ""

    @property
    def utilization_pct(self) -> float:
        """Calculates partition node utilization percentage."""
        if self.total_nodes <= 0:
            return 0.0
        pct = (self.busy_nodes / self.total_nodes) * 100.0
        return max(0.0, min(100.0, round(pct, 2)))


@dataclass
class SlurmNode:
    """Represents an individual compute node in Slurm."""

    node_name: str
    state: str
    cpus_total: int
    cpus_alloc: int
    cpus_idle: int
    memory_mb: int
    alloc_memory_mb: int = 0
    gpus: str = ""
    reason: str = ""
