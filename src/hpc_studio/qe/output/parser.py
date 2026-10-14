"""Quantum ESPRESSO output parser (pw.out / stdout logs)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Union

import numpy as np

from hpc_studio.crystallography.models import Atom, CrystalStructure, Lattice
from hpc_studio.crystallography.parsers.qe import BOHR_TO_ANGSTROM, _build_ibrav_lattice
from hpc_studio.qe.output.models import (
    BandStructureData,
    ConvergenceStatus,
    IonicStep,
    QEOutputResult,
    SCFIteration,
)

RYDBERG_TO_EV = 13.6056980659


class QEOutputParser:
    """Robust parser for Quantum ESPRESSO pw.x output files and streams."""

    MAX_PARSE_SIZE_BYTES = 150 * 1024 * 1024  # 150 MB safety limit for in-memory parsing

    @classmethod
    def parse_file(cls, file_path: Union[str, Path]) -> QEOutputResult:
        """Parse a QE pw.x output file from disk."""
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"File not found: {file_path}")

        file_size = path.stat().st_size
        if file_size > cls.MAX_PARSE_SIZE_BYTES:
            raise ValueError(
                f"File size ({file_size / (1024*1024):.1f} MB) exceeds maximum safe parsing limit "
                f"({cls.MAX_PARSE_SIZE_BYTES / (1024*1024):.0f} MB). Inspect the file via Terminal or chunked reader."
            )

        content = path.read_text(encoding="utf-8", errors="replace")
        res = cls.parse_string(content)
        res.file_path = str(path.resolve())
        return res

    @classmethod
    def parse_string(cls, content: str) -> QEOutputResult:
        """Parse raw Quantum ESPRESSO pw.x output content."""
        res = QEOutputResult()
        # Keep raw_text only if reasonable size (< 20 MB) to preserve RAM
        if len(content) < 20 * 1024 * 1024:
            res.raw_text = content
        lines = content.splitlines()

        # Parse convergence threshold conv_thr if present
        conv_m = re.search(r"conv_thr\s*=\s*([-+]?\d*\.?\d+(?:[eEdD][-+]?\d+)?)", content, re.IGNORECASE)
        if not conv_m:
            conv_m = re.search(r"convergence threshold\s*=\s*([-+]?\d*\.?\d+(?:[eEdD][-+]?\d+)?)", content, re.IGNORECASE)
        if conv_m:
            try:
                res.conv_thr_ry = float(conv_m.group(1).replace("d", "e").replace("D", "e"))
            except ValueError:
                pass

        # 1. Header and Metadata extraction
        cls._parse_header_and_meta(lines, res)

        # 2. System and Input Lattice/Geometry detection
        init_ibrav, init_celldm, init_alat_bohr, init_cell_mat, init_atoms, num_electrons = (
            cls._parse_initial_system(lines)
        )

        # 3. Process ionic steps & SCF history
        cls._parse_scf_and_ionic_steps(lines, res)

        # 4. Energy and forces parsing
        cls._parse_energies_forces_stress(lines, res)

        # 5. Electronic eigenvalues & Band structure
        cls._parse_band_structure(lines, res, num_electrons)

        # 6. Status, errors, and timing
        cls._parse_status_and_time(lines, res)

        # 7. Construct final structure
        res.final_structure = cls._build_final_structure(
            res, init_ibrav, init_celldm, init_alat_bohr, init_cell_mat, init_atoms
        )

        return res

    @staticmethod
    def _parse_header_and_meta(lines: list[str], res: QEOutputResult) -> None:
        """Extract program version, calculation type, and title."""
        for line in lines[:100]:
            # Program PWSCF v.7.2 or v.6.8 or v.7.0
            ver_m = re.search(r"Program PWSCF\s+(v\.?[0-9a-zA-Z._-]+)", line, re.IGNORECASE)
            if ver_m:
                res.version = ver_m.group(1).strip()

            # Title line: Title:\n or title: ...
            if "Title:" in line or "title:" in line:
                parts = line.split(":", 1)
                if len(parts) > 1 and parts[1].strip():
                    res.job_title = parts[1].strip()

            # Calculation type: calculation = 'relax' or 'bands' or 'scf' or 'vc-relax'
            calc_m = re.search(r"calculation\s*=\s*['\"]?([a-zA-Z0-9_-]+)['\"]?", line, re.IGNORECASE)
            if calc_m:
                res.calculation = calc_m.group(1).lower()

        # If title not found in line with 'Title:', check for 'title' namelist item
        if not res.job_title:
            for line in lines[:100]:
                title_item_m = re.search(r"title\s*=\s*['\"]([^'\"]+)['\"]", line, re.IGNORECASE)
                if title_item_m:
                    res.job_title = title_item_m.group(1).strip()
                    break

    @staticmethod
    def _parse_initial_system(lines: list[str]) -> tuple[
        int, dict[int, float], Optional[float], Optional[np.ndarray], list[tuple[str, float, float, float]], Optional[float]
    ]:
        """Extract initial ibrav, celldm, lattice parameters, and initial atomic positions."""
        ibrav = 0
        celldm: dict[int, float] = {}
        alat_bohr: Optional[float] = None
        cell_mat: Optional[np.ndarray] = None
        atoms: list[tuple[str, float, float, float]] = []
        num_electrons: Optional[float] = None

        n_lines = len(lines)
        i = 0
        while i < min(n_lines, 500):
            line = lines[i]

            # ibrav
            ibrav_m = re.search(r"bravais-lattice index\s*=\s*(-?\d+)", line, re.IGNORECASE)
            if ibrav_m:
                ibrav = int(ibrav_m.group(1))

            # lattice parameter (alat) = ... a.u.
            alat_m = re.search(r"lattice parameter \(alat\)\s*=\s*([-+]?\d*\.?\d+)", line, re.IGNORECASE)
            if alat_m:
                alat_bohr = float(alat_m.group(1))

            # celldm(1..6)
            for m in re.finditer(r"celldm\((\d+)\)\s*=\s*([-+]?\d*\.?\d+)", line, re.IGNORECASE):
                celldm[int(m.group(1))] = float(m.group(2))

            # number of electrons
            nelec_m = re.search(r"number of electrons\s*=\s*([-+]?\d*\.?\d+)", line, re.IGNORECASE)
            if nelec_m:
                num_electrons = float(nelec_m.group(1))

            # crystal axes: (cart. coord. in units of alat)
            if "crystal axes: (cart. coord. in units of alat)" in line or "crystal axes: (cart. coord. in units of a_0)" in line:
                rows = []
                for j in range(1, 4):
                    if i + j < n_lines:
                        # a(1) = (  1.000000   0.000000   0.000000 )
                        axis_m = re.search(r"\(\s*([-+]?\d*\.?\d+)\s+([-+]?\d*\.?\d+)\s+([-+]?\d*\.?\d+)\s*\)", lines[i + j])
                        if axis_m:
                            rows.append([float(axis_m.group(1)), float(axis_m.group(2)), float(axis_m.group(3))])
                if len(rows) == 3:
                    cell_mat = np.array(rows, dtype=float)

            # Cartesian axes: or Cart. coord. in units of a_0 or site n. ...
            # Positions in output are often listed under:
            # "Cartesian axes" or "site n.     atom                  positions (alat units)"
            if "positions (alat units)" in line or "positions (a_0 units)" in line:
                # Followed by lines like:
                # 1           Si  tau(   1) = (   0.0000000   0.0000000   0.0000000  )
                k = i + 1
                while k < min(n_lines, i + 300):
                    atom_line = lines[k].strip()
                    if not atom_line or "number of k points" in atom_line or "---" in atom_line or "End of" in atom_line:
                        break
                    atom_m = re.search(
                        r"\d+\s+([A-Za-z]+)\s+tau\(\s*\d+\)\s*=\s*\(\s*([-+]?\d*\.?\d+)\s+([-+]?\d*\.?\d+)\s+([-+]?\d*\.?\d+)\s*\)",
                        atom_line,
                    )
                    if atom_m:
                        sym = atom_m.group(1).capitalize()
                        x, y, z = float(atom_m.group(2)), float(atom_m.group(3)), float(atom_m.group(4))
                        atoms.append((sym, x, y, z))
                    k += 1

            i += 1

        return ibrav, celldm, alat_bohr, cell_mat, atoms, num_electrons

    @staticmethod
    def _parse_scf_and_ionic_steps(lines: list[str], res: QEOutputResult) -> None:
        """Parse all SCF iterations and ionic steps for relax/vc-relax calculations."""
        current_step_scf: list[SCFIteration] = []
        all_scf: list[SCFIteration] = []
        ionic_steps: list[IonicStep] = []

        step_idx = 0
        current_step_energy: Optional[float] = None
        current_step_force: float = 0.0
        current_positions: list[tuple[str, float, float, float]] = []
        current_cell: Optional[list[list[float]]] = None

        n_lines = len(lines)
        i = 0

        # Pattern for iteration:
        # iteration #   1     ecut=    35.00 Ry     beta= 0.70
        # ...
        # total energy              =     -15.79051870 Ry
        # Harris-Foulkes estimate   =     -15.79251870 Ry
        # estimated scf accuracy    <       0.00412850 Ry
        # ...
        # total cpu time spent up to now is      0.2 secs

        iter_pat = re.compile(r"iteration\s*#\s*(\d+)", re.IGNORECASE)
        tot_e_pat = re.compile(r"total energy\s*=\s*([-+]?\d*\.?\d+)\s*Ry", re.IGNORECASE)
        acc_pat = re.compile(r"estimated scf accuracy\s*<\s*([-+]?\d*\.?\d+(?:[eEdD][-+]?\d+)?)", re.IGNORECASE)
        cpu_pat = re.compile(r"total cpu time spent up to now is\s*([-+]?\d*\.?\d+)", re.IGNORECASE)

        # Dynamics step markers
        # "Entering Dynamics" or "Self-consistent Calculation" or "Starting step"
        while i < n_lines:
            line = lines[i]

            # Detect iteration header
            iter_m = iter_pat.search(line)
            if iter_m:
                it_num = int(iter_m.group(1))
                it_e: Optional[float] = None
                it_acc: float = 0.0
                it_cpu: float = 0.0

                # Look forward a few lines for energy, accuracy, and cpu time
                j = i + 1
                while j < min(n_lines, i + 50):
                    subline = lines[j]
                    if iter_pat.search(subline) or "Entering Dynamics" in subline or "Starting step" in subline:
                        break
                    e_m = tot_e_pat.search(subline)
                    if not e_m and "!    total energy" in subline:
                        e_m = re.search(r"!\s+total energy\s*=\s*([-+]?\d*\.?\d+)\s*Ry", subline)
                    if e_m:
                        it_e = float(e_m.group(1))
                    ac_m = acc_pat.search(subline)
                    if ac_m:
                        it_acc = float(ac_m.group(1).replace("d", "e").replace("D", "e"))
                    c_m = cpu_pat.search(subline)
                    if c_m:
                        it_cpu = float(c_m.group(1))
                    if it_e is not None and it_acc > 0 and it_cpu > 0:
                        # Found all three fields for this iteration
                        break
                    j += 1

                if it_e is not None:
                    # Calculate energy difference from previous iteration in the same step
                    err_e = 0.0
                    if current_step_scf:
                        err_e = abs(it_e - current_step_scf[-1].total_energy_ry)
                    scf_it = SCFIteration(
                        iteration=it_num,
                        total_energy_ry=it_e,
                        energy_error_ry=err_e,
                        accuracy_ry=it_acc,
                        cpu_time_s=it_cpu,
                    )
                    current_step_scf.append(scf_it)
                    all_scf.append(scf_it)

            # Detect Total force in relaxation step
            # "Total force =     0.012345     Total SCF correction = ..."
            tf_m = re.search(r"Total force\s*=\s*([-+]?\d*\.?\d+)", line, re.IGNORECASE)
            if tf_m:
                current_step_force = float(tf_m.group(1))

            # Detect ATOMIC_POSITIONS (in relax steps)
            if "ATOMIC_POSITIONS" in line:
                pos_list = []
                # ATOMIC_POSITIONS (angstrom) or (crystal) or (alat)
                unit_match = re.search(r"ATOMIC_POSITIONS\s*(\([a-zA-Z_]+\)|[a-zA-Z_]+)?", line, re.IGNORECASE)
                pos_unit = (unit_match.group(1) or "alat").strip("() \t").lower() if unit_match else "alat"

                k = i + 1
                while k < n_lines:
                    sline = lines[k].strip()
                    if not sline or sline.startswith("Entering") or sline.startswith("CELL_PARAMETERS") or sline.startswith("End") or sline.startswith("Writing"):
                        break
                    parts = sline.split()
                    if len(parts) >= 4:
                        sym = parts[0].strip().capitalize()
                        try:
                            px, py, pz = float(parts[1]), float(parts[2]), float(parts[3])
                            pos_list.append((sym, px, py, pz))
                        except ValueError:
                            break
                    k += 1
                if pos_list:
                    current_positions = pos_list

            # Detect CELL_PARAMETERS (in vc-relax steps)
            if "CELL_PARAMETERS" in line:
                cell_rows = []
                k = i + 1
                while k < min(n_lines, i + 10) and len(cell_rows) < 3:
                    sline = lines[k].strip()
                    parts = sline.split()
                    if len(parts) >= 3:
                        try:
                            cell_rows.append([float(parts[0]), float(parts[1]), float(parts[2])])
                        except ValueError:
                            pass
                    k += 1
                if len(cell_rows) == 3:
                    current_cell = cell_rows

            # Detect Step end or transition to next step
            # e.g., "End of BFGS geometry calculation" or "End of molecular dynamics"
            # or "!    total energy              =     -15.79051870 Ry"
            if "!    total energy" in line:
                fin_e_m = re.search(r"!    total energy\s*=\s*([-+]?\d*\.?\d+)", line)
                if fin_e_m:
                    current_step_energy = float(fin_e_m.group(1))

            # "Entering Dynamics:    iteration =     1" or "step      1"
            step_m = re.search(r"(?:Entering Dynamics:\s*iteration|Starting step|number of scf cycles)\s*=\s*(\d+)", line, re.IGNORECASE)

            if step_m:
                new_step_num = int(step_m.group(1))

                # If we had a previous step with SCF iterations, save previous step
                if step_idx > 0 and current_step_scf:
                    ionic_steps.append(
                        IonicStep(
                            step=step_idx,
                            total_energy_ry=current_step_energy if current_step_energy is not None else (current_step_scf[-1].total_energy_ry if current_step_scf else 0.0),
                            total_force=current_step_force,
                            scf_iterations=list(current_step_scf),
                            positions=list(current_positions),
                            cell_parameters=current_cell,
                        )
                    )
                    current_step_scf.clear()

                step_idx = new_step_num

            i += 1

        # Append final ionic step if relax/vc-relax was performed
        if (step_idx > 0 or current_step_force > 0) and (current_step_energy is not None or current_step_scf):
            e_final = current_step_energy if current_step_energy is not None else (current_step_scf[-1].total_energy_ry if current_step_scf else 0.0)
            ionic_steps.append(
                IonicStep(
                    step=step_idx if step_idx > 0 else 1,
                    total_energy_ry=e_final,
                    total_force=current_step_force,
                    scf_iterations=list(current_step_scf),
                    positions=list(current_positions),
                    cell_parameters=current_cell,
                )
            )

        res.scf_history = all_scf
        res.ionic_steps = ionic_steps

    @staticmethod
    def _parse_energies_forces_stress(lines: list[str], res: QEOutputResult) -> None:
        """Extract final total energy, Fermi energy, forces, and stress tensor."""
        n_lines = len(lines)
        forces: list[tuple[str, float, float, float]] = []

        for i, line in enumerate(lines):
            # Final energy: !    total energy = ... Ry
            if "!    total energy" in line:
                m = re.search(r"!    total energy\s*=\s*([-+]?\d*\.?\d+)\s*Ry", line)
                if m:
                    res.total_energy_ry = float(m.group(1))
                    res.total_energy_ev = res.total_energy_ry * RYDBERG_TO_EV

            # Fermi energy / highest occupied level:
            # the Fermi energy is     6.3541 ev
            # highest occupied level (ev):     6.3541
            # highest occupied, lowest unoccupied level (ev):    6.3541   7.4560
            fermi_m = re.search(r"the Fermi energy is\s*([-+]?\d*\.?\d+)\s*ev", line, re.IGNORECASE)
            if fermi_m:
                res.fermi_energy_ev = float(fermi_m.group(1))
            else:
                homo_m = re.search(r"highest occupied level\s*\(ev\):\s*([-+]?\d*\.?\d+)", line, re.IGNORECASE)
                if homo_m:
                    res.fermi_energy_ev = float(homo_m.group(1))
                else:
                    homo_lumo_m = re.search(
                        r"highest occupied,\s*lowest unoccupied level\s*\(ev\):\s*([-+]?\d*\.?\d+)\s+([-+]?\d*\.?\d+)",
                        line,
                        re.IGNORECASE,
                    )
                    if homo_lumo_m:
                        res.fermi_energy_ev = float(homo_lumo_m.group(1))

            # Forces acting on atoms (cartesian axes, Ry/au):
            # atom   1 type  1   force =     0.00000000    0.00000000    0.00000000
            if "Forces acting on atoms (cartesian axes, Ry/au):" in line or "Forces acting on atoms" in line:
                step_forces = []
                k = i + 1
                while k < min(n_lines, i + 300):
                    f_line = lines[k].strip()
                    if not f_line:
                        k += 1
                        continue
                    if "Total force" in f_line or "The non-local contrib." in f_line or "total   stress" in f_line:
                        break
                    f_match = re.search(
                        r"atom\s+(\d+)\s+type\s+\d+\s+force\s*=\s*([-+]?\d*\.?\d+)\s+([-+]?\d*\.?\d+)\s+([-+]?\d*\.?\d+)",
                        f_line,
                    )
                    if f_match:
                        fx, fy, fz = float(f_match.group(2)), float(f_match.group(3)), float(f_match.group(4))
                        # Symbol can be placeholder or matched by atom index
                        step_forces.append((f"Atom_{f_match.group(1)}", fx, fy, fz))
                    k += 1
                if step_forces:
                    forces = step_forces

            # Stress tensor:
            # total   stress  (Ry/bohr**3)                   (kbar)     P=   ...
            # -0.00000000  0.00000000  0.00000000        -0.00      0.00      0.00
            if "total   stress" in line and "(kbar)" in line:
                stress_rows = []
                for sj in range(1, 4):
                    if i + sj < n_lines:
                        s_parts = lines[i + sj].split()
                        # Last 3 numbers on the line are the kbar values
                        if len(s_parts) >= 6:
                            try:
                                stress_rows.append([float(s_parts[-3]), float(s_parts[-2]), float(s_parts[-1])])
                            except ValueError:
                                pass
                if len(stress_rows) == 3:
                    res.stress_tensor_kbar = stress_rows

        res.forces = forces

        # Fallback for total_energy_ry if '! total energy' was not printed (e.g. non-converged or intermediate)
        if res.total_energy_ry is None and res.scf_history:
            res.total_energy_ry = res.scf_history[-1].total_energy_ry
            res.total_energy_ev = res.total_energy_ry * RYDBERG_TO_EV

    @staticmethod
    def _parse_band_structure(lines: list[str], res: QEOutputResult, num_electrons: Optional[float]) -> None:
        """Parse k-points, eigenvalues, band gaps, and determine direct/indirect character."""
        kpoints: list[tuple[float, float, float]] = []
        eigenvalues: list[list[float]] = []

        n_lines = len(lines)
        i = 0

        # Pattern:
        # k = 0.0000 0.0000 0.0000 (  1234 PWs)   bands (ev):
        #   -5.6033   6.3541   6.3541   6.3541   8.8267   8.8267   8.8267  10.2355
        # or
        # ------ k-point    1 (  0.0000  0.0000  0.0000) ------
        k_pat = re.compile(
            r"k\s*=\s*([-+]?\d*\.?\d+)\s+([-+]?\d*\.?\d+)\s+([-+]?\d*\.?\d+)(?:.*bands\s*\(ev\):)?",
            re.IGNORECASE,
        )

        while i < n_lines:
            line = lines[i]

            # Look for "bands (ev):" or "End of band structure calculation"
            if "k =" in line and ("bands (ev):" in line or "PWs)" in line):
                k_m = k_pat.search(line)
                if k_m:
                    kx, ky, kz = float(k_m.group(1)), float(k_m.group(2)), float(k_m.group(3))
                    kpoints.append((kx, ky, kz))

                    # Read subsequent lines with band eigenvalues
                    ev_list: list[float] = []
                    j = i + 1
                    while j < n_lines:
                        b_line = lines[j].strip()
                        if not b_line:
                            j += 1
                            continue
                        # If next k-point or next section begins, stop
                        if "k =" in b_line or "highest occupied" in b_line or "the Fermi energy" in b_line or "JOB DONE" in b_line:
                            break
                        # Check if line contains numbers
                        tokens = b_line.split()
                        try:
                            floats = [float(t) for t in tokens]
                            ev_list.extend(floats)
                        except ValueError:
                            # Not eigenvalue numbers
                            break
                        j += 1

                    if ev_list:
                        eigenvalues.append(ev_list)
                    i = j - 1

            i += 1

        if not kpoints or not eigenvalues:
            return

        # Build BandStructureData
        band_data = BandStructureData(
            kpoints=kpoints,
            eigenvalues_ev=eigenvalues,
            fermi_energy_ev=res.fermi_energy_ev,
        )

        # Calculate Band Gap (Eg = CBM - VBM) if Fermi energy or valence bands known
        # In insulator/semiconductor systems with N electrons, valence band index = int(N / 2) - 1 (for non-magnetic)
        if eigenvalues:
            nbands = min(len(evs) for evs in eigenvalues)
            nk = len(eigenvalues)

            # Determine valence band index (0-based)
            vbm_idx = None
            if num_electrons is not None and num_electrons > 0:
                # 2 electrons per band
                val_bands = int(round(num_electrons / 2.0))
                if 1 <= val_bands < nbands:
                    vbm_idx = val_bands - 1
            elif res.fermi_energy_ev is not None:
                # Find highest band below or equal to Fermi energy (with small tolerance)
                ef = res.fermi_energy_ev
                below_counts = []
                for band_i in range(nbands):
                    max_b = max(eigenvalues[k][band_i] for k in range(nk))
                    if max_b <= ef + 0.1:
                        below_counts.append(band_i)
                if below_counts:
                    vbm_idx = max(below_counts)

            if vbm_idx is not None and vbm_idx + 1 < nbands:
                cbm_idx = vbm_idx + 1

                # Find VBM and CBM across all k-points
                vbm_val = -1e9
                vbm_k = 0
                for k in range(nk):
                    val = eigenvalues[k][vbm_idx]
                    if val > vbm_val:
                        vbm_val = val
                        vbm_k = k

                cbm_val = 1e9
                cbm_k = 0
                for k in range(nk):
                    val = eigenvalues[k][cbm_idx]
                    if val < cbm_val:
                        cbm_val = val
                        cbm_k = k

                gap = cbm_val - vbm_val
                if gap > 0.001:
                    band_data.band_gap_ev = round(gap, 4)
                    band_data.is_direct_gap = (vbm_k == cbm_k)
                else:
                    band_data.band_gap_ev = 0.0
                    band_data.is_direct_gap = True

        res.band_structure = band_data

    @staticmethod
    def _parse_status_and_time(lines: list[str], res: QEOutputResult) -> None:
        """Determine calculation status (CONVERGED, NOT_CONVERGED, FAILED, RUNNING) and timings."""
        # Inspect only the tail (last 1000 lines) for status and timings to avoid full text reallocation
        tail_lines = lines[-1000:] if len(lines) > 1000 else lines
        tail_text = "\n".join(tail_lines)

        # Check errors first
        # "% Error in routine ..." or "Error in routine" or "from ... : error #"
        err_m = re.search(r"(?:%+\s*)?Error in routine\s+([^\n]+)", tail_text, re.IGNORECASE)
        if not err_m and len(lines) > 1000:
            # Check entire lines list by iteration without full_text string re-allocation
            for l in reversed(lines):
                if "Error in routine" in l:
                    err_m = re.search(r"(?:%+\s*)?Error in routine\s+([^\n]+)", l, re.IGNORECASE)
                    break
        if err_m:
            res.status = ConvergenceStatus.FAILED
            res.error_message = err_m.group(0).strip()
            return

        if "convergence NOT achieved" in tail_text:
            res.status = ConvergenceStatus.NOT_CONVERGED
            res.error_message = "convergence NOT achieved after maximum iterations"
            return

        # Check job done
        if "JOB DONE." in tail_text:
            res.status = ConvergenceStatus.CONVERGED
        else:
            # Check if finished without JOB DONE or still running
            if "PWSCF        :" in tail_text and "CPU" in tail_text:
                res.status = ConvergenceStatus.CONVERGED
            else:
                res.status = ConvergenceStatus.RUNNING

        # Parse CPU and WALL time:
        # PWSCF        :      0.45s CPU      0.52s WALL
        time_m = re.search(
            r"PWSCF\s*:\s*([0-9a-zA-Z._ ]+?)CPU\s+([0-9a-zA-Z._ ]+?)WALL",
            tail_text,
            re.IGNORECASE,
        )
        if time_m:
            res.cpu_time = time_m.group(1).strip()
            res.wall_time = time_m.group(2).strip()
        else:
            # Fallback for total cpu / wall
            cpu_m = re.search(r"total cpu time spent up to now is\s*([-+]?\d*\.?\d+\s*s(?:ecs)?)", tail_text, re.IGNORECASE)
            if cpu_m:
                res.cpu_time = cpu_m.group(1).strip()

    @classmethod
    def _build_final_structure(
        cls,
        res: QEOutputResult,
        ibrav: int,
        celldm: dict[int, float],
        alat_bohr: Optional[float],
        cell_mat: Optional[np.ndarray],
        init_atoms: list[tuple[str, float, float, float]],
    ) -> Optional[CrystalStructure]:
        """Construct the final CrystalStructure from relaxation results or initial structure."""
        # 1. Determine final cell parameters
        final_cell_mat: Optional[np.ndarray] = None
        for step in reversed(res.ionic_steps):
            if step.cell_parameters is not None:
                final_cell_mat = np.array(step.cell_parameters, dtype=float)
                break

        # If no cell parameters updated from vc-relax, use initial cell_mat or ibrav
        alat_ang = (alat_bohr * BOHR_TO_ANGSTROM) if alat_bohr else 1.0

        lattice: Optional[Lattice] = None
        if final_cell_mat is not None:
            # CELL_PARAMETERS output in QE vc-relax is in units of alat or bohr/angstrom
            # In QE output, CELL_PARAMETERS (alat) is multiplied by alat
            lattice = Lattice(final_cell_mat * alat_ang if final_cell_mat.max() < 2.0 else final_cell_mat)
        elif cell_mat is not None:
            lattice = Lattice(cell_mat * alat_ang)
        elif ibrav != 0:
            lattice = _build_ibrav_lattice(ibrav, celldm)

        # 2. Determine final atomic positions
        final_pos_list: list[tuple[str, float, float, float]] = []
        for step in reversed(res.ionic_steps):
            if step.positions:
                final_pos_list = step.positions
                break

        if not final_pos_list and init_atoms:
            final_pos_list = init_atoms

        if not final_pos_list:
            return None

        # Format atoms: QE output positions in "ATOMIC_POSITIONS (angstrom)" or "(alat)" or "(crystal)"
        # Note: In pw.out, ATOMIC_POSITIONS (angstrom) is very common in modern QE relax output,
        # while initial Cartesian axes are in units of alat.
        atoms: list[Atom] = []
        for idx, item in enumerate(final_pos_list):
            sym, px, py, pz = item
            # If initial positions were in alat units and we have alat_ang
            # Check if coords are reasonable Angstroms (> 0.5) or alat scale
            if lattice is not None and not res.ionic_steps:
                # Initial positions were in alat units
                cpos = (px * alat_ang, py * alat_ang, pz * alat_ang)
                fpos = lattice.cartesian_to_fractional(cpos)
            else:
                cpos = (px, py, pz)
                fpos = lattice.cartesian_to_fractional(cpos) if lattice else None

            atoms.append(
                Atom(
                    index=idx,
                    symbol=sym,
                    position=cpos,
                    fractional_position=fpos,
                )
            )

        name = res.job_title or (f"{res.calculation.upper()} Result Structure" if res.calculation else "QE Structure")
        return CrystalStructure(
            lattice=lattice,
            atoms=atoms,
            name=name,
        )
