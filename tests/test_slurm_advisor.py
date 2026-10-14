"""Unit tests for ParallelizationAdvisor."""

import pytest
from hpc_studio.slurm.advisor import ParallelizationAdvisor


class TestParallelizationAdvisor:
    """Test suite for ParallelizationAdvisor logic."""

    def test_recommend_npool_exact_common_divisors(self):
        """Test npool when exact simultaneous divisors exist."""
        # k_points=64, mpi_tasks=32 -> divisors of both: 1, 2, 4, 8, 16, 32 -> max 32
        assert ParallelizationAdvisor.recommend_npool(64, 32) == 32
        # k_points=8, mpi_tasks=16 -> max divisor <= 8 is 8
        assert ParallelizationAdvisor.recommend_npool(8, 16) == 8
        # k_points=6, mpi_tasks=16 -> common divisors: 1, 2 -> max is 2
        assert ParallelizationAdvisor.recommend_npool(6, 16) == 2

    def test_recommend_npool_no_common_divisor_fallback(self):
        """Test fallback when no common divisor exists besides 1 or non-exact."""
        # k_points=7 (prime), mpi_tasks=16 -> common divisor is 1
        assert ParallelizationAdvisor.recommend_npool(7, 16) == 1
        # k_points=5, mpi_tasks=8 -> common divisor is 1
        assert ParallelizationAdvisor.recommend_npool(5, 8) == 1

    def test_recommend_npool_edge_cases(self):
        """Test edge cases with <= 1 k-points or mpi tasks."""
        assert ParallelizationAdvisor.recommend_npool(1, 32) == 1
        assert ParallelizationAdvisor.recommend_npool(0, 32) == 1
        assert ParallelizationAdvisor.recommend_npool(10, 1) == 1
        assert ParallelizationAdvisor.recommend_npool(10, 0) == 1
        assert ParallelizationAdvisor.recommend_npool(-5, 16) == 1

    def test_recommend_ndiag_square_numbers(self):
        """Test -ndiag is the largest square number <= mpi_tasks."""
        assert ParallelizationAdvisor.recommend_ndiag(1) == 1
        assert ParallelizationAdvisor.recommend_ndiag(2) == 1
        assert ParallelizationAdvisor.recommend_ndiag(3) == 1
        assert ParallelizationAdvisor.recommend_ndiag(4) == 4
        assert ParallelizationAdvisor.recommend_ndiag(8) == 4
        assert ParallelizationAdvisor.recommend_ndiag(15) == 9
        assert ParallelizationAdvisor.recommend_ndiag(16) == 16
        assert ParallelizationAdvisor.recommend_ndiag(32) == 25
        assert ParallelizationAdvisor.recommend_ndiag(64) == 64
        assert ParallelizationAdvisor.recommend_ndiag(100) == 100
        assert ParallelizationAdvisor.recommend_ndiag(120) == 100

    def test_recommend_mpi_openmp_balance_low_memory(self):
        """Test balance favoring OpenMP when memory per core is low (< 2 GB)."""
        # 32 cores, 32 GB RAM -> 1 GB/core -> favors OpenMP
        tasks, threads = ParallelizationAdvisor.recommend_mpi_openmp_balance(
            total_cores=32,
            ram_gb_per_node=32.0,
            nat=10,
            is_hybrid_or_paw=False,
        )
        assert tasks * threads == 32
        assert threads in (2, 4, 8)
        assert threads == 4
        assert tasks == 8

    def test_recommend_mpi_openmp_balance_high_atoms_or_paw(self):
        """Test balance favoring OpenMP when nat > 50 or is_hybrid_or_paw."""
        # 32 cores, 128 GB RAM (4 GB/core), but nat=60
        tasks, threads = ParallelizationAdvisor.recommend_mpi_openmp_balance(
            total_cores=32,
            ram_gb_per_node=128.0,
            nat=60,
            is_hybrid_or_paw=False,
        )
        assert tasks * threads == 32
        assert threads == 4

        # 32 cores, 128 GB RAM, nat=10, but is_hybrid_or_paw=True
        tasks, threads = ParallelizationAdvisor.recommend_mpi_openmp_balance(
            total_cores=32,
            ram_gb_per_node=128.0,
            nat=10,
            is_hybrid_or_paw=True,
        )
        assert tasks * threads == 32
        assert threads == 4

    def test_recommend_mpi_openmp_balance_standard_mpi(self):
        """Test balance favoring pure MPI when memory is ample and system is standard."""
        # 32 cores, 128 GB RAM -> 4 GB/core, nat=8, standard LDA/PBE
        tasks, threads = ParallelizationAdvisor.recommend_mpi_openmp_balance(
            total_cores=32,
            ram_gb_per_node=128.0,
            nat=8,
            is_hybrid_or_paw=False,
        )
        assert tasks * threads == 32
        assert threads == 1
        assert tasks == 32

    def test_analyze_qe_input_text_automatic_kpoints(self):
        """Test analyzing QE text with automatic K_POINTS grid."""
        qe_text = """
        &CONTROL
          calculation = 'scf'
          prefix = 'si'
        /
        &SYSTEM
          ibrav = 2
          nat = 2
          ntyp = 1
        /
        &ELECTRONS
        /
        ATOMIC_SPECIES
          Si 28.08 Si.pbe-n-kjpaw_psl.1.0.0.UPF
        ATOMIC_POSITIONS (alat)
          Si 0.0 0.0 0.0
          Si 0.25 0.25 0.25
        K_POINTS (automatic)
          4 4 4 1 1 1
        """
        res = ParallelizationAdvisor.analyze_qe_input_text(
            qe_text,
            total_cores=32,
            nodes=1,
            ram_gb_per_node=64.0,
        )

        assert res["calculation"] == "scf"
        assert res["nat"] == 2
        assert res["k_points_count"] == 64  # 4 * 4 * 4
        assert res["total_mpi_tasks"] == 8  # PAW pseudo detected -> 4 threads, 8 tasks
        assert res["tasks_per_node"] == 8
        assert res["threads_per_task"] == 4
        assert res["npool"] == 8  # divisors of 64 and 8 -> 8
        assert res["ndiag"] == 4  # square <= 8 is 4
        assert "K-points pool (-npool): 8" in res["explanation"]

    def test_analyze_qe_input_text_gamma_kpoints(self):
        """Test analyzing QE text with Gamma point."""
        qe_text = """
        &CONTROL
          calculation = 'relax'
        /
        &SYSTEM
          nat = 5
        /
        &ELECTRONS
        /
        ATOMIC_SPECIES
          C 12.0 C.upf
        ATOMIC_POSITIONS (angstrom)
          C 0.0 0.0 0.0
        K_POINTS (gamma)
        """
        res = ParallelizationAdvisor.analyze_qe_input_text(
            qe_text,
            total_cores=16,
            nodes=2,
            ram_gb_per_node=64.0,
        )

        assert res["calculation"] == "relax"
        assert res["k_points_count"] == 1
        assert res["npool"] == 1
        assert res["total_mpi_tasks"] == 32  # 16 cores * 2 nodes
        assert res["ndiag"] == 25  # largest square <= 32
