"""Tests for notebook parser and serializer."""

import json
from pathlib import Path
import pytest
from hpc_studio.notebook.models import (
    CellType,
    NotebookDocument,
    OutputData,
)
from hpc_studio.notebook.parser import NotebookParser, _split_multiline


SAMPLE_NB_JSON = """{
 "cells": [
  {
   "cell_type": "markdown",
   "id": "md-1",
   "metadata": {},
   "source": [
    "# Quantum ESPRESSO Calculation\\n",
    "Running SCF calculation."
   ]
  },
  {
   "cell_type": "code",
   "execution_count": 1,
   "id": "code-1",
   "metadata": {},
   "outputs": [
    {
     "name": "stdout",
     "output_type": "stream",
     "text": [
      "Starting PWscf...\\n",
      "Iteration 1 complete.\\n"
     ]
    }
   ],
   "source": [
    "print('Starting PWscf...')\\n",
    "print('Iteration 1 complete.')"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": 2,
   "id": "code-2",
   "metadata": {},
   "outputs": [
    {
     "data": {
      "text/plain": [
       "<Figure size 640x480>"
      ],
      "image/png": "iVBORw0KGgoAAAANSUhEUgAA..."
     },
     "metadata": {},
     "output_type": "display_data"
    }
   ],
   "source": [
    "plot_convergence()"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": 3,
   "id": "code-3",
   "metadata": {},
   "outputs": [
    {
     "ename": "ConvergenceError",
     "evalue": "SCF did not converge in 100 iterations",
     "output_type": "error",
     "traceback": [
      "\\u001b[0;31mConvergenceError\\u001b[0m: SCF did not converge"
     ]
    }
   ],
   "source": [
    "raise ConvergenceError('SCF did not converge')"
   ]
  }
 ],
 "metadata": {
  "kernelspec": {
   "display_name": "Python 3",
   "language": "python",
   "name": "python3"
  },
  "language_info": {
   "name": "python",
   "version": "3.10.0"
  }
 },
 "nbformat": 4,
 "nbformat_minor": 5
}
"""


def test_split_multiline_helper():
    assert _split_multiline("") == []
    assert _split_multiline("hello") == ["hello"]
    assert _split_multiline("hello\nworld") == ["hello\n", "world"]
    assert _split_multiline("hello\nworld\n") == ["hello\n", "world\n"]


def test_parse_sample_notebook():
    doc = NotebookParser.parse_string(SAMPLE_NB_JSON)
    assert doc.nbformat == 4
    assert doc.nbformat_minor == 5
    assert len(doc.cells) == 4

    # Cell 0: markdown
    c0 = doc.cells[0]
    assert c0.cell_id == "md-1"
    assert c0.cell_type == CellType.MARKDOWN
    assert c0.source == "# Quantum ESPRESSO Calculation\nRunning SCF calculation."

    # Cell 1: stream output
    c1 = doc.cells[1]
    assert c1.cell_id == "code-1"
    assert c1.cell_type == CellType.CODE
    assert c1.execution_count == 1
    assert len(c1.outputs) == 1
    out1 = c1.outputs[0]
    assert out1.output_type == "stream"
    assert out1.name == "stdout"
    assert out1.text == "Starting PWscf...\nIteration 1 complete.\n"

    # Cell 2: display_data
    c2 = doc.cells[2]
    assert c2.cell_id == "code-2"
    assert len(c2.outputs) == 1
    out2 = c2.outputs[0]
    assert out2.output_type == "display_data"
    assert out2.data["text/plain"] == "<Figure size 640x480>"
    assert out2.data["image/png"] == "iVBORw0KGgoAAAANSUhEUgAA..."

    # Cell 3: error traceback
    c3 = doc.cells[3]
    assert c3.cell_id == "code-3"
    assert len(c3.outputs) == 1
    out3 = c3.outputs[0]
    assert out3.output_type == "error"
    assert out3.ename == "ConvergenceError"
    assert out3.evalue == "SCF did not converge in 100 iterations"
    assert len(out3.traceback) == 1
    assert "ConvergenceError" in out3.traceback[0]


def test_round_trip_fidelity(tmp_path: Path):
    doc = NotebookParser.parse_string(SAMPLE_NB_JSON)
    save_file = tmp_path / "test_roundtrip.ipynb"

    NotebookParser.save_file(doc, save_file)
    assert save_file.exists()
    assert doc.file_path == str(save_file)
    assert not doc.is_dirty

    # Reload and verify
    reloaded = NotebookParser.parse_file(save_file)
    assert reloaded.nbformat == doc.nbformat
    assert reloaded.nbformat_minor == doc.nbformat_minor
    assert len(reloaded.cells) == len(doc.cells)

    for orig, rel in zip(doc.cells, reloaded.cells):
        assert orig.cell_id == rel.cell_id
        assert orig.cell_type == rel.cell_type
        assert orig.source == rel.source
        assert orig.execution_count == rel.execution_count
        assert len(orig.outputs) == len(rel.outputs)
        for out_orig, out_rel in zip(orig.outputs, rel.outputs):
            assert out_orig.output_type == out_rel.output_type
            assert out_orig.name == out_rel.name
            assert out_orig.text == out_rel.text
            assert out_orig.ename == out_rel.ename
            assert out_orig.traceback == out_rel.traceback
            assert out_orig.data == out_rel.data


def test_atomic_save_and_modification(tmp_path: Path):
    doc = NotebookDocument()
    cell = doc.add_cell(CellType.CODE, source="x = 42\nx")
    cell.outputs.append(OutputData(
        output_type="execute_result",
        execution_count=1,
        data={"text/plain": "42"}
    ))
    cell.execution_count = 1

    file_path = tmp_path / "subdir" / "new_calc.ipynb"
    NotebookParser.save_file(doc, file_path)

    assert file_path.exists()
    # Check no leftover .tmp files
    tmp_files = list(file_path.parent.glob("*.tmp*"))
    assert len(tmp_files) == 0

    # Modify cell, save again
    doc.add_cell(CellType.MARKDOWN, source="Finished")
    NotebookParser.save_file(doc, file_path)

    reloaded = NotebookParser.parse_file(file_path)
    assert len(reloaded.cells) == 2
    assert reloaded.cells[1].source == "Finished"


def test_defensive_parser_errors(tmp_path: Path):
    # Empty string
    with pytest.raises(ValueError, match="empty"):
        NotebookParser.parse_string("")

    # Invalid JSON
    with pytest.raises(ValueError, match="Invalid JSON"):
        NotebookParser.parse_string("{not valid json")

    # Non-dict root
    with pytest.raises(ValueError, match="must be a JSON object"):
        NotebookParser.parse_string("[]")

    # Unsupported nbformat
    with pytest.raises(ValueError, match="Unsupported nbformat version"):
        NotebookParser.parse_string('{"nbformat": 3, "metadata": {}, "cells": []}')

    # Missing/invalid cells
    with pytest.raises(ValueError, match="'cells' must be a list"):
        NotebookParser.parse_string('{"nbformat": 4, "metadata": {}, "cells": "invalid"}')

    # Non-existent file
    non_existent = tmp_path / "does_not_exist.ipynb"
    with pytest.raises(FileNotFoundError):
        NotebookParser.parse_file(non_existent)
