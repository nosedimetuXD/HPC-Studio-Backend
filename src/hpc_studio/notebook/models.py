"""Notebook data models conforming to nbformat v4.5 specification."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
import uuid
from typing import Any, Optional, Union


class CellType(str, Enum):
    """Supported cell types in Jupyter Notebooks."""
    CODE = "code"
    MARKDOWN = "markdown"
    RAW = "raw"


OutputMimeBundle = dict[str, Any]


@dataclass
class OutputData:
    """Represents an execution output in a notebook code cell.

    Conforms to Jupyter nbformat v4 output types:
    - stream: stdout / stderr text
    - display_data: rich mime-bundle data without execution_count
    - execute_result: rich mime-bundle data resulting from cell evaluation
    - error: traceback and exception information
    """
    output_type: str  # "stream", "display_data", "execute_result", "error"
    name: Optional[str] = None  # "stdout", "stderr" (for stream)
    text: Optional[str] = None  # (for stream)
    data: OutputMimeBundle = field(default_factory=dict)  # (for display_data / execute_result)
    metadata: dict[str, Any] = field(default_factory=dict)
    execution_count: Optional[int] = None  # (for execute_result)
    ename: Optional[str] = None  # (for error)
    evalue: Optional[str] = None  # (for error)
    traceback: list[str] = field(default_factory=list)  # (for error, ANSI colored strings)

    def to_dict(self) -> dict[str, Any]:
        """Convert output to nbformat-compliant dict."""
        res: dict[str, Any] = {"output_type": self.output_type}
        if self.output_type == "stream":
            res["name"] = self.name or "stdout"
            text_str = self.text or ""
            # In nbformat JSON, multiline strings are serialized as lists of lines or a single string
            res["text"] = text_str
        elif self.output_type in ("display_data", "execute_result"):
            res["data"] = dict(self.data)
            res["metadata"] = dict(self.metadata)
            if self.output_type == "execute_result":
                res["execution_count"] = self.execution_count
        elif self.output_type == "error":
            res["ename"] = self.ename or ""
            res["evalue"] = self.evalue or ""
            res["traceback"] = list(self.traceback)
        else:
            # Fallback for custom or unknown output types
            if self.name:
                res["name"] = self.name
            if self.text is not None:
                res["text"] = self.text
            if self.data:
                res["data"] = dict(self.data)
            if self.metadata:
                res["metadata"] = dict(self.metadata)
            if self.execution_count is not None:
                res["execution_count"] = self.execution_count
            if self.ename:
                res["ename"] = self.ename
            if self.evalue:
                res["evalue"] = self.evalue
            if self.traceback:
                res["traceback"] = list(self.traceback)
        return res

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OutputData:
        """Construct OutputData from raw nbformat output dict."""
        output_type = data.get("output_type", "display_data")
        raw_text = data.get("text")
        if isinstance(raw_text, list):
            text = "".join(raw_text)
        elif raw_text is not None:
            text = str(raw_text)
        else:
            text = None

        raw_traceback = data.get("traceback")
        if isinstance(raw_traceback, list):
            traceback = [str(line) for line in raw_traceback]
        elif raw_traceback is not None:
            traceback = [str(raw_traceback)]
        else:
            traceback = []

        raw_data = data.get("data")
        mime_data: OutputMimeBundle = {}
        if isinstance(raw_data, dict):
            for mime_type, val in raw_data.items():
                if isinstance(val, list):
                    mime_data[mime_type] = "".join(val)
                else:
                    mime_data[mime_type] = val

        return cls(
            output_type=output_type,
            name=data.get("name"),
            text=text,
            data=mime_data,
            metadata=dict(data.get("metadata", {})),
            execution_count=data.get("execution_count"),
            ename=data.get("ename"),
            evalue=data.get("evalue"),
            traceback=traceback,
        )


@dataclass
class CellModel:
    """Represents a single notebook cell."""
    cell_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    cell_type: CellType = CellType.CODE
    source: str = ""
    outputs: list[OutputData] = field(default_factory=list)
    execution_count: Optional[int] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    collapsed: bool = False
    scrolled: bool = False

    @property
    def id(self) -> str:
        """Alias for cell_id."""
        return self.cell_id

    def add_output(self, output: OutputData) -> None:
        """Append an execution output to the cell."""
        self.outputs.append(output)

    def clear_outputs(self) -> None:
        """Clear all execution outputs and reset execution count."""
        self.outputs.clear()
        self.execution_count = None

    def to_dict(self) -> dict[str, Any]:
        """Convert cell to nbformat-compliant dict."""
        d: dict[str, Any] = {
            "cell_type": self.cell_type.value if isinstance(self.cell_type, CellType) else str(self.cell_type),
            "id": self.cell_id,
            "metadata": dict(self.metadata),
            "source": self.source,
        }
        if self.collapsed:
            d["metadata"]["collapsed"] = True
        if self.scrolled:
            d["metadata"]["scrolled"] = True

        if self.cell_type == CellType.CODE:
            d["execution_count"] = self.execution_count
            d["outputs"] = [out.to_dict() for out in self.outputs]
        elif self.cell_type == CellType.RAW:
            # Raw cells do not have execution_count or outputs
            pass
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CellModel:
        """Construct CellModel from raw nbformat cell dict."""
        cell_type_str = data.get("cell_type", "code")
        try:
            cell_type = CellType(cell_type_str)
        except ValueError:
            cell_type = CellType.RAW

        cell_id = data.get("id") or uuid.uuid4().hex[:8]
        raw_source = data.get("source", "")
        if isinstance(raw_source, list):
            source = "".join(raw_source)
        else:
            source = str(raw_source)

        meta = dict(data.get("metadata", {}))
        collapsed = bool(meta.get("collapsed", False))
        scrolled = bool(meta.get("scrolled", False))

        outputs: list[OutputData] = []
        raw_outputs = data.get("outputs", [])
        if isinstance(raw_outputs, list):
            for out in raw_outputs:
                if isinstance(out, dict):
                    outputs.append(OutputData.from_dict(out))

        execution_count = data.get("execution_count")

        return cls(
            cell_id=cell_id,
            cell_type=cell_type,
            source=source,
            outputs=outputs,
            execution_count=execution_count,
            metadata=meta,
            collapsed=collapsed,
            scrolled=scrolled,
        )


@dataclass
class NotebookDocument:
    """Document model representing an entire Jupyter Notebook."""
    nbformat: int = 4
    nbformat_minor: int = 5
    metadata: dict[str, Any] = field(default_factory=lambda: {
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3"
        },
        "language_info": {
            "name": "python",
            "version": "3.10.0",
            "mimetype": "text/x-python",
            "file_extension": ".py"
        }
    })
    cells: list[CellModel] = field(default_factory=list)
    file_path: Optional[str] = None
    is_dirty: bool = False

    def add_cell(
        self,
        cell_type: CellType = CellType.CODE,
        index: Optional[int] = None,
        source: str = ""
    ) -> CellModel:
        """Create and add a new cell to the notebook.

        Args:
            cell_type: CellType ("code", "markdown", "raw")
            index: Insertion index. If None, appends to the end.
            source: Initial source text for the cell.

        Returns:
            The created CellModel instance.
        """
        cell = CellModel(
            cell_id=uuid.uuid4().hex[:8],
            cell_type=cell_type,
            source=source,
        )
        if index is None or index >= len(self.cells):
            self.cells.append(cell)
        else:
            idx = max(0, index)
            self.cells.insert(idx, cell)
        self.is_dirty = True
        return cell

    def remove_cell(self, index_or_id: Union[int, str]) -> bool:
        """Remove a cell by index or cell_id.

        Returns:
            True if cell was found and removed, False otherwise.
        """
        if isinstance(index_or_id, int):
            if 0 <= index_or_id < len(self.cells):
                del self.cells[index_or_id]
                self.is_dirty = True
                return True
            return False

        for i, cell in enumerate(self.cells):
            if cell.cell_id == index_or_id:
                del self.cells[i]
                self.is_dirty = True
                return True
        return False

    def move_cell(self, from_index: int, to_index: int) -> bool:
        """Move cell from from_index to to_index.

        Returns:
            True if move succeeded, False if indices are invalid.
        """
        n = len(self.cells)
        if not (0 <= from_index < n and 0 <= to_index < n):
            return False
        if from_index == to_index:
            return True

        cell = self.cells.pop(from_index)
        self.cells.insert(to_index, cell)
        self.is_dirty = True
        return True

    def get_cell(self, index_or_id: Union[int, str]) -> Optional[CellModel]:
        """Retrieve a cell by its index or cell_id."""
        if isinstance(index_or_id, int):
            if 0 <= index_or_id < len(self.cells):
                return self.cells[index_or_id]
            return None

        for cell in self.cells:
            if cell.cell_id == index_or_id:
                return cell
        return None

    def clear_all_outputs(self) -> None:
        """Clear outputs and execution count for all cells."""
        for cell in self.cells:
            if cell.cell_type == CellType.CODE:
                cell.clear_outputs()
        self.is_dirty = True

    def clear_cell_outputs(self, index_or_id: Union[int, str]) -> bool:
        """Clear outputs and execution count for a specific cell.

        Returns:
            True if cell was found and outputs cleared, False otherwise.
        """
        cell = self.get_cell(index_or_id)
        if cell is not None and cell.cell_type == CellType.CODE:
            cell.clear_outputs()
            self.is_dirty = True
            return True
        return False


def _sanitize_html(raw_html: str) -> str:
    """Sanitize HTML by stripping harmful script tags, iframe, object, embed, and dangerous handlers."""
    if not raw_html:
        return ""
    # Remove all script tags (with or without closing tag)
    cleaned = re.sub(r"(?is)<script\b[^>]*>.*?(?:</script>|$)", "", raw_html)
    # Remove iframe, object, embed, applet, form, meta, link, base
    cleaned = re.sub(r"(?is)<(iframe|object|embed|applet|form|meta|link|base)\b[^>]*>.*?(?:</\1>|$)", "", cleaned)
    cleaned = re.sub(r"(?is)<(iframe|object|embed|applet|form|meta|link|base)\b[^>]*/>", "", cleaned)
    # Remove all event handlers on* (regardless of spacing or delimiters like / or newline)
    cleaned = re.sub(r'(?i)[\s/]+on[a-z]+\s*=\s*(?:"[^"]*"|\'[^\']*\'|[^\s>]+)', " ", cleaned)
    # Remove dangerous schemes (javascript:, vbscript:, file:, data: except data:image/)
    cleaned = re.sub(
        r'(?i)(href|src|action)\s*=\s*(?:"\s*(?:javascript|vbscript|file|data:(?!image\/))[^"]*"|\'\s*(?:javascript|vbscript|file|data:(?!image\/))[^\']*\'|(?:javascript|vbscript|file|data:(?!image\/))[^\s>]+)',
        "",
        cleaned,
    )
    return cleaned

