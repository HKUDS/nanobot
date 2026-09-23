"""Tests for EditFileTool enhancements: read-independent editing, path suggestions,
notebook JSON editing, and create-file semantics."""

import os

import pytest

from nanobot.agent.tools import file_state
from nanobot.agent.tools.apply_patch import ApplyPatchTool
from nanobot.agent.tools.filesystem import EditFileTool, ReadFileTool

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
# Read-independent editing
# ---------------------------------------------------------------------------

class TestEditReadTracking:
    """edit_file validates current contents independently of prior reads."""

    @pytest.fixture()
    def file_states(self):
        return file_state.FileStates()

    @pytest.fixture()
    def read_tool(self, tmp_path, file_states):
        return ReadFileTool(workspace=tmp_path, file_states=file_states)

    @pytest.fixture()
    def edit_tool(self, tmp_path, file_states):
        return EditFileTool(workspace=tmp_path, file_states=file_states)

    @pytest.mark.asyncio
    async def test_edit_does_not_warn_without_read_record(self, edit_tool, tmp_path):
        f = tmp_path / "a.py"
        f.write_text("hello world", encoding="utf-8")
        result = await edit_tool.execute(path=str(f), old_text="world", new_text="earth")
        assert result == "Patch applied:\n- update a.py (+1/-1)"
        assert f.read_text() == "hello earth"

    @pytest.mark.asyncio
    async def test_edit_succeeds_cleanly_after_read(self, read_tool, edit_tool, tmp_path):
        f = tmp_path / "a.py"
        f.write_text("hello world", encoding="utf-8")
        await read_tool.execute(path=str(f))
        result = await edit_tool.execute(path=str(f), old_text="world", new_text="earth")
        assert result == "Patch applied:\n- update a.py (+1/-1)"
        assert f.read_text() == "hello earth"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("reread", ["none", "read_file", "shell"])
    async def test_edit_after_file_modified_since_read(
        self, read_tool, edit_tool, tmp_path, reread,
    ):
        f = tmp_path / "a.py"
        f.write_text("hello world", encoding="utf-8")
        await read_tool.execute(path=str(f))
        # External modification
        mtime = f.stat().st_mtime
        f.write_text("hello universe", encoding="utf-8")
        os.utime(f, (mtime + 2, mtime + 2))
        if reread == "read_file":
            assert "hello universe" in await read_tool.execute(path=str(f))
        elif reread == "shell":
            import subprocess
            import sys

            read = subprocess.run(
                [sys.executable, "-c", "from pathlib import Path; import sys; print(Path(sys.argv[1]).read_text())", str(f)],
                capture_output=True, text=True, check=True,
            )
            assert read.stdout.strip() == "hello universe"
        result = await edit_tool.execute(path=str(f), old_text="universe", new_text="earth")
        summary = "Patch applied:\n- update a.py (+1/-1)"
        assert result == summary
        assert f.read_text() == "hello earth"


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
        assert result == "Patch applied:\n- add subdir/new.py (+1/-0)"
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
        assert result == "Patch applied:\n- update empty.py (+1/-0)"
        assert f.read_text() == "print('hi')"


# ---------------------------------------------------------------------------
# .ipynb editing
# ---------------------------------------------------------------------------

class TestEditIpynbFiles:
    """edit_file edits notebooks as normal JSON files."""

    @pytest.fixture()
    def tool(self, tmp_path):
        return EditFileTool(workspace=tmp_path)

    @pytest.mark.asyncio
    async def test_ipynb_can_be_edited_as_json(self, tool, tmp_path):
        f = tmp_path / "analysis.ipynb"
        f.write_text('{"cells": []}', encoding="utf-8")
        result = await tool.execute(
            path=str(f),
            old_text='"cells": []',
            new_text='"cells": [{"cell_type": "markdown", "source": "hi"}]',
        )
        assert "Patch applied:" in result
        assert '"source": "hi"' in f.read_text(encoding="utf-8")


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


async def test_edit_summary_matches_apply_patch(tmp_path):
    states = file_state.FileStates()
    target = tmp_path / "config.toml"
    target.write_bytes(b"a = 1\n")
    edited = await EditFileTool(workspace=tmp_path, file_states=states).execute(
        path="config.toml", old_text="1", new_text="2",
    )
    target.write_bytes(b"a = 1\n")
    patched = await ApplyPatchTool(workspace=tmp_path, file_states=states).execute(
        edits=[{"path": "config.toml", "action": "replace", "old_text": "1", "new_text": "2"}],
    )
    assert patched == "Patch applied:\n- update config.toml (+1/-1)"
    assert edited == patched
