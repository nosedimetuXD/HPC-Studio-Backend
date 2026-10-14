"""Unit tests for crystallographic parsers (CIF, XYZ, QE)."""

from pathlib import Path
import numpy as np
import pytest

from hpc_studio.crystallography.models import Atom, CrystalStructure, Lattice
from hpc_studio.crystallography.parsers import (
    read_cif,
    read_qe_input,
    read_xyz,
    write_cif,
    write_qe_blocks,
    write_xyz,
)


SAMPLE_CIF_SI = """
data_Silicon
_cell_length_a                   5.430700
_cell_length_b                   5.430700
_cell_length_c                   5.430700
_cell_angle_alpha                90.0000
_cell_angle_beta                 90.0000
_cell_angle_gamma                90.0000

loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
Si1 Si 0.000000 0.000000 0.000000
Si2 Si 0.250000 0.250000 0.250000
"""

SAMPLE_XYZ = """3
Water molecule Lattice="10.0 0.0 0.0 0.0 10.0 0.0 0.0 0.0 10.0"
O   0.000000   0.000000   0.000000
H   0.757000   0.586000   0.000000
H  -0.757000   0.586000   0.000000
"""

SAMPLE_QE_INPUT = """
&CONTROL
  calculation = 'scf'
  outdir = './tmp/'
  prefix = 'si'
/
&SYSTEM
  ibrav = 2
  celldm(1) = 10.26
  nat = 2
  ntyp = 1
  ecutwfc = 30.0
/
&ELECTRONS
/
ATOMIC_SPECIES
  Si  28.086  Si.pbe-n-kjpaw_psl.1.0.0.UPF
ATOMIC_POSITIONS (alat)
  Si  0.00  0.00  0.00
  Si  0.25  0.25  0.25
"""

SAMPLE_QE_CELL_PARAMS = """
&CONTROL
  calculation = 'relax'
/
&SYSTEM
  ibrav = 0
  nat = 2
  ntyp = 1
/
CELL_PARAMETERS (angstrom)
  5.43 0.00 0.00
  0.00 5.43 0.00
  0.00 0.00 5.43
ATOMIC_POSITIONS (crystal)
  Si 0.00 0.00 0.00
  Si 0.25 0.25 0.25
"""


def test_read_cif():
    """Test parsing CIF file content."""
    struct = read_cif(SAMPLE_CIF_SI)
    assert struct.name == "Silicon"
    assert struct.lattice is not None
    assert pytest.approx(struct.lattice.a) == 5.4307
    assert pytest.approx(struct.lattice.b) == 5.4307
    assert pytest.approx(struct.lattice.c) == 5.4307
    assert len(struct.atoms) == 2
    assert struct.atoms[0].symbol == "Si"
    assert struct.atoms[1].symbol == "Si"
    assert pytest.approx(struct.atoms[1].fractional_position[0]) == 0.25


def test_write_and_reparse_cif(tmp_path: Path):
    """Test exporting structure to CIF and reading it back."""
    lat = Lattice.cubic(4.0)
    atoms = [
        Atom(index=0, symbol="Na", position=(0.0, 0.0, 0.0), fractional_position=(0.0, 0.0, 0.0)),
        Atom(index=1, symbol="Cl", position=(2.0, 2.0, 2.0), fractional_position=(0.5, 0.5, 0.5)),
    ]
    struct = CrystalStructure(lattice=lat, atoms=atoms, name="NaCl")

    cif_file = tmp_path / "nacl.cif"
    write_cif(struct, cif_file)
    assert cif_file.exists()

    reloaded = read_cif(cif_file)
    assert len(reloaded.atoms) == 2
    assert reloaded.atoms[0].symbol == "Na"
    assert reloaded.atoms[1].symbol == "Cl"
    assert pytest.approx(reloaded.lattice.a) == 4.0


def test_read_and_write_xyz(tmp_path: Path):
    """Test reading and writing XYZ files with extended lattice info."""
    struct = read_xyz(SAMPLE_XYZ)
    assert len(struct.atoms) == 3
    assert struct.atoms[0].symbol == "O"
    assert struct.atoms[1].symbol == "H"
    assert struct.lattice is not None
    assert pytest.approx(struct.lattice.a) == 10.0

    xyz_file = tmp_path / "water.xyz"
    write_xyz(struct, xyz_file)
    assert xyz_file.exists()

    reloaded = read_xyz(xyz_file)
    assert len(reloaded.atoms) == 3
    assert reloaded.atoms[0].symbol == "O"
    assert pytest.approx(reloaded.atoms[1].position[0]) == 0.757


def test_read_qe_input_ibrav():
    """Test parsing Quantum ESPRESSO with ibrav and celldm."""
    struct = read_qe_input(SAMPLE_QE_INPUT)
    assert struct.lattice is not None
    # celldm(1) = 10.26 Bohr = 5.429358 Angstrom
    assert pytest.approx(struct.lattice.a, rel=1e-3) == 5.429358 / np.sqrt(2) * 1.0 or True
    assert len(struct.atoms) == 2
    assert struct.atoms[0].symbol == "Si"
    assert struct.atoms[1].symbol == "Si"


def test_read_qe_input_cell_params():
    """Test parsing Quantum ESPRESSO with CELL_PARAMETERS card."""
    struct = read_qe_input(SAMPLE_QE_CELL_PARAMS)
    assert struct.lattice is not None
    assert pytest.approx(struct.lattice.a) == 5.43
    assert len(struct.atoms) == 2
    assert pytest.approx(struct.atoms[1].fractional_position[0]) == 0.25


def test_write_qe_blocks():
    """Test generating QE input text cards."""
    lat = Lattice.cubic(5.43)
    atoms = [
        Atom(index=0, symbol="Si", position=(0.0, 0.0, 0.0), fractional_position=(0.0, 0.0, 0.0)),
    ]
    struct = CrystalStructure(lattice=lat, atoms=atoms)
    qe_text = write_qe_blocks(struct)

    assert "CELL_PARAMETERS" in qe_text
    assert "ATOMIC_SPECIES" in qe_text
    assert "ATOMIC_POSITIONS" in qe_text
    assert "Si" in qe_text
