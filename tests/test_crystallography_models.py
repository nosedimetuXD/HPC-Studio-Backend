"""Unit tests for crystallography data models."""

import numpy as np
import pytest

from hpc_studio.crystallography.models import (
    Atom,
    CrystalStructure,
    ElementData,
    Lattice,
    get_element_data,
)


def test_element_data_cpk():
    """Verify chemical elements properties and CPK color attributes."""
    si = get_element_data("Si")
    assert si.symbol == "Si"
    assert si.atomic_number == 14
    assert round(si.atomic_mass, 2) == 28.09
    assert si.cpk_hex.startswith("#")
    assert len(si.cpk_rgb) == 3
    assert 0.0 <= si.cpk_rgb[0] <= 1.0
    assert 0.0 <= si.cpk_rgb[1] <= 1.0
    assert 0.0 <= si.cpk_rgb[2] <= 1.0

    c = get_element_data("C")
    assert c.atomic_number == 6
    assert c.covalent_radius == 0.76

    # Fallback element
    unknown = get_element_data("Xx")
    assert unknown.atomic_number == 0
    assert unknown.cpk_hex == "#FF1493"


def test_lattice_properties_and_transformations():
    """Verify Lattice constants, volume, and coordinate conversions."""
    # Cubic cell a = 5.0 Å
    lat = Lattice.cubic(5.0)
    assert pytest.approx(lat.a) == 5.0
    assert pytest.approx(lat.b) == 5.0
    assert pytest.approx(lat.c) == 5.0
    assert pytest.approx(lat.alpha) == 90.0
    assert pytest.approx(lat.beta) == 90.0
    assert pytest.approx(lat.gamma) == 90.0
    assert pytest.approx(lat.volume) == 125.0

    # Conversions
    cart = (2.5, 2.5, 2.5)
    fract = lat.cartesian_to_fractional(cart)
    assert pytest.approx(fract[0]) == 0.5
    assert pytest.approx(fract[1]) == 0.5
    assert pytest.approx(fract[2]) == 0.5

    cart_back = lat.fractional_to_cartesian(fract)
    assert pytest.approx(cart_back[0]) == 2.5
    assert pytest.approx(cart_back[1]) == 2.5
    assert pytest.approx(cart_back[2]) == 2.5

    # Non-orthogonal lattice from parameters
    lat_hex = Lattice.from_parameters(3.0, 3.0, 5.0, 90.0, 90.0, 120.0)
    assert pytest.approx(lat_hex.a) == 3.0
    assert pytest.approx(lat_hex.b) == 3.0
    assert pytest.approx(lat_hex.c) == 5.0
    assert pytest.approx(lat_hex.gamma) == 120.0
    expected_vol = 3.0 * 3.0 * np.sin(np.radians(120.0)) * 5.0
    assert pytest.approx(lat_hex.volume, rel=1e-4) == expected_vol


def test_crystal_structure_formula():
    """Test reduced stoichiometric formula computation."""
    atoms_nacl = [
        Atom(index=0, symbol="Na", position=(0.0, 0.0, 0.0)),
        Atom(index=1, symbol="Cl", position=(2.8, 2.8, 2.8)),
    ]
    struct_nacl = CrystalStructure(lattice=Lattice.cubic(5.64), atoms=atoms_nacl)
    assert struct_nacl.formula() == "ClNa" or "NaCl" in struct_nacl.formula()

    atoms_tio2 = [
        Atom(index=0, symbol="Ti", position=(0.0, 0.0, 0.0)),
        Atom(index=1, symbol="O", position=(1.0, 1.0, 0.0)),
        Atom(index=2, symbol="O", position=(2.0, 2.0, 0.0)),
    ]
    struct_tio2 = CrystalStructure(lattice=Lattice.cubic(4.5), atoms=atoms_tio2)
    assert struct_tio2.formula() == "O2Ti" or "TiO2" in struct_tio2.formula()


def test_distance_and_mic():
    """Test interatomic distance with Minimum Image Convention."""
    lat = Lattice.cubic(10.0)
    atoms = [
        Atom(index=0, symbol="H", position=(0.5, 0.0, 0.0), fractional_position=(0.05, 0.0, 0.0)),
        Atom(index=1, symbol="H", position=(9.5, 0.0, 0.0), fractional_position=(0.95, 0.0, 0.0)),
    ]
    struct = CrystalStructure(lattice=lat, atoms=atoms)
    # Direct Cartesian distance is 9.0 Å
    assert pytest.approx(struct.distance(0, 1, mic=False)) == 9.0
    # Minimum image convention distance across boundary is 1.0 Å
    assert pytest.approx(struct.distance(0, 1, mic=True)) == 1.0


def test_angle_and_dihedral():
    """Test bond angle and dihedral calculations."""
    # Water-like geometry in Cartesian
    # O at origin, H1 at (0, 1, 0), H2 at (1, 0, 0) -> angle = 90 deg
    atoms = [
        Atom(index=0, symbol="H", position=(0.0, 1.0, 0.0)),
        Atom(index=1, symbol="O", position=(0.0, 0.0, 0.0)),
        Atom(index=2, symbol="H", position=(1.0, 0.0, 0.0)),
    ]
    struct = CrystalStructure(lattice=None, atoms=atoms)
    assert pytest.approx(struct.angle(0, 1, 2)) == 90.0

    # Dihedral angle of cis / trans chain
    # 0 -> 1 -> 2 -> 3
    # 1=(0,0,0), 2=(1,0,0), 0=(0,1,0), 3=(1,1,0) -> planar cis (0 deg)
    atoms_dihed = [
        Atom(index=0, symbol="C", position=(0.0, 1.0, 0.0)),
        Atom(index=1, symbol="C", position=(0.0, 0.0, 0.0)),
        Atom(index=2, symbol="C", position=(1.0, 0.0, 0.0)),
        Atom(index=3, symbol="C", position=(1.0, 1.0, 0.0)),
    ]
    struct_dihed = CrystalStructure(lattice=None, atoms=atoms_dihed)
    assert pytest.approx(struct_dihed.dihedral(0, 1, 2, 3), abs=1e-3) == 0.0

    # trans (180 deg) with 3 at (1, -1, 0)
    atoms_dihed[3] = Atom(index=3, symbol="C", position=(1.0, -1.0, 0.0))
    struct_trans = CrystalStructure(lattice=None, atoms=atoms_dihed)
    assert pytest.approx(abs(struct_trans.dihedral(0, 1, 2, 3)), abs=1e-3) == 180.0


def test_bonds_calculation():
    """Test bond calculation respecting covalent radii."""
    # C-C single bond is ~1.54 Å; r_cov(C) = 0.76 => sum = 1.52 Å
    lat = Lattice.cubic(10.0)
    atoms = [
        Atom(index=0, symbol="C", position=(0.0, 0.0, 0.0)),
        Atom(index=1, symbol="C", position=(1.54, 0.0, 0.0)),
        Atom(index=2, symbol="C", position=(6.0, 0.0, 0.0)),  # Far away
    ]
    struct = CrystalStructure(lattice=lat, atoms=atoms)
    bonds = struct.calculate_bonds(tolerance=0.45)
    assert len(bonds) == 1
    assert bonds[0][0] == 0
    assert bonds[0][1] == 1
    assert pytest.approx(bonds[0][2], abs=0.01) == 1.54


def test_supercell_creation():
    """Test 2x2x2 supercell generation."""
    lat = Lattice.cubic(5.0)
    atoms = [
        Atom(index=0, symbol="Si", position=(0.0, 0.0, 0.0), fractional_position=(0.0, 0.0, 0.0)),
    ]
    struct = CrystalStructure(lattice=lat, atoms=atoms, name="Si")
    supercell = struct.create_supercell(2, 2, 2)

    assert len(supercell.atoms) == 8
    assert pytest.approx(supercell.lattice.a) == 10.0
    assert pytest.approx(supercell.lattice.b) == 10.0
    assert pytest.approx(supercell.lattice.c) == 10.0
    assert pytest.approx(supercell.lattice.volume) == 1000.0
