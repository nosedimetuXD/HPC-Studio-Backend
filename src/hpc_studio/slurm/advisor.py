"""Parallelization Advisor for Quantum ESPRESSO and SLURM workloads."""

from __future__ import annotations

import math
from typing import Any

from hpc_studio.qe.parser import parse_qe_input


class ParallelizationAdvisor:
    """Expert advisor for Quantum ESPRESSO parallelization parameters."""

    @staticmethod
    def recommend_npool(k_points_count: int, mpi_tasks: int) -> int:
        """Find the optimal -npool value for Quantum ESPRESSO.

        A pool divides the k-points and must divide the total MPI tasks.
        Returns the best integer npool such that:
          mpi_tasks % npool == 0 and k_points_count % npool == 0,
        with 1 <= npool <= min(k_points_count, mpi_tasks).
        If no exact simultaneous divisor exists, returns the largest divisor of
        mpi_tasks that does not exceed k_points_count and min(k_points_count, mpi_tasks).
        Returns 1 if k_points_count <= 1 or mpi_tasks <= 1.
        """
        if k_points_count <= 1 or mpi_tasks <= 1:
            return 1

        limit = min(k_points_count, mpi_tasks)

        # 1. Exact common divisors (mpi_tasks % p == 0 and k_points_count % p == 0)
        exact_divisors = [
            p for p in range(1, limit + 1)
            if mpi_tasks % p == 0 and k_points_count % p == 0
        ]
        if exact_divisors:
            return max(exact_divisors)

        # 2. Fallback: largest divisor of mpi_tasks <= limit
        mpi_divisors = [
            p for p in range(1, limit + 1)
            if mpi_tasks % p == 0
        ]
        if mpi_divisors:
            return max(mpi_divisors)

        return 1

    @staticmethod
    def recommend_ndiag(mpi_tasks: int) -> int:
        """Find the optimal -ndiag value (linear algebra / ortho diagonalization group).

        -ndiag must be a square number (1, 4, 9, 16, 25, 36, 49, 64, ...) where
        ndiag <= mpi_tasks.
        Returns largest M**2 <= mpi_tasks. Returns 1 if mpi_tasks < 4.
        """
        if mpi_tasks < 4:
            return 1

        m = int(math.isqrt(mpi_tasks))
        return m * m

    @staticmethod
    def recommend_mpi_openmp_balance(
        total_cores: int,
        ram_gb_per_node: float,
        nat: int = 10,
        is_hybrid_or_paw: bool = False,
    ) -> tuple[int, int]:
        """Balance MPI tasks and OpenMP threads per node.

        Returns (tasks_per_node, threads_per_task):
        If memory per core is low (< 2 GB/core) or is_hybrid_or_paw or nat > 50,
        favors OpenMP (e.g. 2, 4, or 8 threads per task, tasks_per_node = total_cores // threads).
        Otherwise, favors MPI (1 or 2 threads per task).
        Ensures tasks_per_node * threads_per_task == total_cores.
        """
        if total_cores <= 0:
            return (1, 1)

        mem_per_core = ram_gb_per_node / total_cores if total_cores > 0 else 0.0
        favor_openmp = (mem_per_core < 2.0) or is_hybrid_or_paw or (nat > 50)

        divisors = [d for d in range(1, total_cores + 1) if total_cores % d == 0]

        if favor_openmp:
            # Prefer 4, then 8, then 2, else largest <= total_cores
            candidate_threads = [4, 8, 2]
            selected_threads = 1
            for cand in candidate_threads:
                if cand in divisors and cand <= total_cores:
                    selected_threads = cand
                    break
            else:
                # Fallback to largest divisor <= 8
                small_divs = [d for d in divisors if d <= 8]
                selected_threads = max(small_divs) if small_divs else 1
        else:
            # Favor MPI: prefer 1, then 2 threads per task
            if 1 in divisors:
                selected_threads = 1
            elif 2 in divisors and total_cores >= 2:
                selected_threads = 2
            else:
                selected_threads = 1

        tasks_per_node = total_cores // selected_threads
        return (tasks_per_node, selected_threads)

    @classmethod
    def analyze_qe_input_text(
        cls,
        qe_text: str,
        total_cores: int = 32,
        nodes: int = 1,
        ram_gb_per_node: float = 64.0,
    ) -> dict[str, Any]:
        """Parse Quantum ESPRESSO input and determine optimal parallelization settings.

        Parses k-points count (from K_POINTS automatic grid or card lines),
        number of atoms (nat), and calculation type from &CONTROL.
        Returns a dictionary with:
        {
            "k_points_count": int,
            "nat": int,
            "calculation": str,
            "tasks_per_node": int,
            "threads_per_task": int,
            "total_mpi_tasks": int,
            "npool": int,
            "ndiag": int,
            "explanation": str
        }
        """
        qe_obj = parse_qe_input(qe_text)

        # 1. Calculation
        calculation = qe_obj.control.calculation or "scf"

        # 2. Number of atoms (nat)
        nat = qe_obj.system.nat
        if nat is None or nat <= 0:
            nat = len(qe_obj.atomic_positions.positions)
        if nat <= 0:
            nat = 1

        # 3. Check for PAW or hybrid functional indicators
        is_hybrid_or_paw = False
        # Check pseudo files for PAW
        for sp in qe_obj.atomic_species.species:
            if "paw" in sp.pseudo_file.lower():
                is_hybrid_or_paw = True
                break
        # Check input parameters
        input_func = str(
            getattr(qe_obj.system, "input_dft", "")
            or qe_obj.system.extra_params.get("input_dft", "")
            or ""
        ).lower()
        if any(h in input_func for h in ["hse", "pbe0", "b3lyp", "hybrid"]):
            is_hybrid_or_paw = True

        # 4. K-points count
        k_mode = qe_obj.k_points.mode.lower()
        if k_mode == "gamma":
            k_points_count = 1
        elif k_mode == "automatic":
            grid = qe_obj.k_points.grid
            if grid and len(grid) == 3 and any(g > 0 for g in grid):
                k_points_count = max(1, grid[0] * grid[1] * grid[2])
            else:
                k_points_count = 1
        else:
            # Explicit list
            k_points_count = max(1, len(qe_obj.k_points.kpoints))

        # 5. MPI & OpenMP balance per node
        tasks_per_node, threads_per_task = cls.recommend_mpi_openmp_balance(
            total_cores=total_cores,
            ram_gb_per_node=ram_gb_per_node,
            nat=nat,
            is_hybrid_or_paw=is_hybrid_or_paw,
        )

        total_mpi_tasks = tasks_per_node * nodes
        npool = cls.recommend_npool(k_points_count, total_mpi_tasks)
        ndiag = cls.recommend_ndiag(total_mpi_tasks)

        explanation = (
            f"Configured for {calculation} calculation with {nat} atom(s). "
            f"Allocating {total_mpi_tasks} total MPI tasks across {nodes} node(s) "
            f"({tasks_per_node} tasks/node, {threads_per_task} threads/task). "
            f"K-points pool (-npool): {npool} for {k_points_count} k-points. "
            f"Diagonalization group (-ndiag): {ndiag}."
        )

        return {
            "k_points_count": k_points_count,
            "nat": nat,
            "calculation": calculation,
            "tasks_per_node": tasks_per_node,
            "threads_per_task": threads_per_task,
            "total_mpi_tasks": total_mpi_tasks,
            "npool": npool,
            "ndiag": ndiag,
            "explanation": explanation,
        }
