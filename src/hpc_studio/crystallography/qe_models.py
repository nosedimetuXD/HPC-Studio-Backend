"""Quantum ESPRESSO input data model and bidirectional parser/generator."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

from hpc_studio.crystallography.models import (
    Atom,
    CrystalStructure,
    ElementData,
    Lattice,
    get_element_data,
)
from hpc_studio.crystallography.parsers.qe import BOHR_TO_ANGSTROM, _build_ibrav_lattice


@dataclass
class AtomicSpecies:
    """Atomic species specification for ATOMIC_SPECIES card."""

    name: str
    mass: float
    pseudo: str

    def to_string(self) -> str:
        return f"  {self.name:<3}  {self.mass:8.4f}  {self.pseudo}"


@dataclass
class AtomicPosition:
    """Atomic position and coordinate fixing flags for ATOMIC_POSITIONS card."""

    name: str
    x: float
    y: float
    z: float
    if_pos: tuple[int, int, int] = (1, 1, 1)

    def to_string(self, include_if_pos: bool = False) -> str:
        base = f"  {self.name:<3}  {self.x:14.9f}  {self.y:14.9f}  {self.z:14.9f}"
        if include_if_pos or self.if_pos != (1, 1, 1):
            return f"{base}  {self.if_pos[0]} {self.if_pos[1]} {self.if_pos[2]}"
        return base


@dataclass
class QEInput:
    """Comprehensive Quantum ESPRESSO pw.x input file data structure."""

    # &CONTROL namelist
    calculation: str = "scf"  # scf, nscf, bands, relax, vc-relax, md
    restart_mode: str = "from_scratch"
    prefix: str = "pwscf"
    outdir: str = "./tmp/"
    pseudo_dir: str = "./pseudo/"
    verbosity: str = "low"
    tprnfor: bool = False
    tstress: bool = False
    forc_conv_thr: float = 1.0e-3
    etot_conv_thr: float = 1.0e-4
    nstep: int = 50
    control_extra: Dict[str, Any] = field(default_factory=dict)

    # &SYSTEM namelist
    ibrav: int = 1
    celldm: Dict[int, float] = field(default_factory=lambda: {1: 10.0})
    a: Optional[float] = None
    b: Optional[float] = None
    c: Optional[float] = None
    cosab: Optional[float] = None
    cosac: Optional[float] = None
    cosbc: Optional[float] = None
    nat: int = 1
    ntyp: int = 1
    ecutwfc: float = 30.0
    ecutrho: Optional[float] = None
    occupations: str = "fixed"  # fixed, smearing, tetrahedra
    smearing: str = "gaussian"  # gaussian, methfessel-paxton, marzari-vanderbilt, fermi-dirac
    degauss: float = 0.01
    nspin: int = 1  # 1: non-magnetic, 2: collinear spin-polarized
    tot_magnetization: Optional[float] = None
    system_extra: Dict[str, Any] = field(default_factory=dict)

    # &ELECTRONS namelist
    conv_thr: float = 1.0e-8
    electron_maxstep: int = 100
    mixing_beta: float = 0.7
    mixing_mode: str = "plain"  # plain, TF, local-TF
    diagonalization: str = "david"  # david, cg, ppcg, paro
    startingpot: str = "atomic"
    startingwfc: str = "atomic+random"
    electrons_extra: Dict[str, Any] = field(default_factory=dict)

    # &IONS namelist (relax, vc-relax, md)
    ion_dynamics: str = "bfgs"
    ions_extra: Dict[str, Any] = field(default_factory=dict)

    # &CELL namelist (vc-relax)
    cell_dynamics: str = "bfgs"
    press: float = 0.0
    cell_extra: Dict[str, Any] = field(default_factory=dict)

    # CARDS
    species: List[AtomicSpecies] = field(
        default_factory=lambda: [
            AtomicSpecies("Si", 28.086, "Si.pbe-n-kjpaw_psl.1.0.0.UPF")
        ]
    )
    positions_unit: str = "alat"  # alat, bohr, angstrom, crystal
    positions: List[AtomicPosition] = field(
        default_factory=lambda: [
            AtomicPosition("Si", 0.0, 0.0, 0.0),
            AtomicPosition("Si", 0.25, 0.25, 0.25),
        ]
    )
    kpoints_mode: str = "automatic"  # automatic, gamma
    kpoints_grid: Tuple[int, int, int] = (4, 4, 4)
    kpoints_shift: Tuple[int, int, int] = (1, 1, 1)
    kpoints_raw: str = ""
    cell_parameters_unit: str = "angstrom"  # angstrom, bohr, alat
    cell_parameters: Optional[List[List[float]]] = None

    def validate(self) -> List[str]:
        """Validate physical and syntactic parameters. Returns list of warning/error messages."""
        errors: List[str] = []
        if not self.species:
            errors.append("Debe definir al menos una especie atómica (ATOMIC_SPECIES).")
        if not self.positions:
            errors.append("Debe definir al menos una posición atómica (ATOMIC_POSITIONS).")

        # Species check
        known_species = {s.name for s in self.species}
        for pos in self.positions:
            if pos.name not in known_species:
                errors.append(f"El átomo '{pos.name}' no está definido en ATOMIC_SPECIES.")

        for sp in self.species:
            if not sp.pseudo.strip():
                errors.append(f"La especie '{sp.name}' no tiene asignado archivo de pseudopotencial.")
            if sp.mass <= 0:
                errors.append(f"La especie '{sp.name}' tiene masa atómica inválida ({sp.mass}).")

        if self.ecutwfc <= 0:
            errors.append("ecutwfc debe ser mayor que 0 Ry.")

        if self.ibrav == 0 and not self.cell_parameters:
            errors.append("ibrav=0 requiere especificar vectores de celda CELL_PARAMETERS.")

        if self.ibrav != 0:
            alat = self.celldm.get(1, self.a)
            if alat is None or alat <= 0:
                errors.append(f"ibrav={self.ibrav} requiere definir celldm(1) o constante de red A > 0.")

        if self.kpoints_mode == "automatic":
            kx, ky, kz = self.kpoints_grid
            if kx < 1 or ky < 1 or kz < 1:
                errors.append("La malla de K-Points automática debe tener dimensiones >= 1.")

        return errors

    def to_string(self) -> str:
        """Serialize QEInput instance into a standard Quantum ESPRESSO pw.x input script."""
        # Update nat and ntyp automatically
        nat_val = len(self.positions) if self.positions else self.nat
        ntyp_val = len(self.species) if self.species else self.ntyp

        lines: List[str] = []

        # 1. &CONTROL
        lines.append("&CONTROL")
        lines.append(f"  calculation = '{self.calculation}',")
        if self.restart_mode != "from_scratch":
            lines.append(f"  restart_mode = '{self.restart_mode}',")
        lines.append(f"  prefix = '{self.prefix}',")
        lines.append(f"  outdir = '{self.outdir}',")
        lines.append(f"  pseudo_dir = '{self.pseudo_dir}',")
        if self.verbosity != "low":
            lines.append(f"  verbosity = '{self.verbosity}',")
        if self.tprnfor:
            lines.append("  tprnfor = .true.,")
        if self.tstress:
            lines.append("  tstress = .true.,")
        if self.calculation in ("relax", "vc-relax", "md"):
            lines.append(f"  forc_conv_thr = {self.forc_conv_thr:.1e},".replace("e-0", "d-").replace("e-", "d-").replace("e+", "d+"))
            lines.append(f"  etot_conv_thr = {self.etot_conv_thr:.1e},".replace("e-0", "d-").replace("e-", "d-").replace("e+", "d+"))
            lines.append(f"  nstep = {self.nstep},")
        for k, v in self.control_extra.items():
            lines.append(f"  {k} = {self._format_val(v)},")
        lines.append("/")

        # 2. &SYSTEM
        lines.append("&SYSTEM")
        lines.append(f"  ibrav = {self.ibrav},")
        if self.ibrav != 0:
            for idx in sorted(self.celldm.keys()):
                lines.append(f"  celldm({idx}) = {self.celldm[idx]:.8f},")
            if self.a is not None and 1 not in self.celldm:
                lines.append(f"  A = {self.a:.8f},")
            if self.b is not None and 2 not in self.celldm:
                lines.append(f"  B = {self.b:.8f},")
            if self.c is not None and 3 not in self.celldm:
                lines.append(f"  C = {self.c:.8f},")
            if self.cosab is not None and 6 not in self.celldm:
                lines.append(f"  cosAB = {self.cosab:.8f},")
            if self.cosac is not None and 5 not in self.celldm:
                lines.append(f"  cosAC = {self.cosac:.8f},")
            if self.cosbc is not None and 4 not in self.celldm:
                lines.append(f"  cosBC = {self.cosbc:.8f},")

        lines.append(f"  nat = {nat_val},")
        lines.append(f"  ntyp = {ntyp_val},")
        lines.append(f"  ecutwfc = {self.ecutwfc:.1f},")
        if self.ecutrho is not None:
            lines.append(f"  ecutrho = {self.ecutrho:.1f},")

        if self.occupations != "fixed":
            lines.append(f"  occupations = '{self.occupations}',")
            if self.occupations == "smearing":
                lines.append(f"  smearing = '{self.smearing}',")
                lines.append(f"  degauss = {self.degauss:.4f},")

        if self.nspin > 1:
            lines.append(f"  nspin = {self.nspin},")
            if self.tot_magnetization is not None:
                lines.append(f"  tot_magnetization = {self.tot_magnetization:.4f},")

        for k, v in self.system_extra.items():
            lines.append(f"  {k} = {self._format_val(v)},")
        lines.append("/")

        # 3. &ELECTRONS
        lines.append("&ELECTRONS")
        conv_str = f"{self.conv_thr:.1e}".replace("e-0", "d-").replace("e-", "d-").replace("e+", "d+")
        lines.append(f"  conv_thr = {conv_str},")
        if self.mixing_beta != 0.7:
            lines.append(f"  mixing_beta = {self.mixing_beta:.2f},")
        if self.mixing_mode != "plain":
            lines.append(f"  mixing_mode = '{self.mixing_mode}',")
        if self.diagonalization != "david":
            lines.append(f"  diagonalization = '{self.diagonalization}',")
        if self.electron_maxstep != 100:
            lines.append(f"  electron_maxstep = {self.electron_maxstep},")
        for k, v in self.electrons_extra.items():
            lines.append(f"  {k} = {self._format_val(v)},")
        lines.append("/")

        # 4. &IONS (optional)
        if self.calculation in ("relax", "vc-relax", "md"):
            lines.append("&IONS")
            lines.append(f"  ion_dynamics = '{self.ion_dynamics}',")
            for k, v in self.ions_extra.items():
                lines.append(f"  {k} = {self._format_val(v)},")
            lines.append("/")

        # 5. &CELL (optional)
        if self.calculation == "vc-relax":
            lines.append("&CELL")
            lines.append(f"  cell_dynamics = '{self.cell_dynamics}',")
            if self.press != 0.0:
                lines.append(f"  press = {self.press:.4f},")
            for k, v in self.cell_extra.items():
                lines.append(f"  {k} = {self._format_val(v)},")
            lines.append("/")

        # 6. CELL_PARAMETERS (if ibrav=0 or present)
        if (self.ibrav == 0 or self.cell_parameters) and self.cell_parameters:
            lines.append(f"CELL_PARAMETERS ({self.cell_parameters_unit})")
            for row in self.cell_parameters:
                lines.append(f"  {row[0]:14.9f}  {row[1]:14.9f}  {row[2]:14.9f}")
            lines.append("")

        # 7. ATOMIC_SPECIES
        lines.append("ATOMIC_SPECIES")
        for sp in self.species:
            lines.append(sp.to_string())
        lines.append("")

        # 8. ATOMIC_POSITIONS
        has_flags = any(p.if_pos != (1, 1, 1) for p in self.positions)
        lines.append(f"ATOMIC_POSITIONS ({self.positions_unit})")
        for p in self.positions:
            lines.append(p.to_string(include_if_pos=has_flags))
        lines.append("")

        # 9. K_POINTS
        if self.kpoints_mode == "gamma":
            lines.append("K_POINTS (gamma)")
        elif self.kpoints_mode == "automatic":
            lines.append("K_POINTS (automatic)")
            kx, ky, kz = self.kpoints_grid
            sx, sy, sz = self.kpoints_shift
            lines.append(f"  {kx} {ky} {kz}  {sx} {sy} {sz}")
        elif self.kpoints_raw:
            lines.append(self.kpoints_raw)
        else:
            lines.append("K_POINTS (automatic)")
            lines.append("  4 4 4  1 1 1")

        return "\n".join(lines).strip() + "\n"

    @staticmethod
    def _format_val(v: Any) -> str:
        if isinstance(v, bool):
            return ".true." if v else ".false."
        if isinstance(v, str):
            return f"'{v}'"
        return str(v)

    @classmethod
    def from_string(cls, content: str) -> QEInput:
        """Parse Quantum ESPRESSO pw.x input text into a structured QEInput."""
        instance = cls()
        instance.species = []
        instance.positions = []
        instance.celldm = {}

        # Remove comments and blank lines for namelist parsing
        lines = content.splitlines()

        # Parse namelists using regex blocks
        def get_namelist(name: str) -> Dict[str, str]:
            pattern = rf"&{name}\b(.*?)(?:\n\s*/|\n\s*&|\Z)"
            m = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
            if not m:
                return {}
            block = m.group(1)
            params = {}
            clean_block_lines = []
            for bline in block.splitlines():
                clean_block_lines.append(re.split(r"[!#]", bline, maxsplit=1)[0])
            clean_block = "\n".join(clean_block_lines)

            # Match key = 'val' or key = "val" or key = unquoted_val
            matches = re.finditer(
                r"([A-Za-z_][A-Za-z0-9_\(\)]*)\s*=\s*(?:'([^']*)'|\"([^\"]*)\"|([^,/\n]+))",
                clean_block,
            )
            for match in matches:
                k = match.group(1).strip().lower()
                if match.group(2) is not None:
                    v = match.group(2).strip()
                elif match.group(3) is not None:
                    v = match.group(3).strip()
                else:
                    v = match.group(4).strip()
                params[k] = v
            return params

        ctrl = get_namelist("CONTROL")
        if "calculation" in ctrl:
            instance.calculation = ctrl["calculation"].lower()
        if "restart_mode" in ctrl:
            instance.restart_mode = ctrl["restart_mode"].lower()
        if "prefix" in ctrl:
            instance.prefix = ctrl["prefix"]
        if "outdir" in ctrl:
            instance.outdir = ctrl["outdir"]
        if "pseudo_dir" in ctrl:
            instance.pseudo_dir = ctrl["pseudo_dir"]
        if "verbosity" in ctrl:
            instance.verbosity = ctrl["verbosity"].lower()
        if "tprnfor" in ctrl:
            instance.tprnfor = ".true." in ctrl["tprnfor"].lower() or ctrl["tprnfor"].lower() == "true"
        if "tstress" in ctrl:
            instance.tstress = ".true." in ctrl["tstress"].lower() or ctrl["tstress"].lower() == "true"
        if "forc_conv_thr" in ctrl:
            try:
                instance.forc_conv_thr = float(ctrl["forc_conv_thr"].replace("d", "e").replace("D", "e"))
            except ValueError:
                pass
        if "etot_conv_thr" in ctrl:
            try:
                instance.etot_conv_thr = float(ctrl["etot_conv_thr"].replace("d", "e").replace("D", "e"))
            except ValueError:
                pass
        if "nstep" in ctrl:
            try:
                instance.nstep = int(ctrl["nstep"])
            except ValueError:
                pass

        sys = get_namelist("SYSTEM")
        if "ibrav" in sys:
            try:
                instance.ibrav = int(sys["ibrav"])
            except ValueError:
                pass
        for k, v in sys.items():
            m_celldm = re.match(r"celldm\((\d+)\)", k)
            if m_celldm:
                try:
                    idx = int(m_celldm.group(1))
                    instance.celldm[idx] = float(v.replace("d", "e").replace("D", "e"))
                except ValueError:
                    pass
        if "a" in sys:
            try:
                instance.a = float(sys["a"].replace("d", "e").replace("D", "e"))
            except ValueError:
                pass
        if "b" in sys:
            try:
                instance.b = float(sys["b"].replace("d", "e").replace("D", "e"))
            except ValueError:
                pass
        if "c" in sys:
            try:
                instance.c = float(sys["c"].replace("d", "e").replace("D", "e"))
            except ValueError:
                pass
        if "cosab" in sys:
            try:
                instance.cosab = float(sys["cosab"].replace("d", "e").replace("D", "e"))
            except ValueError:
                pass
        if "cosac" in sys:
            try:
                instance.cosac = float(sys["cosac"].replace("d", "e").replace("D", "e"))
            except ValueError:
                pass
        if "cosbc" in sys:
            try:
                instance.cosbc = float(sys["cosbc"].replace("d", "e").replace("D", "e"))
            except ValueError:
                pass
        if "nat" in sys:
            try:
                instance.nat = int(sys["nat"])
            except ValueError:
                pass
        if "ntyp" in sys:
            try:
                instance.ntyp = int(sys["ntyp"])
            except ValueError:
                pass
        if "ecutwfc" in sys:
            try:
                instance.ecutwfc = float(sys["ecutwfc"].replace("d", "e").replace("D", "e"))
            except ValueError:
                pass
        if "ecutrho" in sys:
            try:
                instance.ecutrho = float(sys["ecutrho"].replace("d", "e").replace("D", "e"))
            except ValueError:
                pass
        if "occupations" in sys:
            instance.occupations = sys["occupations"].lower()
        if "smearing" in sys:
            instance.smearing = sys["smearing"].lower()
        if "degauss" in sys:
            try:
                instance.degauss = float(sys["degauss"].replace("d", "e").replace("D", "e"))
            except ValueError:
                pass
        if "nspin" in sys:
            try:
                instance.nspin = int(sys["nspin"])
            except ValueError:
                pass
        if "tot_magnetization" in sys:
            try:
                instance.tot_magnetization = float(sys["tot_magnetization"].replace("d", "e").replace("D", "e"))
            except ValueError:
                pass

        elec = get_namelist("ELECTRONS")
        if "conv_thr" in elec:
            try:
                instance.conv_thr = float(elec["conv_thr"].replace("d", "e").replace("D", "e"))
            except ValueError:
                pass
        if "electron_maxstep" in elec:
            try:
                instance.electron_maxstep = int(elec["electron_maxstep"])
            except ValueError:
                pass
        if "mixing_beta" in elec:
            try:
                instance.mixing_beta = float(elec["mixing_beta"].replace("d", "e").replace("D", "e"))
            except ValueError:
                pass
        if "mixing_mode" in elec:
            instance.mixing_mode = elec["mixing_mode"]
        if "diagonalization" in elec:
            instance.diagonalization = elec["diagonalization"]

        ions = get_namelist("IONS")
        if "ion_dynamics" in ions:
            instance.ion_dynamics = ions["ion_dynamics"].lower()

        cell = get_namelist("CELL")
        if "cell_dynamics" in cell:
            instance.cell_dynamics = cell["cell_dynamics"].lower()
        if "press" in cell:
            try:
                instance.press = float(cell["press"].replace("d", "e").replace("D", "e"))
            except ValueError:
                pass

        # Parse Cards
        # 1. ATOMIC_SPECIES
        species_m = re.search(
            r"ATOMIC_SPECIES[ \t]*\n((?:[ \t]*[A-Za-z]+[ \t]+[-+]?\d*\.?\d+[ \t]+[^\n]+\n?)+)",
            content,
            re.IGNORECASE,
        )
        if species_m:
            for sline in species_m.group(1).strip().splitlines():
                parts = sline.split()
                if len(parts) >= 3:
                    try:
                        name = parts[0].strip()
                        mass = float(parts[1])
                        pseudo = parts[2].strip()
                        instance.species.append(AtomicSpecies(name=name, mass=mass, pseudo=pseudo))
                    except ValueError:
                        continue

        # 2. CELL_PARAMETERS
        cell_m = re.search(
            r"CELL_PARAMETERS\s*(\([a-zA-Z_]+\)|[a-zA-Z_]+)?\s*\n((?:[ \t]*[-+]?\d*\.?\d+[^\n]*\n?){3})",
            content,
            re.IGNORECASE,
        )
        if cell_m:
            instance.cell_parameters_unit = (cell_m.group(1) or "angstrom").strip("() \t").lower()
            mat_lines = [l.strip() for l in cell_m.group(2).strip().splitlines() if l.strip()]
            if len(mat_lines) >= 3:
                mat = []
                for r in mat_lines[:3]:
                    mat.append([float(x) for x in r.split()[:3]])
                instance.cell_parameters = mat

        # 3. ATOMIC_POSITIONS
        pos_m = re.search(
            r"ATOMIC_POSITIONS\s*(\([a-zA-Z_]+\)|[a-zA-Z_]+)?\s*\n((?:[ \t]*[A-Za-z]+[ \t]+[-+]?\d*\.?\d+[^\n]*\n?)+)",
            content,
            re.IGNORECASE,
        )
        if pos_m:
            instance.positions_unit = (pos_m.group(1) or "alat").strip("() \t").lower()
            for pline in pos_m.group(2).strip().splitlines():
                parts = pline.split()
                if len(parts) >= 4:
                    try:
                        name = parts[0].strip().capitalize()
                        x = float(parts[1])
                        y = float(parts[2])
                        z = float(parts[3])
                        if_pos = (1, 1, 1)
                        if len(parts) >= 7:
                            if_pos = (int(parts[4]), int(parts[5]), int(parts[6]))
                        instance.positions.append(
                            AtomicPosition(name=name, x=x, y=y, z=z, if_pos=if_pos)
                        )
                    except ValueError:
                        continue

        # 4. K_POINTS
        k_m = re.search(
            r"K_POINTS\s*(\([a-zA-Z_]+\)|[a-zA-Z_]+)?\s*\n([^\n]+)",
            content,
            re.IGNORECASE,
        )
        if k_m:
            k_unit = (k_m.group(1) or "automatic").strip("() \t").lower()
            instance.kpoints_mode = k_unit
            if k_unit == "automatic":
                kparts = k_m.group(2).split()
                if len(kparts) >= 3:
                    try:
                        instance.kpoints_grid = (int(kparts[0]), int(kparts[1]), int(kparts[2]))
                        if len(kparts) >= 6:
                            instance.kpoints_shift = (int(kparts[3]), int(kparts[4]), int(kparts[5]))
                    except ValueError:
                        pass
            elif k_unit == "gamma":
                instance.kpoints_mode = "gamma"
                instance.kpoints_grid = (1, 1, 1)
                instance.kpoints_shift = (0, 0, 0)
            else:
                instance.kpoints_raw = k_m.group(0).strip()

        # Sync nat & ntyp
        if instance.positions:
            instance.nat = len(instance.positions)
        if instance.species:
            instance.ntyp = len(instance.species)

        return instance

    def to_crystal_structure(self) -> CrystalStructure:
        """Convert this QEInput configuration into a 3D renderable CrystalStructure."""
        # 1. Determine lattice
        alat = None
        if 1 in self.celldm:
            alat = self.celldm[1] * BOHR_TO_ANGSTROM
        elif self.a is not None:
            alat = self.a

        lattice: Optional[Lattice] = None
        if self.cell_parameters and len(self.cell_parameters) >= 3:
            mat = np.array(self.cell_parameters[:3], dtype=float)
            u = self.cell_parameters_unit.lower()
            if u == "bohr":
                mat *= BOHR_TO_ANGSTROM
            elif u in ("alat", "") and alat is not None:
                mat *= alat
            lattice = Lattice(mat)
        elif self.ibrav != 0:
            lattice = _build_ibrav_lattice(
                self.ibrav, self.celldm, self.a, self.b, self.c,
                self.cosab, self.cosac, self.cosbc
            )
        else:
            # Fallback simple cubic if ibrav=0 without cell parameters
            scale = alat if alat is not None else 5.0
            lattice = Lattice(np.eye(3) * scale)

        # 2. Build atoms
        atoms: List[Atom] = []
        unit = self.positions_unit.lower()

        for idx, pos in enumerate(self.positions):
            c1, c2, c3 = pos.x, pos.y, pos.z
            fpos = None
            cpos = (c1, c2, c3)

            if unit == "crystal":
                fpos = (c1, c2, c3)
                cpos = lattice.fractional_to_cartesian(fpos) if lattice else (c1, c2, c3)
            elif unit == "bohr":
                cpos = (c1 * BOHR_TO_ANGSTROM, c2 * BOHR_TO_ANGSTROM, c3 * BOHR_TO_ANGSTROM)
                fpos = lattice.cartesian_to_fractional(cpos) if lattice else None
            elif unit == "angstrom":
                cpos = (c1, c2, c3)
                fpos = lattice.cartesian_to_fractional(cpos) if lattice else None
            elif unit in ("alat", ""):
                a_scale = alat if alat is not None else 1.0
                cpos = (c1 * a_scale, c2 * a_scale, c3 * a_scale)
                fpos = lattice.cartesian_to_fractional(cpos) if lattice else None

            atoms.append(
                Atom(
                    index=idx,
                    symbol=pos.name.capitalize(),
                    position=cpos,
                    fractional_position=fpos,
                )
            )

        formula = "".join(f"{s.name}" for s in self.species) if self.species else "QE Structure"
        return CrystalStructure(
            lattice=lattice,
            atoms=atoms,
            name=f"QE: {formula}",
        )

    @classmethod
    def from_crystal_structure(
        cls,
        structure: CrystalStructure,
        prefix: str = "pwscf",
        calculation: str = "scf",
    ) -> QEInput:
        """Construct a valid QEInput template from an arbitrary CrystalStructure (e.g. from CIF)."""
        instance = cls(prefix=prefix, calculation=calculation)
        instance.species = []
        instance.positions = []

        # Unique elements
        unique_syms = sorted(list({atom.symbol for atom in structure.atoms}))
        for sym in unique_syms:
            elem = get_element_data(sym)
            instance.species.append(
                AtomicSpecies(
                    name=sym,
                    mass=elem.atomic_mass,
                    pseudo=f"{sym}.pbe-n-kjpaw_psl.1.0.0.UPF",
                )
            )

        lat = structure.lattice
        if lat is not None:
            instance.ibrav = 0
            instance.cell_parameters_unit = "angstrom"
            instance.cell_parameters = lat.matrix.tolist()
            instance.positions_unit = "crystal"
            for atom in structure.atoms:
                fx, fy, fz = (
                    atom.fractional_position
                    if atom.fractional_position is not None
                    else lat.cartesian_to_fractional(atom.position)
                )
                instance.positions.append(
                    AtomicPosition(name=atom.symbol, x=fx, y=fy, z=fz)
                )
        else:
            instance.ibrav = 1
            instance.positions_unit = "angstrom"
            for atom in structure.atoms:
                instance.positions.append(
                    AtomicPosition(name=atom.symbol, x=atom.position[0], y=atom.position[1], z=atom.position[2])
                )

        instance.nat = len(instance.positions)
        instance.ntyp = len(instance.species)
        return instance


__all__ = ["AtomicSpecies", "AtomicPosition", "QEInput"]
