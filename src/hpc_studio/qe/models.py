"""Quantum ESPRESSO input data models and structures."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import TYPE_CHECKING, Any, Optional

import numpy as np

from hpc_studio.crystallography.models import (
    Atom,
    CrystalStructure,
    Lattice,
    get_element_data,
)

if TYPE_CHECKING:
    from .validator import ValidationError

BOHR_TO_ANGSTROM = 0.529177210903


def _format_fortran_val(val: Any) -> str:
    """Format Python values into valid Quantum ESPRESSO Fortran representation."""
    if isinstance(val, bool):
        return ".true." if val else ".false."
    if isinstance(val, (int, np.integer)):
        return str(val)
    if isinstance(val, (float, np.floating)):
        if val == 0.0:
            return "0.0"
        abs_val = abs(val)
        if abs_val < 1e-4 or abs_val >= 1e6:
            # Format scientific with clean e notation, e.g. 1.0e-8
            s = f"{val:.6e}"
            mantissa, exp = s.split("e")
            mantissa = mantissa.rstrip("0")
            if mantissa.endswith("."):
                mantissa += "0"
            exp_int = int(exp)
            return f"{mantissa}e{exp_int}"
        # Format standard floating point
        formatted = f"{val:.8f}".rstrip("0")
        if formatted.endswith("."):
            formatted += "0"
        return formatted
    if isinstance(val, str):
        # Escape internal single quotes as '' per Fortran namelist standard
        clean = val.strip("'\"").replace("'", "''")
        return f"'{clean}'"
    return str(val)


def _build_ibrav_lattice(
    ibrav: int,
    celldm: dict[int, float],
    a: Optional[float] = None,
    b: Optional[float] = None,
    c: Optional[float] = None,
    cosab: Optional[float] = None,
    cosac: Optional[float] = None,
    cosbc: Optional[float] = None,
) -> Optional[Lattice]:
    """Construct Lattice object from QE ibrav and cell parameters."""
    if ibrav == 0:
        return None

    # celldm(1) is in Bohr; a is in Angstrom (or user unit)
    if 1 in celldm and celldm[1] > 0:
        alat = celldm[1] * BOHR_TO_ANGSTROM
    elif a is not None and a > 0:
        alat = a
    else:
        alat = 1.0

    if ibrav == 1:
        # Simple cubic (sc)
        mat = np.eye(3) * alat
        return Lattice(mat)

    elif ibrav == 2:
        # Face-centered cubic (fcc)
        mat = np.array([
            [-0.5, 0.0, 0.5],
            [0.0, 0.5, 0.5],
            [-0.5, 0.5, 0.0],
        ]) * alat
        return Lattice(mat)

    elif ibrav == 3:
        # Body-centered cubic (bcc)
        mat = np.array([
            [0.5, 0.5, 0.5],
            [-0.5, 0.5, 0.5],
            [-0.5, -0.5, 0.5],
        ]) * alat
        return Lattice(mat)

    elif ibrav == -3:
        # Body-centered cubic (bcc, more symmetric axis)
        mat = np.array([
            [-0.5, 0.5, 0.5],
            [0.5, -0.5, 0.5],
            [0.5, 0.5, -0.5],
        ]) * alat
        return Lattice(mat)

    elif ibrav == 4:
        # Hexagonal / Trigonal P
        c_fac = celldm.get(3, (c / alat) if (c and alat) else 1.0)
        c_val = c_fac * alat
        mat = np.array([
            [alat, 0.0, 0.0],
            [-0.5 * alat, math.sqrt(3) / 2.0 * alat, 0.0],
            [0.0, 0.0, c_val],
        ])
        return Lattice(mat)

    elif ibrav == 5:
        # Trigonal R (3-fold axis c)
        cos_g = celldm.get(4, cosab if cosab is not None and cosab != 0.0 else 0.0)
        tx = math.sqrt((1.0 - cos_g) / 2.0)
        ty = math.sqrt((1.0 - cos_g) / 6.0)
        tz = math.sqrt((1.0 + 2.0 * cos_g) / 3.0)
        mat = np.array([
            [tx * alat, -ty * alat, tz * alat],
            [0.0, 2.0 * ty * alat, tz * alat],
            [-tx * alat, -ty * alat, tz * alat],
        ])
        return Lattice(mat)

    elif ibrav == 6:
        # Tetragonal P (st)
        c_fac = celldm.get(3, (c / alat) if (c and alat) else 1.0)
        c_val = c_fac * alat
        mat = np.array([
            [alat, 0.0, 0.0],
            [0.0, alat, 0.0],
            [0.0, 0.0, c_val],
        ])
        return Lattice(mat)

    elif ibrav == 7:
        # Tetragonal I (bct)
        c_fac = celldm.get(3, (c / alat) if (c and alat) else 1.0)
        c_val = c_fac * alat
        mat = np.array([
            [0.5 * alat, -0.5 * alat, 0.5 * c_val],
            [0.5 * alat, 0.5 * alat, 0.5 * c_val],
            [-0.5 * alat, -0.5 * alat, 0.5 * c_val],
        ])
        return Lattice(mat)

    elif ibrav == 8:
        # Orthorhombic P
        b_fac = celldm.get(2, (b / alat) if (b and alat) else 1.0)
        c_fac = celldm.get(3, (c / alat) if (c and alat) else 1.0)
        mat = np.array([
            [alat, 0.0, 0.0],
            [0.0, b_fac * alat, 0.0],
            [0.0, 0.0, c_fac * alat],
        ])
        return Lattice(mat)

    elif ibrav == 14:
        # Triclinic
        b_fac = celldm.get(2, (b / alat) if (b and alat) else 1.0)
        c_fac = celldm.get(3, (c / alat) if (c and alat) else 1.0)
        cos_bc = celldm.get(4, cosbc if cosbc is not None else 0.0)
        cos_ac = celldm.get(5, cosac if cosac is not None else 0.0)
        cos_ab = celldm.get(6, cosab if cosab is not None else 0.0)
        alpha = math.degrees(math.acos(max(-1.0, min(1.0, cos_bc))))
        beta = math.degrees(math.acos(max(-1.0, min(1.0, cos_ac))))
        gamma = math.degrees(math.acos(max(-1.0, min(1.0, cos_ab))))
        return Lattice.from_parameters(alat, b_fac * alat, c_fac * alat, alpha, beta, gamma)

    else:
        # Fallback for remaining crystal classes
        mat = np.eye(3) * alat
        return Lattice(mat)


@dataclass
class ControlNamelist:
    """&CONTROL namelist parameters."""

    calculation: str = "scf"
    title: str = ""
    prefix: str = "pwscf"
    outdir: str = "./out"
    pseudo_dir: str = "./pseudo"
    restart_mode: str = "from_scratch"
    tprnfor: bool = False
    tstress: bool = False
    wf_collect: bool = False
    verbosity: str = "low"
    etot_conv_thr: float = 1e-4
    forc_conv_thr: float = 1e-3
    extra_params: dict[str, Any] = field(default_factory=dict)

    def to_string(self) -> str:
        lines = ["&CONTROL"]
        lines.append(f"  calculation = {_format_fortran_val(self.calculation)},")
        if self.title:
            lines.append(f"  title = {_format_fortran_val(self.title)},")
        lines.append(f"  prefix = {_format_fortran_val(self.prefix)},")
        lines.append(f"  outdir = {_format_fortran_val(self.outdir)},")
        lines.append(f"  pseudo_dir = {_format_fortran_val(self.pseudo_dir)},")
        lines.append(f"  restart_mode = {_format_fortran_val(self.restart_mode)},")
        if self.tprnfor:
            lines.append(f"  tprnfor = {_format_fortran_val(self.tprnfor)},")
        if self.tstress:
            lines.append(f"  tstress = {_format_fortran_val(self.tstress)},")
        if self.wf_collect:
            lines.append(f"  wf_collect = {_format_fortran_val(self.wf_collect)},")
        if self.verbosity != "low":
            lines.append(f"  verbosity = {_format_fortran_val(self.verbosity)},")
        if self.etot_conv_thr != 1e-4:
            lines.append(f"  etot_conv_thr = {_format_fortran_val(self.etot_conv_thr)},")
        if self.forc_conv_thr != 1e-3:
            lines.append(f"  forc_conv_thr = {_format_fortran_val(self.forc_conv_thr)},")

        for k, v in self.extra_params.items():
            lines.append(f"  {k} = {_format_fortran_val(v)},")

        lines.append("/")
        return "\n".join(lines)


@dataclass
class SystemNamelist:
    """&SYSTEM namelist parameters."""

    ibrav: int = 1
    celldm: dict[int, float] = field(default_factory=dict)
    a: float = 0.0
    b: float = 0.0
    c: float = 0.0
    cosab: float = 0.0
    cosac: float = 0.0
    cosbc: float = 0.0
    nat: int = 1
    ntyp: int = 1
    ecutwfc: float = 30.0
    ecutrho: Optional[float] = None
    occupations: str = "fixed"
    smearing: str = "gaussian"
    degauss: float = 0.0
    nspin: int = 1
    starting_magnetization: dict[str, float] = field(default_factory=dict)
    vdw_corr: str = "none"
    lda_plus_u: bool = False
    tot_charge: float = 0.0
    extra_params: dict[str, Any] = field(default_factory=dict)

    def to_string(self) -> str:
        lines = ["&SYSTEM"]
        lines.append(f"  ibrav = {self.ibrav},")

        if self.celldm:
            for idx in sorted(self.celldm.keys()):
                lines.append(f"  celldm({idx}) = {_format_fortran_val(self.celldm[idx])},")
        if self.a > 0:
            lines.append(f"  a = {_format_fortran_val(self.a)},")
        if self.b > 0:
            lines.append(f"  b = {_format_fortran_val(self.b)},")
        if self.c > 0:
            lines.append(f"  c = {_format_fortran_val(self.c)},")
        if self.cosab != 0.0:
            lines.append(f"  cosab = {_format_fortran_val(self.cosab)},")
        if self.cosac != 0.0:
            lines.append(f"  cosac = {_format_fortran_val(self.cosac)},")
        if self.cosbc != 0.0:
            lines.append(f"  cosbc = {_format_fortran_val(self.cosbc)},")

        lines.append(f"  nat = {self.nat},")
        lines.append(f"  ntyp = {self.ntyp},")
        lines.append(f"  ecutwfc = {_format_fortran_val(self.ecutwfc)},")

        if self.ecutrho is not None:
            lines.append(f"  ecutrho = {_format_fortran_val(self.ecutrho)},")
        if self.tot_charge != 0.0:
            lines.append(f"  tot_charge = {_format_fortran_val(self.tot_charge)},")

        lines.append(f"  occupations = {_format_fortran_val(self.occupations)},")
        if self.occupations.lower() in ("smearing", "tetrahedra", "tetrahedra_lin", "tetrahedra_opt", "fd"):
            lines.append(f"  smearing = {_format_fortran_val(self.smearing)},")
            if self.degauss != 0.0:
                lines.append(f"  degauss = {_format_fortran_val(self.degauss)},")

        if self.nspin != 1:
            lines.append(f"  nspin = {self.nspin},")

        if self.starting_magnetization:
            for k, v in self.starting_magnetization.items():
                lines.append(f"  starting_magnetization({k}) = {_format_fortran_val(v)},")

        if self.vdw_corr.lower() != "none":
            lines.append(f"  vdw_corr = {_format_fortran_val(self.vdw_corr)},")

        if self.lda_plus_u:
            lines.append(f"  lda_plus_u = {_format_fortran_val(self.lda_plus_u)},")

        for k, v in self.extra_params.items():
            lines.append(f"  {k} = {_format_fortran_val(v)},")

        lines.append("/")
        return "\n".join(lines)


@dataclass
class ElectronsNamelist:
    """&ELECTRONS namelist parameters."""

    conv_thr: float = 1e-8
    electron_maxstep: int = 100
    mixing_beta: float = 0.7
    mixing_mode: str = "plain"
    diagonalization: str = "david"
    diago_david_ndim: int = 4
    extra_params: dict[str, Any] = field(default_factory=dict)

    def to_string(self) -> str:
        lines = ["&ELECTRONS"]
        lines.append(f"  conv_thr = {_format_fortran_val(self.conv_thr)},")
        lines.append(f"  electron_maxstep = {self.electron_maxstep},")
        lines.append(f"  mixing_beta = {_format_fortran_val(self.mixing_beta)},")
        lines.append(f"  mixing_mode = {_format_fortran_val(self.mixing_mode)},")
        lines.append(f"  diagonalization = {_format_fortran_val(self.diagonalization)},")
        if self.diago_david_ndim != 4:
            lines.append(f"  diago_david_ndim = {self.diago_david_ndim},")

        for k, v in self.extra_params.items():
            lines.append(f"  {k} = {_format_fortran_val(v)},")

        lines.append("/")
        return "\n".join(lines)


@dataclass
class IonsNamelist:
    """&IONS namelist parameters for relax / vc-relax / md calculations."""

    ion_dynamics: str = "bfgs"
    ion_positions: str = "default"
    pot_extrapolation: str = "atomic"
    wfc_extrapolation: str = "none"
    remove_rigid_rot: bool = False
    extra_params: dict[str, Any] = field(default_factory=dict)

    def to_string(self) -> str:
        lines = ["&IONS"]
        lines.append(f"  ion_dynamics = {_format_fortran_val(self.ion_dynamics)},")
        if self.ion_positions != "default":
            lines.append(f"  ion_positions = {_format_fortran_val(self.ion_positions)},")
        if self.pot_extrapolation != "atomic":
            lines.append(f"  pot_extrapolation = {_format_fortran_val(self.pot_extrapolation)},")
        if self.wfc_extrapolation != "none":
            lines.append(f"  wfc_extrapolation = {_format_fortran_val(self.wfc_extrapolation)},")
        if self.remove_rigid_rot:
            lines.append(f"  remove_rigid_rot = {_format_fortran_val(self.remove_rigid_rot)},")

        for k, v in self.extra_params.items():
            lines.append(f"  {k} = {_format_fortran_val(v)},")

        lines.append("/")
        return "\n".join(lines)


@dataclass
class CellNamelist:
    """&CELL namelist parameters for vc-relax / vc-md calculations."""

    cell_dynamics: str = "bfgs"
    press: float = 0.0
    wmass: float = 0.0
    cell_factor: float = 1.2
    cell_dofree: str = "all"
    extra_params: dict[str, Any] = field(default_factory=dict)

    def to_string(self) -> str:
        lines = ["&CELL"]
        lines.append(f"  cell_dynamics = {_format_fortran_val(self.cell_dynamics)},")
        if self.press != 0.0:
            lines.append(f"  press = {_format_fortran_val(self.press)},")
        if self.wmass != 0.0:
            lines.append(f"  wmass = {_format_fortran_val(self.wmass)},")
        if self.cell_factor != 1.2:
            lines.append(f"  cell_factor = {_format_fortran_val(self.cell_factor)},")
        if self.cell_dofree != "all":
            lines.append(f"  cell_dofree = {_format_fortran_val(self.cell_dofree)},")

        for k, v in self.extra_params.items():
            lines.append(f"  {k} = {_format_fortran_val(v)},")

        lines.append("/")
        return "\n".join(lines)


@dataclass
class SpeciesItem:
    """Individual atomic species specification."""

    symbol: str
    mass: float
    pseudo_file: str


@dataclass
class AtomicSpeciesCard:
    """ATOMIC_SPECIES card."""

    species: list[SpeciesItem] = field(default_factory=list)

    def to_string(self) -> str:
        lines = ["ATOMIC_SPECIES"]
        for sp in self.species:
            lines.append(f"  {sp.symbol:<4}  {sp.mass:>10.5f}  {sp.pseudo_file}")
        return "\n".join(lines)


@dataclass
class PositionItem:
    """Individual atomic position coordinate with optional relaxation constraints."""

    symbol: str
    x: float
    y: float
    z: float
    if_pos: tuple[int, int, int] = (1, 1, 1)


@dataclass
class AtomicPositionsCard:
    """ATOMIC_POSITIONS card."""

    mode: str = "angstrom"  # 'alat', 'bohr', 'angstrom', 'crystal'
    positions: list[PositionItem] = field(default_factory=list)

    def to_string(self) -> str:
        lines = [f"ATOMIC_POSITIONS {{{self.mode}}}"]
        has_constraint = any(p.if_pos != (1, 1, 1) for p in self.positions)

        for p in self.positions:
            base = f"  {p.symbol:<4}  {p.x:>14.8f}  {p.y:>14.8f}  {p.z:>14.8f}"
            if has_constraint or p.if_pos != (1, 1, 1):
                base += f"   {p.if_pos[0]}  {p.if_pos[1]}  {p.if_pos[2]}"
            lines.append(base)
        return "\n".join(lines)


@dataclass
class KPointsCard:
    """K_POINTS card."""

    mode: str = "automatic"  # 'automatic', 'gamma', 'crystal_b', 'tpiba_b', etc.
    grid: tuple[int, int, int] = (4, 4, 4)
    shift: tuple[int, int, int] = (1, 1, 1)
    kpoints: list[tuple[float, float, float, float]] = field(default_factory=list)

    def to_string(self) -> str:
        m = self.mode.lower()
        if m == "automatic":
            return (
                f"K_POINTS {{automatic}}\n"
                f"  {self.grid[0]} {self.grid[1]} {self.grid[2]}   "
                f"{self.shift[0]} {self.shift[1]} {self.shift[2]}"
            )
        elif m == "gamma":
            return "K_POINTS {gamma}"
        else:
            # Explicit k-points list
            lines = [f"K_POINTS {{{self.mode}}}", f"  {len(self.kpoints)}"]
            for kp in self.kpoints:
                lines.append(f"  {kp[0]:>12.8f}  {kp[1]:>12.8f}  {kp[2]:>12.8f}  {kp[3]:>8.4f}")
            return "\n".join(lines)


@dataclass
class CellParametersCard:
    """CELL_PARAMETERS card."""

    mode: str = "angstrom"  # 'alat', 'bohr', 'angstrom'
    matrix: list[list[float]] = field(default_factory=list)

    def to_string(self) -> str:
        lines = [f"CELL_PARAMETERS {{{self.mode}}}"]
        for row in self.matrix:
            lines.append(f"  {row[0]:>14.8f}  {row[1]:>14.8f}  {row[2]:>14.8f}")
        return "\n".join(lines)


@dataclass
class QEInput:
    """Full Quantum ESPRESSO calculation input document."""

    control: ControlNamelist = field(default_factory=ControlNamelist)
    system: SystemNamelist = field(default_factory=SystemNamelist)
    electrons: ElectronsNamelist = field(default_factory=ElectronsNamelist)
    ions: Optional[IonsNamelist] = None
    cell: Optional[CellNamelist] = None

    atomic_species: AtomicSpeciesCard = field(default_factory=AtomicSpeciesCard)
    atomic_positions: AtomicPositionsCard = field(default_factory=AtomicPositionsCard)
    k_points: KPointsCard = field(default_factory=KPointsCard)
    cell_parameters: Optional[CellParametersCard] = None

    def to_string(self) -> str:
        """Generate clean, formatted Quantum ESPRESSO .in input text."""
        sections: list[str] = []

        # Namelists
        sections.append(self.control.to_string())
        sections.append(self.system.to_string())
        sections.append(self.electrons.to_string())

        if self.ions is not None:
            sections.append(self.ions.to_string())

        if self.cell is not None:
            sections.append(self.cell.to_string())

        # Cards
        if self.atomic_species.species:
            sections.append(self.atomic_species.to_string())

        if self.atomic_positions.positions:
            sections.append(self.atomic_positions.to_string())

        sections.append(self.k_points.to_string())

        if self.cell_parameters is not None and self.cell_parameters.matrix:
            sections.append(self.cell_parameters.to_string())

        return "\n\n".join(sections) + "\n"

    def to_crystal_structure(self) -> CrystalStructure:
        """Convert input geometry to a CrystalStructure for 3D visualization."""
        lattice: Optional[Lattice] = None

        # Determine lattice
        if self.cell_parameters is not None and len(self.cell_parameters.matrix) >= 3:
            mat = np.array(self.cell_parameters.matrix, dtype=float)[:3, :3]
            unit = self.cell_parameters.mode.lower()
            if unit == "bohr":
                mat = mat * BOHR_TO_ANGSTROM
            elif unit in ("alat", ""):
                alat = 1.0
                if 1 in self.system.celldm and self.system.celldm[1] > 0:
                    alat = self.system.celldm[1] * BOHR_TO_ANGSTROM
                elif self.system.a > 0:
                    alat = self.system.a
                mat = mat * alat
            # unit == 'angstrom' uses mat directly
            lattice = Lattice(mat)
        elif self.system.ibrav != 0:
            lattice = _build_ibrav_lattice(
                ibrav=self.system.ibrav,
                celldm=self.system.celldm,
                a=self.system.a if self.system.a > 0 else None,
                b=self.system.b if self.system.b > 0 else None,
                c=self.system.c if self.system.c > 0 else None,
                cosab=self.system.cosab if self.system.cosab != 0.0 else None,
                cosac=self.system.cosac if self.system.cosac != 0.0 else None,
                cosbc=self.system.cosbc if self.system.cosbc != 0.0 else None,
            )

        # Determine alat for atomic positions if needed
        alat = 1.0
        if 1 in self.system.celldm and self.system.celldm[1] > 0:
            alat = self.system.celldm[1] * BOHR_TO_ANGSTROM
        elif self.system.a > 0:
            alat = self.system.a

        atoms: list[Atom] = []
        pos_mode = self.atomic_positions.mode.lower()

        for idx, pos in enumerate(self.atomic_positions.positions):
            sym = pos.symbol.strip().capitalize()
            raw_coords = (pos.x, pos.y, pos.z)

            if pos_mode == "crystal":
                fpos = raw_coords
                cart_pos = lattice.fractional_to_cartesian(fpos) if lattice else raw_coords
            elif pos_mode == "bohr":
                cart_pos = (
                    pos.x * BOHR_TO_ANGSTROM,
                    pos.y * BOHR_TO_ANGSTROM,
                    pos.z * BOHR_TO_ANGSTROM,
                )
                fpos = lattice.cartesian_to_fractional(cart_pos) if lattice else None
            elif pos_mode == "angstrom":
                cart_pos = raw_coords
                fpos = lattice.cartesian_to_fractional(cart_pos) if lattice else None
            elif pos_mode in ("alat", ""):
                cart_pos = (pos.x * alat, pos.y * alat, pos.z * alat)
                fpos = lattice.cartesian_to_fractional(cart_pos) if lattice else None
            else:
                cart_pos = raw_coords
                fpos = None

            atoms.append(
                Atom(
                    index=idx,
                    symbol=sym,
                    position=cart_pos,
                    fractional_position=fpos,
                )
            )

        structure_name = (
            self.control.title
            or self.control.prefix
            or "Quantum ESPRESSO Structure"
        )
        return CrystalStructure(
            lattice=lattice,
            atoms=atoms,
            name=structure_name,
        )

    @classmethod
    def from_crystal_structure(
        cls,
        structure: CrystalStructure,
        calculation: str = "scf",
    ) -> QEInput:
        """Create a preconfigured QEInput from a CrystalStructure."""
        # Find unique chemical species
        unique_symbols: list[str] = []
        seen = set()
        for atom in structure.atoms:
            sym = atom.symbol.strip().capitalize()
            if sym not in seen:
                seen.add(sym)
                unique_symbols.append(sym)

        # Species card
        species_items: list[SpeciesItem] = []
        for sym in unique_symbols:
            elem = get_element_data(sym)
            pseudo_name = f"{sym}.pbe-n-kjpaw_psl.1.0.0.UPF"
            species_items.append(
                SpeciesItem(
                    symbol=sym,
                    mass=elem.atomic_mass,
                    pseudo_file=pseudo_name,
                )
            )
        atomic_species = AtomicSpeciesCard(species=species_items)

        # Positions card (in Angstrom)
        positions: list[PositionItem] = []
        for atom in structure.atoms:
            positions.append(
                PositionItem(
                    symbol=atom.symbol.strip().capitalize(),
                    x=float(atom.position[0]),
                    y=float(atom.position[1]),
                    z=float(atom.position[2]),
                    if_pos=(1, 1, 1),
                )
            )
        atomic_positions = AtomicPositionsCard(mode="angstrom", positions=positions)

        # Lattice / Cell parameters
        cell_card: Optional[CellParametersCard] = None
        if structure.lattice is not None:
            cell_card = CellParametersCard(
                mode="angstrom",
                matrix=structure.lattice.matrix.tolist(),
            )
            ibrav = 0
        else:
            ibrav = 0

        # Namelists
        calc_clean = calculation.lower()
        title_str = structure.name or structure.formula()
        prefix_clean = structure.name.lower().replace(" ", "_") if structure.name else "pwscf"

        control = ControlNamelist(
            calculation=calc_clean,
            title=title_str,
            prefix=prefix_clean,
            tprnfor=(calc_clean in ("relax", "vc-relax")),
            tstress=(calc_clean in ("vc-relax",)),
        )

        system = SystemNamelist(
            ibrav=ibrav,
            nat=len(structure.atoms),
            ntyp=len(unique_symbols),
            ecutwfc=30.0,
        )

        electrons = ElectronsNamelist()

        ions = IonsNamelist() if calc_clean in ("relax", "vc-relax") else None
        cell = CellNamelist() if calc_clean == "vc-relax" else None

        k_points = KPointsCard(mode="automatic", grid=(4, 4, 4), shift=(1, 1, 1))

        return cls(
            control=control,
            system=system,
            electrons=electrons,
            ions=ions,
            cell=cell,
            atomic_species=atomic_species,
            atomic_positions=atomic_positions,
            k_points=k_points,
            cell_parameters=cell_card,
        )

    def validate(self) -> list[ValidationError]:
        """Convenience method to validate this input."""
        from .validator import QEValidator

        return QEValidator.validate(self)
