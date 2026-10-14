"""Unit tests for Quantum ESPRESSO output parser and DFT results models."""

import pytest
from pathlib import Path

from hpc_studio.qe.output import (
    BandStructureData,
    ConvergenceStatus,
    IonicStep,
    QEOutputParser,
    QEOutputResult,
    SCFIteration,
)


SAMPLE_SCF_OUTPUT = """
     Program PWSCF v.7.2 starts on 11Oct2026 at 10:00:00

     This run was submitted to host cluster-node01
     Title: Silicon Bulk SCF Calculation
     calculation = 'scf'

     bravais-lattice index     =            2
     lattice parameter (alat)  =      10.2600  a.u.
     unit-cell volume          =     269.9579 (a.u.)^3
     number of atoms/cell      =            2
     number of atomic types    =            1
     number of electrons       =         8.00
     number of Kohn-Sham states=            8
     kinetic-energy cutoff     =      30.0000  Ry
     charge-density cutoff     =     120.0000  Ry
     convergence threshold     =      1.0E-08

     celldm(1)=  10.260000  celldm(2)=   0.000000  celldm(3)=   0.000000
     celldm(4)=   0.000000  celldm(5)=   0.000000  celldm(6)=   0.000000

     crystal axes: (cart. coord. in units of alat)
               a(1) = (  -0.500000   0.000000   0.500000 )
               a(2) = (   0.000000   0.500000   0.500000 )
               a(3) = (  -0.500000   0.500000   0.000000 )

     Cartesian axes

     site n.     atom                  positions (alat units)
         1           Si  tau(   1) = (   0.0000000   0.0000000   0.0000000  )
         2           Si  tau(   2) = (   0.2500000   0.2500000   0.2500000  )

     number of k points=     8

     Self-consistent Calculation

     iteration #   1     ecut=    30.00 Ry     beta= 0.70
     Davidson diagonalization with overlap
     ethr =  1.00E-02,  avg # of iterations =  2.0

     total cpu time spent up to now is      0.2 secs

     total energy              =     -15.79051870 Ry
     Harris-Foulkes estimate   =     -15.84512340 Ry
     estimated scf accuracy    <       0.06541200 Ry

     iteration #   2     ecut=    30.00 Ry     beta= 0.70
     Davidson diagonalization with overlap
     ethr =  8.18E-04,  avg # of iterations =  1.0

     total cpu time spent up to now is      0.4 secs

     total energy              =     -15.84501230 Ry
     Harris-Foulkes estimate   =     -15.84501890 Ry
     estimated scf accuracy    <       0.00012500 Ry

     iteration #   3     ecut=    30.00 Ry     beta= 0.70
     Davidson diagonalization with overlap
     ethr =  1.56E-06,  avg # of iterations =  1.0

     total cpu time spent up to now is      0.6 secs

     End of self-consistent calculation

          k = 0.0000 0.0000 0.0000 (   331 PWs)   bands (ev):

    -5.6033   6.3541   6.3541   6.3541   8.8267   8.8267   8.8267  10.2355

     highest occupied level (ev):     6.3541

!    total energy              =     -15.84501892 Ry
     Harris-Foulkes estimate   =     -15.84501892 Ry
     estimated scf accuracy    <          1.2E-09 Ry

     Forces acting on atoms (cartesian axes, Ry/au):

     atom    1 type  1   force =     0.00000000    0.00000000    0.00000000
     atom    2 type  1   force =     0.00000000    0.00000000    0.00000000

     Total force =     0.000000     Total SCF correction =     0.000004

     total   stress  (Ry/bohr**3)                   (kbar)     P=   -1.42
       -0.00000965   0.00000000   0.00000000         -1.42      0.00      0.00
        0.00000000  -0.00000965   0.00000000          0.00     -1.42      0.00
        0.00000000   0.00000000  -0.00000965          0.00      0.00     -1.42

     init_run     :      0.15s CPU      0.16s WALL (       1 calls)
     electrons    :      0.45s CPU      0.50s WALL (       1 calls)

     PWSCF        :      0.62s CPU      0.68s WALL

     JOB DONE.
"""


SAMPLE_RELAX_OUTPUT = """
     Program PWSCF v.7.0 starts on 11Oct2026 at 10:05:00
     Title: Perovskite SrTiO3 Relaxation
     calculation = 'relax'

     bravais-lattice index     =            0
     lattice parameter (alat)  =       7.3700  a.u.
     number of atoms/cell      =            5
     number of electrons       =        40.00

     crystal axes: (cart. coord. in units of alat)
               a(1) = (   1.000000   0.000000   0.000000 )
               a(2) = (   0.000000   1.000000   0.000000 )
               a(3) = (   0.000000   0.000000   1.000000 )

     Entering Dynamics:    iteration =     1

     iteration #   1     ecut=    40.00 Ry     beta= 0.70
     total energy              =    -120.50123000 Ry
     estimated scf accuracy    <       0.01000000 Ry
     total cpu time spent up to now is      1.2 secs

     iteration #   2     ecut=    40.00 Ry     beta= 0.70
     total energy              =    -120.55234000 Ry
     estimated scf accuracy    <       0.00001000 Ry
     total cpu time spent up to now is      2.4 secs

     End of self-consistent calculation

!    total energy              =    -120.55234500 Ry

     Forces acting on atoms (cartesian axes, Ry/au):
     atom    1 type  1   force =     0.00000000    0.00000000    0.01250000
     atom    2 type  2   force =     0.00000000    0.00000000   -0.01250000
     atom    3 type  3   force =     0.00000000    0.00000000    0.00000000
     atom    4 type  3   force =     0.00000000    0.00000000    0.00000000
     atom    5 type  3   force =     0.00000000    0.00000000    0.00000000

     Total force =     0.017678     Total SCF correction =     0.000021

ATOMIC_POSITIONS (angstrom)
Sr   0.000000   0.000000   0.000000
Ti   1.950000   1.950000   1.970000
O    1.950000   1.950000   0.000000
O    1.950000   0.000000   1.950000
O    0.000000   1.950000   1.950000

     Entering Dynamics:    iteration =     2

     iteration #   1     ecut=    40.00 Ry     beta= 0.70
     total energy              =    -120.55800000 Ry
     estimated scf accuracy    <       0.00500000 Ry
     total cpu time spent up to now is      3.6 secs

     iteration #   2     ecut=    40.00 Ry     beta= 0.70
     total energy              =    -120.56012000 Ry
     estimated scf accuracy    <       0.00000500 Ry
     total cpu time spent up to now is      4.8 secs

     End of self-consistent calculation

!    total energy              =    -120.56012340 Ry

     Forces acting on atoms (cartesian axes, Ry/au):
     atom    1 type  1   force =     0.00000000    0.00000000    0.00001000
     atom    2 type  2   force =     0.00000000    0.00000000   -0.00001000
     atom    3 type  3   force =     0.00000000    0.00000000    0.00000000
     atom    4 type  3   force =     0.00000000    0.00000000    0.00000000
     atom    5 type  3   force =     0.00000000    0.00000000    0.00000000

     Total force =     0.000014     Total SCF correction =     0.000001

ATOMIC_POSITIONS (angstrom)
Sr   0.000000   0.000000   0.000000
Ti   1.950000   1.950000   1.950200
O    1.950000   1.950000   0.000000
O    1.950000   0.000000   1.950000
O    0.000000   1.950000   1.950000

     bfgs converged in   2 scf cycles and   2 bfgs steps
     End of BFGS geometry calculation

     PWSCF        :      5.20s CPU      5.45s WALL

     JOB DONE.
"""


SAMPLE_BANDS_OUTPUT = """
     Program PWSCF v.7.2 starts on 11Oct2026 at 10:10:00
     Title: Silicon Band Structure
     calculation = 'bands'

     number of electrons       =         8.00
     number of Kohn-Sham states=         8
     the Fermi energy is     6.2500 ev

     End of band structure calculation

          k = 0.0000 0.0000 0.0000 (   331 PWs)   bands (ev):
    -5.6033   6.2500   6.2500   6.2500   8.8267   8.8267   8.8267  10.2355

          k = 0.5000 0.0000 0.5000 (   325 PWs)   bands (ev):
    -3.8200   2.1000   4.8500   5.1000   7.4500   7.9500   9.3200  11.4500

          k = 0.5000 0.5000 0.5000 (   318 PWs)   bands (ev):
    -4.1000   1.5000   4.2000   4.9000   7.8000   8.1000   9.9000  12.1000

     PWSCF        :      1.10s CPU      1.25s WALL

     JOB DONE.
"""


SAMPLE_NON_CONVERGED_OUTPUT = """
     Program PWSCF v.7.1 starts on 11Oct2026 at 10:15:00
     Title: Failed SCF
     calculation = 'scf'

     iteration #   1     ecut=    30.00 Ry     beta= 0.70
     total energy              =     -10.12345678 Ry
     estimated scf accuracy    <       0.05000000 Ry

     iteration #   2     ecut=    30.00 Ry     beta= 0.70
     total energy              =     -10.13456789 Ry
     estimated scf accuracy    <       0.04000000 Ry

     convergence NOT achieved after maximum iterations
     PWSCF        :      2.50s CPU      2.70s WALL
"""


SAMPLE_ERROR_OUTPUT = """
     Program PWSCF v.7.2 starts on 11Oct2026 at 10:20:00
     Title: Crash test
     calculation = 'scf'

 %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
     Error in routine card_atomic_positions (1):
     two atoms have the same coordinates
 %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

     stopping ...
"""


def test_parse_scf_output():
    """Test parsing a converged self-consistent field calculation."""
    res = QEOutputParser.parse_string(SAMPLE_SCF_OUTPUT)

    assert res.status == ConvergenceStatus.CONVERGED
    assert res.version == "v.7.2"
    assert res.calculation == "scf"
    assert "Silicon" in res.job_title
    assert pytest.approx(res.total_energy_ry) == -15.84501892
    assert pytest.approx(res.total_energy_ev) == -15.84501892 * 13.6056980659
    assert pytest.approx(res.fermi_energy_ev) == 6.3541

    assert len(res.scf_history) == 3
    assert res.scf_history[0].iteration == 1
    assert pytest.approx(res.scf_history[0].total_energy_ry) == -15.79051870
    assert pytest.approx(res.scf_history[0].accuracy_ry) == 0.06541200
    assert res.scf_history[0].cpu_time_s == 0.2

    assert len(res.forces) == 2
    assert res.stress_tensor_kbar is not None
    assert len(res.stress_tensor_kbar) == 3
    assert pytest.approx(res.stress_tensor_kbar[0][0]) == -1.42

    assert "0.62s" in res.cpu_time
    assert "0.68s" in res.wall_time

    assert res.final_structure is not None
    assert len(res.final_structure.atoms) == 2
    assert res.final_structure.atoms[0].symbol == "Si"
    assert res.final_structure.lattice is not None


def test_parse_relax_output():
    """Test parsing a structural relaxation with ionic steps."""
    res = QEOutputParser.parse_string(SAMPLE_RELAX_OUTPUT)

    assert res.status == ConvergenceStatus.CONVERGED
    assert res.calculation == "relax"
    assert len(res.ionic_steps) == 2

    # Step 1
    step1 = res.ionic_steps[0]
    assert step1.step == 1
    assert pytest.approx(step1.total_energy_ry) == -120.55234500
    assert pytest.approx(step1.total_force) == 0.017678
    assert len(step1.scf_iterations) == 2

    # Step 2
    step2 = res.ionic_steps[1]
    assert step2.step == 2
    assert pytest.approx(step2.total_energy_ry) == -120.56012340
    assert pytest.approx(step2.total_force) == 0.000014
    assert len(step2.scf_iterations) == 2
    assert len(step2.positions) == 5
    assert step2.positions[1][0] == "Ti"
    assert pytest.approx(step2.positions[1][3]) == 1.950200

    # Final structure should reflect relaxed coordinates
    assert res.final_structure is not None
    assert len(res.final_structure.atoms) == 5
    assert res.final_structure.atoms[1].symbol == "Ti"
    assert pytest.approx(res.final_structure.atoms[1].position[2]) == 1.950200


def test_parse_bands_output():
    """Test parsing electronic bands calculation and band gap determination."""
    res = QEOutputParser.parse_string(SAMPLE_BANDS_OUTPUT)

    assert res.status == ConvergenceStatus.CONVERGED
    assert res.calculation == "bands"
    assert res.fermi_energy_ev == 6.2500

    bs = res.band_structure
    assert bs is not None
    assert len(bs.kpoints) == 3
    assert len(bs.eigenvalues_ev) == 3
    assert len(bs.eigenvalues_ev[0]) == 8

    # Silicon has 8 electrons -> 4 valence bands (indices 0..3)
    # k0: valence band 4 (index 3) is 6.2500, conduction band 5 (index 4) is 8.8267
    # k1: valence band 4 is 5.1000, conduction band 5 is 7.4500
    # k2: valence band 4 is 4.9000, conduction band 5 is 7.8000
    # VBM = max(6.2500, 5.1000, 4.9000) = 6.2500 at k0
    # CBM = min(8.8267, 7.4500, 7.8000) = 7.4500 at k1
    # Band gap = 7.4500 - 6.2500 = 1.2000 eV (indirect gap)
    assert bs.band_gap_ev is not None
    assert pytest.approx(bs.band_gap_ev, abs=1e-3) == 1.2000
    assert bs.is_direct_gap is False


def test_parse_non_converged_output():
    """Test handling of non-converged SCF calculation."""
    res = QEOutputParser.parse_string(SAMPLE_NON_CONVERGED_OUTPUT)

    assert res.status == ConvergenceStatus.NOT_CONVERGED
    assert res.error_message is not None
    assert "convergence NOT achieved" in res.error_message
    assert len(res.scf_history) == 2
    assert res.total_energy_ry == -10.13456789


def test_parse_error_output():
    """Test error detection from crash routine."""
    res = QEOutputParser.parse_string(SAMPLE_ERROR_OUTPUT)

    assert res.status == ConvergenceStatus.FAILED
    assert res.error_message is not None
    assert "card_atomic_positions" in res.error_message


def test_parse_file(tmp_path: Path):
    """Test parse_file convenience method on disk."""
    out_file = tmp_path / "silicon.out"
    out_file.write_text(SAMPLE_SCF_OUTPUT, encoding="utf-8")

    res = QEOutputParser.parse_file(out_file)
    assert res.status == ConvergenceStatus.CONVERGED
    assert pytest.approx(res.total_energy_ry) == -15.84501892
