"""Crystallographic and atomic data models."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np


@dataclass(frozen=True)
class ElementData:
    """Chemical and crystallographic data for chemical elements."""

    symbol: str
    atomic_number: int
    atomic_mass: float
    covalent_radius: float  # in Angstroms
    vdw_radius: float  # in Angstroms
    cpk_hex: str  # e.g. "#FF0000"
    cpk_rgb: tuple[float, float, float]  # normalized 0.0 .. 1.0


def _hex_to_rgb(hex_code: str) -> tuple[float, float, float]:
    hex_code = hex_code.lstrip("#")
    r = int(hex_code[0:2], 16) / 255.0
    g = int(hex_code[2:4], 16) / 255.0
    b = int(hex_code[4:6], 16) / 255.0
    return (round(r, 4), round(g, 4), round(b, 4))


# Comprehensive element database (common elements and standard defaults)
_ELEMENT_TABLE: dict[str, tuple[int, float, float, float, str]] = {
    # symbol: (atomic_number, mass, cov_radius, vdw_radius, hex_color)
    "H": (1, 1.008, 0.31, 1.20, "#FFFFFF"),
    "He": (2, 4.0026, 0.28, 1.40, "#D9FFFF"),
    "Li": (3, 6.94, 1.28, 1.82, "#CC80FF"),
    "Be": (4, 9.0122, 0.96, 1.53, "#C2FF00"),
    "B": (5, 10.81, 0.84, 1.92, "#FFB5B5"),
    "C": (6, 12.011, 0.76, 1.70, "#909090"),
    "N": (7, 14.007, 0.71, 1.55, "#3050F8"),
    "O": (8, 15.999, 0.66, 1.52, "#FF0D0D"),
    "F": (9, 18.998, 0.57, 1.47, "#90E050"),
    "Ne": (10, 20.180, 0.58, 1.54, "#B3E3F5"),
    "Na": (11, 22.990, 1.66, 2.27, "#AB5CF2"),
    "Mg": (12, 24.305, 1.41, 1.73, "#8AFF00"),
    "Al": (13, 26.982, 1.21, 1.84, "#BFA6A6"),
    "Si": (14, 28.085, 1.11, 2.10, "#F0C8A0"),
    "P": (15, 30.974, 1.07, 1.80, "#FF8000"),
    "S": (16, 32.06, 1.05, 1.80, "#FFFF30"),
    "Cl": (17, 35.45, 1.02, 1.75, "#1FF01F"),
    "Ar": (18, 39.948, 1.06, 1.88, "#80D1E3"),
    "K": (19, 39.098, 2.03, 2.75, "#8F40D4"),
    "Ca": (20, 40.078, 1.76, 2.31, "#3DFF00"),
    "Sc": (21, 44.956, 1.70, 2.11, "#E6E6E6"),
    "Ti": (22, 47.867, 1.60, 2.00, "#BFC2C7"),
    "V": (23, 50.942, 1.53, 2.00, "#A6A6AB"),
    "Cr": (24, 51.996, 1.39, 2.00, "#8A99C7"),
    "Mn": (25, 54.938, 1.39, 2.00, "#9C7AC7"),
    "Fe": (26, 55.845, 1.32, 2.00, "#E06633"),
    "Co": (27, 58.933, 1.26, 2.00, "#F090A0"),
    "Ni": (28, 58.693, 1.24, 1.63, "#50D050"),
    "Cu": (29, 63.546, 1.32, 1.40, "#C88033"),
    "Zn": (30, 65.38, 1.22, 1.39, "#7D80B0"),
    "Ga": (31, 69.723, 1.22, 1.87, "#C28F8F"),
    "Ge": (32, 72.630, 1.20, 2.11, "#668F8F"),
    "As": (33, 74.922, 1.19, 1.85, "#BD80E3"),
    "Se": (34, 78.971, 1.20, 1.90, "#FFA100"),
    "Br": (35, 79.904, 1.20, 1.85, "#A62929"),
    "Kr": (36, 83.798, 1.16, 2.02, "#5CB8D1"),
    "Rb": (37, 85.468, 2.20, 3.03, "#702EB0"),
    "Sr": (38, 87.62, 1.95, 2.49, "#00FF00"),
    "Y": (39, 88.906, 1.90, 2.00, "#94FFFF"),
    "Zr": (40, 91.224, 1.75, 2.00, "#94E0E0"),
    "Nb": (41, 92.906, 1.64, 2.00, "#73C2C9"),
    "Mo": (42, 95.95, 1.54, 2.00, "#54B5B5"),
    "Tc": (43, 98.0, 1.47, 2.00, "#3B9E9E"),
    "Ru": (44, 101.07, 1.46, 2.00, "#248F8F"),
    "Rh": (45, 102.91, 1.42, 2.00, "#0A7D8C"),
    "Pd": (46, 106.42, 1.39, 1.63, "#006985"),
    "Ag": (47, 107.87, 1.45, 1.72, "#C0C0C0"),
    "Cd": (48, 112.41, 1.44, 1.58, "#FFD98F"),
    "In": (49, 114.82, 1.42, 1.93, "#A67573"),
    "Sn": (50, 118.71, 1.39, 2.17, "#668080"),
    "Sb": (51, 121.76, 1.39, 2.06, "#9E63B5"),
    "Te": (52, 127.60, 1.38, 2.06, "#D47A00"),
    "I": (53, 126.90, 1.39, 1.98, "#940094"),
    "Xe": (54, 131.29, 1.40, 2.16, "#429EB0"),
    "Cs": (55, 132.91, 2.44, 3.43, "#57178F"),
    "Ba": (56, 137.33, 2.15, 2.68, "#00C900"),
    "La": (57, 138.91, 2.07, 2.00, "#70D4FF"),
    "Ce": (58, 140.12, 2.04, 2.00, "#FFFFC7"),
    "Pr": (59, 140.91, 2.03, 2.00, "#D9FFC7"),
    "Nd": (60, 144.24, 2.01, 2.00, "#C7FFC7"),
    "Pm": (61, 145.0, 1.99, 2.00, "#A3FFC7"),
    "Sm": (62, 150.36, 1.98, 2.00, "#8FFFC7"),
    "Eu": (63, 151.96, 1.98, 2.00, "#61FFC7"),
    "Gd": (64, 157.25, 1.96, 2.00, "#45FFC7"),
    "Tb": (65, 158.93, 1.94, 2.00, "#30FFC7"),
    "Dy": (66, 162.50, 1.92, 2.00, "#1FFFC7"),
    "Ho": (67, 164.93, 1.92, 2.00, "#00FF9C"),
    "Er": (68, 167.26, 1.89, 2.00, "#00E675"),
    "Tm": (69, 168.93, 1.90, 2.00, "#00D452"),
    "Yb": (70, 173.05, 1.87, 2.00, "#00BF38"),
    "Lu": (71, 174.97, 1.87, 2.00, "#00AB24"),
    "Hf": (72, 178.49, 1.75, 2.00, "#4DC2FF"),
    "Ta": (73, 180.95, 1.70, 2.00, "#4DA6FF"),
    "W": (74, 183.84, 1.62, 2.00, "#2194D6"),
    "Re": (75, 186.21, 1.51, 2.00, "#267DAB"),
    "Os": (76, 190.23, 1.44, 2.00, "#266696"),
    "Ir": (77, 192.22, 1.41, 2.00, "#175487"),
    "Pt": (78, 195.08, 1.36, 1.75, "#D0D0E0"),
    "Au": (79, 196.97, 1.36, 1.66, "#FFD123"),
    "Hg": (80, 200.59, 1.32, 1.55, "#B8B8D0"),
    "Tl": (81, 204.38, 1.45, 1.96, "#A6544D"),
    "Pb": (82, 207.2, 1.46, 2.02, "#575961"),
    "Bi": (83, 208.98, 1.48, 2.07, "#9E4FB5"),
    "Po": (84, 209.0, 1.40, 1.97, "#AB5C00"),
    "At": (85, 210.0, 1.50, 2.02, "#754F45"),
    "Rn": (86, 222.0, 1.50, 2.20, "#428296"),
    "Fr": (87, 223.0, 2.60, 3.48, "#420066"),
    "Ra": (88, 226.0, 2.21, 2.83, "#007D00"),
    "Ac": (89, 227.0, 2.15, 2.00, "#70ABFA"),
    "Th": (90, 232.04, 2.06, 2.00, "#00BAFF"),
    "Pa": (91, 231.04, 2.00, 2.00, "#00A1FF"),
    "U": (92, 238.03, 1.96, 1.86, "#008FFF"),
    "Np": (93, 237.0, 1.90, 2.00, "#0080FF"),
    "Pu": (94, 244.0, 1.87, 2.00, "#006BFF"),
}

ELEMENT_CACHE: dict[str, ElementData] = {}


def get_element_data(symbol: str) -> ElementData:
    """Get standard element data by chemical symbol."""
    clean_sym = symbol.strip().capitalize()
    if clean_sym in ELEMENT_CACHE:
        return ELEMENT_CACHE[clean_sym]

    if clean_sym in _ELEMENT_TABLE:
        z, mass, cov, vdw, hex_code = _ELEMENT_TABLE[clean_sym]
        rgb = _hex_to_rgb(hex_code)
        data = ElementData(
            symbol=clean_sym,
            atomic_number=z,
            atomic_mass=mass,
            covalent_radius=cov,
            vdw_radius=vdw,
            cpk_hex=hex_code,
            cpk_rgb=rgb,
        )
    else:
        # Fallback for unknown / dummy elements
        data = ElementData(
            symbol=clean_sym,
            atomic_number=0,
            atomic_mass=0.0,
            covalent_radius=1.2,
            vdw_radius=1.7,
            cpk_hex="#FF1493",
            cpk_rgb=_hex_to_rgb("#FF1493"),
        )
    ELEMENT_CACHE[clean_sym] = data
    return data


@dataclass
class Atom:
    """Atomic site in a structure."""

    index: int
    symbol: str
    position: tuple[float, float, float]  # Cartesian coordinates in Angstroms
    fractional_position: Optional[tuple[float, float, float]] = None
    tag: str = ""

    @property
    def element_data(self) -> ElementData:
        return get_element_data(self.symbol)


@dataclass
class Lattice:
    """3x3 Crystal lattice definition with cell parameters and transformations."""

    matrix: np.ndarray  # shape (3, 3), rows are lattice vectors a, b, c
    a: float = field(init=False)
    b: float = field(init=False)
    c: float = field(init=False)
    alpha: float = field(init=False)  # degrees
    beta: float = field(init=False)  # degrees
    gamma: float = field(init=False)  # degrees
    volume: float = field(init=False)  # Angstrom^3
    reciprocal_matrix: np.ndarray = field(init=False)  # 2*pi * (matrix^-1)^T or (matrix^-1)^T

    def __post_init__(self):
        mat = np.array(self.matrix, dtype=float)
        if mat.shape != (3, 3):
            raise ValueError(f"Lattice matrix must be 3x3, got shape {mat.shape}")

        object.__setattr__(self, "matrix", mat)

        va, vb, vc = mat[0], mat[1], mat[2]
        len_a = float(np.linalg.norm(va))
        len_b = float(np.linalg.norm(vb))
        len_c = float(np.linalg.norm(vc))

        if len_a < 1e-8 or len_b < 1e-8 or len_c < 1e-8:
            raise ValueError("Lattice vectors must have non-zero length")

        object.__setattr__(self, "a", len_a)
        object.__setattr__(self, "b", len_b)
        object.__setattr__(self, "c", len_c)

        # Angles in degrees
        alpha_rad = np.arccos(np.clip(np.dot(vb, vc) / (len_b * len_c), -1.0, 1.0))
        beta_rad = np.arccos(np.clip(np.dot(va, vc) / (len_a * len_c), -1.0, 1.0))
        gamma_rad = np.arccos(np.clip(np.dot(va, vb) / (len_a * len_b), -1.0, 1.0))

        object.__setattr__(self, "alpha", float(np.degrees(alpha_rad)))
        object.__setattr__(self, "beta", float(np.degrees(beta_rad)))
        object.__setattr__(self, "gamma", float(np.degrees(gamma_rad)))

        vol = float(np.abs(np.dot(va, np.cross(vb, vc))))
        object.__setattr__(self, "volume", vol)

        # Reciprocal matrix: b_i = 2 * pi * inv(matrix)^T
        inv_mat = np.linalg.inv(mat)
        object.__setattr__(self, "reciprocal_matrix", 2.0 * np.pi * inv_mat.T)
        object.__setattr__(self, "_inv_matrix", inv_mat)

    @classmethod
    def from_parameters(
        cls,
        a: float,
        b: float,
        c: float,
        alpha: float,
        beta: float,
        gamma: float,
    ) -> Lattice:
        """Create Lattice from lattice constants and angles (in degrees)."""
        alpha_r = np.radians(alpha)
        beta_r = np.radians(beta)
        gamma_r = np.radians(gamma)

        cos_a = np.cos(alpha_r)
        cos_b = np.cos(beta_r)
        cos_g = np.cos(gamma_r)
        sin_g = np.sin(gamma_r)

        # Vector a along X
        va = np.array([a, 0.0, 0.0])
        # Vector b in XY plane
        vb = np.array([b * cos_g, b * sin_g, 0.0])
        # Vector c
        term = (cos_a - cos_b * cos_g) / sin_g
        cz_sq = np.clip(np.sin(beta_r) ** 2 - term**2, 0.0, None)
        cz = c * np.sqrt(cz_sq)
        vc = np.array([c * cos_b, c * term, cz])

        mat = np.vstack([va, vb, vc])
        return cls(mat)

    @classmethod
    def cubic(cls, a: float) -> Lattice:
        return cls(np.eye(3) * a)

    def cartesian_to_fractional(
        self, pos: Sequence[float] | np.ndarray
    ) -> tuple[float, float, float]:
        """Convert Cartesian coordinates (Å) to fractional coordinates [0, 1)."""
        # pos = fpos @ matrix  => fpos = pos @ inv(matrix)
        pos_arr = np.array(pos, dtype=float)
        inv_m = getattr(self, "_inv_matrix", np.linalg.inv(self.matrix))
        fpos = pos_arr @ inv_m
        return (float(fpos[0]), float(fpos[1]), float(fpos[2]))

    def fractional_to_cartesian(
        self, fpos: Sequence[float] | np.ndarray
    ) -> tuple[float, float, float]:
        """Convert fractional coordinates to Cartesian coordinates (Å)."""
        fpos_arr = np.array(fpos, dtype=float)
        pos = fpos_arr @ self.matrix
        return (float(pos[0]), float(pos[1]), float(pos[2]))


@dataclass
class CrystalStructure:
    """Crystal structure combining Lattice, atomic sites and chemical info."""

    lattice: Optional[Lattice]
    atoms: list[Atom]
    name: str = ""
    formula_str: Optional[str] = None

    def __post_init__(self):
        # Synchronize coordinates if lattice is present
        if self.lattice is not None:
            for atom in self.atoms:
                if atom.fractional_position is None and atom.position is not None:
                    atom.fractional_position = self.lattice.cartesian_to_fractional(
                        atom.position
                    )
                elif atom.position is None and atom.fractional_position is not None:
                    atom.position = self.lattice.fractional_to_cartesian(
                        atom.fractional_position
                    )

    def formula(self) -> str:
        """Calculate reduced chemical formula (e.g. 'Si2', 'NaCl', 'TiO2')."""
        if self.formula_str:
            return self.formula_str
        if not self.atoms:
            return ""

        counts = Counter(atom.symbol for atom in self.atoms)
        if not counts:
            return ""

        # Compute greatest common divisor across element counts
        gcd_val = math.gcd(*counts.values())

        # Sort elements Hill system (C, H, then alphabetical)
        elements = list(counts.keys())
        has_c = "C" in elements
        if has_c:
            elements.remove("C")
            if "H" in elements:
                elements.remove("H")
                sorted_elems = ["C", "H"] + sorted(elements)
            else:
                sorted_elems = ["C"] + sorted(elements)
        else:
            sorted_elems = sorted(elements)

        parts = []
        for elem in sorted_elems:
            red_count = counts[elem] // gcd_val
            parts.append(f"{elem}{red_count if red_count > 1 else ''}")

        return "".join(parts)

    def distance(self, atom_idx1: int, atom_idx2: int, mic: bool = True) -> float:
        """Calculate distance between two atoms with optional Minimum Image Convention (MIC)."""
        p1 = np.array(self.atoms[atom_idx1].position, dtype=float)
        p2 = np.array(self.atoms[atom_idx2].position, dtype=float)

        if not mic or self.lattice is None:
            return float(np.linalg.norm(p2 - p1))

        # Minimum Image Convention in fractional coordinates
        f1 = np.array(
            self.atoms[atom_idx1].fractional_position
            if self.atoms[atom_idx1].fractional_position is not None
            else self.lattice.cartesian_to_fractional(p1),
            dtype=float,
        )
        f2 = np.array(
            self.atoms[atom_idx2].fractional_position
            if self.atoms[atom_idx2].fractional_position is not None
            else self.lattice.cartesian_to_fractional(p2),
            dtype=float,
        )

        df = f2 - f1
        df -= np.round(df)  # wrap to [-0.5, 0.5]
        dr = df @ self.lattice.matrix
        return float(np.linalg.norm(dr))

    def angle(self, atom_idx1: int, atom_idx2: int, atom_idx3: int) -> float:
        """Calculate bond angle between atom1 - atom2(vertex) - atom3 in degrees."""
        if self.lattice is not None:
            # Respect periodic displacement relative to vertex atom2
            f1 = np.array(
                self.atoms[atom_idx1].fractional_position
                if self.atoms[atom_idx1].fractional_position is not None
                else self.lattice.cartesian_to_fractional(self.atoms[atom_idx1].position)
            )
            f2 = np.array(
                self.atoms[atom_idx2].fractional_position
                if self.atoms[atom_idx2].fractional_position is not None
                else self.lattice.cartesian_to_fractional(self.atoms[atom_idx2].position)
            )
            f3 = np.array(
                self.atoms[atom_idx3].fractional_position
                if self.atoms[atom_idx3].fractional_position is not None
                else self.lattice.cartesian_to_fractional(self.atoms[atom_idx3].position)
            )
            df12 = f1 - f2
            df12 -= np.round(df12)
            v1 = df12 @ self.lattice.matrix

            df32 = f3 - f2
            df32 -= np.round(df32)
            v2 = df32 @ self.lattice.matrix
        else:
            p1 = np.array(self.atoms[atom_idx1].position)
            p2 = np.array(self.atoms[atom_idx2].position)
            p3 = np.array(self.atoms[atom_idx3].position)
            v1 = p1 - p2
            v2 = p3 - p2

        n1 = np.linalg.norm(v1)
        n2 = np.linalg.norm(v2)
        if n1 < 1e-8 or n2 < 1e-8:
            return 0.0

        cos_theta = np.dot(v1, v2) / (n1 * n2)
        cos_theta = np.clip(cos_theta, -1.0, 1.0)
        return float(np.degrees(np.arccos(cos_theta)))

    def dihedral(self, i1: int, i2: int, i3: int, i4: int) -> float:
        """Calculate dihedral (torsion) angle between i1-i2-i3-i4 in degrees."""
        if self.lattice is not None:
            # Relative vectors with MIC referenced from i2
            f1 = np.array(self.lattice.cartesian_to_fractional(self.atoms[i1].position))
            f2 = np.array(self.lattice.cartesian_to_fractional(self.atoms[i2].position))
            f3 = np.array(self.lattice.cartesian_to_fractional(self.atoms[i3].position))
            f4 = np.array(self.lattice.cartesian_to_fractional(self.atoms[i4].position))

            df12 = f1 - f2
            df12 -= np.round(df12)
            b1 = -(df12 @ self.lattice.matrix)  # vector i1 -> i2

            df32 = f3 - f2
            df32 -= np.round(df32)
            b2 = df32 @ self.lattice.matrix  # vector i2 -> i3

            df43 = f4 - f3
            df43 -= np.round(df43)
            b3 = df43 @ self.lattice.matrix  # vector i3 -> i4
        else:
            p1 = np.array(self.atoms[i1].position)
            p2 = np.array(self.atoms[i2].position)
            p3 = np.array(self.atoms[i3].position)
            p4 = np.array(self.atoms[i4].position)
            b1 = p2 - p1
            b2 = p3 - p2
            b3 = p4 - p3

        # Praxeolitic dihedral angle formula
        n1 = np.cross(b1, b2)
        n2 = np.cross(b2, b3)
        n1_norm = np.linalg.norm(n1)
        n2_norm = np.linalg.norm(n2)
        if n1_norm < 1e-8 or n2_norm < 1e-8:
            return 0.0

        n1 /= n1_norm
        n2 /= n2_norm
        m1 = np.cross(n1, b2 / np.linalg.norm(b2))
        x = np.dot(n1, n2)
        y = np.dot(m1, n2)
        return float(np.degrees(np.arctan2(y, x)))

    def calculate_bonds(
        self, tolerance: float = 0.45
    ) -> list[tuple[int, int, float]]:
        """Calculate atomic bonds based on covalent radii and tolerance (Å).

        Bond criteria:
            0.1 Å < d <= r_cov(A) + r_cov(B) + tolerance
        Returns list of (atom_idx_i, atom_idx_j, distance).
        """
        bonds = []
        n_atoms = len(self.atoms)
        if n_atoms < 2:
            return bonds

        r_cov = [atom.element_data.covalent_radius for atom in self.atoms]

        for i in range(n_atoms):
            for j in range(i + 1, n_atoms):
                d = self.distance(i, j, mic=(self.lattice is not None))
                cutoff = r_cov[i] + r_cov[j] + tolerance
                if 0.1 <= d <= cutoff:
                    bonds.append((i, j, round(d, 4)))

        return bonds

    def create_supercell(self, nx: int, ny: int, nz: int) -> CrystalStructure:
        """Create a periodic supercell by replicating the unit cell nx x ny x nz times."""
        if nx < 1 or ny < 1 or nz < 1:
            raise ValueError("Supercell dimensions nx, ny, nz must be positive integers")

        if self.lattice is None:
            raise ValueError("Cannot create supercell for structure without Lattice")

        # New lattice vectors scaled by replication factors
        new_matrix = np.copy(self.lattice.matrix)
        new_matrix[0] *= nx
        new_matrix[1] *= ny
        new_matrix[2] *= nz
        new_lattice = Lattice(new_matrix)

        new_atoms: list[Atom] = []
        atom_idx = 0

        for ix in range(nx):
            for iy in range(ny):
                for iz in range(nz):
                    shift = np.array([ix, iy, iz], dtype=float)
                    for atom in self.atoms:
                        if atom.fractional_position is not None:
                            fpos_orig = np.array(atom.fractional_position, dtype=float)
                        else:
                            fpos_orig = np.array(
                                self.lattice.cartesian_to_fractional(atom.position),
                                dtype=float,
                            )
                        # Fractional coordinate in supercell
                        new_fpos = (fpos_orig + shift) / np.array([nx, ny, nz], dtype=float)
                        new_cpos = new_lattice.fractional_to_cartesian(new_fpos)

                        new_atoms.append(
                            Atom(
                                index=atom_idx,
                                symbol=atom.symbol,
                                position=new_cpos,
                                fractional_position=new_fpos,
                                tag=atom.tag,
                            )
                        )
                        atom_idx += 1

        name = f"{self.name} {nx}x{ny}x{nz}" if self.name else f"Supercell {nx}x{ny}x{nz}"
        return CrystalStructure(
            lattice=new_lattice,
            atoms=new_atoms,
            name=name,
        )


# Re-export QE data models
from .qe_models import AtomicPosition, AtomicSpecies, QEInput  # noqa: E402
