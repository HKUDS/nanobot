"""Tests for NotebookEditTool — Jupyter .ipynb editing."""

import json

import pytest

from nanobot.agent.tools.notebook import NotebookEditTool


def _make_notebook(cells: list[dict] | None = None, nbformat: int = 4, nbformat_minor: int = 5) -> dict:
    """Build a minimal valid .ipynb structure."""
    return {
        "nbformat": nbformat,
        "nbformat_minor": nbformat_minor,
        "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}},
        "cells": cells or [],
    }


def _code_cell(source: str, cell_id: str | None = None) -> dict:
    cell = {"cell_type": "code", "source": source, "metadata": {}, "outputs": [], "execution_count": None}
    if cell_id:
        cell["id"] = cell_id
    return cell


def _md_cell(source: str, cell_id: str | None = None) -> dict:
    cell = {"cell_type": "markdown", "source": source, "metadata": {}}
    if cell_id:
        cell["id"] = cell_id
    return cell


def _write_nb(tmp_path, name: str, nb: dict) -> str:
    p = tmp_path / name
    p.write_text(json.dumps(nb), encoding="utf-8")
    return str(p)


class TestNotebookEdit:

    @pytest.fixture()
    def tool(self, tmp_path):
        return NotebookEditTool(workspace=tmp_path)

    @pytest.mark.asyncio
    async def test_replace_cell_content(self, tool, tmp_path):
        nb = _make_notebook([_code_cell("print('hello')"), _code_cell("x = 1")])
        path = _write_nb(tmp_path, "test.ipynb", nb)
        result = await tool.execute(path=path, cell_index=0, new_source="print('world')")
        assert "Successfully" in result
        saved = json.loads((tmp_path / "test.ipynb").read_text())
        assert saved["cells"][0]["source"] == "print('world')"
        assert saved["cells"][1]["source"] == "x = 1"

    @pytest.mark.asyncio
    async def test_insert_cell_after_target(self, tool, tmp_path):
        nb = _make_notebook([_code_cell("cell 0"), _code_cell("cell 1")])
        path = _write_nb(tmp_path, "test.ipynb", nb)
        result = await tool.execute(path=path, cell_index=0, new_source="inserted", edit_mode="insert")
        assert "Successfully" in result
        saved = json.loads((tmp_path / "test.ipynb").read_text())
        assert len(saved["cells"]) == 3
        assert saved["cells"][0]["source"] == "cell 0"
        assert saved["cells"][1]["source"] == "inserted"
        assert saved["cells"][2]["source"] == "cell 1"

    @pytest.mark.asyncio
    async def test_delete_cell(self, tool, tmp_path):
        nb = _make_notebook([_code_cell("A"), _code_cell("B"), _code_cell("C")])
        path = _write_nb(tmp_path, "test.ipynb", nb)
        result = await tool.execute(path=path, cell_index=1, edit_mode="delete")
        assert "Successfully" in result
        saved = json.loads((tmp_path / "test.ipynb").read_text())
        assert len(saved["cells"]) == 2
        assert saved["cells"][0]["source"] == "A"
        assert saved["cells"][1]["source"] == "C"

    @pytest.mark.asyncio
    async def test_create_new_notebook_from_scratch(self, tool, tmp_path):
        path = str(tmp_path / "new.ipynb")
        result = await tool.execute(path=path, cell_index=0, new_source="# Hello", edit_mode="insert", cell_type="markdown")
        assert "Successfully" in result or "created" in result.lower()
        saved = json.loads((tmp_path / "new.ipynb").read_text())
        assert saved["nbformat"] == 4
        assert len(saved["cells"]) == 1
        assert saved["cells"][0]["cell_type"] == "markdown"
        assert saved["cells"][0]["source"] == "# Hello"

    @pytest.mark.asyncio
    async def test_invalid_cell_index_error(self, tool, tmp_path):
        nb = _make_notebook([_code_cell("only cell")])
        path = _write_nb(tmp_path, "test.ipynb", nb)
        result = await tool.execute(path=path, cell_index=5, new_source="x")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_non_ipynb_rejected(self, tool, tmp_path):
        f = tmp_path / "script.py"
        f.write_text("pass")
        result = await tool.execute(path=str(f), cell_index=0, new_source="x")
        assert "Error" in result
        assert ".ipynb" in result

    @pytest.mark.asyncio
    async def test_preserves_metadata_and_outputs(self, tool, tmp_path):
        cell = _code_cell("old")
        cell["outputs"] = [{"output_type": "stream", "text": "hello\n"}]
        cell["execution_count"] = 42
        nb = _make_notebook([cell])
        path = _write_nb(tmp_path, "test.ipynb", nb)
        await tool.execute(path=path, cell_index=0, new_source="new")
        saved = json.loads((tmp_path / "test.ipynb").read_text())
        assert saved["metadata"]["kernelspec"]["language"] == "python"

    @pytest.mark.asyncio
    async def test_nbformat_45_generates_cell_id(self, tool, tmp_path):
        nb = _make_notebook([], nbformat_minor=5)
        path = _write_nb(tmp_path, "test.ipynb", nb)
        await tool.execute(path=path, cell_index=0, new_source="x = 1", edit_mode="insert")
        saved = json.loads((tmp_path / "test.ipynb").read_text())
        assert "id" in saved["cells"][0]
        assert len(saved["cells"][0]["id"]) > 0

    @pytest.mark.asyncio
    async def test_insert_with_cell_type_markdown(self, tool, tmp_path):
        nb = _make_notebook([_code_cell("code")])
        path = _write_nb(tmp_path, "test.ipynb", nb)
        await tool.execute(path=path, cell_index=0, new_source="# Title", edit_mode="insert", cell_type="markdown")
        saved = json.loads((tmp_path / "test.ipynb").read_text())
        assert saved["cells"][1]["cell_type"] == "markdown"

    @pytest.mark.asyncio
    async def test_invalid_edit_mode_rejected(self, tool, tmp_path):
        nb = _make_notebook([_code_cell("code")])
        path = _write_nb(tmp_path, "test.ipynb", nb)
        result = await tool.execute(path=path, cell_index=0, new_source="x", edit_mode="replcae")
        assert "Error" in result
        assert "edit_mode" in result

    @pytest.mark.asyncio
    async def test_invalid_cell_type_rejected(self, tool, tmp_path):
        nb = _make_notebook([_code_cell("code")])
        path = _write_nb(tmp_path, "test.ipynb", nb)
        result = await tool.execute(path=path, cell_index=0, new_source="x", cell_type="raw")
        assert "Error" in result
        assert "cell_type" in result
