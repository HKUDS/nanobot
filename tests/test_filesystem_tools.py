"""Tests for nanobot.agent.tools.filesystem — file system tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.agent.tools.filesystem import (
    EditFileTool,
    ListDirTool,
    ReadFileTool,
    WriteFileTool,
    _resolve_path,  # noqa: PLC2701
)

# ---------------------------------------------------------------------------
# _resolve_path
# ---------------------------------------------------------------------------


class TestResolvePath:
    def test_absolute_path(self, tmp_path: Path):
        target = tmp_path / "file.txt"
        target.touch()
        result = _resolve_path(str(target))
        assert result == target.resolve()

    def test_relative_path_with_workspace(self, tmp_path: Path):
        (tmp_path / "sub").mkdir()
        result = _resolve_path("sub", workspace=tmp_path)
        assert result == (tmp_path / "sub").resolve()

    def test_allowed_dir_ok(self, tmp_path: Path):
        target = tmp_path / "file.txt"
        target.touch()
        result = _resolve_path(str(target), allowed_dir=tmp_path)
        assert result == target.resolve()

    def test_allowed_dir_violation(self, tmp_path: Path):
        with pytest.raises(PermissionError, match="outside allowed directory"):
            _resolve_path("/etc/passwd", allowed_dir=tmp_path)


# ---------------------------------------------------------------------------
# ReadFileTool
# ---------------------------------------------------------------------------


class TestReadFileTool:
    async def test_read_existing_file(self, tmp_path: Path):
        f = tmp_path / "hello.txt"
        f.write_text("hello world", encoding="utf-8")
        tool = ReadFileTool(workspace=tmp_path, allowed_dir=tmp_path)
        result = await tool.execute(path=str(f))
        assert result.success
        assert result.output == "hello world"

    async def test_read_missing_file(self, tmp_path: Path):
        tool = ReadFileTool(workspace=tmp_path, allowed_dir=tmp_path)
        result = await tool.execute(path=str(tmp_path / "nope.txt"))
        assert not result.success
        assert "not found" in result.output.lower()

    async def test_read_directory_fails(self, tmp_path: Path):
        tool = ReadFileTool(workspace=tmp_path, allowed_dir=tmp_path)
        result = await tool.execute(path=str(tmp_path))
        assert not result.success
        assert "Not a file" in result.output

    async def test_read_outside_allowed_dir(self, tmp_path: Path):
        tool = ReadFileTool(workspace=tmp_path, allowed_dir=tmp_path)
        result = await tool.execute(path="/etc/hostname")
        assert not result.success
        assert "outside" in result.output.lower()


# ---------------------------------------------------------------------------
# WriteFileTool
# ---------------------------------------------------------------------------


class TestWriteFileTool:
    async def test_write_new_file(self, tmp_path: Path):
        tool = WriteFileTool(workspace=tmp_path, allowed_dir=tmp_path)
        result = await tool.execute(path=str(tmp_path / "out.txt"), content="written")
        assert result.success
        assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "written"

    async def test_write_creates_parent_dirs(self, tmp_path: Path):
        tool = WriteFileTool(workspace=tmp_path, allowed_dir=tmp_path)
        target = tmp_path / "a" / "b" / "c.txt"
        result = await tool.execute(path=str(target), content="deep")
        assert result.success
        assert target.read_text(encoding="utf-8") == "deep"

    async def test_write_outside_allowed_dir(self, tmp_path: Path):
        tool = WriteFileTool(workspace=tmp_path, allowed_dir=tmp_path)
        result = await tool.execute(path="/tmp/nanobot_test_illegal.txt", content="x")
        assert not result.success


# ---------------------------------------------------------------------------
# EditFileTool
# ---------------------------------------------------------------------------


class TestEditFileTool:
    async def test_edit_replaces_text(self, tmp_path: Path):
        f = tmp_path / "src.py"
        f.write_text("foo = 1\nbar = 2\n", encoding="utf-8")
        tool = EditFileTool(workspace=tmp_path, allowed_dir=tmp_path)
        result = await tool.execute(path=str(f), old_text="foo = 1", new_text="foo = 42")
        assert result.success
        assert "foo = 42" in f.read_text(encoding="utf-8")

    async def test_edit_missing_file(self, tmp_path: Path):
        tool = EditFileTool(workspace=tmp_path, allowed_dir=tmp_path)
        result = await tool.execute(
            path=str(tmp_path / "nope.py"), old_text="a", new_text="b"
        )
        assert not result.success
        assert "not found" in result.output.lower()

    async def test_edit_text_not_found(self, tmp_path: Path):
        f = tmp_path / "src.py"
        f.write_text("hello world\n", encoding="utf-8")
        tool = EditFileTool(workspace=tmp_path, allowed_dir=tmp_path)
        result = await tool.execute(path=str(f), old_text="nonexistent", new_text="x")
        assert not result.success
        assert "not found" in result.output.lower()

    async def test_edit_ambiguous_multiple_matches(self, tmp_path: Path):
        f = tmp_path / "dup.py"
        f.write_text("x = 1\nx = 1\n", encoding="utf-8")
        tool = EditFileTool(workspace=tmp_path, allowed_dir=tmp_path)
        result = await tool.execute(path=str(f), old_text="x = 1", new_text="x = 2")
        assert not result.success
        assert "2 times" in result.output

    async def test_edit_similar_text_shows_diff(self, tmp_path: Path):
        f = tmp_path / "sim.py"
        f.write_text("foo_bar = 1\nbaz = 2\n", encoding="utf-8")
        tool = EditFileTool(workspace=tmp_path, allowed_dir=tmp_path)
        result = await tool.execute(path=str(f), old_text="foo_baz = 1", new_text="x")
        assert not result.success
        assert "similar" in result.output.lower()

    async def test_edit_no_similar_text(self, tmp_path: Path):
        f = tmp_path / "no_match.py"
        f.write_text("completely different content\n", encoding="utf-8")
        tool = EditFileTool(workspace=tmp_path, allowed_dir=tmp_path)
        result = await tool.execute(
            path=str(f),
            old_text="zzzzzzzzzzzzz nothing remotely close",
            new_text="x",
        )
        assert not result.success
        assert "no similar" in result.output.lower()

    async def test_edit_outside_allowed_dir(self, tmp_path: Path):
        tool = EditFileTool(workspace=tmp_path, allowed_dir=tmp_path)
        result = await tool.execute(path="/etc/passwd", old_text="a", new_text="b")
        assert not result.success


# ---------------------------------------------------------------------------
# ListDirTool
# ---------------------------------------------------------------------------


class TestListDirTool:
    async def test_list_directory(self, tmp_path: Path):
        (tmp_path / "file.txt").touch()
        (tmp_path / "subdir").mkdir()
        tool = ListDirTool(workspace=tmp_path, allowed_dir=tmp_path)
        result = await tool.execute(path=str(tmp_path))
        assert result.success
        assert "file.txt" in result.output
        assert "subdir" in result.output

    async def test_list_empty_directory(self, tmp_path: Path):
        empty = tmp_path / "empty"
        empty.mkdir()
        tool = ListDirTool(workspace=tmp_path, allowed_dir=tmp_path)
        result = await tool.execute(path=str(empty))
        assert result.success
        assert "empty" in result.output.lower()

    async def test_list_missing_directory(self, tmp_path: Path):
        tool = ListDirTool(workspace=tmp_path, allowed_dir=tmp_path)
        result = await tool.execute(path=str(tmp_path / "nope"))
        assert not result.success
        assert "not found" in result.output.lower()

    async def test_list_file_not_directory(self, tmp_path: Path):
        f = tmp_path / "file.txt"
        f.touch()
        tool = ListDirTool(workspace=tmp_path, allowed_dir=tmp_path)
        result = await tool.execute(path=str(f))
        assert not result.success
        assert "Not a directory" in result.output

    async def test_list_outside_allowed_dir(self, tmp_path: Path):
        tool = ListDirTool(workspace=tmp_path, allowed_dir=tmp_path)
        result = await tool.execute(path="/etc")
        assert not result.success
