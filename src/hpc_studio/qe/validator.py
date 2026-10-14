"""Quantum ESPRESSO semantic validator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import QEInput


@dataclass
class ValidationError:
    """Validation issue found in a Quantum ESPRESSO input configuration."""

    level: str  # 'ERROR' | 'WARNING'
    parameter: str
    message: str

    def is_error(self) -> bool:
        return self.level.upper() == "ERROR"

    def is_warning(self) -> bool:
        return self.level.upper() == "WARNING"

    def __str__(self) -> str:
        return f"[{self.level.upper()}] {self.parameter}: {self.message}"


class QEValidator:
    """Semantic validator for Quantum ESPRESSO input decks."""

    @classmethod
    def validate(cls, qe_input: QEInput) -> list[ValidationError]:
        """Perform full semantic validation on a QEInput structure."""
        errors: list[ValidationError] = []

        # 1. Comprobar nat con cantidad real de positions
        num_positions = len(qe_input.atomic_positions.positions)
        if qe_input.system.nat != num_positions:
            errors.append(
                ValidationError(
                    level="ERROR",
                    parameter="nat",
                    message=(
                        f"nat={qe_input.system.nat} does not match the actual number "
                        f"of atomic positions ({num_positions})."
                    ),
                )
            )

        # 2. Comprobar ntyp con cantidad de species
        num_species = len(qe_input.atomic_species.species)
        if qe_input.system.ntyp != num_species:
            errors.append(
                ValidationError(
                    level="ERROR",
                    parameter="ntyp",
                    message=(
                        f"ntyp={qe_input.system.ntyp} does not match the number "
                        f"of atomic species ({num_species})."
                    ),
                )
            )

        # 3. Comprobar si cada símbolo en positions existe en species
        declared_species = {
            s.symbol.strip().upper() for s in qe_input.atomic_species.species
        }
        unknown_symbols = sorted({
            p.symbol.strip().capitalize()
            for p in qe_input.atomic_positions.positions
            if p.symbol.strip().upper() not in declared_species
        })
        if unknown_symbols:
            errors.append(
                ValidationError(
                    level="ERROR",
                    parameter="atomic_positions",
                    message=(
                        f"Atomic positions contain symbols not declared in ATOMIC_SPECIES: "
                        f"{', '.join(unknown_symbols)}."
                    ),
                )
            )

        # 4. Si ecutrho está definido, advertir si ecutrho < 4 * ecutwfc
        if qe_input.system.ecutrho is not None:
            min_recommended_rho = 4.0 * qe_input.system.ecutwfc
            if qe_input.system.ecutrho < min_recommended_rho:
                errors.append(
                    ValidationError(
                        level="WARNING",
                        parameter="ecutrho",
                        message=(
                            f"ecutrho ({qe_input.system.ecutrho} Ry) is less than 4 * ecutwfc "
                            f"({min_recommended_rho} Ry). For standard pseudopotentials, "
                            f"ecutrho should normally be >= 4 * ecutwfc."
                        ),
                    )
                )

        # 5. Si occupations == 'smearing', advertir si degauss == 0.0
        if (
            qe_input.system.occupations.lower() == "smearing"
            and qe_input.system.degauss == 0.0
        ):
            errors.append(
                ValidationError(
                    level="WARNING",
                    parameter="degauss",
                    message=(
                        "occupations='smearing' is set but degauss is 0.0. "
                        "A finite degauss smearing width is required."
                    ),
                )
            )

        # 6. Si calculation in ('relax', 'vc-relax'), verificar que existan namelists de iones
        calc_lower = qe_input.control.calculation.lower()
        if calc_lower in ("relax", "vc-relax") and qe_input.ions is None:
            errors.append(
                ValidationError(
                    level="ERROR",
                    parameter="ions",
                    message=(
                        f"calculation='{qe_input.control.calculation}' requires &IONS namelist."
                    ),
                )
            )

        if calc_lower == "vc-relax" and qe_input.cell is None:
            errors.append(
                ValidationError(
                    level="WARNING",
                    parameter="cell",
                    message="calculation='vc-relax' typically requires &CELL namelist.",
                )
            )

        # 7. Si ibrav == 0, exigir la presencia de CELL_PARAMETERS
        if qe_input.system.ibrav == 0:
            if (
                qe_input.cell_parameters is None
                or len(qe_input.cell_parameters.matrix) < 3
            ):
                errors.append(
                    ValidationError(
                        level="ERROR",
                        parameter="cell_parameters",
                        message="ibrav=0 requires CELL_PARAMETERS card with 3 lattice vectors.",
                    )
                )

        # Extra sanity checks
        if qe_input.system.ecutwfc <= 0:
            errors.append(
                ValidationError(
                    level="ERROR",
                    parameter="ecutwfc",
                    message="ecutwfc must be positive.",
                )
            )

        if (
            qe_input.system.ibrav != 0
            and (1 not in qe_input.system.celldm or qe_input.system.celldm[1] <= 0)
            and qe_input.system.a <= 0
        ):
            errors.append(
                ValidationError(
                    level="WARNING",
                    parameter="ibrav",
                    message=(
                        f"ibrav={qe_input.system.ibrav} specified but neither "
                        f"celldm(1) nor 'a' parameter is defined."
                    ),
                )
            )

        return errors
