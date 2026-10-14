"""Unit tests for Quantum ESPRESSO Input Engine, AST Parser and Semantic Validator."""

from __future__ import annotations

import numpy as np
import pytest

from hpc_studio.crystallography.models import Atom, CrystalStructure, Lattice
from hpc_studio.qe import (
    AtomicPositionsCard,
    AtomicSpeciesCard,
    CellNamelist,
    CellParametersCard,
    ControlNamelist,
    ElectronsNamelist,
    IonsNamelist,
    KPointsCard,
    PositionItem,
    QEInput,
    QEValidator,
    SpeciesItem,
    SystemNamelist,
    ValidationError,
    parse_qe_input,
)


class TestQESerializationAndParsing:
    """Test suite for to_string() serialization and parse_qe_input() AST parsing."""

    def test_scf_roundtrip(self):
        """Test SCF calculation input serialization and parsing."""
        qe_in = QEInput(
            control=ControlNamelist(
                calculation="scf",
                title="Silicon Diamond SCF",
                prefix="si_scf",
                outdir="./scratch",
                pseudo_dir="./pseudo",
            ),
            system=SystemNamelist(
                ibrav=2,
                celldm={1: 10.26},
                nat=2,
                ntyp=1,
                ecutwfc=35.0,
                ecutrho=140.0,
                occupations="fixed",
            ),
            electrons=ElectronsNamelist(
                conv_thr=1e-8,
                mixing_beta=0.7,
                diagonalization="david",
            ),
            atomic_species=AtomicSpeciesCard(
                species=[SpeciesItem(symbol="Si", mass=28.0855, pseudo_file="Si.pbe-n-kjpaw_psl.1.0.0.UPF")]
            ),
            atomic_positions=AtomicPositionsCard(
                mode="alat",
                positions=[
                    PositionItem(symbol="Si", x=0.0, y=0.0, z=0.0),
                    PositionItem(symbol="Si", x=0.25, y=0.25, z=0.25),
                ],
            ),
            k_points=KPointsCard(
                mode="automatic",
                grid=(8, 8, 8),
                shift=(1, 1, 1),
            ),
        )

        text = qe_in.to_string()
        assert "&CONTROL" in text
        assert "calculation = 'scf'" in text
        assert "&SYSTEM" in text
        assert "ibrav = 2" in text
        assert "celldm(1) = 10.26" in text
        assert "&ELECTRONS" in text
        assert "conv_thr = 1.0e-8" in text or "1.0e-8" in text or "1e-8" in text
        assert "ATOMIC_SPECIES" in text
        assert "Si.pbe-n-kjpaw_psl.1.0.0.UPF" in text
        assert "ATOMIC_POSITIONS {alat}" in text
        assert "K_POINTS {automatic}" in text

        # Parse back
        parsed = parse_qe_input(text)
        assert parsed.control.calculation == "scf"
        assert parsed.control.prefix == "si_scf"
        assert parsed.system.ibrav == 2
        assert parsed.system.celldm[1] == pytest.approx(10.26)
        assert parsed.system.nat == 2
        assert parsed.system.ntyp == 1
        assert parsed.system.ecutwfc == pytest.approx(35.0)
        assert parsed.system.ecutrho == pytest.approx(140.0)
        assert parsed.electrons.conv_thr == pytest.approx(1e-8)
        assert len(parsed.atomic_species.species) == 1
        assert parsed.atomic_species.species[0].symbol == "Si"
        assert len(parsed.atomic_positions.positions) == 2
        assert parsed.atomic_positions.mode == "alat"
        assert parsed.k_points.grid == (8, 8, 8)
        assert parsed.k_points.shift == (1, 1, 1)

    def test_relax_roundtrip(self):
        """Test relax calculation with &IONS and selective dynamics if_pos constraints."""
        qe_in = QEInput(
            control=ControlNamelist(
                calculation="relax",
                prefix="si_slab",
                tprnfor=True,
                forc_conv_thr=1e-3,
            ),
            system=SystemNamelist(
                ibrav=0,
                nat=2,
                ntyp=1,
                ecutwfc=40.0,
            ),
            electrons=ElectronsNamelist(conv_thr=1e-7),
            ions=IonsNamelist(
                ion_dynamics="bfgs",
                pot_extrapolation="atomic",
            ),
            atomic_species=AtomicSpeciesCard(
                species=[SpeciesItem(symbol="Si", mass=28.0855, pseudo_file="Si.upf")]
            ),
            atomic_positions=AtomicPositionsCard(
                mode="angstrom",
                positions=[
                    PositionItem(symbol="Si", x=0.0, y=0.0, z=0.0, if_pos=(0, 0, 0)),
                    PositionItem(symbol="Si", x=1.35, y=1.35, z=1.35, if_pos=(1, 1, 1)),
                ],
            ),
            k_points=KPointsCard(mode="automatic", grid=(4, 4, 1), shift=(0, 0, 0)),
            cell_parameters=CellParametersCard(
                mode="angstrom",
                matrix=[
                    [5.43, 0.0, 0.0],
                    [0.0, 5.43, 0.0],
                    [0.0, 0.0, 20.0],
                ],
            ),
        )

        text = qe_in.to_string()
        assert "&IONS" in text
        assert "ion_dynamics = 'bfgs'" in text
        assert "CELL_PARAMETERS {angstrom}" in text

        parsed = parse_qe_input(text)
        assert parsed.control.calculation == "relax"
        assert parsed.control.tprnfor is True
        assert parsed.ions is not None
        assert parsed.ions.ion_dynamics == "bfgs"
        assert parsed.atomic_positions.positions[0].if_pos == (0, 0, 0)
        assert parsed.atomic_positions.positions[1].if_pos == (1, 1, 1)
        assert parsed.cell_parameters is not None
        assert parsed.cell_parameters.matrix[0][0] == pytest.approx(5.43)
        assert parsed.cell_parameters.matrix[2][2] == pytest.approx(20.0)

    def test_vc_relax_roundtrip(self):
        """Test vc-relax calculation with &IONS and &CELL namelists."""
        qe_in = QEInput(
            control=ControlNamelist(
                calculation="vc-relax",
                prefix="fe_bcc",
                tprnfor=True,
                tstress=True,
            ),
            system=SystemNamelist(
                ibrav=0,
                nat=1,
                ntyp=1,
                ecutwfc=50.0,
                occupations="smearing",
                smearing="marzari-vanderbilt",
                degauss=0.02,
                nspin=2,
                starting_magnetization={"1": 0.6},
            ),
            electrons=ElectronsNamelist(conv_thr=1e-8),
            ions=IonsNamelist(ion_dynamics="bfgs"),
            cell=CellNamelist(
                cell_dynamics="bfgs",
                press=0.0,
                cell_factor=2.0,
            ),
            atomic_species=AtomicSpeciesCard(
                species=[SpeciesItem(symbol="Fe", mass=55.845, pseudo_file="Fe.pbe.UPF")]
            ),
            atomic_positions=AtomicPositionsCard(
                mode="angstrom",
                positions=[PositionItem(symbol="Fe", x=0.0, y=0.0, z=0.0)],
            ),
            k_points=KPointsCard(mode="automatic", grid=(10, 10, 10), shift=(1, 1, 1)),
            cell_parameters=CellParametersCard(
                mode="angstrom",
                matrix=[[2.87, 0.0, 0.0], [0.0, 2.87, 0.0], [0.0, 0.0, 2.87]],
            ),
        )

        text = qe_in.to_string()
        assert "&IONS" in text
        assert "&CELL" in text
        assert "cell_dynamics = 'bfgs'" in text
        assert "cell_factor = 2" in text or "cell_factor = 2.0" in text

        parsed = parse_qe_input(text)
        assert parsed.control.calculation == "vc-relax"
        assert parsed.ions is not None
        assert parsed.cell is not None
        assert parsed.cell.cell_dynamics == "bfgs"
        assert parsed.cell.cell_factor == pytest.approx(2.0)
        assert parsed.system.nspin == 2
        assert parsed.system.occupations == "smearing"
        assert parsed.system.degauss == pytest.approx(0.02)
        assert parsed.system.starting_magnetization.get("1") == pytest.approx(0.6)

    def test_bands_roundtrip(self):
        """Test bands calculation with explicit k-points path in crystal_b mode."""
        kpts = [
            (0.0, 0.0, 0.0, 20.0),      # Gamma to X
            (0.5, 0.0, 0.5, 20.0),      # X to W
            (0.5, 0.25, 0.75, 20.0),    # W to K
            (0.375, 0.375, 0.75, 20.0), # K to Gamma
            (0.0, 0.0, 0.0, 1.0),
        ]
        qe_in = QEInput(
            control=ControlNamelist(
                calculation="bands",
                prefix="si_bands",
            ),
            system=SystemNamelist(
                ibrav=2,
                celldm={1: 10.26},
                nat=2,
                ntyp=1,
                ecutwfc=30.0,
            ),
            electrons=ElectronsNamelist(conv_thr=1e-8),
            atomic_species=AtomicSpeciesCard(
                species=[SpeciesItem(symbol="Si", mass=28.0855, pseudo_file="Si.UPF")]
            ),
            atomic_positions=AtomicPositionsCard(
                mode="crystal",
                positions=[
                    PositionItem(symbol="Si", x=0.0, y=0.0, z=0.0),
                    PositionItem(symbol="Si", x=0.25, y=0.25, z=0.25),
                ],
            ),
            k_points=KPointsCard(
                mode="crystal_b",
                kpoints=kpts,
            ),
        )

        text = qe_in.to_string()
        assert "K_POINTS {crystal_b}" in text
        assert "5" in text  # 5 k-points

        parsed = parse_qe_input(text)
        assert parsed.control.calculation == "bands"
        assert parsed.k_points.mode == "crystal_b"
        assert len(parsed.k_points.kpoints) == 5
        assert parsed.k_points.kpoints[0][0] == pytest.approx(0.0)
        assert parsed.k_points.kpoints[1][0] == pytest.approx(0.5)

    def test_parser_tolerance_and_quirks(self):
        """Test parser tolerance against Fortran quirks, comments, casing, and formats."""
        qe_raw = """
        ! This is a comment at the top
        # Another style of comment
        &control
          CALCULATION = 'scf',
          restart_mode = "from_scratch" ! inline comment
          PREFIX = 'test_run',
          verbosity = 'high'
        /
        &system
          ibrav = 0, nat = 2, ntyp = 1,
          ecutwfc = 3.50D+01, ecutrho = 1.40d+02,
          LDA_PLUS_U = .TRUE.,
          celldm(1) = 10.260
        /
        &electrons
          conv_thr = 1.0d-8,
          mixing_beta = 0.5D0
        /
        ATOMIC_SPECIES
          Si   28.0855   Si.pbe.UPF
        ATOMIC_POSITIONS (crystal)
          Si   0.0000  0.0000  0.0000   0 0 0
          Si   0.2500  0.2500  0.2500   ! second atom
        K_POINTS {automatic}
          6 6 6   1 1 1
        CELL_PARAMETERS bohr
          10.26 0.00 0.00
          0.00 10.26 0.00
          0.00 0.00 10.26
        """

        parsed = parse_qe_input(qe_raw)
        assert parsed.control.calculation == "scf"
        assert parsed.control.restart_mode == "from_scratch"
        assert parsed.control.prefix == "test_run"
        assert parsed.control.verbosity == "high"

        assert parsed.system.ibrav == 0
        assert parsed.system.nat == 2
        assert parsed.system.ntyp == 1
        assert parsed.system.ecutwfc == pytest.approx(35.0)
        assert parsed.system.ecutrho == pytest.approx(140.0)
        assert parsed.system.lda_plus_u is True
        assert parsed.system.celldm[1] == pytest.approx(10.26)

        assert parsed.electrons.conv_thr == pytest.approx(1e-8)
        assert parsed.electrons.mixing_beta == pytest.approx(0.5)

        assert len(parsed.atomic_positions.positions) == 2
        assert parsed.atomic_positions.mode == "crystal"
        assert parsed.atomic_positions.positions[0].if_pos == (0, 0, 0)
        assert parsed.atomic_positions.positions[1].if_pos == (1, 1, 1)

        assert parsed.cell_parameters is not None
        assert parsed.cell_parameters.mode == "bohr"
        assert parsed.cell_parameters.matrix[0][0] == pytest.approx(10.26)


class TestQECrystalStructureConversion:
    """Test suite for bidirectional conversion with CrystalStructure."""

    def test_from_crystal_structure_scf(self):
        """Test generating QEInput from CrystalStructure for an SCF run."""
        lattice = Lattice.cubic(5.43)
        atoms = [
            Atom(index=0, symbol="Si", position=(0.0, 0.0, 0.0)),
            Atom(index=1, symbol="Si", position=(1.3575, 1.3575, 1.3575)),
        ]
        struct = CrystalStructure(lattice=lattice, atoms=atoms, name="Silicon")

        qe_in = QEInput.from_crystal_structure(struct, calculation="scf")

        assert qe_in.control.calculation == "scf"
        assert qe_in.control.prefix == "silicon"
        assert qe_in.system.ibrav == 0
        assert qe_in.system.nat == 2
        assert qe_in.system.ntyp == 1
        assert len(qe_in.atomic_species.species) == 1
        assert qe_in.atomic_species.species[0].symbol == "Si"
        assert qe_in.atomic_species.species[0].mass == pytest.approx(28.085, rel=1e-2)
        assert qe_in.cell_parameters is not None
        assert qe_in.cell_parameters.matrix[0][0] == pytest.approx(5.43)
        assert qe_in.ions is None
        assert qe_in.cell is None

    def test_from_crystal_structure_relax_and_vc_relax(self):
        """Test generating QEInput for relax and vc-relax calculations."""
        lattice = Lattice.cubic(3.8)
        atoms = [Atom(index=0, symbol="Al", position=(0.0, 0.0, 0.0))]
        struct = CrystalStructure(lattice=lattice, atoms=atoms, name="Aluminum")

        # relax
        qe_relax = QEInput.from_crystal_structure(struct, calculation="relax")
        assert qe_relax.control.calculation == "relax"
        assert qe_relax.control.tprnfor is True
        assert qe_relax.ions is not None
        assert qe_relax.cell is None

        # vc-relax
        qe_vcrelax = QEInput.from_crystal_structure(struct, calculation="vc-relax")
        assert qe_vcrelax.control.calculation == "vc-relax"
        assert qe_vcrelax.control.tprnfor is True
        assert qe_vcrelax.control.tstress is True
        assert qe_vcrelax.ions is not None
        assert qe_vcrelax.cell is not None

    def test_to_crystal_structure_with_cell_parameters(self):
        """Test converting QEInput back to CrystalStructure using CELL_PARAMETERS card."""
        qe_in = QEInput(
            control=ControlNamelist(prefix="graphene"),
            system=SystemNamelist(ibrav=0, nat=2, ntyp=1),
            atomic_species=AtomicSpeciesCard(species=[SpeciesItem("C", 12.011, "C.upf")]),
            atomic_positions=AtomicPositionsCard(
                mode="angstrom",
                positions=[
                    PositionItem("C", 0.0, 0.0, 0.0),
                    PositionItem("C", 1.42, 0.0, 0.0),
                ],
            ),
            cell_parameters=CellParametersCard(
                mode="angstrom",
                matrix=[
                    [2.46, 0.0, 0.0],
                    [1.23, 2.13, 0.0],
                    [0.0, 0.0, 15.0],
                ],
            ),
        )

        struct = qe_in.to_crystal_structure()
        assert struct.lattice is not None
        assert struct.lattice.a == pytest.approx(2.46)
        assert len(struct.atoms) == 2
        assert struct.atoms[0].symbol == "C"
        assert struct.atoms[1].position[0] == pytest.approx(1.42)
        assert struct.name == "graphene"

    def test_to_crystal_structure_with_ibrav(self):
        """Test converting QEInput with ibrav=1 (simple cubic) and ibrav=2 (fcc)."""
        # Simple cubic with a in Angstrom
        qe_sc = QEInput(
            system=SystemNamelist(ibrav=1, a=4.0, nat=1, ntyp=1),
            atomic_species=AtomicSpeciesCard(species=[SpeciesItem("Po", 209.0, "Po.upf")]),
            atomic_positions=AtomicPositionsCard(
                mode="alat",
                positions=[PositionItem("Po", 0.0, 0.0, 0.0)],
            ),
        )
        struct_sc = qe_sc.to_crystal_structure()
        assert struct_sc.lattice is not None
        assert struct_sc.lattice.a == pytest.approx(4.0)
        assert struct_sc.lattice.b == pytest.approx(4.0)
        assert struct_sc.lattice.c == pytest.approx(4.0)

        # FCC with celldm(1) in Bohr
        bohr_to_ang = 0.529177210903
        alat_bohr = 10.26
        qe_fcc = QEInput(
            system=SystemNamelist(ibrav=2, celldm={1: alat_bohr}, nat=1, ntyp=1),
            atomic_species=AtomicSpeciesCard(species=[SpeciesItem("Si", 28.08, "Si.upf")]),
            atomic_positions=AtomicPositionsCard(
                mode="crystal",
                positions=[PositionItem("Si", 0.0, 0.0, 0.0)],
            ),
        )
        struct_fcc = qe_fcc.to_crystal_structure()
        assert struct_fcc.lattice is not None
        expected_alat = alat_bohr * bohr_to_ang
        assert struct_fcc.lattice.a == pytest.approx(expected_alat / np.sqrt(2.0))


class TestQESemanticValidator:
    """Test suite for QEValidator and semantic consistency rules."""

    def test_valid_input_passes(self):
        """A properly formatted input deck should yield zero validation errors."""
        qe_in = QEInput(
            control=ControlNamelist(calculation="scf"),
            system=SystemNamelist(
                ibrav=1,
                a=5.0,
                nat=1,
                ntyp=1,
                ecutwfc=30.0,
                ecutrho=120.0,
                occupations="fixed",
            ),
            electrons=ElectronsNamelist(),
            atomic_species=AtomicSpeciesCard(species=[SpeciesItem("Si", 28.08, "Si.upf")]),
            atomic_positions=AtomicPositionsCard(
                mode="angstrom",
                positions=[PositionItem("Si", 0.0, 0.0, 0.0)],
            ),
        )

        errors = QEValidator.validate(qe_in)
        assert len([e for e in errors if e.is_error()]) == 0

    def test_nat_mismatch(self):
        """nat must match the actual count of position items."""
        qe_in = QEInput(
            system=SystemNamelist(ibrav=1, a=5.0, nat=3, ntyp=1),
            atomic_species=AtomicSpeciesCard(species=[SpeciesItem("Si", 28.08, "Si.upf")]),
            atomic_positions=AtomicPositionsCard(
                positions=[PositionItem("Si", 0.0, 0.0, 0.0)],  # only 1 position
            ),
        )
        errors = QEValidator.validate(qe_in)
        nat_errors = [e for e in errors if e.parameter == "nat" and e.is_error()]
        assert len(nat_errors) == 1
        assert "nat=3" in nat_errors[0].message

    def test_ntyp_mismatch(self):
        """ntyp must match the number of atomic species declared."""
        qe_in = QEInput(
            system=SystemNamelist(ibrav=1, a=5.0, nat=1, ntyp=2),
            atomic_species=AtomicSpeciesCard(
                species=[SpeciesItem("Si", 28.08, "Si.upf")]  # only 1 species
            ),
            atomic_positions=AtomicPositionsCard(positions=[PositionItem("Si", 0.0, 0.0, 0.0)]),
        )
        errors = QEValidator.validate(qe_in)
        ntyp_errors = [e for e in errors if e.parameter == "ntyp" and e.is_error()]
        assert len(ntyp_errors) == 1
        assert "ntyp=2" in ntyp_errors[0].message

    def test_undeclared_species_in_positions(self):
        """All symbols in ATOMIC_POSITIONS must be present in ATOMIC_SPECIES."""
        qe_in = QEInput(
            system=SystemNamelist(ibrav=1, a=5.0, nat=2, ntyp=1),
            atomic_species=AtomicSpeciesCard(species=[SpeciesItem("Si", 28.08, "Si.upf")]),
            atomic_positions=AtomicPositionsCard(
                positions=[
                    PositionItem("Si", 0.0, 0.0, 0.0),
                    PositionItem("Fe", 1.0, 1.0, 1.0),  # Fe is not in species!
                ]
            ),
        )
        errors = QEValidator.validate(qe_in)
        pos_errors = [e for e in errors if e.parameter == "atomic_positions" and e.is_error()]
        assert len(pos_errors) == 1
        assert "Fe" in pos_errors[0].message

    def test_ecutrho_low_warning(self):
        """If ecutrho < 4 * ecutwfc, a warning must be issued."""
        qe_in = QEInput(
            system=SystemNamelist(
                ibrav=1,
                a=5.0,
                nat=1,
                ntyp=1,
                ecutwfc=30.0,
                ecutrho=90.0,  # < 4 * 30 = 120
            ),
            atomic_species=AtomicSpeciesCard(species=[SpeciesItem("Si", 28.08, "Si.upf")]),
            atomic_positions=AtomicPositionsCard(positions=[PositionItem("Si", 0.0, 0.0, 0.0)]),
        )
        errors = QEValidator.validate(qe_in)
        rho_warns = [e for e in errors if e.parameter == "ecutrho" and e.is_warning()]
        assert len(rho_warns) == 1
        assert "ecutrho (90.0 Ry) is less than 4 * ecutwfc" in rho_warns[0].message

    def test_smearing_degauss_zero_warning(self):
        """If occupations is smearing, degauss == 0.0 must trigger a warning."""
        qe_in = QEInput(
            system=SystemNamelist(
                ibrav=1,
                a=5.0,
                nat=1,
                ntyp=1,
                occupations="smearing",
                degauss=0.0,
            ),
            atomic_species=AtomicSpeciesCard(species=[SpeciesItem("Si", 28.08, "Si.upf")]),
            atomic_positions=AtomicPositionsCard(positions=[PositionItem("Si", 0.0, 0.0, 0.0)]),
        )
        errors = QEValidator.validate(qe_in)
        degauss_warns = [e for e in errors if e.parameter == "degauss" and e.is_warning()]
        assert len(degauss_warns) == 1
        assert "degauss is 0.0" in degauss_warns[0].message

    def test_relax_requires_ions_namelist(self):
        """calculation='relax' requires &IONS namelist."""
        qe_in = QEInput(
            control=ControlNamelist(calculation="relax"),
            system=SystemNamelist(ibrav=1, a=5.0, nat=1, ntyp=1),
            atomic_species=AtomicSpeciesCard(species=[SpeciesItem("Si", 28.08, "Si.upf")]),
            atomic_positions=AtomicPositionsCard(positions=[PositionItem("Si", 0.0, 0.0, 0.0)]),
            ions=None,
        )
        errors = QEValidator.validate(qe_in)
        ion_errors = [e for e in errors if e.parameter == "ions" and e.is_error()]
        assert len(ion_errors) == 1
        assert "requires &IONS namelist" in ion_errors[0].message

    def test_vc_relax_requires_ions_and_warns_cell(self):
        """calculation='vc-relax' requires &IONS and warns if &CELL missing."""
        qe_in = QEInput(
            control=ControlNamelist(calculation="vc-relax"),
            system=SystemNamelist(ibrav=1, a=5.0, nat=1, ntyp=1),
            atomic_species=AtomicSpeciesCard(species=[SpeciesItem("Si", 28.08, "Si.upf")]),
            atomic_positions=AtomicPositionsCard(positions=[PositionItem("Si", 0.0, 0.0, 0.0)]),
            ions=None,
            cell=None,
        )
        errors = QEValidator.validate(qe_in)
        assert any(e.parameter == "ions" and e.is_error() for e in errors)
        assert any(e.parameter == "cell" and e.is_warning() for e in errors)

    def test_ibrav_0_requires_cell_parameters(self):
        """ibrav=0 requires CELL_PARAMETERS card with 3 lattice vectors."""
        qe_in = QEInput(
            system=SystemNamelist(ibrav=0, nat=1, ntyp=1),
            atomic_species=AtomicSpeciesCard(species=[SpeciesItem("Si", 28.08, "Si.upf")]),
            atomic_positions=AtomicPositionsCard(positions=[PositionItem("Si", 0.0, 0.0, 0.0)]),
            cell_parameters=None,
        )
        errors = QEValidator.validate(qe_in)
        cell_errors = [e for e in errors if e.parameter == "cell_parameters" and e.is_error()]
        assert len(cell_errors) == 1
        assert "ibrav=0 requires CELL_PARAMETERS card" in cell_errors[0].message
