"""CIF (Crystallographic Information File) parser."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Union

import numpy as np

from hpc_studio.crystallography.models import Atom, CrystalStructure, Lattice


def _clean_cif_value(val: str) -> str:
    """Strip CIF quotes and uncertainties like 1.5432(5) -> 1.5432."""
    val = val.strip().strip("'\"")
    # Remove standard uncertainty parenthesis: 5.4307(2) -> 5.4307
    val = re.sub(r"\(\d+\)", "", val)
    return val


def _parse_float(val: str, default: float = 0.0) -> float:
    cleaned = _clean_cif_value(val)
    try:
        return float(cleaned)
    except ValueError:
        return default


def _extract_symbol(raw_symbol: str) -> str:
    """Extract standard chemical element symbol from CIF atom label or type symbol.

    Examples:
        'Si1' -> 'Si', 'Fe2+' -> 'Fe', 'C_1' -> 'C', 'O1A' -> 'O'
    """
    raw = _clean_cif_value(raw_symbol)
    m = re.match(r"^([A-Z][a-z]?)", raw)
    if m:
        return m.group(1)
    return raw[:2].strip().capitalize()


def read_cif(filepath_or_content: Union[str, Path]) -> CrystalStructure:
    """Parse standard CIF file or CIF content string into a CrystalStructure."""
    content: str
    try:
        if "\n" not in str(filepath_or_content) and Path(filepath_or_content).is_file():
            content = Path(filepath_or_content).read_text(encoding="utf-8", errors="replace")
        else:
            content = str(filepath_or_content)
    except (OSError, ValueError):
        content = str(filepath_or_content)

    lines = content.splitlines()

    data_name = ""
    cell_lengths = {}
    cell_angles = {}
    atoms: list[Atom] = []

    # Simple tokenizer / line scanner
    i = 0
    n_lines = len(lines)

    while i < n_lines:
        line = lines[i].strip()
        if not line or line.startswith("#"):
            i += 1
            continue

        # Data header
        if line.lower().startswith("data_"):
            data_name = line[5:].strip()
            i += 1
            continue

        # Cell parameters
        if line.startswith("_cell_length_a"):
            parts = line.split()
            if len(parts) >= 2:
                cell_lengths["a"] = _parse_float(parts[1])
            i += 1
            continue
        if line.startswith("_cell_length_b"):
            parts = line.split()
            if len(parts) >= 2:
                cell_lengths["b"] = _parse_float(parts[1])
            i += 1
            continue
        if line.startswith("_cell_length_c"):
            parts = line.split()
            if len(parts) >= 2:
                cell_lengths["c"] = _parse_float(parts[1])
            i += 1
            continue
        if line.startswith("_cell_angle_alpha"):
            parts = line.split()
            if len(parts) >= 2:
                cell_angles["alpha"] = _parse_float(parts[1])
            i += 1
            continue
        if line.startswith("_cell_angle_beta"):
            parts = line.split()
            if len(parts) >= 2:
                cell_angles["beta"] = _parse_float(parts[1])
            i += 1
            continue
        if line.startswith("_cell_angle_gamma"):
            parts = line.split()
            if len(parts) >= 2:
                cell_angles["gamma"] = _parse_float(parts[1])
            i += 1
            continue

        # Loop block
        if line.lower() == "loop_":
            i += 1
            loop_headers = []
            while i < n_lines and lines[i].strip().startswith("_"):
                loop_headers.append(lines[i].strip())
                i += 1

            # Check if this loop is atom sites
            is_atom_loop = any(
                h.startswith("_atom_site_") for h in loop_headers
            )

            if is_atom_loop:
                # Find column indices for atom properties
                label_idx = None
                type_idx = None
                fract_x_idx = None
                fract_y_idx = None
                fract_z_idx = None
                cart_x_idx = None
                cart_y_idx = None
                cart_z_idx = None

                for idx, h in enumerate(loop_headers):
                    hl = h.lower()
                    if hl in ("_atom_site_label",):
                        label_idx = idx
                    elif hl in ("_atom_site_type_symbol",):
                        type_idx = idx
                    elif hl in ("_atom_site_fract_x",):
                        fract_x_idx = idx
                    elif hl in ("_atom_site_fract_y",):
                        fract_y_idx = idx
                    elif hl in ("_atom_site_fract_z",):
                        fract_z_idx = idx
                    elif hl in ("_atom_site_cartn_x",):
                        cart_x_idx = idx
                    elif hl in ("_atom_site_cartn_y",):
                        cart_y_idx = idx
                    elif hl in ("_atom_site_cartn_z",):
                        cart_z_idx = idx

                # Read loop records
                atom_idx = 0
                while i < n_lines:
                    record_line = lines[i].strip()
                    if not record_line or record_line.startswith("#"):
                        i += 1
                        continue
                    if record_line.lower() == "loop_" or record_line.startswith("_"):
                        # Next section started
                        break

                    parts = record_line.split()
                    if len(parts) < len(loop_headers):
                        # Multi-line record or incomplete line; skip or handle
                        i += 1
                        continue

                    # Determine element symbol
                    raw_sym = ""
                    if type_idx is not None and type_idx < len(parts):
                        raw_sym = parts[type_idx]
                    elif label_idx is not None and label_idx < len(parts):
                        raw_sym = parts[label_idx]

                    sym = _extract_symbol(raw_sym)
                    tag = parts[label_idx] if label_idx is not None else sym

                    fpos = None
                    pos = None

                    if fract_x_idx is not None and fract_y_idx is not None and fract_z_idx is not None:
                        fx = _parse_float(parts[fract_x_idx])
                        fy = _parse_float(parts[fract_y_idx])
                        fz = _parse_float(parts[fract_z_idx])
                        fpos = (fx, fy, fz)

                    if cart_x_idx is not None and cart_y_idx is not None and cart_z_idx is not None:
                        cx = _parse_float(parts[cart_x_idx])
                        cy = _parse_float(parts[cart_y_idx])
                        cz = _parse_float(parts[cart_z_idx])
                        pos = (cx, cy, cz)

                    atoms.append(
                        Atom(
                            index=atom_idx,
                            symbol=sym,
                            position=pos if pos is not None else (0.0, 0.0, 0.0),
                            fractional_position=fpos,
                            tag=tag,
                        )
                    )
                    atom_idx += 1
                    i += 1
                continue

        i += 1

    # Build Lattice
    lattice = None
    if "a" in cell_lengths and "b" in cell_lengths and "c" in cell_lengths:
        a = cell_lengths["a"]
        b = cell_lengths["b"]
        c = cell_lengths["c"]
        alpha = cell_angles.get("alpha", 90.0)
        beta = cell_angles.get("beta", 90.0)
        gamma = cell_angles.get("gamma", 90.0)
        lattice = Lattice.from_parameters(a, b, c, alpha, beta, gamma)

    structure = CrystalStructure(
        lattice=lattice,
        atoms=atoms,
        name=data_name,
    )
    return structure
