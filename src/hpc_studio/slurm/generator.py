"""SLURM batch script generator for Quantum ESPRESSO and HPC workloads."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from .advisor import ParallelizationAdvisor


def _sanitize_string(val: str) -> str:
    """Sanitize string to prevent newline injection or unsafe characters."""
    if not val:
        return ""
    # Strip dangerous newline/carriage return characters
    cleaned = re.sub(r"[\r\n]+", " ", str(val)).strip()
    return cleaned


def _escape_shell_double_quotes(val: str) -> str:
    """Escape backslashes, double quotes, dollar signs, and backticks for safe double-quoted string embedding."""
    cleaned = _sanitize_string(val)
    return cleaned.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")


def _validate_safe_file_or_exec(val: str, field_name: str) -> str:
    """Validate that filename or executable does not contain dangerous shell command separators."""
    clean = _sanitize_string(val)
    if not clean:
        return ""
    if re.search(r"[;&|`$><]", clean):
        raise ValueError(f"Dangerous shell characters detected in {field_name}: {val!r}")
    return clean


@dataclass
class SlurmBatchConfig:
    """Configuration for SLURM batch job submission script."""

    job_name: str = "qe_job"
    nodes: int = 1
    ntasks_per_node: int = 32
    cpus_per_task: int = 1
    time_limit: str = "04:00:00"
    partition: str = "standard"
    memory: str = ""  # e.g. "32G" or empty
    gpus: str = ""    # e.g. "1" or "a100:2" or empty
    account: str = ""
    qos: str = ""
    mail_type: str = ""
    mail_user: str = ""
    modules: list[str] = field(default_factory=lambda: ["intel", "openmpi", "quantum-espresso"])
    env_vars: dict[str, str] = field(default_factory=dict)
    work_dir: str = "$SLURM_SUBMIT_DIR"
    executable: str = "pw.x"
    qe_flags: dict[str, Any] = field(default_factory=dict)  # e.g. {"-npool": 4, "-ndiag": 4}
    input_file: str = "calc.in"
    output_file: str = "calc.out"
    pre_commands: list[str] = field(default_factory=lambda: ["ulimit -s unlimited"])
    post_commands: list[str] = field(default_factory=list)


class SlurmScriptGenerator:
    """Generator for robust, secure, and production-ready SLURM Bash scripts."""

    @classmethod
    def generate(cls, config: SlurmBatchConfig) -> str:
        """Generate a clean, production-ready, safe #SBATCH Bash script."""
        lines: list[str] = ["#!/usr/bin/env bash", ""]

        # 1. Job and Resource directives
        lines.append(f"#SBATCH --job-name={_sanitize_string(config.job_name)}")
        lines.append(f"#SBATCH --nodes={config.nodes}")
        lines.append(f"#SBATCH --ntasks-per-node={config.ntasks_per_node}")
        lines.append(f"#SBATCH --cpus-per-task={config.cpus_per_task}")
        lines.append(f"#SBATCH --time={_sanitize_string(config.time_limit)}")
        lines.append(f"#SBATCH --partition={_sanitize_string(config.partition)}")

        if config.memory:
            lines.append(f"#SBATCH --mem={_sanitize_string(config.memory)}")
        if config.gpus:
            lines.append(f"#SBATCH --gpus={_sanitize_string(config.gpus)}")
        if config.account:
            lines.append(f"#SBATCH --account={_sanitize_string(config.account)}")
        if config.qos:
            lines.append(f"#SBATCH --qos={_sanitize_string(config.qos)}")
        if config.mail_type:
            lines.append(f"#SBATCH --mail-type={_sanitize_string(config.mail_type)}")
        if config.mail_user:
            lines.append(f"#SBATCH --mail-user={_sanitize_string(config.mail_user)}")

        # Output and Error files
        lines.append("#SBATCH --output=%x_%j.out")
        lines.append("#SBATCH --error=%x_%j.err")
        lines.append("")

        # 2. Bash safety / error trapping
        lines.append("# Exit on error, undefined vars, and pipe failures")
        lines.append("set -euo pipefail")
        lines.append("")

        # 3. Working directory
        work_dir = _sanitize_string(config.work_dir)
        if work_dir and work_dir != "$SLURM_SUBMIT_DIR":
            safe_work_dir = _escape_shell_double_quotes(work_dir)
            lines.append(f'cd "{safe_work_dir}"')
            lines.append("")
        elif work_dir == "$SLURM_SUBMIT_DIR":
            lines.append('cd "${SLURM_SUBMIT_DIR:-.}"')
            lines.append("")

        # 4. Environment modules
        if config.modules:
            lines.append("# Environment Modules")
            for mod in config.modules:
                clean_mod = _sanitize_string(mod)
                if clean_mod:
                    lines.append(f"module load {clean_mod}")
            lines.append("")

        # 5. Environment variables
        lines.append("# Parallelization and Threading Environment")
        # Ensure OMP_NUM_THREADS defaults to cpus_per_task
        env = dict(config.env_vars)
        if "OMP_NUM_THREADS" not in env:
            env["OMP_NUM_THREADS"] = str(config.cpus_per_task)

        for k, v in env.items():
            clean_k = _sanitize_string(k)
            if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", clean_k):
                raise ValueError(f"Invalid environment variable name in SlurmBatchConfig: {k!r}")
            safe_v = _escape_shell_double_quotes(v)
            lines.append(f'export {clean_k}="{safe_v}"')
        lines.append("")

        # 6. Pre-execution commands
        if config.pre_commands:
            lines.append("# Pre-execution setup")
            for cmd in config.pre_commands:
                clean_cmd = _sanitize_string(cmd)
                if clean_cmd:
                    lines.append(clean_cmd)
            lines.append("")

        # 7. Main execution command
        lines.append("# Execution")
        cmd_parts: list[str] = ["srun", "-n", "${SLURM_NTASKS}"]
        clean_exec = _validate_safe_file_or_exec(config.executable, "executable")
        cmd_parts.append(clean_exec)

        # Append QE flags (e.g. -npool 4 -ndiag 4)
        for flag_name, flag_val in config.qe_flags.items():
            clean_f = _validate_safe_file_or_exec(str(flag_name), "qe_flags key")
            clean_val = _validate_safe_file_or_exec(str(flag_val), "qe_flags value")
            if clean_f:
                if clean_val != "":
                    cmd_parts.append(f"{clean_f} {clean_val}")
                else:
                    cmd_parts.append(clean_f)

        in_file = _validate_safe_file_or_exec(config.input_file, "input_file")
        out_file = _validate_safe_file_or_exec(config.output_file, "output_file")

        if in_file:
            cmd_parts.append(f"-in {in_file}")
        if out_file:
            cmd_parts.append(f"> {out_file}")

        lines.append(" ".join(cmd_parts))
        lines.append("")

        # 8. Post-execution commands
        if config.post_commands:
            lines.append("# Post-execution cleanup")
            for cmd in config.post_commands:
                clean_cmd = _sanitize_string(cmd)
                if clean_cmd:
                    lines.append(clean_cmd)
            lines.append("")

        return "\n".join(lines).strip() + "\n"

    @classmethod
    def generate_from_qe_input(
        cls,
        qe_text: str,
        input_filename: str = "calc.in",
        output_filename: str = "calc.out",
        total_cores_per_node: int = 32,
        nodes: int = 1,
        partition: str = "standard",
    ) -> tuple[str, SlurmBatchConfig]:
        """Analyze QE input, build optimized SlurmBatchConfig, and generate SLURM script."""
        analysis = ParallelizationAdvisor.analyze_qe_input_text(
            qe_text=qe_text,
            total_cores=total_cores_per_node,
            nodes=nodes,
        )

        qe_flags: dict[str, Any] = {}
        if analysis["npool"] > 1:
            qe_flags["-npool"] = analysis["npool"]
        if analysis["ndiag"] > 1:
            qe_flags["-ndiag"] = analysis["ndiag"]

        job_prefix = analysis["calculation"]
        config = SlurmBatchConfig(
            job_name=f"qe_{job_prefix}",
            nodes=nodes,
            ntasks_per_node=analysis["tasks_per_node"],
            cpus_per_task=analysis["threads_per_task"],
            partition=partition,
            input_file=input_filename,
            output_file=output_filename,
            qe_flags=qe_flags,
        )

        script = cls.generate(config)
        return (script, config)
