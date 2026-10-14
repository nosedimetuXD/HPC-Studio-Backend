"""High-symmetry k-path generator for electronic band structure calculations.

Follows the SeeK-path and Hinuma et al. (Comp. Mat. Sci. 128, 140-184, 2017) conventions
for standard Brillouin zone paths across crystal systems.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple, Union

from hpc_studio.crystallography.models import CrystalStructure, Lattice


# Standard high-symmetry k-points (in fractional reciprocal lattice coordinates)
# and paths for common crystal systems based on Hinuma / SeeK-path.

# 1. Simple Cubic (SC, ibrav=1)
# Points: GAMMA=(0,0,0), X=(0, 0.5, 0), M=(0.5, 0.5, 0), R=(0.5, 0.5, 0.5)
# Path: GAMMA - X - M - GAMMA - R - X
SC_POINTS: Dict[str, Tuple[float, float, float]] = {
    "GAMMA": (0.0, 0.0, 0.0),
    "X": (0.0, 0.5, 0.0),
    "M": (0.5, 0.5, 0.0),
    "R": (0.5, 0.5, 0.5),
}
SC_PATH = ["GAMMA", "X", "M", "GAMMA", "R", "X"]

# 2. Face-Centered Cubic (FCC, ibrav=2)
# Points: GAMMA=(0,0,0), X=(0.5, 0, 0.5), W=(0.5, 0.25, 0.75), K=(0.375, 0.375, 0.75),
#         L=(0.5, 0.5, 0.5), U=(0.625, 0.25, 0.625)
# Path: GAMMA - X - W - K - GAMMA - L - U - W - X
FCC_POINTS: Dict[str, Tuple[float, float, float]] = {
    "GAMMA": (0.0, 0.0, 0.0),
    "X": (0.5, 0.0, 0.5),
    "W": (0.5, 0.25, 0.75),
    "K": (0.375, 0.375, 0.75),
    "L": (0.5, 0.5, 0.5),
    "U": (0.625, 0.25, 0.625),
}
FCC_PATH = ["GAMMA", "X", "W", "K", "GAMMA", "L", "U", "W", "X"]

# 3. Body-Centered Cubic (BCC, ibrav=3)
# Points: GAMMA=(0,0,0), H=(0.5, -0.5, 0.5), P=(0.25, 0.25, 0.25), N=(0, 0.5, 0)
# Path: GAMMA - H - P - GAMMA - N
BCC_POINTS: Dict[str, Tuple[float, float, float]] = {
    "GAMMA": (0.0, 0.0, 0.0),
    "H": (0.5, -0.5, 0.5),
    "P": (0.25, 0.25, 0.25),
    "N": (0.0, 0.5, 0.0),
}
BCC_PATH = ["GAMMA", "H", "P", "GAMMA", "N"]

# 4. Hexagonal (HEX, ibrav=4)
# Points: GAMMA=(0,0,0), M=(0.5, 0, 0), K=(1/3, 1/3, 0), A=(0, 0, 0.5),
#         L=(0.5, 0, 0.5), H=(1/3, 1/3, 0.5)
# Path: GAMMA - M - K - GAMMA - A - L - H - A
HEX_POINTS: Dict[str, Tuple[float, float, float]] = {
    "GAMMA": (0.0, 0.0, 0.0),
    "M": (0.5, 0.0, 0.0),
    "K": (1.0 / 3.0, 1.0 / 3.0, 0.0),
    "A": (0.0, 0.0, 0.5),
    "L": (0.5, 0.0, 0.5),
    "H": (1.0 / 3.0, 1.0 / 3.0, 0.5),
}
HEX_PATH = ["GAMMA", "M", "K", "GAMMA", "A", "L", "H", "A"]

# 5. Simple Tetragonal (ST, ibrav=6)
# Points: GAMMA=(0,0,0), X=(0, 0.5, 0), M=(0.5, 0.5, 0), Z=(0, 0, 0.5),
#         R=(0, 0.5, 0.5), A=(0.5, 0.5, 0.5)
# Path: GAMMA - X - M - GAMMA - Z - R - A - Z
TET_POINTS: Dict[str, Tuple[float, float, float]] = {
    "GAMMA": (0.0, 0.0, 0.0),
    "X": (0.0, 0.5, 0.0),
    "M": (0.5, 0.5, 0.0),
    "Z": (0.0, 0.0, 0.5),
    "R": (0.0, 0.5, 0.5),
    "A": (0.5, 0.5, 0.5),
}
TET_PATH = ["GAMMA", "X", "M", "GAMMA", "Z", "R", "A", "Z"]


class KPath:
    """Brillouin zone high-symmetry k-path generator for Quantum ESPRESSO."""

    @classmethod
    def detect_bravais_lattice(
        cls, structure_or_ibrav: Union[int, CrystalStructure, Lattice, Any]
    ) -> int:
        """Infer standard ibrav code from input integer, CrystalStructure, or Lattice."""
        if isinstance(structure_or_ibrav, int):
            return structure_or_ibrav

        # If it's a QEInput or object with system.ibrav
        if hasattr(structure_or_ibrav, "system") and hasattr(structure_or_ibrav.system, "ibrav"):
            ib = structure_or_ibrav.system.ibrav
            if ib != 0:
                return ib

        # If it's a crystallography.qe_models.QEInput with ibrav
        if hasattr(structure_or_ibrav, "ibrav"):
            ib = getattr(structure_or_ibrav, "ibrav")
            if isinstance(ib, int) and ib != 0:
                return ib

        # Extract lattice
        lattice: Optional[Lattice] = None
        if isinstance(structure_or_ibrav, Lattice):
            lattice = structure_or_ibrav
        elif isinstance(structure_or_ibrav, CrystalStructure):
            lattice = structure_or_ibrav.lattice
        elif hasattr(structure_or_ibrav, "to_crystal_structure"):
            cs = structure_or_ibrav.to_crystal_structure()
            lattice = cs.lattice if cs else None

        if lattice is None:
            # Fallback to Simple Cubic
            return 1

        a, b, c = lattice.a, lattice.b, lattice.c
        alpha, beta, gamma = lattice.alpha, lattice.beta, lattice.gamma

        eps_ang = 1.0  # degrees tolerance
        eps_len = 0.05  # length relative tolerance

        is_a_eq_b = abs(a - b) / max(a, b) < eps_len
        is_b_eq_c = abs(b - c) / max(b, c) < eps_len
        is_a_eq_c = abs(a - c) / max(a, c) < eps_len

        is_cubic_angles = (
            abs(alpha - 90.0) < eps_ang
            and abs(beta - 90.0) < eps_ang
            and abs(gamma - 90.0) < eps_ang
        )

        if is_cubic_angles and is_a_eq_b and is_b_eq_c:
            return 1  # Simple cubic default if unknown centering

        # Hexagonal check: a=b!=c, alpha=beta=90, gamma=120
        if (
            is_a_eq_b
            and abs(alpha - 90.0) < eps_ang
            and abs(beta - 90.0) < eps_ang
            and (abs(gamma - 120.0) < eps_ang or abs(gamma - 60.0) < eps_ang)
        ):
            return 4

        # Tetragonal check: a=b!=c, alpha=beta=gamma=90
        if is_a_eq_b and is_cubic_angles and not is_b_eq_c:
            return 6

        # Default fallback
        return 1

    @classmethod
    def get_path_definition(
        cls, ibrav: int
    ) -> Tuple[Dict[str, Tuple[float, float, float]], List[str]]:
        """Return high-symmetry special point coordinates and path sequence for an ibrav."""
        ib = abs(ibrav)
        if ib == 1:
            return SC_POINTS, SC_PATH
        elif ib == 2:
            return FCC_POINTS, FCC_PATH
        elif ib == 3:
            return BCC_POINTS, BCC_PATH
        elif ib == 4:
            return HEX_POINTS, HEX_PATH
        elif ib in (6, 7):
            return TET_POINTS, TET_PATH
        else:
            # Fallback to simple cubic
            return SC_POINTS, SC_PATH

    @classmethod
    def generate_kpath(
        cls,
        structure_or_ibrav: Union[int, CrystalStructure, Lattice, Any],
        n_points_per_segment: int = 20,
    ) -> Tuple[List[Tuple[float, float, float, int, str]], List[Tuple[int, str]]]:
        """Generate high-symmetry k-path in crystal coordinates.

        Returns:
            - kpoints: list of tuples (kx, ky, kz, weight/nstep, label)
              In Quantum ESPRESSO 'crystal_b' format, each point in the path specifies
              its fractional coordinates and the number of steps to interpolate to the next point.
            - special_points: list of (index, label) for plotting band structures.
        """
        ibrav = cls.detect_bravais_lattice(structure_or_ibrav)
        points_dict, path_nodes = cls.get_path_definition(ibrav)

        kpoints: List[Tuple[float, float, float, int, str]] = []
        special_points: List[Tuple[int, str]] = []

        total_nodes = len(path_nodes)
        for i, node in enumerate(path_nodes):
            coords = points_dict[node]
            # In crystal_b, the weight integer specifies the number of points in the segment
            # towards the next vertex. The last vertex has 1 (or 0).
            step = n_points_per_segment if i < total_nodes - 1 else 1
            kpoints.append((coords[0], coords[1], coords[2], step, node))
            special_points.append((i, node))

        return kpoints, special_points

    @classmethod
    def apply_to_qe_input(
        cls,
        qe_input: Any,
        n_points_per_segment: int = 20,
    ) -> Any:
        """Inject bands calculation settings and K_POINTS crystal_b card into a QEInput.

        Compatible with both hpc_studio.qe.models.QEInput and
        hpc_studio.crystallography.qe_models.QEInput.
        """
        # 1. Determine ibrav
        ibrav = cls.detect_bravais_lattice(qe_input)
        kpoints, _ = cls.generate_kpath(ibrav, n_points_per_segment=n_points_per_segment)

        # 2. Check which QEInput variant we are dealing with
        # Case A: src/hpc_studio/qe/models.py (has control, system, k_points: KPointsCard)
        if hasattr(qe_input, "control") and hasattr(qe_input, "k_points"):
            from hpc_studio.qe.models import KPointsCard

            qe_input.control.calculation = "bands"
            # Format kpoints as list of (kx, ky, kz, weight)
            card_kpts: List[Tuple[float, float, float, float]] = []
            for kp in kpoints:
                card_kpts.append((kp[0], kp[1], kp[2], float(kp[3])))

            qe_input.k_points = KPointsCard(
                mode="crystal_b",
                kpoints=card_kpts,
            )
            return qe_input

        # Case B: src/hpc_studio/crystallography/qe_models.py (calculation, kpoints_mode, kpoints_raw)
        if hasattr(qe_input, "calculation") and hasattr(qe_input, "kpoints_mode"):
            qe_input.calculation = "bands"
            qe_input.kpoints_mode = "crystal_b"

            raw_lines = [f"K_POINTS (crystal_b)", f"  {len(kpoints)}"]
            for kp in kpoints:
                raw_lines.append(f"  {kp[0]:>12.8f}  {kp[1]:>12.8f}  {kp[2]:>12.8f}  {kp[3]:>4} ! {kp[4]}")
            qe_input.kpoints_raw = "\n".join(raw_lines)
            return qe_input

        return qe_input
