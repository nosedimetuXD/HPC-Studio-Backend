"""Unit tests for SlurmScriptGenerator and SlurmBatchConfig."""

import pytest
from hpc_studio.slurm.generator import SlurmBatchConfig, SlurmScriptGenerator


class TestSlurmScriptGenerator:
    """Test suite for SLURM script generator."""

    def test_default_config_generation(self):
        """Test generating script from default SlurmBatchConfig."""
        config = SlurmBatchConfig()
        script = SlurmScriptGenerator.generate(config)

        assert script.startswith("#!/usr/bin/env bash")
        assert "#SBATCH --job-name=qe_job" in script
        assert "#SBATCH --nodes=1" in script
        assert "#SBATCH --ntasks-per-node=32" in script
        assert "#SBATCH --cpus-per-task=1" in script
        assert "#SBATCH --time=04:00:00" in script
        assert "#SBATCH --partition=standard" in script
        assert "#SBATCH --output=%x_%j.out" in script
        assert "#SBATCH --error=%x_%j.err" in script
        assert "set -euo pipefail" in script
        assert 'cd "${SLURM_SUBMIT_DIR:-.}"' in script
        assert "module load intel" in script
        assert "module load openmpi" in script
        assert "module load quantum-espresso" in script
        assert 'export OMP_NUM_THREADS="1"' in script
        assert "ulimit -s unlimited" in script
        assert "srun -n ${SLURM_NTASKS} pw.x -in calc.in > calc.out" in script

    def test_custom_config_generation(self):
        """Test generating script with custom parameters, GPUs, memory, and flags."""
        config = SlurmBatchConfig(
            job_name="diamond_bands",
            nodes=2,
            ntasks_per_node=16,
            cpus_per_task=2,
            time_limit="12:00:00",
            partition="gpu",
            memory="64G",
            gpus="a100:1",
            account="physics_proj",
            qos="high",
            mail_type="FAIL,END",
            mail_user="researcher@university.edu",
            work_dir="/scratch/users/test/job1",
            executable="pw.x",
            qe_flags={"-npool": 4, "-ndiag": 16},
            input_file="bands.in",
            output_file="bands.out",
            env_vars={"ESPRESSO_PSEUDO": "/shared/pseudos"},
            post_commands=["echo 'Job completed successfully'"],
        )
        script = SlurmScriptGenerator.generate(config)

        assert "#SBATCH --job-name=diamond_bands" in script
        assert "#SBATCH --nodes=2" in script
        assert "#SBATCH --ntasks-per-node=16" in script
        assert "#SBATCH --cpus-per-task=2" in script
        assert "#SBATCH --time=12:00:00" in script
        assert "#SBATCH --partition=gpu" in script
        assert "#SBATCH --mem=64G" in script
        assert "#SBATCH --gpus=a100:1" in script
        assert "#SBATCH --account=physics_proj" in script
        assert "#SBATCH --qos=high" in script
        assert "#SBATCH --mail-type=FAIL,END" in script
        assert "#SBATCH --mail-user=researcher@university.edu" in script
        assert 'cd "/scratch/users/test/job1"' in script
        assert 'export OMP_NUM_THREADS="2"' in script
        assert 'export ESPRESSO_PSEUDO="/shared/pseudos"' in script
        assert "-npool 4" in script
        assert "-ndiag 16" in script
        assert "srun -n ${SLURM_NTASKS} pw.x -npool 4 -ndiag 16 -in bands.in > bands.out" in script
        assert "echo 'Job completed successfully'" in script

    def test_sanitization_against_newline_injection(self):
        """Verify that carriage returns and newlines in inputs are sanitized."""
        malicious_job_name = "job_name\n#SBATCH --account=hacked\nmalicious_cmd"
        config = SlurmBatchConfig(
            job_name=malicious_job_name,
            partition="debug\n#SBATCH --priority=9999",
        )
        script = SlurmScriptGenerator.generate(config)

        # Ensure no injected lines got placed on their own lines
        assert "\n#SBATCH --account=hacked" not in script
        assert "\nmalicious_cmd" not in script
        assert "\n#SBATCH --priority=9999" not in script
        # Check that newline got replaced with space
        assert "#SBATCH --job-name=job_name #SBATCH --account=hacked malicious_cmd" in script
        assert "#SBATCH --partition=debug #SBATCH --priority=9999" in script

    def test_generate_from_qe_input(self):
        """Test end-to-end generation from QE input text."""
        qe_text = """
        &CONTROL
          calculation = 'vc-relax'
        /
        &SYSTEM
          ibrav = 0
          nat = 4
        /
        &ELECTRONS
        /
        ATOMIC_SPECIES
          Fe 55.845 Fe.pbe-sp-van.UPF
        ATOMIC_POSITIONS (angstrom)
          Fe 0.0 0.0 0.0
          Fe 1.0 1.0 1.0
          Fe 2.0 2.0 2.0
          Fe 3.0 3.0 3.0
        K_POINTS (automatic)
          6 6 6 0 0 0
        """
        script, config = SlurmScriptGenerator.generate_from_qe_input(
            qe_text=qe_text,
            input_filename="relax.in",
            output_filename="relax.out",
            total_cores_per_node=32,
            nodes=2,
            partition="compute",
        )

        assert config.job_name == "qe_vc-relax"
        assert config.nodes == 2
        assert config.partition == "compute"
        assert config.input_file == "relax.in"
        assert config.output_file == "relax.out"
        assert "#SBATCH --job-name=qe_vc-relax" in script
        assert "#SBATCH --nodes=2" in script
        assert "#SBATCH --partition=compute" in script
        assert "-in relax.in > relax.out" in script
