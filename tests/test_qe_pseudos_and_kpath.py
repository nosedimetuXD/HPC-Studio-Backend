"""Unit tests for Quantum ESPRESSO Pseudopotentials (SSSP / Pslibrary) and K-Path Band Structure generator."""

from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import pytest

from hpc_studio.crystallography.kpath import KPath
from hpc_studio.crystallography.models import Atom, CrystalStructure, Lattice
from hpc_studio.qe.models import ControlNamelist, KPointsCard, QEInput, SystemNamelist
from hpc_studio.qe.pseudos import (
    PseudoManager,
    PseudoMetadata,
    SSSPFamily,
    UPFParser,
)
import hpc_studio.crystallography.qe_models as crystal_qe


# ==============================================================================
# 1. UPF Parser Tests (UPF v1 and UPF v2)
# ==============================================================================

UPF_V1_SAMPLE = """\
<PP_HEADER>
   0                     Version Number
  Si                     Element
  US                     Ultrasoft pseudopotential
   T                     Nonlinear Core Correction
 SLA  PW   PBX  PBC      PBE  Exchange-Correlation functional
   4.00000000000         Z valence
  12.345678              Total energy
   0.000000    0.000000  Suggested cutoff for wfc and rho:  30.0   240.0
   2                     Number of Beta functions
   1   2                 L-values of Beta functions
<PP_MESH>
   size=850
</PP_MESH>
</PP_HEADER>
"""

UPF_V2_XML_SAMPLE = """\
<UPF version="2.0.1">
  <PP_HEADER
      generated="Generated using ONCVPSP code by D. R. Hamann"
      author="D. R. Hamann"
      date="150101"
      comment=""
      element="Fe"
      pseudo_type="NC"
      relativistic="scalar"
      is_ultrasoft="F"
      is_paw="F"
      is_coulomb="F"
      has_so="F"
      has_gipaw="F"
      core_correction="T"
      functional="PBE"
      z_valence="16.0"
      total_psenergy="-1.234567E+02"
      wfc_cutoff="65.0"
      rho_cutoff="260.0"
      mesh_size="1195"
      number_of_wfc="4"
      number_of_proj="8"/>
  <PP_MESH>
  </PP_MESH>
</UPF>
"""

UPF_V2_SEPARATE_TAGS_SAMPLE = """\
<UPF version="2.0.1">
  <PP_HEADER>
    Element: C
    Type: PAW
    DFT functional: PBE
    Z valence: 4.0
  </PP_HEADER>
  <PP_WFC_CUTOFF> 50.0 </PP_WFC_CUTOFF>
  <PP_RHO_CUTOFF> 400.0 </PP_RHO_CUTOFF>
  <PP_MESH size="920"/>
</UPF>
"""


def test_upf_parser_v1_header():
    """Test parsing UPF v1 synthetic file."""
    meta = UPFParser.parse_content(UPF_V1_SAMPLE, filename="Si.pbe-van.UPF")
    assert meta["element"] == "Si"
    assert meta["pseudo_type"] == "USPP"
    assert "PBE" in meta["functional"]
    assert meta["z_valence"] == 4.0
    assert meta["wfc_cutoff"] == 30.0
    assert meta["rho_cutoff"] == 240.0


def test_upf_parser_v2_xml_attributes():
    """Test parsing UPF v2 XML attribute header."""
    meta = UPFParser.parse_content(UPF_V2_XML_SAMPLE, filename="Fe_ONCV_PBE-1.0.upf")
    assert meta["element"] == "Fe"
    assert meta["pseudo_type"] == "NC"
    assert meta["functional"] == "PBE"
    assert meta["z_valence"] == 16.0
    assert meta["wfc_cutoff"] == 65.0
    assert meta["rho_cutoff"] == 260.0
    assert meta["mesh_size"] == 1195


def test_upf_parser_v2_separate_tags():
    """Test parsing UPF v2 with separate cutoff tags."""
    meta = UPFParser.parse_content(UPF_V2_SEPARATE_TAGS_SAMPLE, filename="C.pbe-paw.UPF")
    assert meta["element"] == "C"
    assert meta["pseudo_type"] == "PAW"
    assert meta["functional"] == "PBE"
    assert meta["z_valence"] == 4.0
    assert meta["wfc_cutoff"] == 50.0
    assert meta["rho_cutoff"] == 400.0
    assert meta["mesh_size"] == 920


def test_upf_parser_from_disk(tmp_path: Path):
    """Test parse_file reading directly from disk."""
    p = tmp_path / "O_pbe_v1.2.uspp.F.UPF"
    p.write_text(UPF_V1_SAMPLE.replace("Si", "O").replace("4.000", "6.000"))
    meta = UPFParser.parse_file(p)
    assert meta["element"] == "O"
    assert meta["z_valence"] == 6.0


# ==============================================================================
# 2. PseudoManager Catalog & Cutoff Queries
# ==============================================================================

def test_sssp_efficiency_catalog_lookups(tmp_path: Path):
    """Verify SSSP Efficiency cutoff lookups for common elements."""
    mgr = PseudoManager(cache_dir=tmp_path)

    # Silicon (Si)
    si_meta = mgr.get_pseudo_for_element("Si", SSSPFamily.SSSP_EFFICIENCY)
    assert si_meta is not None
    assert si_meta.element == "Si"
    assert si_meta.recommended_ecutwfc == 30.0
    assert si_meta.recommended_ecutrho == 240.0
    assert "Si" in si_meta.filename

    # Carbon (C)
    c_meta = mgr.get_pseudo_for_element("C", SSSPFamily.SSSP_EFFICIENCY)
    assert c_meta is not None
    assert c_meta.element == "C"
    assert c_meta.recommended_ecutwfc == 45.0
    assert c_meta.recommended_ecutrho == 360.0

    # Oxygen (O)
    o_meta = mgr.get_pseudo_for_element("O", SSSPFamily.SSSP_EFFICIENCY)
    assert o_meta is not None
    assert o_meta.element == "O"
    assert o_meta.recommended_ecutwfc == 50.0
    assert o_meta.recommended_ecutrho == 400.0

    # Iron (Fe)
    fe_meta = mgr.get_pseudo_for_element("Fe", SSSPFamily.SSSP_EFFICIENCY)
    assert fe_meta is not None
    assert fe_meta.element == "Fe"
    assert fe_meta.recommended_ecutwfc == 45.0
    assert fe_meta.recommended_ecutrho == 360.0


def test_sssp_precision_and_pslibrary_catalog_lookups(tmp_path: Path):
    """Verify SSSP Precision and Pslibrary cutoffs for high-accuracy runs."""
    mgr = PseudoManager(cache_dir=tmp_path)

    # Precision for Si
    si_prec = mgr.get_pseudo_for_element("Si", SSSPFamily.SSSP_PRECISION)
    assert si_prec is not None
    assert si_prec.recommended_ecutwfc == 40.0
    assert si_prec.recommended_ecutrho == 320.0

    # Precision for Fe
    fe_prec = mgr.get_pseudo_for_element("Fe", SSSPFamily.SSSP_PRECISION)
    assert fe_prec is not None
    assert fe_prec.recommended_ecutwfc == 60.0
    assert fe_prec.recommended_ecutrho == 480.0

    # Pslibrary PAW for Si
    si_paw = mgr.get_pseudo_for_element("Si", SSSPFamily.PSLIBRARY_PAW)
    assert si_paw is not None
    assert si_paw.pseudo_type == "PAW"


# ==============================================================================
# 3. Integrity Verification & Directory Scanning
# ==============================================================================

def test_sha256_integrity_calculation_and_verification(tmp_path: Path):
    """Test SHA256 integrity hashing and validation against expected digest."""
    mgr = PseudoManager(cache_dir=tmp_path)
    pseudo_file = tmp_path / "test_pseudo.UPF"
    content = b"Mock UPF content for SHA256 test"
    pseudo_file.write_bytes(content)

    expected_hash = hashlib.sha256(content).hexdigest()
    calc_hash = mgr.calculate_sha256(pseudo_file)
    assert calc_hash == expected_hash

    # Verification passes with correct hash
    assert mgr.verify_integrity(pseudo_file, expected_hash) is True
    # Verification fails with bad hash
    assert mgr.verify_integrity(pseudo_file, "bad_hash_12345") is False


def test_scan_local_directory(tmp_path: Path):
    """Test discovering and parsing .UPF files in any local folder."""
    mgr = PseudoManager(cache_dir=tmp_path)
    scan_dir = tmp_path / "custom_pseudos"
    scan_dir.mkdir()

    # Create two synthetic UPF files
    (scan_dir / "Si.pbe-van.UPF").write_text(UPF_V1_SAMPLE)
    (scan_dir / "Fe.pbe-nc.upf").write_text(UPF_V2_XML_SAMPLE)
    (scan_dir / "ignored.txt").write_text("not a pseudo")

    scanned = mgr.scan_local_directory(scan_dir)
    assert len(scanned) == 2

    elements = {s.element for s in scanned}
    assert "Si" in elements
    assert "Fe" in elements

    for meta in scanned:
        assert meta.sha256 != ""
        assert Path(meta.local_path).exists()


def test_download_pseudo_already_cached(tmp_path: Path):
    """Test download_pseudo returns local path immediately when file exists and matches hash."""
    mgr = PseudoManager(cache_dir=tmp_path)
    file_content = b"Sample file content for Si"
    digest = hashlib.sha256(file_content).hexdigest()

    meta = PseudoMetadata(
        element="Si",
        filename="Si_test.UPF",
        family=SSSPFamily.CUSTOM.value,
        functional="PBE",
        pseudo_type="NC",
        recommended_ecutwfc=30.0,
        recommended_ecutrho=240.0,
        sha256=digest,
        download_url="http://mock.example.com/Si_test.UPF",
    )

    # Pre-cache the file
    (tmp_path / "Si_test.UPF").write_bytes(file_content)

    path = mgr.download_pseudo(meta)
    assert Path(path).exists()
    assert mgr.is_pseudo_cached(meta) is True


# ==============================================================================
# 4. K-Path Generation Tests (SeeK-path / Hinuma convention)
# ==============================================================================

def test_kpath_fcc_silicon():
    """Verify FCC high-symmetry path (Si, diamond/fcc ibrav=2)."""
    # Path: GAMMA - X - W - K - GAMMA - L - U - W - X
    kpts, spec = KPath.generate_kpath(2, n_points_per_segment=15)
    labels = [s[1] for s in spec]
    assert labels == ["GAMMA", "X", "W", "K", "GAMMA", "L", "U", "W", "X"]

    # Check kpoint coordinates
    gamma = kpts[0]
    assert gamma[0] == 0.0 and gamma[1] == 0.0 and gamma[2] == 0.0
    assert gamma[3] == 15  # steps

    x_point = kpts[1]
    assert x_point[0] == 0.5 and x_point[1] == 0.0 and x_point[2] == 0.5


def test_kpath_bcc():
    """Verify BCC high-symmetry path (ibrav=3)."""
    # Path: GAMMA - H - P - GAMMA - N
    kpts, spec = KPath.generate_kpath(3, n_points_per_segment=20)
    labels = [s[1] for s in spec]
    assert labels == ["GAMMA", "H", "P", "GAMMA", "N"]
    assert kpts[1][4] == "H"
    assert kpts[1][0] == 0.5 and kpts[1][1] == -0.5 and kpts[1][2] == 0.5


def test_kpath_simple_cubic():
    """Verify Simple Cubic high-symmetry path (ibrav=1)."""
    # Path: GAMMA - X - M - GAMMA - R - X
    kpts, spec = KPath.generate_kpath(1, n_points_per_segment=10)
    labels = [s[1] for s in spec]
    assert labels == ["GAMMA", "X", "M", "GAMMA", "R", "X"]


def test_kpath_hexagonal():
    """Verify Hexagonal high-symmetry path (ibrav=4)."""
    # Path: GAMMA - M - K - GAMMA - A - L - H - A
    kpts, spec = KPath.generate_kpath(4, n_points_per_segment=25)
    labels = [s[1] for s in spec]
    assert labels == ["GAMMA", "M", "K", "GAMMA", "A", "L", "H", "A"]


def test_kpath_from_crystal_structure():
    """Test generating kpath automatically from a CrystalStructure object."""
    # Create simple cubic lattice
    lat = Lattice.cubic(5.43)
    struct = CrystalStructure(
        lattice=lat,
        atoms=[Atom(index=0, symbol="Si", position=(0.0, 0.0, 0.0))],
    )

    kpts, spec = KPath.generate_kpath(struct, n_points_per_segment=10)
    assert len(kpts) == 6
    assert spec[0][1] == "GAMMA"


# ==============================================================================
# 5. Ingestion of K-Path into QEInput (calculation='bands')
# ==============================================================================

def test_apply_kpath_to_qe_input_models():
    """Test injecting k-path into hpc_studio.qe.models.QEInput."""
    qe_in = QEInput(
        control=ControlNamelist(calculation="scf"),
        system=SystemNamelist(ibrav=2, a=5.43),
    )

    KPath.apply_to_qe_input(qe_in, n_points_per_segment=20)
    assert qe_in.control.calculation == "bands"
    assert qe_in.k_points.mode == "crystal_b"
    assert len(qe_in.k_points.kpoints) == 9  # FCC has 9 nodes

    # Serialize to text and check K_POINTS card
    text = qe_in.to_string()
    assert "calculation = 'bands'" in text
    assert "K_POINTS {crystal_b}" in text
    assert "9" in text  # number of kpoint vertices


def test_apply_kpath_to_crystallography_qe_input():
    """Test injecting k-path into hpc_studio.crystallography.qe_models.QEInput."""
    qe_in = crystal_qe.QEInput(calculation="scf", ibrav=2)

    KPath.apply_to_qe_input(qe_in, n_points_per_segment=15)
    assert qe_in.calculation == "bands"
    assert qe_in.kpoints_mode == "crystal_b"
    assert "K_POINTS (crystal_b)" in qe_in.kpoints_raw

    rendered = qe_in.to_string()
    assert "calculation = 'bands'" in rendered
    assert "K_POINTS (crystal_b)" in rendered
    assert "GAMMA" in rendered or "W" in rendered
