"""Slurm client executing commands via SSH.

Interacts with squeue, sinfo, scancel, and scontrol to inspect and manage HPC jobs and resources.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Tuple

from ..ssh.client import SSHClientManager
from .models import JobState, SlurmJob, SlurmNode, SlurmPartition

logger = logging.getLogger(__name__)


class SlurmClient:
    """Client for interacting with Slurm over an SSH connection."""

    def __init__(self, ssh_manager: Optional[SSHClientManager] = None) -> None:
        self.ssh_manager = ssh_manager

    @property
    def is_connected(self) -> bool:
        """True if the underlying SSH manager is connected."""
        return bool(self.ssh_manager and self.ssh_manager.is_connected)

    def get_jobs(
        self,
        user: Optional[str] = None,
        partition: Optional[str] = None,
        states: Optional[List[str]] = None,
        timeout: int = 10,
    ) -> List[SlurmJob]:
        """Fetch queued and running Slurm jobs.

        Executes `squeue -o "%i|%j|%u|%T|%M|%l|%D|%C|%R|%Z|%N" --noheader` over SSH.
        """
        if not self.is_connected or not self.ssh_manager:
            logger.warning("SlurmClient not connected. Cannot fetch jobs.")
            return []

        cmd_parts = ["squeue", '-o "%i|%j|%u|%T|%M|%l|%D|%C|%R|%Z|%N"', "--noheader"]
        if user:
            clean_user = user.strip()
            if not re.match(r"^[A-Za-z0-9_.-]+$", clean_user):
                raise ValueError(f"Invalid username for squeue: {user!r}")
            cmd_parts.extend(["-u", clean_user])
        if partition:
            clean_part = partition.strip()
            if not re.match(r"^[A-Za-z0-9_.-]+$", clean_part):
                raise ValueError(f"Invalid partition for squeue: {partition!r}")
            cmd_parts.extend(["-p", clean_part])
        if states:
            clean_states = [s.strip() for s in states]
            for s in clean_states:
                if not re.match(r"^[A-Za-z0-9_]+$", s):
                    raise ValueError(f"Invalid job state for squeue: {s!r}")
            cmd_parts.extend(["-t", ",".join(clean_states)])

        cmd = " ".join(cmd_parts)
        try:
            result = self.ssh_manager.execute_command(cmd, timeout=timeout)
            if not result.success:
                logger.error("squeue command failed (exit %d): %s", result.exit_code, result.stderr)
                return []

            jobs: List[SlurmJob] = []
            for line in result.stdout.strip().splitlines():
                line = line.strip()
                if not line:
                    continue

                parts = line.split("|")
                # Format: %i|%j|%u|%T|%M|%l|%D|%C|%R|%Z|%N
                # Expecting at least 11 tokens, but tolerate variance
                if len(parts) < 11:
                    parts = parts + [""] * (11 - len(parts))

                job_id = parts[0].strip()
                name = parts[1].strip()
                username = parts[2].strip()
                raw_state = parts[3].strip()
                time_used = parts[4].strip()
                time_limit = parts[5].strip()
                
                try:
                    nodes = int(parts[6].strip())
                except (ValueError, TypeError):
                    nodes = 1

                try:
                    cpus = int(parts[7].strip())
                except (ValueError, TypeError):
                    cpus = 1

                reason = parts[8].strip()
                work_dir = parts[9].strip()
                nodelist = parts[10].strip()

                state = JobState.from_string(raw_state)

                jobs.append(
                    SlurmJob(
                        job_id=job_id,
                        name=name,
                        user=username,
                        partition=partition or "",  # Will be refined if partition is present or parsed
                        state=state,
                        time_used=time_used or "00:00",
                        time_limit=time_limit or "UNLIMITED",
                        nodes=nodes,
                        cpus=cpus,
                        work_dir=work_dir,
                        reason=reason,
                        nodelist=nodelist,
                        raw_state=raw_state,
                    )
                )

            return jobs
        except Exception as exc:
            logger.error("Error executing squeue: %s", exc)
            return []

    def get_partitions(self, timeout: int = 10) -> List[SlurmPartition]:
        """Fetch partition information.

        Executes `sinfo -o "%P|%a|%l|%D|%F|%c|%m|%G|%N" --noheader` over SSH.
        Node states in %F are formatted as allocated/idle/other/total.
        """
        if not self.is_connected or not self.ssh_manager:
            logger.warning("SlurmClient not connected. Cannot fetch partitions.")
            return []

        cmd = 'sinfo -o "%P|%a|%l|%D|%F|%c|%m|%G|%N" --noheader'
        try:
            result = self.ssh_manager.execute_command(cmd, timeout=timeout)
            if not result.success:
                logger.error("sinfo partitions command failed (exit %d): %s", result.exit_code, result.stderr)
                return []

            partitions: List[SlurmPartition] = []
            for line in result.stdout.strip().splitlines():
                line = line.strip()
                if not line:
                    continue

                parts = line.split("|")
                if len(parts) < 9:
                    parts = parts + [""] * (9 - len(parts))

                raw_name = parts[0].strip()
                # Partition name might end with '*' if default
                name = raw_name.rstrip("*")
                state = parts[1].strip()
                max_time = parts[2].strip()

                try:
                    total_nodes = int(parts[3].strip())
                except (ValueError, TypeError):
                    total_nodes = 0

                node_states = parts[4].strip().split("/")
                busy_nodes = 0
                idle_nodes = 0
                other_nodes = 0
                if len(node_states) >= 4:
                    try:
                        busy_nodes = int(node_states[0])
                        idle_nodes = int(node_states[1])
                        other_nodes = int(node_states[2])
                        total_nodes = int(node_states[3])
                    except (ValueError, TypeError):
                        pass

                cpus_per_node = parts[5].strip()
                gpus = parts[7].strip()

                partitions.append(
                    SlurmPartition(
                        name=name,
                        state=state,
                        total_nodes=total_nodes,
                        idle_nodes=idle_nodes,
                        busy_nodes=busy_nodes,
                        other_nodes=other_nodes,
                        max_time=max_time,
                        cpus_per_node=cpus_per_node,
                        gpus=gpus,
                    )
                )

            return partitions
        except Exception as exc:
            logger.error("Error executing sinfo partitions: %s", exc)
            return []

    def get_nodes(self, timeout: int = 10) -> List[SlurmNode]:
        """Fetch node details.

        Executes `sinfo -N -o "%N|%T|%c|%C|%m|%G|%E" --noheader` over SSH.
        %c is cpus total, %C is cpus allocated/idle/other/total, %m is memory, %G is gpus, %E is reason.
        """
        if not self.is_connected or not self.ssh_manager:
            logger.warning("SlurmClient not connected. Cannot fetch nodes.")
            return []

        cmd = 'sinfo -N -o "%N|%T|%c|%C|%m|%G|%E" --noheader'
        try:
            result = self.ssh_manager.execute_command(cmd, timeout=timeout)
            if not result.success:
                logger.error("sinfo nodes command failed (exit %d): %s", result.exit_code, result.stderr)
                return []

            nodes: List[SlurmNode] = []
            for line in result.stdout.strip().splitlines():
                line = line.strip()
                if not line:
                    continue

                parts = line.split("|")
                if len(parts) < 7:
                    parts = parts + [""] * (7 - len(parts))

                node_name = parts[0].strip()
                state = parts[1].strip()

                try:
                    cpus_total = int(parts[2].strip())
                except (ValueError, TypeError):
                    cpus_total = 0

                cpus_alloc = 0
                cpus_idle = 0
                cpu_breakdown = parts[3].strip().split("/")
                if len(cpu_breakdown) >= 4:
                    try:
                        cpus_alloc = int(cpu_breakdown[0])
                        cpus_idle = int(cpu_breakdown[1])
                        # other = int(cpu_breakdown[2])
                        # total = int(cpu_breakdown[3])
                    except (ValueError, TypeError):
                        pass

                try:
                    memory_mb = int(parts[4].strip())
                except (ValueError, TypeError):
                    memory_mb = 0

                gpus = parts[5].strip()
                reason = parts[6].strip()

                nodes.append(
                    SlurmNode(
                        node_name=node_name,
                        state=state,
                        cpus_total=cpus_total,
                        cpus_alloc=cpus_alloc,
                        cpus_idle=cpus_idle,
                        memory_mb=memory_mb,
                        alloc_memory_mb=0,
                        gpus=gpus,
                        reason=reason,
                    )
                )

            return nodes
        except Exception as exc:
            logger.error("Error executing sinfo nodes: %s", exc)
            return []

    @staticmethod
    def _validate_job_id(job_id: str) -> str:
        """Validate Slurm job ID format to prevent shell injection."""
        if not isinstance(job_id, str):
            job_id = str(job_id)
        clean = job_id.strip()
        if not re.match(r"^[0-9]+(?:_[0-9]+)?$", clean):
            raise ValueError(f"Invalid Slurm job ID: {job_id!r}")
        return clean

    def cancel_job(self, job_id: str, signal: Optional[str] = None) -> Tuple[bool, str]:
        """Cancel a running or pending job with optional signal."""
        clean_id = self._validate_job_id(job_id)
        if signal:
            clean_sig = signal.strip()
            if not re.match(r"^[A-Za-z0-9]+$", clean_sig):
                raise ValueError(f"Invalid signal name: {signal!r}")
            cmd = f"scancel -s {clean_sig} {clean_id}"
        else:
            cmd = f"scancel {clean_id}"

        if not self.is_connected or not self.ssh_manager:
            return False, "SSH client is not connected."

        try:
            result = self.ssh_manager.execute_command(cmd)
            if result.success:
                return True, result.stdout.strip()
            return False, result.stderr.strip() or f"Process exited with code {result.exit_code}"
        except Exception as exc:
            if isinstance(exc, ValueError):
                raise
            logger.error("Error running scancel for %s: %s", job_id, exc)
            return False, str(exc)

    def hold_job(self, job_id: str) -> Tuple[bool, str]:
        """Hold a pending job."""
        clean_id = self._validate_job_id(job_id)
        if not self.is_connected or not self.ssh_manager:
            return False, "SSH client is not connected."

        cmd = f"scontrol hold {clean_id}"
        try:
            result = self.ssh_manager.execute_command(cmd)
            if result.success:
                return True, result.stdout.strip()
            return False, result.stderr.strip() or f"Process exited with code {result.exit_code}"
        except Exception as exc:
            if isinstance(exc, ValueError):
                raise
            logger.error("Error holding job %s: %s", job_id, exc)
            return False, str(exc)

    def release_job(self, job_id: str) -> Tuple[bool, str]:
        """Release a held job."""
        clean_id = self._validate_job_id(job_id)
        if not self.is_connected or not self.ssh_manager:
            return False, "SSH client is not connected."

        cmd = f"scontrol release {clean_id}"
        try:
            result = self.ssh_manager.execute_command(cmd)
            if result.success:
                return True, result.stdout.strip()
            return False, result.stderr.strip() or f"Process exited with code {result.exit_code}"
        except Exception as exc:
            if isinstance(exc, ValueError):
                raise
            logger.error("Error releasing job %s: %s", job_id, exc)
            return False, str(exc)

    def get_job_details(self, job_id: str) -> Dict[str, str]:
        """Get detailed job inspection via `scontrol show job -d <job_id>`."""
        clean_id = self._validate_job_id(job_id)
        if not self.is_connected or not self.ssh_manager:
            logger.warning("SlurmClient not connected. Cannot fetch job details.")
            return {}

        cmd = f"scontrol show job -d {clean_id}"
        try:
            result = self.ssh_manager.execute_command(cmd)
            if not result.success:
                logger.error("scontrol show job failed: %s", result.stderr)
                return {}

            details: Dict[str, str] = {}
            # Match Key=Value pairs taking into account spaces or multiline output
            # Slurm scontrol output typically formats as: JobId=123 JobName=test
            # or with multiple tokens per line
            pattern = re.compile(r'(\b[A-Za-z0-9_]+)=([^\s=]+(?:\s+(?![A-Za-z0-9_]+=)[^\s=]+)*)')
            for line in result.stdout.splitlines():
                for match in pattern.finditer(line):
                    k, v = match.groups()
                    details[k] = v.strip()

            return details
        except Exception as exc:
            logger.error("Error executing scontrol show job for %s: %s", job_id, exc)
            return {}
