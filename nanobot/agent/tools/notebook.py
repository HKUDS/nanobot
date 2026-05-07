"""NotebookEditTool — edit Jupyter .ipynb notebooks."""

from __future__ import annotations

import json
import uuid
from typing import Any

from nanobot.agent.tools.base import tool_parameters
from nanobot.agent.tools.schema import IntegerSchema, StringSchema, tool_parameters_schema
from nanobot.agent.tools.filesystem import _FsTool


def _new_cell(source: str, cell_type: str = "code", generate_id: bool = False) -> dict:
    cell: dict[str, Any] = {
        "cell_type": cell_type,
        "source": source,
        "metadata": {},
    }
    if cell_type == "code":
        cell["outputs"] = []
        cell["execution_count"] = None
    if generate_id:
        cell["id"] = uuid.uuid4().hex[:8]
    return cell


def _make_empty_notebook() -> dict:
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "cells": [],
    }


@tool_parameters(
    tool_parameters_schema(
        path=StringSchema("Path to the .ipynb notebook file"),
        cell_index=IntegerSchema(0, description="0-based index of the cell to edit", minimum=0),
        new_source=StringSchema("New source content for the cell"),
        cell_type=StringSchema(
            "Cell type: 'code' or 'markdown' (default: code)",
            enum=["code", "markdown"],
        ),
        edit_mode=StringSchema(
            "Mode: 'replace' (default), 'insert' (after target), or 'delete'",
            enum=["replace", "insert", "delete"],
        ),
        required=["path", "cell_index"],
    )
)
class NotebookEditTool(_FsTool):
    """Edit Jupyter notebook cells: replace, insert, or delete."""

    _VALID_CELL_TYPES = frozenset({"code", "markdown"})
    _VALID_EDIT_MODES = frozenset({"replace", "insert", "delete"})

    @property
    def name(self) -> str:
        return "notebook_edit"

    @property
    def description(self) -> str:
        return (
            "Edit a Jupyter notebook (.ipynb) cell. "
            "Modes: replace (default) replaces cell content, "
            "insert adds a new cell after the target index, "
            "delete removes the cell at the index. "
            "cell_index is 0-based."
        )

    async def execute(
        self,
        path: str | None = None,
        cell_index: int = 0,
        new_source: str = "",
        cell_type: str = "code",
        edit_mode: str = "replace",
        **kwargs: Any,
    ) -> str:
        try:
            if not path:
                return "Error: path is required"

            if not path.endswith(".ipynb"):
                return "Error: notebook_edit only works on .ipynb files. Use edit_file for other files."

            if edit_mode not in self._VALID_EDIT_MODES:
                return (
                    f"Error: Invalid edit_mode '{edit_mode}'. "
                    "Use one of: replace, insert, delete."
                )

            if cell_type not in self._VALID_CELL_TYPES:
                return (
                    f"Error: Invalid cell_type '{cell_type}'. "
                    "Use one of: code, markdown."
                )

            fp = self._resolve(path)

            # Create new notebook if file doesn't exist and mode is insert
            if not fp.exists():
                if edit_mode != "insert":
                    return f"Error: File not found: {path}"
                nb = _make_empty_notebook()
                cell = _new_cell(new_source, cell_type, generate_id=True)
                nb["cells"].append(cell)
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
                return f"Successfully created {fp} with 1 cell"

            try:
                nb = json.loads(fp.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                return f"Error: Failed to parse notebook: {e}"

            cells = nb.get("cells", [])
            nbformat_minor = nb.get("nbformat_minor", 0)
            generate_id = nb.get("nbformat", 0) >= 4 and nbformat_minor >= 5

            if edit_mode == "delete":
                if cell_index < 0 or cell_index >= len(cells):
                    return f"Error: cell_index {cell_index} out of range (notebook has {len(cells)} cells)"
                cells.pop(cell_index)
                nb["cells"] = cells
                fp.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
                return f"Successfully deleted cell {cell_index} from {fp}"

            if edit_mode == "insert":
                insert_at = min(cell_index + 1, len(cells))
                cell = _new_cell(new_source, cell_type, generate_id=generate_id)
                cells.insert(insert_at, cell)
                nb["cells"] = cells
                fp.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
                return f"Successfully inserted cell at index {insert_at} in {fp}"

            # Default: replace
            if cell_index < 0 or cell_index >= len(cells):
                return f"Error: cell_index {cell_index} out of range (notebook has {len(cells)} cells)"
            cells[cell_index]["source"] = new_source
            if cell_type and cells[cell_index].get("cell_type") != cell_type:
                cells[cell_index]["cell_type"] = cell_type
                if cell_type == "code":
                    cells[cell_index].setdefault("outputs", [])
                    cells[cell_index].setdefault("execution_count", None)
                elif "outputs" in cells[cell_index]:
                    del cells[cell_index]["outputs"]
                    cells[cell_index].pop("execution_count", None)
            nb["cells"] = cells
            fp.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
            return f"Successfully edited cell {cell_index} in {fp}"

        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error editing notebook: {e}"
