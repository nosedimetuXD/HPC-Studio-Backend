"""Slurm workload manager integration for HPC Studio.

Provides data models, SSH-based client, asynchronous monitoring workers,
expert parallelization advisor, and automated SLURM script generators.
"""

from __future__ import annotations

from .advisor import ParallelizationAdvisor
from .client import SlurmClient
from .generator import SlurmBatchConfig, SlurmScriptGenerator
from .log_follower import RemoteLogStreamer
from .models import JobState, SlurmJob, SlurmNode, SlurmPartition
from .monitor import SlurmMonitorWorker
from .watchdog import ConvergenceWatchdog

__all__ = [
    "JobState",
    "SlurmJob",
    "SlurmPartition",
    "SlurmNode",
    "SlurmClient",
    "SlurmMonitorWorker",
    "ParallelizationAdvisor",
    "SlurmBatchConfig",
    "SlurmScriptGenerator",
    "RemoteLogStreamer",
    "ConvergenceWatchdog",
]

