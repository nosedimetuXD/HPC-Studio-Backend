"""Unit tests for SlurmClient with mocked SSHClientManager."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from hpc_studio.slurm.client import SlurmClient
from hpc_studio.slurm.models import JobState
from hpc_studio.ssh.client import CommandResult, SSHClientManager


@pytest.fixture
def mock_ssh_manager():
    manager = MagicMock(spec=SSHClientManager)
    manager.is_connected = True
    return manager


@pytest.fixture
def slurm_client(mock_ssh_manager):
    return SlurmClient(ssh_manager=mock_ssh_manager)


class TestSlurmClient:
    """Test SlurmClient command generation and parsing."""

    def test_connection_status(self, mock_ssh_manager):
        client = SlurmClient(ssh_manager=mock_ssh_manager)
        assert client.is_connected is True

        mock_ssh_manager.is_connected = False
        assert client.is_connected is False

        client_none = SlurmClient(ssh_manager=None)
        assert client_none.is_connected is False

    def test_get_jobs_parsing(self, slurm_client, mock_ssh_manager):
        # Format: %i|%j|%u|%T|%M|%l|%D|%C|%R|%Z|%N
        stdout = (
            "1001|sim_qe|user1|RUNNING|01:23:45|12:00:00|2|64|None|/scratch/user1/job1|node[01-02]\n"
            "1002|train_ml|user2|PENDING|00:00|04:00:00|1|32|Resources|/home/user2/ml|\n"
            "1003|bad_run|user3|FAILED|00:05|01:00:00|1|8|NonZeroExitCode|/scratch/user3|node03\n"
        )
        mock_ssh_manager.execute_command.return_value = CommandResult(
            command="squeue",
            stdout=stdout,
            stderr="",
            exit_code=0,
            duration=0.1,
        )

        jobs = slurm_client.get_jobs(user="user1", partition="gpu", states=["R", "PD"])
        assert len(jobs) == 3

        j1 = jobs[0]
        assert j1.job_id == "1001"
        assert j1.name == "sim_qe"
        assert j1.user == "user1"
        assert j1.state == JobState.RUNNING
        assert j1.time_used == "01:23:45"
        assert j1.time_limit == "12:00:00"
        assert j1.nodes == 2
        assert j1.cpus == 64
        assert j1.reason == "None"
        assert j1.work_dir == "/scratch/user1/job1"
        assert j1.nodelist == "node[01-02]"

        j2 = jobs[1]
        assert j2.job_id == "1002"
        assert j2.state == JobState.PENDING
        assert j2.reason == "Resources"

        j3 = jobs[2]
        assert j3.job_id == "1003"
        assert j3.state == JobState.FAILED

        # Verify command flags
        executed_cmd = mock_ssh_manager.execute_command.call_args[0][0]
        assert "-u user1" in executed_cmd
        assert "-p gpu" in executed_cmd
        assert "-t R,PD" in executed_cmd

    def test_get_jobs_disconnected(self, slurm_client, mock_ssh_manager):
        mock_ssh_manager.is_connected = False
        jobs = slurm_client.get_jobs()
        assert jobs == []
        mock_ssh_manager.execute_command.assert_not_called()

    def test_get_jobs_command_failure(self, slurm_client, mock_ssh_manager):
        mock_ssh_manager.execute_command.return_value = CommandResult(
            command="squeue",
            stdout="",
            stderr="squeue: command not found",
            exit_code=127,
            duration=0.05,
        )
        jobs = slurm_client.get_jobs()
        assert jobs == []

    def test_get_partitions(self, slurm_client, mock_ssh_manager):
        # Format: %P|%a|%l|%D|%F|%c|%m|%G|%N
        # Node states: allocated/idle/other/total
        stdout = (
            "gpu*|up|2-00:00:00|8|4/2/2/8|64|256000|gpu:a100:4|node[01-08]\n"
            "compute|up|infinite|16|8/8/0/16|128|512000|(null)|node[09-24]\n"
        )
        mock_ssh_manager.execute_command.return_value = CommandResult(
            command="sinfo",
            stdout=stdout,
            stderr="",
            exit_code=0,
            duration=0.1,
        )

        partitions = slurm_client.get_partitions()
        assert len(partitions) == 2

        p1 = partitions[0]
        assert p1.name == "gpu"  # asterisk stripped
        assert p1.state == "up"
        assert p1.max_time == "2-00:00:00"
        assert p1.total_nodes == 8
        assert p1.busy_nodes == 4
        assert p1.idle_nodes == 2
        assert p1.other_nodes == 2
        assert p1.cpus_per_node == "64"
        assert p1.gpus == "gpu:a100:4"
        assert p1.utilization_pct == 50.0

        p2 = partitions[1]
        assert p2.name == "compute"
        assert p2.total_nodes == 16
        assert p2.busy_nodes == 8
        assert p2.idle_nodes == 8
        assert p2.utilization_pct == 50.0

    def test_get_nodes(self, slurm_client, mock_ssh_manager):
        # Format: %N|%T|%c|%C|%m|%G|%E
        # %C is cpus allocated/idle/other/total
        stdout = (
            "node01|idle|64|0/64/0/64|256000|gpu:a100:4|none\n"
            "node02|mixed|64|32/32/0/64|256000|gpu:a100:4|none\n"
            "node03|down*|64|0/0/64/64|256000|gpu:a100:4|Node unresponsive\n"
        )
        mock_ssh_manager.execute_command.return_value = CommandResult(
            command="sinfo -N",
            stdout=stdout,
            stderr="",
            exit_code=0,
            duration=0.1,
        )

        nodes = slurm_client.get_nodes()
        assert len(nodes) == 3

        n1 = nodes[0]
        assert n1.node_name == "node01"
        assert n1.state == "idle"
        assert n1.cpus_total == 64
        assert n1.cpus_alloc == 0
        assert n1.cpus_idle == 64
        assert n1.memory_mb == 256000
        assert n1.gpus == "gpu:a100:4"

        n2 = nodes[1]
        assert n2.node_name == "node02"
        assert n2.state == "mixed"
        assert n2.cpus_alloc == 32
        assert n2.cpus_idle == 32

        n3 = nodes[2]
        assert n3.node_name == "node03"
        assert n3.reason == "Node unresponsive"

    def test_cancel_job(self, slurm_client, mock_ssh_manager):
        mock_ssh_manager.execute_command.return_value = CommandResult(
            command="scancel 1001",
            stdout="",
            stderr="",
            exit_code=0,
            duration=0.05,
        )
        ok, msg = slurm_client.cancel_job("1001")
        assert ok is True
        mock_ssh_manager.execute_command.assert_called_with("scancel 1001")

        # With signal
        ok, msg = slurm_client.cancel_job("1001", signal="SIGTERM")
        assert ok is True
        mock_ssh_manager.execute_command.assert_called_with("scancel -s SIGTERM 1001")

    def test_hold_and_release_job(self, slurm_client, mock_ssh_manager):
        mock_ssh_manager.execute_command.return_value = CommandResult(
            command="scontrol hold 1001",
            stdout="",
            stderr="",
            exit_code=0,
            duration=0.05,
        )
        ok, _ = slurm_client.hold_job("1001")
        assert ok is True
        mock_ssh_manager.execute_command.assert_called_with("scontrol hold 1001")

        mock_ssh_manager.execute_command.return_value = CommandResult(
            command="scontrol release 1001",
            stdout="",
            stderr="",
            exit_code=0,
            duration=0.05,
        )
        ok, _ = slurm_client.release_job("1001")
        assert ok is True
        mock_ssh_manager.execute_command.assert_called_with("scontrol release 1001")

    def test_get_job_details(self, slurm_client, mock_ssh_manager):
        stdout = (
            "JobId=1001 JobName=sim_qe\n"
            "   UserId=user1(1001) GroupId=users(1000) MCS_label=N/A\n"
            "   Priority=12345 Nice=0 Account=physics QOS=normal\n"
            "   JobState=RUNNING Reason=None Dependency=(null)\n"
            "   NumNodes=2 NumCPUs=64 NumTasks=64 CPUs/Task=1 ReqB:S:C:T=0:0:*:*\n"
            "   WorkDir=/scratch/user1/job1\n"
        )
        mock_ssh_manager.execute_command.return_value = CommandResult(
            command="scontrol show job -d 1001",
            stdout=stdout,
            stderr="",
            exit_code=0,
            duration=0.1,
        )

        details = slurm_client.get_job_details("1001")
        assert details.get("JobId") == "1001"
        assert details.get("JobName") == "sim_qe"
        assert details.get("JobState") == "RUNNING"
        assert details.get("Account") == "physics"
        assert details.get("NumNodes") == "2"
        assert details.get("WorkDir") == "/scratch/user1/job1"
