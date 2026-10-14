"""XYZ file parser and writer (including extended XYZ format)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Union

import numpy as np

from hpc_studio.crystallography.models import Atom, CrystalStructure, Lattice


def read_xyz(filepath_or_content: Union[str, Path]) -> CrystalStructure:
    """Parse standard or extended XYZ format.

    Extended XYZ comment lines may contain:
    Lattice="ax ay az bx by bz cx cy cz" Properties=species:S:1:pos:R:3
    """
    content: str
    try:
        if "\n" not in str(filepath_or_content) and Path(filepath_or_content).is_file():
            content = Path(filepath_or_content).read_text(encoding="utf-8", errors="replace")
        else:
            content = str(filepath_or_content)
    except (OSError, ValueError):
        content = str(filepath_or_content)

    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if not lines:
        return CrystalStructure(lattice=None, atoms=[])

    # First line: atom count
    try:
        natoms = int(lines[0].split()[0])
        comment_line = lines[1] if len(lines) > 1 else ""
        atom_lines = lines[2 : 2 + natoms]
    except ValueError:
        # Malformed header; try parsing all lines as atom lines
        natoms = len(lines)
        comment_line = ""
        atom_lines = lines

    # Check for extended XYZ lattice parameter in comment
    lattice = None
    lat_match = re.search(r'Lattice="([^"]+)"', comment_line)
    if lat_match:
        lat_vals = [float(x) for x in lat_match.group(1).split()]
        if len(lat_vals) == 9:
            mat = np.array(lat_vals).reshape((3, 3))
            lattice = Lattice(mat)

    atoms: list[Atom] = []
    for idx, line in enumerate(atom_lines):
        parts = line.split()
        if len(parts) >= 4:
            sym = parts[0].strip().capitalize()
            try:
                x = float(parts[1])
                y = float(parts[2])
                z = float(parts[3])
                atoms.append(
                    Atom(
                        index=idx,
                        symbol=sym,
                        position=(x, y, z),
                    )
                )
            except ValueError:
                continue

    name = comment_line.strip() if comment_line else "XYZ Structure"
    # Clean extended XYZ tags from name if any
    if 'Lattice="' in name:
        name = re.sub(r'Lattice="[^"]*"', '', name).strip()

    return CrystalStructure(
        lattice=lattice,
        atoms=atoms,
        name=name,
    )


def write_xyz(structure: CrystalStructure, filepath_or_buffer=None) -> str:
    """Write CrystalStructure to standard or extended XYZ format string."""
    lines = []
    lines.append(str(len(structure.atoms)))

    # Comment line with optional Lattice
    if structure.lattice is not None:
        flat_lat = " ".join(f"{val:.8f}" for val in structure.lattice.matrix.flatten())
        comment = f'Lattice="{flat_lat}" Properties=species:S:1:pos:R:3'
        if structure.name:
            comment += f' name="{structure.name}"'
    else:
        comment = structure.name if structure.name else "Created by HPC Studio"

    lines.append(comment)

    for atom in structure.atoms:
        x, y, z = atom.position
        lines.append(f"{atom.symbol:<3} {x:15.8f} {y:15.8f} {z:15.8f}")

    content = "\n".join(lines) + "\n"

    if filepath_or_buffer is not None:
        if isinstance(filepath_or_buffer, (str, Path)):
            Path(filepath_or_buffer).write_text(content, encoding="utf-8")
        else:
            filepath_or_buffer.write(content)

    return content
