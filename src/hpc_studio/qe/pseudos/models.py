"""Data models and enums for pseudopotential management in Quantum ESPRESSO."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class SSSPFamily(str, Enum):
    """Standard pseudopotential library families."""

    SSSP_EFFICIENCY = "SSSP_1.3.0_PBE_efficiency"
    SSSP_PRECISION = "SSSP_1.3.0_PBE_precision"
    PSLIBRARY_PAW = "pslibrary_pbe_paw"
    CUSTOM = "custom"


ELEMENT_GROUPS = {
    "No metales": ["H", "C", "N", "O", "P", "S", "Se"],
    "Gases nobles": ["He", "Ne", "Ar", "Kr", "Xe", "Rn"],
    "Alcalinos": ["Li", "Na", "K", "Rb", "Cs", "Fr"],
    "Alcalinotérreos": ["Be", "Mg", "Ca", "Sr", "Ba", "Ra"],
    "Metaloides": ["B", "Si", "Ge", "As", "Sb", "Te"],
    "Halógenos": ["F", "Cl", "Br", "I", "At"],
    "Metales de transición": [
        "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
        "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd",
        "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg",
    ],
    "Post-transición": ["Al", "Ga", "In", "Sn", "Tl", "Pb", "Bi", "Po"],
    "Lantánidos": ["La", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu"],
    "Actínidos": ["Ac", "Th", "Pa", "U", "Np", "Pu"],
}


def get_element_group(symbol: str) -> str:
    """Return the chemical classification for a periodic element."""
    sym = symbol.capitalize()
    for grp, elements in ELEMENT_GROUPS.items():
        if sym in elements:
            return grp
    return "Otros"


@dataclass
class PseudoMetadata:
    """Metadata describing a Quantum ESPRESSO pseudopotential file."""

    element: str
    filename: str
    family: str
    functional: str = "PBE"
    pseudo_type: str = "USPP"  # 'USPP', 'NC', 'PAW', 'SL'
    recommended_ecutwfc: float = 30.0
    recommended_ecutrho: float = 240.0
    sha256: str = ""
    download_url: Optional[str] = None
    local_path: Optional[str] = None
    z_valence: Optional[float] = None
    mesh_size: Optional[int] = None
    group: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.group:
            self.group = get_element_group(self.element)

    @property
    def ecutwfc(self) -> float:
        return self.recommended_ecutwfc

    @ecutwfc.setter
    def ecutwfc(self, val: float) -> None:
        self.recommended_ecutwfc = val

    @property
    def ecutrho(self) -> float:
        return self.recommended_ecutrho

    @ecutrho.setter
    def ecutrho(self, val: float) -> None:
        self.recommended_ecutrho = val

    @property
    def url(self) -> str:
        return self.download_url or ""

