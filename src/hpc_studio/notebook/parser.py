"""Notebook parser and serializer adhering to nbformat v4 specification."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Union

from .models import CellModel, CellType, NotebookDocument, OutputData


def _split_multiline(text: str) -> list[str]:
    """Split string into lines preserving trailing newlines for nbformat serialization.

    Empty string serializes to [].
    Single line without newline serializes to [text].
    Multiple lines preserve trailing '\n' on all except possibly the last line.
    """
    if not text:
        return []
    lines = text.splitlines(keepends=True)
    return lines


def _format_output_for_nbformat(output: OutputData) -> dict[str, Any]:
    """Convert OutputData into nbformat v4 JSON dict representation."""
    d = output.to_dict()
    # Format text fields in output if they exist
    if "text" in d and isinstance(d["text"], str):
        d["text"] = _split_multiline(d["text"])

    if "data" in d and isinstance(d["data"], dict):
        formatted_data: dict[str, Any] = {}
        for mime_type, val in d["data"].items():
            if isinstance(val, str) and mime_type in (
                "text/plain",
                "text/html",
                "text/latex",
                "text/markdown",
                "application/javascript",
            ):
                formatted_data[mime_type] = _split_multiline(val)
            else:
                formatted_data[mime_type] = val
        d["data"] = formatted_data

    return d


def _format_cell_for_nbformat(cell: CellModel) -> dict[str, Any]:
    """Convert CellModel into nbformat v4 JSON dict representation."""
    d: dict[str, Any] = {
        "cell_type": cell.cell_type.value if isinstance(cell.cell_type, CellType) else str(cell.cell_type),
        "id": cell.cell_id,
        "metadata": dict(cell.metadata),
        "source": _split_multiline(cell.source),
    }

    if cell.collapsed:
        d["metadata"]["collapsed"] = True
    if cell.scrolled:
        d["metadata"]["scrolled"] = True

    if cell.cell_type == CellType.CODE:
        d["execution_count"] = cell.execution_count
        d["outputs"] = [_format_output_for_nbformat(out) for out in cell.outputs]

    return d


class NotebookParser:
    """Parser and serializer for Jupyter Notebook v4 format."""

    @staticmethod
    def parse_string(content: str) -> NotebookDocument:
        """Parse a JSON string containing nbformat v4 data into NotebookDocument.

        Raises:
            ValueError: If JSON is invalid or nbformat structure is missing or incompatible.
        """
        if not content or not content.strip():
            raise ValueError("Notebook content is empty")

        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON format: {e}") from e

        if not isinstance(data, dict):
            raise ValueError("Invalid notebook structure: root must be a JSON object")

        nbformat = data.get("nbformat")
        if nbformat != 4:
            raise ValueError(
                f"Unsupported nbformat version: {nbformat}. Only nbformat v4 is supported."
            )

        nbformat_minor = data.get("nbformat_minor", 5)
        metadata = data.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError("Invalid notebook structure: 'metadata' must be an object")

        raw_cells = data.get("cells")
        if not isinstance(raw_cells, list):
            raise ValueError("Invalid notebook structure: 'cells' must be a list")

        cells: list[CellModel] = []
        for i, cell_data in enumerate(raw_cells):
            if not isinstance(cell_data, dict):
                raise ValueError(f"Invalid cell data at index {i}: cell must be an object")
            cells.append(CellModel.from_dict(cell_data))

        return NotebookDocument(
            nbformat=nbformat,
            nbformat_minor=nbformat_minor,
            metadata=metadata,
            cells=cells,
            is_dirty=False,
        )

    @staticmethod
    def parse_file(file_path: Union[str, Path]) -> NotebookDocument:
        """Read a .ipynb file and parse into NotebookDocument.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If parsing fails or file content is invalid.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Notebook file not found: {file_path}")

        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            raise ValueError(f"Failed to read notebook file '{file_path}': {e}") from e

        doc = NotebookParser.parse_string(content)
        doc.file_path = str(path.resolve())
        doc.is_dirty = False
        return doc

    @staticmethod
    def to_json(doc: NotebookDocument, indent: int = 1) -> str:
        """Serialize a NotebookDocument into nbformat v4 JSON string."""
        nb_dict: dict[str, Any] = {
            "cells": [_format_cell_for_nbformat(cell) for cell in doc.cells],
            "metadata": dict(doc.metadata),
            "nbformat": doc.nbformat,
            "nbformat_minor": doc.nbformat_minor,
        }
        return json.dumps(nb_dict, indent=indent, ensure_ascii=False) + "\n"

    @staticmethod
    def save_file(doc: NotebookDocument, file_path: Union[str, Path]) -> None:
        """Serialize and atomically save NotebookDocument to file.

        Uses atomic write (.tmp -> rename/replace) to prevent file corruption during save.
        Updates doc.file_path and clears doc.is_dirty flag.

        Raises:
            IOError: If writing or renaming fails.
        """
        path = Path(file_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)

        content = NotebookParser.to_json(doc)

        tmp_path = path.with_suffix(f"{path.suffix}.tmp.{os.getpid()}")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())

            # Atomic replace
            tmp_path.replace(path)
            doc.file_path = str(path)
            doc.is_dirty = False
        except Exception as e:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            raise IOError(f"Failed to save notebook to '{path}': {e}") from e
