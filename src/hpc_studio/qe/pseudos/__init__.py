"""Pseudopotential management package for Quantum ESPRESSO in HPC Studio."""

from .manager import PseudoManager
from .models import ELEMENT_GROUPS, PseudoMetadata, SSSPFamily, get_element_group
from .upf_parser import UPFParser

FAMILIES = [
    "SSSP Efficiency 1.3.0",
    "SSSP Precision 1.3.0",
    "Pslibrary PAW",
]

__all__ = [
    "FAMILIES",
    "ELEMENT_GROUPS",
    "get_element_group",
    "PseudoManager",
    "PseudoMetadata",
    "SSSPFamily",
    "UPFParser",
]
