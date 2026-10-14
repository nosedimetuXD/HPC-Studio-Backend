"""Tests for notebook data models."""

import pytest
from hpc_studio.notebook.models import (
    CellModel,
    CellType,
    NotebookDocument,
    OutputData,
)


def test_default_notebook_document_creation():
    doc = NotebookDocument()
    assert doc.nbformat == 4
    assert doc.nbformat_minor == 5
    assert len(doc.cells) == 0
    assert not doc.is_dirty
    assert "kernelspec" in doc.metadata
    assert doc.metadata["kernelspec"]["name"] == "python3"


def test_add_cell_ordering_and_defaults():
    doc = NotebookDocument()
    cell1 = doc.add_cell(CellType.CODE, source="print('hello')")
    assert len(doc.cells) == 1
    assert cell1.cell_type == CellType.CODE
    assert cell1.source == "print('hello')"
    assert doc.is_dirty

    # Append markdown cell
    cell2 = doc.add_cell(CellType.MARKDOWN, source="# Title")
    assert len(doc.cells) == 2
    assert doc.cells[1] == cell2

    # Insert at beginning
    cell0 = doc.add_cell(CellType.RAW, index=0, source="raw text")
    assert len(doc.cells) == 3
    assert doc.cells[0] == cell0
    assert doc.cells[1] == cell1
    assert doc.cells[2] == cell2


def test_remove_cell_by_index_and_id():
    doc = NotebookDocument()
    c1 = doc.add_cell(CellType.CODE, source="c1")
    c2 = doc.add_cell(CellType.CODE, source="c2")
    c3 = doc.add_cell(CellType.CODE, source="c3")

    # Remove by invalid index
    assert not doc.remove_cell(10)
    assert not doc.remove_cell(-1)
    assert len(doc.cells) == 3

    # Remove by index
    assert doc.remove_cell(1)
    assert len(doc.cells) == 2
    assert doc.cells[0] == c1
    assert doc.cells[1] == c3

    # Remove by id
    assert doc.remove_cell(c1.cell_id)
    assert len(doc.cells) == 1
    assert doc.cells[0] == c3

    # Remove by nonexistent id
    assert not doc.remove_cell("nonexistent-id")
    assert len(doc.cells) == 1


def test_move_cell():
    doc = NotebookDocument()
    c1 = doc.add_cell(CellType.CODE, source="1")
    c2 = doc.add_cell(CellType.CODE, source="2")
    c3 = doc.add_cell(CellType.CODE, source="3")

    # Out of bounds moves
    assert not doc.move_cell(-1, 2)
    assert not doc.move_cell(0, 5)

    # Move same index
    assert doc.move_cell(1, 1)
    assert [c.source for c in doc.cells] == ["1", "2", "3"]

    # Move first to last
    assert doc.move_cell(0, 2)
    assert [c.source for c in doc.cells] == ["2", "3", "1"]

    # Move last to first
    assert doc.move_cell(2, 0)
    assert [c.source for c in doc.cells] == ["1", "2", "3"]


def test_get_cell():
    doc = NotebookDocument()
    c1 = doc.add_cell(CellType.CODE, source="cell1")
    c2 = doc.add_cell(CellType.MARKDOWN, source="cell2")

    assert doc.get_cell(0) == c1
    assert doc.get_cell(1) == c2
    assert doc.get_cell(2) is None
    assert doc.get_cell(c1.cell_id) == c1
    assert doc.get_cell(c2.cell_id) == c2
    assert doc.get_cell("unknown") is None


def test_clear_cell_and_all_outputs():
    doc = NotebookDocument()
    c1 = doc.add_cell(CellType.CODE, source="1+1")
    c1.execution_count = 1
    c1.outputs.append(OutputData(
        output_type="execute_result",
        execution_count=1,
        data={"text/plain": "2"}
    ))

    c2 = doc.add_cell(CellType.CODE, source="import sys; sys.stderr.write('err')")
    c2.execution_count = 2
    c2.outputs.append(OutputData(
        output_type="stream",
        name="stderr",
        text="err"
    ))

    c3 = doc.add_cell(CellType.MARKDOWN, source="text")

    # Clear individual cell output
    assert doc.clear_cell_outputs(c1.cell_id)
    assert len(c1.outputs) == 0
    assert c1.execution_count is None
    assert len(c2.outputs) == 1

    # Re-add output to c1 and clear all
    c1.outputs.append(OutputData(output_type="stream", name="stdout", text="ok"))
    c1.execution_count = 3
    doc.clear_all_outputs()

    assert len(c1.outputs) == 0
    assert c1.execution_count is None
    assert len(c2.outputs) == 0
    assert c2.execution_count is None


def test_cell_model_to_and_from_dict():
    out = OutputData(
        output_type="error",
        ename="ValueError",
        evalue="invalid argument",
        traceback=["Traceback (most recent call last):", "ValueError: invalid argument"]
    )
    cell = CellModel(
        cell_id="abc123",
        cell_type=CellType.CODE,
        source="raise ValueError('invalid argument')",
        outputs=[out],
        execution_count=4,
        metadata={"collapsed": True, "scrolled": False},
        collapsed=True,
    )

    d = cell.to_dict()
    assert d["cell_type"] == "code"
    assert d["id"] == "abc123"
    assert d["execution_count"] == 4
    assert len(d["outputs"]) == 1
    assert d["outputs"][0]["output_type"] == "error"
    assert d["outputs"][0]["ename"] == "ValueError"

    restored = CellModel.from_dict(d)
    assert restored.cell_id == cell.cell_id
    assert restored.cell_type == cell.cell_type
    assert restored.source == cell.source
    assert restored.execution_count == cell.execution_count
    assert restored.collapsed is True
    assert len(restored.outputs) == 1
    assert restored.outputs[0].output_type == "error"
    assert restored.outputs[0].ename == "ValueError"
    assert restored.outputs[0].traceback == out.traceback
