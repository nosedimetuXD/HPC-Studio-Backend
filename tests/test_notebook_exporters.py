"""Unit tests for NotebookExporter (Python, SLURM, and Quantum ESPRESSO exports)."""

import pytest

from hpc_studio.crystallography.models import Atom, CrystalStructure, Lattice
from hpc_studio.notebook import CellModel, CellType, NotebookDocument, NotebookExporter


@pytest.fixture
def sample_notebook() -> NotebookDocument:
    """Creates a sample notebook containing markdown, code, and magic commands."""
    doc = NotebookDocument()
    # Cell 1: Markdown
    doc.add_cell(
        cell_type=CellType.MARKDOWN,
        source="# Title of Calculation\nThis notebook demonstrates HPC workflows.\nSecond line of explanation.",
    )
    # Cell 2: Code with magic commands and normal Python
    doc.add_cell(
        cell_type=CellType.CODE,
        source="%matplotlib inline\n!nvidia-smi\nimport numpy as np\nx = np.linspace(0, 10, 100)\nprint('Done')",
    )
    # Cell 3: Raw cell
    doc.add_cell(
        cell_type=CellType.RAW,
        source="Raw text notes that should be preserved as comments.",
    )
    return doc


def test_export_to_python(sample_notebook):
    """Test exporting NotebookDocument to clean Python script."""
    py_code = NotebookExporter.export_to_python(sample_notebook)

    # Verify header
    assert "#!/usr/bin/env python3" in py_code
    assert "# -*- coding: utf-8 -*-" in py_code

    # Verify markdown cells are converted to block comments
    assert "# %% [markdown]" in py_code
    assert "# # Title of Calculation" in py_code
    assert "# This notebook demonstrates HPC workflows." in py_code

    # Verify cell markers
    assert "# %% [code] Cell 2" in py_code

    # Verify magic commands are commented out safely
    assert "# [magic/shell] %matplotlib inline" in py_code
    assert "# [magic/shell] !nvidia-smi" in py_code

    # Verify clean code is intact
    assert "import numpy as np" in py_code
    assert "x = np.linspace(0, 10, 100)" in py_code
    assert "print('Done')" in py_code

    # Verify raw cell
    assert "# %% [raw]" in py_code
    assert "# Raw text notes that should be preserved as comments." in py_code


def test_export_to_slurm(sample_notebook):
    """Test generating a production-ready SLURM .sbatch script."""
    slurm_script = NotebookExporter.export_to_slurm(
        sample_notebook,
        job_name="qe_silicon_test",
        nodes=2,
        ntasks=16,
        time="04:30:00",
        partition="gpu-compute",
        mem="32G",
    )

    # Check bash shebang
    assert slurm_script.startswith("#!/bin/bash")

    # Check #SBATCH directives
    assert "#SBATCH --job-name=qe_silicon_test" in slurm_script
    assert "#SBATCH --nodes=2" in slurm_script
    assert "#SBATCH --ntasks=16" in slurm_script
    assert "#SBATCH --time=04:30:00" in slurm_script
    assert "#SBATCH --partition=gpu-compute" in slurm_script
    assert "#SBATCH --mem=32G" in slurm_script
    assert "#SBATCH --output=%x_%j.out" in slurm_script

    # Check module loading commands
    assert "module purge" in slurm_script
    assert "module load python" in slurm_script

    # Check embedded python script execution
    assert "python3 - << 'EOF'" in slurm_script
    assert "import numpy as np" in slurm_script
    assert "# [magic/shell] !nvidia-smi" in slurm_script
    assert "EOF" in slurm_script
    assert "exit $EXIT_CODE" in slurm_script


def test_export_to_qe_input_from_deck():
    """Test extracting Quantum ESPRESSO pw.x input deck from raw/markdown cell."""
    doc = NotebookDocument()
    qe_text = """&CONTROL
  calculation = 'scf'
  prefix = 'silicon'
  outdir = './tmp'
  pseudo_dir = './pseudo'
/
&SYSTEM
  ibrav = 2
  celldm(1) = 10.26
  nat = 2
  ntyp = 1
  ecutwfc = 30.0
/
&ELECTRONS
  conv_thr = 1.0e-8
/
ATOMIC_SPECIES
  Si 28.086 Si.pbe-n-kjpaw_psl.1.0.0.UPF
ATOMIC_POSITIONS {alat}
  Si 0.00 0.00 0.00
  Si 0.25 0.25 0.25
K_POINTS {automatic}
  4 4 4 1 1 1
"""
    # Put deck in a Markdown block with code fence
    doc.add_cell(
        cell_type=CellType.MARKDOWN,
        source=f"Here is the QE calculation configuration:\n```\n{qe_text}```",
    )

    extracted_qe = NotebookExporter.export_to_qe_input(doc)
    assert extracted_qe is not None
    assert "&CONTROL" in extracted_qe
    assert "calculation = 'scf'" in extracted_qe
    assert "&SYSTEM" in extracted_qe
    assert "ibrav = 2" in extracted_qe
    assert "ATOMIC_SPECIES" in extracted_qe
    assert "Si.pbe-n-kjpaw_psl.1.0.0.UPF" in extracted_qe
    assert "ATOMIC_POSITIONS {alat}" in extracted_qe


def test_export_to_qe_input_from_metadata():
    """Test extracting Quantum ESPRESSO input from cell metadata crystal_structure."""
    doc = NotebookDocument()
    lat = Lattice.cubic(5.43)
    atoms = [
        Atom(index=0, symbol="Si", position=(0.0, 0.0, 0.0)),
        Atom(index=1, symbol="Si", position=(1.3575, 1.3575, 1.3575)),
    ]
    struct = CrystalStructure(lattice=lat, atoms=atoms)

    cell = doc.add_cell(
        cell_type=CellType.CODE,
        source="# Build Silicon crystal structure\nstruct = ...",
    )
    cell.metadata["crystal_structure"] = struct

    extracted_qe = NotebookExporter.export_to_qe_input(doc)
    assert extracted_qe is not None
    assert "&CONTROL" in extracted_qe
    assert "ATOMIC_SPECIES" in extracted_qe
    assert "Si" in extracted_qe
    assert "ATOMIC_POSITIONS" in extracted_qe


def test_export_to_qe_input_none_when_absent():
    """Test export_to_qe_input returns None when no QE decks or structures exist."""
    doc = NotebookDocument()
    doc.add_cell(cell_type=CellType.CODE, source="a = 1 + 2\nprint(a)")
    doc.add_cell(cell_type=CellType.MARKDOWN, source="# Plain notebook notes")

    extracted = NotebookExporter.export_to_qe_input(doc)
    assert extracted is None


def test_export_to_slurm_sanitization(sample_notebook):
    """Test export_to_slurm sanitizes parameters to prevent newline injection."""
    script = NotebookExporter.export_to_slurm(
        sample_notebook,
        job_name="test_job\n#SBATCH --wrap='touch /tmp/evil'",
        partition="gpu\nrm -rf /",
        time="01:00:00\n",
        mem="16G; id",
    )
    assert "\n#SBATCH --wrap='touch /tmp/evil'" not in script
    assert "rm -rf /" not in script
    assert "; id" not in script
    assert "#SBATCH --job-name=test_job__SBATCH_--wrap__touch__tmp_evil_" in script
