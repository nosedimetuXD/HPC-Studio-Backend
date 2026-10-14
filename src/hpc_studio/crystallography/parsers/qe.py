"""Quantum ESPRESSO input file parser."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Union

import numpy as np

from hpc_studio.crystallography.models import Atom, CrystalStructure, Lattice

# Bohr radius in Angstroms
BOHR_TO_ANGSTROM = 0.529177210903


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
    """Build Lattice from Quantum ESPRESSO ibrav and celldm/lattice parameters.

    In QE: celldm(1) is in Bohr.
    If a is provided, it's typically in Angstroms or Bohr depending on input.
    """
    if ibrav == 0:
        return None  # ibrav=0 requires CELL_PARAMETERS card

    # celldm(1) = a in Bohr
    alat_bohr = celldm.get(1, None)
    if alat_bohr is not None:
        alat = alat_bohr * BOHR_TO_ANGSTROM
    elif a is not None:
        alat = a
    else:
        alat = 1.0

    if ibrav == 1:
        # Simple cubic (sc)
        mat = np.array([
            [alat, 0.0, 0.0],
            [0.0, alat, 0.0],
            [0.0, 0.0, alat],
        ])
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

    elif ibrav == 4:
        # Hexagonal / Trigonal
        # celldm(3) = c/a
        c_fac = celldm.get(3, c / alat if c and alat else 1.0)
        c_val = c_fac * alat
        mat = np.array([
            [alat, 0.0, 0.0],
            [-0.5 * alat, np.sqrt(3) / 2.0 * alat, 0.0],
            [0.0, 0.0, c_val],
        ])
        return Lattice(mat)

    elif ibrav == 6:
        # Tetragonal P (st)
        c_fac = celldm.get(3, c / alat if c and alat else 1.0)
        c_val = c_fac * alat
        mat = np.array([
            [alat, 0.0, 0.0],
            [0.0, alat, 0.0],
            [0.0, 0.0, c_val],
        ])
        return Lattice(mat)

    elif ibrav == 8:
        # Orthorhombic P
        b_fac = celldm.get(2, b / alat if b and alat else 1.0)
        c_fac = celldm.get(3, c / alat if c and alat else 1.0)
        mat = np.array([
            [alat, 0.0, 0.0],
            [0.0, b_fac * alat, 0.0],
            [0.0, 0.0, c_fac * alat],
        ])
        return Lattice(mat)

    elif ibrav == 14:
        # Triclinic
        b_fac = celldm.get(2, 1.0)
        c_fac = celldm.get(3, 1.0)
        cos_bc = celldm.get(4, 0.0)
        cos_ac = celldm.get(5, 0.0)
        cos_ab = celldm.get(6, 0.0)
        alpha = np.degrees(np.arccos(cos_bc))
        beta = np.degrees(np.arccos(cos_ac))
        gamma = np.degrees(np.arccos(cos_ab))
        return Lattice.from_parameters(alat, b_fac * alat, c_fac * alat, alpha, beta, gamma)

    else:
        # Fallback to simple cubic with lattice constant alat
        mat = np.eye(3) * alat
        return Lattice(mat)


def read_qe_input(filepath_or_content: Union[str, Path]) -> CrystalStructure:
    """Parse Quantum ESPRESSO input file (.in or .pwi).

    Extracts:
      - ibrav, celldm(1..6), a, b, c from &SYSTEM namelist
      - CELL_PARAMETERS card (if ibrav=0 or present)
      - ATOMIC_SPECIES card
      - ATOMIC_POSITIONS card (alat, bohr, angstrom, crystal)
    """
    path = Path(str(filepath_or_content))
    if path.is_file():
        content = path.read_text(encoding="utf-8", errors="replace")
    else:
        content = str(filepath_or_content)

    # Clean comments (! and #)
    lines_clean = []
    for line in content.splitlines():
        line_no_comment = re.split(r"[!#]", line, maxsplit=1)[0].strip()
        lines_clean.append(line_no_comment)

    full_text = "\n".join(lines_clean)

    # 1. Parse SYSTEM namelist parameters
    ibrav = 0
    celldm: dict[int, float] = {}
    param_a = None
    param_b = None
    param_c = None

    ibrav_match = re.search(r"\bibrav\s*=\s*(-?\d+)", full_text, re.IGNORECASE)
    if ibrav_match:
        ibrav = int(ibrav_match.group(1))

    for m in re.finditer(r"celldm\((\d+)\)\s*=\s*([-+]?\d*\.?\d+(?:[eEdD][-+]?\d+)?)", full_text, re.IGNORECASE):
        idx = int(m.group(1))
        val_str = m.group(2).replace("d", "e").replace("D", "e")
        celldm[idx] = float(val_str)

    a_match = re.search(r"\bA\s*=\s*([-+]?\d*\.?\d+(?:[eEdD][-+]?\d+)?)", full_text, re.IGNORECASE)
    if a_match:
        param_a = float(a_match.group(1).replace("d", "e").replace("D", "e"))

    b_match = re.search(r"\bB\s*=\s*([-+]?\d*\.?\d+(?:[eEdD][-+]?\d+)?)", full_text, re.IGNORECASE)
    if b_match:
        param_b = float(b_match.group(1).replace("d", "e").replace("D", "e"))

    c_match = re.search(r"\bC\s*=\s*([-+]?\d*\.?\d+(?:[eEdD][-+]?\d+)?)", full_text, re.IGNORECASE)
    if c_match:
        param_c = float(c_match.group(1).replace("d", "e").replace("D", "e"))

    # Determine alat (in Angstroms)
    alat = None
    if 1 in celldm:
        alat = celldm[1] * BOHR_TO_ANGSTROM
    elif param_a is not None:
        alat = param_a

    # 2. Check for CELL_PARAMETERS card
    cell_card_match = re.search(
        r"CELL_PARAMETERS\s*(\([a-zA-Z_]+\)|[a-zA-Z_]+)?\s*\n((?:[ \t]*[-+]?\d*\.?\d+[^\n]*\n?){3})",
        full_text,
        re.IGNORECASE,
    )

    lattice = None
    if cell_card_match:
        unit = (cell_card_match.group(1) or "").strip("() \t").lower()
        matrix_lines = [l.strip() for l in cell_card_match.group(2).strip().splitlines() if l.strip()]
        if len(matrix_lines) >= 3:
            mat_rows = []
            for r in matrix_lines[:3]:
                mat_rows.append([float(x) for x in r.split()[:3]])
            mat = np.array(mat_rows, dtype=float)

            if unit == "bohr":
                mat *= BOHR_TO_ANGSTROM
            elif unit in ("alat", "") and alat is not None:
                mat *= alat
            # unit == 'angstrom' is default if not bohr or alat
            lattice = Lattice(mat)

    if lattice is None and ibrav != 0:
        lattice = _build_ibrav_lattice(ibrav, celldm, param_a, param_b, param_c)

    # 3. Parse ATOMIC_POSITIONS card
    # Format: ATOMIC_POSITIONS {alat | bohr | crystal | angstrom}
    pos_card_match = re.search(
        r"ATOMIC_POSITIONS\s*(\([a-zA-Z_]+\)|[a-zA-Z_]+)?\s*\n((?:[ \t]*[A-Za-z]+[ \t]+[-+]?\d*\.?\d+[^\n]*\n?)+)",
        full_text,
        re.IGNORECASE,
    )

    atoms: list[Atom] = []
    if pos_card_match:
        pos_unit = (pos_card_match.group(1) or "alat").strip("() \t").lower()
        pos_block = pos_card_match.group(2).strip().splitlines()

        for idx, line in enumerate(pos_block):
            parts = line.split()
            if len(parts) >= 4:
                sym = parts[0].strip().capitalize()
                try:
                    c1 = float(parts[1])
                    c2 = float(parts[2])
                    c3 = float(parts[3])
                except ValueError:
                    continue

                if pos_unit == "crystal":
                    fpos = (c1, c2, c3)
                    pos = lattice.fractional_to_cartesian(fpos) if lattice else (c1, c2, c3)
                elif pos_unit == "bohr":
                    pos = (c1 * BOHR_TO_ANGSTROM, c2 * BOHR_TO_ANGSTROM, c3 * BOHR_TO_ANGSTROM)
                    fpos = lattice.cartesian_to_fractional(pos) if lattice else None
                elif pos_unit == "angstrom":
                    pos = (c1, c2, c3)
                    fpos = lattice.cartesian_to_fractional(pos) if lattice else None
                elif pos_unit in ("alat", ""):
                    a_scale = alat if alat is not None else 1.0
                    pos = (c1 * a_scale, c2 * a_scale, c3 * a_scale)
                    fpos = lattice.cartesian_to_fractional(pos) if lattice else None
                else:
                    pos = (c1, c2, c3)
                    fpos = None

                atoms.append(
                    Atom(
                        index=idx,
                        symbol=sym,
                        position=pos,
                        fractional_position=fpos,
                    )
                )

    return CrystalStructure(
        lattice=lattice,
        atoms=atoms,
        name="Quantum ESPRESSO Structure",
    )
