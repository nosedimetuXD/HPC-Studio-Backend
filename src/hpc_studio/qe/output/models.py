"""Data models for Quantum ESPRESSO output parsing."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from hpc_studio.crystallography.models import CrystalStructure


class ConvergenceStatus(str, Enum):
    """Execution and convergence status of a Quantum ESPRESSO calculation."""

    CONVERGED = "CONVERGED"
    NOT_CONVERGED = "NOT_CONVERGED"
    RUNNING = "RUNNING"
    FAILED = "FAILED"


@dataclass
class SCFIteration:
    """A single self-consistent field (SCF) electronic iteration."""

    iteration: int
    total_energy_ry: float
    energy_error_ry: float
    accuracy_ry: float
    cpu_time_s: float


@dataclass
class IonicStep:
    """A single ionic step during relaxation or molecular dynamics."""

    step: int
    total_energy_ry: float
    total_force: float
    scf_iterations: list[SCFIteration] = field(default_factory=list)
    positions: list[tuple[str, float, float, float]] = field(default_factory=list)
    cell_parameters: Optional[list[list[float]]] = None


@dataclass
class BandStructureData:
    """Electronic band structure eigenvalues and k-points data."""

    kpoints: list[tuple[float, float, float]] = field(default_factory=list)
    k_labels: dict[int, str] = field(default_factory=dict)
    eigenvalues_ev: list[list[float]] = field(default_factory=list)  # shape: [nkpoints, nbands]
    fermi_energy_ev: Optional[float] = None
    band_gap_ev: Optional[float] = None
    is_direct_gap: Optional[bool] = None


@dataclass
class QEOutputResult:
    """Comprehensive Quantum ESPRESSO calculation results."""

    job_title: str = ""
    calculation: str = "scf"
    version: str = ""
    wall_time: str = ""
    cpu_time: str = ""
    status: ConvergenceStatus = ConvergenceStatus.RUNNING

    total_energy_ry: Optional[float] = None
    total_energy_ev: Optional[float] = None
    fermi_energy_ev: Optional[float] = None
    conv_thr_ry: Optional[float] = None

    scf_history: list[SCFIteration] = field(default_factory=list)
    ionic_steps: list[IonicStep] = field(default_factory=list)

    final_structure: Optional[CrystalStructure] = None
    forces: list[tuple[str, float, float, float]] = field(default_factory=list)  # (symbol, fx, fy, fz) in Ry/bohr
    stress_tensor_kbar: Optional[list[list[float]]] = None  # 3x3 in kbar
    band_structure: Optional[BandStructureData] = None
    error_message: Optional[str] = None
    raw_text: str = ""
    file_path: Optional[str] = None

    @property
    def is_converged(self) -> bool:
        """True if the calculation converged successfully."""
        return self.status == ConvergenceStatus.CONVERGED

    @property
    def band_gap_ev(self) -> Optional[float]:
        """Convenience accessor for calculated band gap."""
        if self.band_structure and self.band_structure.band_gap_ev is not None:
            return self.band_structure.band_gap_ev
        return None

    @property
    def gap_type(self) -> Optional[str]:
        """Convenience accessor for gap type description."""
        if self.band_structure:
            if self.band_structure.band_gap_ev is not None and self.band_structure.band_gap_ev <= 0.001:
                return "Metálico"
            if self.band_structure.is_direct_gap is True:
                return "Directo"
            elif self.band_structure.is_direct_gap is False:
                return "Indirecto"
        return None
