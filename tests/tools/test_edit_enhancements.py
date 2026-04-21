"""Tests for EditFileTool enhancements: read-before-edit tracking, path suggestions,
.ipynb detection, and create-file semantics."""

import pytest

from nanobot.agent.tools.filesystem import EditFileTool, ReadFileTool, WriteFileTool
from nanobot.agent.tools import file_state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_file_state():
    """Reset global read-state between tests."""
    file_state.clear()
    yield
    file_state.clear()


# ---------------------------------------------------------------------------
# Read-before-edit tracking
# ---------------------------------------------------------------------------

class TestEditReadTracking:
    """edit_file should warn when file hasn't been read first."""

    @pytest.fixture()
    def read_tool(self, tmp_path):
        return ReadFileTool(workspace=tmp_path)

    @pytest.fixture()
    def edit_tool(self, tmp_path):
        return EditFileTool(workspace=tmp_path)

    @pytest.mark.asyncio
    async def test_edit_warns_if_file_not_read_first(self, edit_tool, tmp_path):
        f = tmp_path / "a.py"
        f.write_text("hello world", encoding="utf-8")
        result = await edit_tool.execute(path=str(f), old_text="world", new_text="earth")
        # Should still succeed but include a warning
        assert "Successfully" in result
        assert "not been read" in result.lower() or "warning" in result.lower()

    @pytest.mark.asyncio
    async def test_edit_succeeds_cleanly_after_read(self, read_tool, edit_tool, tmp_path):
        f = tmp_path / "a.py"
        f.write_text("hello world", encoding="utf-8")
        await read_tool.execute(path=str(f))
        result = await edit_tool.execute(path=str(f), old_text="world", new_text="earth")
        assert "Successfully" in result
        # No warning when file was read first
        assert "not been read" not in result.lower()
        assert f.read_text() == "hello earth"

    @pytest.mark.asyncio
    async def test_edit_warns_if_file_modified_since_read(self, read_tool, edit_tool, tmp_path):
        f = tmp_path / "a.py"
        f.write_text("hello world", encoding="utf-8")
        await read_tool.execute(path=str(f))
        # External modification
        f.write_text("hello universe", encoding="utf-8")
        result = await edit_tool.execute(path=str(f), old_text="universe", new_text="earth")
        assert "Successfully" in result
        assert "modified" in result.lower() or "warning" in result.lower()


# ---------------------------------------------------------------------------
# Create-file semantics
# ---------------------------------------------------------------------------

class TestEditCreateFile:
    """edit_file with old_text='' creates new file if not exists."""

    @pytest.fixture()
    def tool(self, tmp_path):
        return EditFileTool(workspace=tmp_path)

    @pytest.mark.asyncio
    async def test_create_new_file_with_empty_old_text(self, tool, tmp_path):
        f = tmp_path / "subdir" / "new.py"
        result = await tool.execute(path=str(f), old_text="", new_text="print('hi')")
        assert "created" in result.lower() or "Successfully" in result
        assert f.exists()
        assert f.read_text() == "print('hi')"

    @pytest.mark.asyncio
    async def test_create_fails_if_file_already_exists_and_not_empty(self, tool, tmp_path):
        f = tmp_path / "existing.py"
        f.write_text("existing content", encoding="utf-8")
        result = await tool.execute(path=str(f), old_text="", new_text="new content")
        assert "Error" in result or "already exists" in result.lower()
        # File should be unchanged
        assert f.read_text() == "existing content"

    @pytest.mark.asyncio
    async def test_create_succeeds_if_file_exists_but_empty(self, tool, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("", encoding="utf-8")
        result = await tool.execute(path=str(f), old_text="", new_text="print('hi')")
        assert "Successfully" in result
        assert f.read_text() == "print('hi')"


# ---------------------------------------------------------------------------
# .ipynb detection
# ---------------------------------------------------------------------------

class TestEditIpynbDetection:
    """edit_file should refuse .ipynb and suggest notebook_edit."""

    @pytest.fixture()
    def tool(self, tmp_path):
        return EditFileTool(workspace=tmp_path)

    @pytest.mark.asyncio
    async def test_ipynb_rejected_with_suggestion(self, tool, tmp_path):
        f = tmp_path / "analysis.ipynb"
        f.write_text('{"cells": []}', encoding="utf-8")
        result = await tool.execute(path=str(f), old_text="x", new_text="y")
        assert "notebook" in result.lower()


# ---------------------------------------------------------------------------
# Path suggestion on not-found
# ---------------------------------------------------------------------------

class TestEditPathSuggestion:
    """edit_file should suggest similar paths on not-found."""

    @pytest.fixture()
    def tool(self, tmp_path):
        return EditFileTool(workspace=tmp_path)

    @pytest.mark.asyncio
    async def test_suggests_similar_filename(self, tool, tmp_path):
        f = tmp_path / "config.py"
        f.write_text("x = 1", encoding="utf-8")
        # Typo: conifg.py
        result = await tool.execute(
            path=str(tmp_path / "conifg.py"), old_text="x = 1", new_text="x = 2",
        )
        assert "Error" in result
        assert "config.py" in result

    @pytest.mark.asyncio
    async def test_shows_cwd_in_error(self, tool, tmp_path):
        result = await tool.execute(
            path=str(tmp_path / "nonexistent.py"), old_text="a", new_text="b",
        )
        assert "Error" in result
