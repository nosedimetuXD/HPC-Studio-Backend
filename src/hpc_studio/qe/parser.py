"""Quantum ESPRESSO AST Parser for input files (.in / .pwi)."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Union

from .models import (
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
    SpeciesItem,
    SystemNamelist,
)


def _strip_comments(line: str) -> str:
    """Remove Fortran/QE comments (! and #) outside quoted strings."""
    out: list[str] = []
    in_quote: str | None = None

    for char in line:
        if in_quote:
            if char == in_quote:
                in_quote = None
            out.append(char)
        else:
            if char in ("'", '"'):
                in_quote = char
                out.append(char)
            elif char in ("!", "#"):
                break
            else:
                out.append(char)

    return "".join(out).strip()


def _parse_namelist_value(val_str: str) -> Any:
    """Convert raw token string to appropriate Python type."""
    val_clean = val_str.strip()

    # Quoted string
    if (val_clean.startswith("'") and val_clean.endswith("'")) or (
        val_clean.startswith('"') and val_clean.endswith('"')
    ):
        return val_clean[1:-1]

    val_lower = val_clean.lower()

    # Fortran logical / booleans
    if val_lower in (".true.", ".t.", "true", "t"):
        return True
    if val_lower in (".false.", ".f.", "false", "f"):
        return False

    # Integer
    if re.fullmatch(r"[-+]?\d+", val_clean):
        try:
            return int(val_clean)
        except ValueError:
            pass

    # Floating point with optional Fortran exponent (d/D/e/E)
    if re.fullmatch(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eEdD][-+]?\d+)?", val_clean):
        try:
            return float(val_clean.replace("d", "e").replace("D", "e"))
        except ValueError:
            pass

    # String without quotes
    return val_clean


def _parse_namelist_kv_pairs(content: str) -> list[tuple[str, Any]]:
    """Extract key-value assignments from namelist text."""
    pairs: list[tuple[str, Any]] = []
    pattern = re.compile(
        r"([a-zA-Z_][a-zA-Z0-9_]*(?:\s*\([^)]*\))?)\s*=\s*('[^']*'|\"[^\"]*\"|[^\s,=/]+)",
        re.DOTALL,
    )

    for match in pattern.finditer(content):
        key = match.group(1).strip()
        val_str = match.group(2).strip()
        parsed_val = _parse_namelist_value(val_str)
        pairs.append((key, parsed_val))

    return pairs


def _find_namelist_terminator(line: str) -> int:
    """Find index of '/' outside quotes in a line, or -1 if not found."""
    in_quote: str | None = None
    for idx, char in enumerate(line):
        if in_quote:
            if char == in_quote:
                in_quote = None
        else:
            if char in ("'", '"'):
                in_quote = char
            elif char == "/":
                return idx
    return -1


def parse_qe_input(text_or_path: Union[str, Path]) -> QEInput:
    """Parse Quantum ESPRESSO input text or file into a structured QEInput."""
    if isinstance(text_or_path, Path) or (
        isinstance(text_or_path, str) and "\n" not in text_or_path and Path(text_or_path).is_file()
    ):
        path = Path(str(text_or_path))
        text = path.read_text(encoding="utf-8", errors="replace")
    else:
        text = str(text_or_path)

    # Clean lines and remove comments
    raw_lines = text.splitlines()
    clean_lines = [_strip_comments(l) for l in raw_lines]

    # Sectioning: namelists vs cards
    namelists_raw: dict[str, list[str]] = {}
    cards_raw: dict[str, tuple[str, list[str]]] = {}

    current_namelist: str | None = None
    current_card: str | None = None
    current_card_mode: str = ""
    current_card_lines: list[str] = []

    card_header_re = re.compile(
        r"^(ATOMIC_SPECIES|ATOMIC_POSITIONS|K_POINTS|CELL_PARAMETERS)\b(?:\s*[({]\s*([a-zA-Z0-9_]+)\s*[)}]|(?:\s+([a-zA-Z0-9_]+)))?",
        re.IGNORECASE,
    )

    for line in clean_lines:
        if not line:
            continue

        # Check for start of a namelist
        if line.startswith("&"):
            # Close any open card
            if current_card:
                cards_raw[current_card] = (current_card_mode, current_card_lines)
                current_card = None
                current_card_lines = []

            nml_name = line[1:].strip().split()[0].upper()
            if nml_name.endswith("/"):
                nml_name = nml_name[:-1]

            if nml_name not in ("END", ""):
                current_namelist = nml_name
                namelists_raw[current_namelist] = []
                # Check if there is content after &NAME
                rest = line[len(nml_name) + 1 :].strip()
                if rest:
                    namelists_raw[current_namelist].append(rest)
            continue

        # Check for end of namelist
        if current_namelist:
            term_idx = _find_namelist_terminator(line)
            if term_idx >= 0:
                before = line[:term_idx].strip()
                if before:
                    namelists_raw[current_namelist].append(before)
                current_namelist = None
                continue
            elif line.upper().startswith("&END"):
                current_namelist = None
                continue
            else:
                namelists_raw[current_namelist].append(line)
                continue

        # Check for Card header
        m_card = card_header_re.match(line)
        if m_card:
            # Close previous card
            if current_card:
                cards_raw[current_card] = (current_card_mode, current_card_lines)

            current_card = m_card.group(1).upper()
            mode = m_card.group(2) or m_card.group(3) or ""
            current_card_mode = mode.lower()
            current_card_lines = []
            continue

        # Line belonging to the current active card
        if current_card:
            current_card_lines.append(line)

    # Save last card if open
    if current_card:
        cards_raw[current_card] = (current_card_mode, current_card_lines)

    # Build namelists
    control = ControlNamelist()
    system = SystemNamelist()
    electrons = ElectronsNamelist()
    ions: IonsNamelist | None = None
    cell: CellNamelist | None = None

    # 1. &CONTROL
    if "CONTROL" in namelists_raw:
        content = "\n".join(namelists_raw["CONTROL"])
        for k, v in _parse_namelist_kv_pairs(content):
            k_lower = k.lower()
            if k_lower == "calculation":
                control.calculation = str(v).lower()
            elif k_lower == "title":
                control.title = str(v)
            elif k_lower == "prefix":
                control.prefix = str(v)
            elif k_lower == "outdir":
                control.outdir = str(v)
            elif k_lower == "pseudo_dir":
                control.pseudo_dir = str(v)
            elif k_lower == "restart_mode":
                control.restart_mode = str(v).lower()
            elif k_lower == "tprnfor":
                control.tprnfor = bool(v)
            elif k_lower == "tstress":
                control.tstress = bool(v)
            elif k_lower == "wf_collect":
                control.wf_collect = bool(v)
            elif k_lower == "verbosity":
                control.verbosity = str(v).lower()
            elif k_lower == "etot_conv_thr":
                control.etot_conv_thr = float(v)
            elif k_lower == "forc_conv_thr":
                control.forc_conv_thr = float(v)
            else:
                control.extra_params[k_lower] = v

    # 2. &SYSTEM
    if "SYSTEM" in namelists_raw:
        content = "\n".join(namelists_raw["SYSTEM"])
        for k, v in _parse_namelist_kv_pairs(content):
            k_lower = k.lower()
            # Check for celldm(i)
            m_celldm = re.match(r"celldm\s*\(\s*(\d+)\s*\)", k_lower)
            if m_celldm:
                idx = int(m_celldm.group(1))
                system.celldm[idx] = float(v)
                continue

            # Check for starting_magnetization(i)
            m_mag = re.match(r"starting_magnetization\s*\(\s*([^)]+)\s*\)", k_lower)
            if m_mag:
                mag_key = m_mag.group(1).strip()
                system.starting_magnetization[mag_key] = float(v)
                continue

            if k_lower == "ibrav":
                system.ibrav = int(v)
            elif k_lower == "a":
                system.a = float(v)
            elif k_lower == "b":
                system.b = float(v)
            elif k_lower == "c":
                system.c = float(v)
            elif k_lower == "cosab":
                system.cosab = float(v)
            elif k_lower == "cosac":
                system.cosac = float(v)
            elif k_lower == "cosbc":
                system.cosbc = float(v)
            elif k_lower == "nat":
                system.nat = int(v)
            elif k_lower == "ntyp":
                system.ntyp = int(v)
            elif k_lower == "ecutwfc":
                system.ecutwfc = float(v)
            elif k_lower == "ecutrho":
                system.ecutrho = float(v)
            elif k_lower == "occupations":
                system.occupations = str(v).lower()
            elif k_lower == "smearing":
                system.smearing = str(v).lower()
            elif k_lower == "degauss":
                system.degauss = float(v)
            elif k_lower == "nspin":
                system.nspin = int(v)
            elif k_lower == "vdw_corr":
                system.vdw_corr = str(v).lower()
            elif k_lower == "lda_plus_u":
                system.lda_plus_u = bool(v)
            elif k_lower == "tot_charge":
                system.tot_charge = float(v)
            else:
                system.extra_params[k_lower] = v

    # 3. &ELECTRONS
    if "ELECTRONS" in namelists_raw:
        content = "\n".join(namelists_raw["ELECTRONS"])
        for k, v in _parse_namelist_kv_pairs(content):
            k_lower = k.lower()
            if k_lower == "conv_thr":
                electrons.conv_thr = float(v)
            elif k_lower == "electron_maxstep":
                electrons.electron_maxstep = int(v)
            elif k_lower == "mixing_beta":
                electrons.mixing_beta = float(v)
            elif k_lower == "mixing_mode":
                electrons.mixing_mode = str(v).lower()
            elif k_lower == "diagonalization":
                electrons.diagonalization = str(v).lower()
            elif k_lower == "diago_david_ndim":
                electrons.diago_david_ndim = int(v)
            else:
                electrons.extra_params[k_lower] = v

    # 4. &IONS
    if "IONS" in namelists_raw:
        ions = IonsNamelist()
        content = "\n".join(namelists_raw["IONS"])
        for k, v in _parse_namelist_kv_pairs(content):
            k_lower = k.lower()
            if k_lower == "ion_dynamics":
                ions.ion_dynamics = str(v).lower()
            elif k_lower == "ion_positions":
                ions.ion_positions = str(v).lower()
            elif k_lower == "pot_extrapolation":
                ions.pot_extrapolation = str(v).lower()
            elif k_lower == "wfc_extrapolation":
                ions.wfc_extrapolation = str(v).lower()
            elif k_lower == "remove_rigid_rot":
                ions.remove_rigid_rot = bool(v)
            else:
                ions.extra_params[k_lower] = v

    # 5. &CELL
    if "CELL" in namelists_raw:
        cell = CellNamelist()
        content = "\n".join(namelists_raw["CELL"])
        for k, v in _parse_namelist_kv_pairs(content):
            k_lower = k.lower()
            if k_lower == "cell_dynamics":
                cell.cell_dynamics = str(v).lower()
            elif k_lower == "press":
                cell.press = float(v)
            elif k_lower == "wmass":
                cell.wmass = float(v)
            elif k_lower == "cell_factor":
                cell.cell_factor = float(v)
            elif k_lower == "cell_dofree":
                cell.cell_dofree = str(v).lower()
            else:
                cell.extra_params[k_lower] = v

    # Parse Cards
    atomic_species = AtomicSpeciesCard()
    if "ATOMIC_SPECIES" in cards_raw:
        _, lines = cards_raw["ATOMIC_SPECIES"]
        for line in lines:
            parts = line.split()
            if len(parts) >= 3:
                sym = parts[0].strip()
                mass = float(parts[1].replace("d", "e").replace("D", "e"))
                pseudo = parts[2].strip()
                atomic_species.species.append(
                    SpeciesItem(symbol=sym, mass=mass, pseudo_file=pseudo)
                )

    atomic_positions = AtomicPositionsCard()
    if "ATOMIC_POSITIONS" in cards_raw:
        mode, lines = cards_raw["ATOMIC_POSITIONS"]
        atomic_positions.mode = mode or "alat"
        for line in lines:
            parts = line.split()
            if len(parts) >= 4:
                sym = parts[0].strip()
                x = float(parts[1].replace("d", "e").replace("D", "e"))
                y = float(parts[2].replace("d", "e").replace("D", "e"))
                z = float(parts[3].replace("d", "e").replace("D", "e"))
                if_pos = (1, 1, 1)
                if len(parts) >= 7:
                    try:
                        if_pos = (int(parts[4]), int(parts[5]), int(parts[6]))
                    except ValueError:
                        pass
                atomic_positions.positions.append(
                    PositionItem(symbol=sym, x=x, y=y, z=z, if_pos=if_pos)
                )

    k_points = KPointsCard()
    if "K_POINTS" in cards_raw:
        mode, lines = cards_raw["K_POINTS"]
        k_mode = mode or "automatic"
        k_points.mode = k_mode

        if k_mode == "automatic":
            if lines:
                parts = [int(p) for p in lines[0].split() if re.fullmatch(r"[-+]?\d+", p)]
                if len(parts) >= 6:
                    k_points.grid = (parts[0], parts[1], parts[2])
                    k_points.shift = (parts[3], parts[4], parts[5])
                elif len(parts) >= 3:
                    k_points.grid = (parts[0], parts[1], parts[2])
                    k_points.shift = (0, 0, 0)
        elif k_mode == "gamma":
            pass
        else:
            # Explicit list: crystal_b, tpiba_b, crystal, etc.
            kpoints_list = []
            if lines:
                first_parts = lines[0].split()
                start_idx = 0
                if len(first_parts) == 1 and first_parts[0].isdigit():
                    start_idx = 1
                for line in lines[start_idx:]:
                    parts = line.split()
                    if len(parts) >= 4:
                        kp = (
                            float(parts[0].replace("d", "e").replace("D", "e")),
                            float(parts[1].replace("d", "e").replace("D", "e")),
                            float(parts[2].replace("d", "e").replace("D", "e")),
                            float(parts[3].replace("d", "e").replace("D", "e")),
                        )
                        kpoints_list.append(kp)
                    elif len(parts) == 3:
                        kp = (
                            float(parts[0].replace("d", "e").replace("D", "e")),
                            float(parts[1].replace("d", "e").replace("D", "e")),
                            float(parts[2].replace("d", "e").replace("D", "e")),
                            1.0,
                        )
                        kpoints_list.append(kp)
            k_points.kpoints = kpoints_list

    cell_parameters: CellParametersCard | None = None
    if "CELL_PARAMETERS" in cards_raw:
        mode, lines = cards_raw["CELL_PARAMETERS"]
        mat_rows: list[list[float]] = []
        for line in lines[:3]:
            parts = line.split()
            if len(parts) >= 3:
                mat_rows.append([
                    float(parts[0].replace("d", "e").replace("D", "e")),
                    float(parts[1].replace("d", "e").replace("D", "e")),
                    float(parts[2].replace("d", "e").replace("D", "e")),
                ])
        cell_parameters = CellParametersCard(mode=mode or "angstrom", matrix=mat_rows)

    return QEInput(
        control=control,
        system=system,
        electrons=electrons,
        ions=ions,
        cell=cell,
        atomic_species=atomic_species,
        atomic_positions=atomic_positions,
        k_points=k_points,
        cell_parameters=cell_parameters,
    )
