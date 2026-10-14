"""Unit tests for Slurm data models and state transitions."""

from __future__ import annotations

import pytest

from hpc_studio.slurm.models import JobState, SlurmJob, SlurmNode, SlurmPartition


class TestJobState:
    """Test Slurm JobState enum parsing and abbreviation handling."""

    def test_from_string_abbreviations(self):
        assert JobState.from_string("PD") == JobState.PENDING
        assert JobState.from_string("R") == JobState.RUNNING
        assert JobState.from_string("CG") == JobState.COMPLETED
        assert JobState.from_string("CD") == JobState.COMPLETED
        assert JobState.from_string("CA") == JobState.CANCELLED
        assert JobState.from_string("F") == JobState.FAILED
        assert JobState.from_string("TO") == JobState.TIMEOUT
        assert JobState.from_string("NF") == JobState.NODE_FAIL
        assert JobState.from_string("PR") == JobState.PREEMPTED
        assert JobState.from_string("BF") == JobState.BOOT_FAIL
        assert JobState.from_string("DL") == JobState.DEADLINE
        assert JobState.from_string("OOM") == JobState.OUT_OF_MEMORY
        assert JobState.from_string("S") == JobState.SUSPENDED

    def test_from_string_full_names_and_case_insensitivity(self):
        assert JobState.from_string("PENDING") == JobState.PENDING
        assert JobState.from_string("running") == JobState.RUNNING
        assert JobState.from_string("COMPLETED") == JobState.COMPLETED
        assert JobState.from_string("CANCELLED") == JobState.CANCELLED
        assert JobState.from_string("CANCELED") == JobState.CANCELLED
        assert JobState.from_string("FAILED") == JobState.FAILED
        assert JobState.from_string("TIMEOUT") == JobState.TIMEOUT
        assert JobState.from_string("NODE_FAIL") == JobState.NODE_FAIL
        assert JobState.from_string("OUT_OF_MEMORY") == JobState.OUT_OF_MEMORY

    def test_from_string_with_flags_and_modifiers(self):
        # Flags like PD+, R*, CG+
        assert JobState.from_string("PD+") == JobState.PENDING
        assert JobState.from_string("R*") == JobState.RUNNING
        assert JobState.from_string("CD+") == JobState.COMPLETED

    def test_from_string_invalid(self):
        assert JobState.from_string("") == JobState.UNKNOWN
        assert JobState.from_string("NONEXISTENT_STATE") == JobState.UNKNOWN
        assert JobState.from_string(None) == JobState.UNKNOWN


class TestSlurmJob:
    """Test SlurmJob properties and badge colors."""

    def test_job_properties_active_and_done(self):
        job_running = SlurmJob(
            job_id="101",
            name="test_sim",
            user="user1",
            partition="gpu",
            state=JobState.RUNNING,
        )
        assert job_running.is_active is True
        assert job_running.is_done is False
        assert job_running.state_badge_color == "#98c379"

        job_pending = SlurmJob(
            job_id="102",
            name="test_sim_2",
            user="user1",
            partition="gpu",
            state=JobState.PENDING,
        )
        assert job_pending.is_active is True
        assert job_pending.is_done is False
        assert job_pending.state_badge_color == "#e5c07b"

        job_failed = SlurmJob(
            job_id="103",
            name="test_fail",
            user="user1",
            partition="standard",
            state=JobState.FAILED,
        )
        assert job_failed.is_active is False
        assert job_failed.is_done is True
        assert job_failed.state_badge_color == "#e06c75"

        job_completed = SlurmJob(
            job_id="104",
            name="test_ok",
            user="user1",
            partition="standard",
            state=JobState.COMPLETED,
        )
        assert job_completed.is_active is False
        assert job_completed.is_done is True
        assert job_completed.state_badge_color == "#abb2bf"

        job_cancelled = SlurmJob(
            job_id="105",
            name="test_cancel",
            user="user1",
            partition="standard",
            state=JobState.CANCELLED,
        )
        assert job_cancelled.is_active is False
        assert job_cancelled.is_done is True
        assert job_cancelled.state_badge_color == "#abb2bf"

        job_unknown = SlurmJob(
            job_id="106",
            name="test_unk",
            user="user1",
            partition="standard",
            state=JobState.UNKNOWN,
        )
        assert job_unknown.is_active is False
        assert job_unknown.is_done is False


class TestSlurmPartition:
    """Test SlurmPartition utilization calculation."""

    def test_utilization_pct(self):
        part = SlurmPartition(
            name="compute",
            state="up",
            total_nodes=10,
            idle_nodes=3,
            busy_nodes=7,
            other_nodes=0,
            max_time="24:00:00",
            cpus_per_node="64",
        )
        assert part.utilization_pct == 70.0

    def test_utilization_zero_nodes(self):
        part = SlurmPartition(
            name="empty",
            state="down",
            total_nodes=0,
            idle_nodes=0,
            busy_nodes=0,
            other_nodes=0,
            max_time="infinite",
            cpus_per_node="0",
        )
        assert part.utilization_pct == 0.0


class TestSlurmNode:
    """Test SlurmNode dataclass instantiation."""

    def test_node_instantiation(self):
        node = SlurmNode(
            node_name="node01",
            state="idle",
            cpus_total=64,
            cpus_alloc=0,
            cpus_idle=64,
            memory_mb=128000,
            alloc_memory_mb=0,
            gpus="gpu:a100:4",
            reason="none",
        )
        assert node.node_name == "node01"
        assert node.gpus == "gpu:a100:4"
        assert node.cpus_idle == 64
