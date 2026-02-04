import pytest

from nanobot.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool


@pytest.mark.asyncio
async def test_read_file_success(tmp_path) -> None:
    p = tmp_path / "a.txt"
    p.write_text("hello", encoding="utf-8")

    tool = ReadFileTool()
    out = await tool.execute(str(p))
    assert out == "hello"


@pytest.mark.asyncio
async def test_read_file_missing_and_not_a_file(tmp_path) -> None:
    tool = ReadFileTool()

    missing = tmp_path / "missing.txt"
    out = await tool.execute(str(missing))
    assert "Error: File not found" in out

    out = await tool.execute(str(tmp_path))
    assert "Error: Not a file" in out


@pytest.mark.asyncio
async def test_write_file_creates_parents_and_writes(tmp_path) -> None:
    tool = WriteFileTool()

    p = tmp_path / "nested" / "dir" / "b.txt"
    out = await tool.execute(str(p), "hello")
    assert "Successfully wrote 5 bytes" in out
    assert p.read_text(encoding="utf-8") == "hello"


@pytest.mark.asyncio
async def test_edit_file_replaces_once_and_validates_old_text(tmp_path) -> None:
    tool = EditFileTool()

    p = tmp_path / "c.txt"
    p.write_text("abc", encoding="utf-8")

    out = await tool.execute(str(p), "b", "B")
    assert out == f"Successfully edited {p}"
    assert p.read_text(encoding="utf-8") == "aBc"

    out = await tool.execute(str(p), "NOT_FOUND", "x")
    assert "old_text not found" in out


@pytest.mark.asyncio
async def test_edit_file_warns_on_multiple_matches_and_does_not_modify(tmp_path) -> None:
    tool = EditFileTool()

    p = tmp_path / "d.txt"
    p.write_text("x x x", encoding="utf-8")

    out = await tool.execute(str(p), "x", "y")
    assert "Warning: old_text appears 3 times" in out
    assert p.read_text(encoding="utf-8") == "x x x"


@pytest.mark.asyncio
async def test_list_dir_empty_and_lists_items(tmp_path) -> None:
    tool = ListDirTool()

    out = await tool.execute(str(tmp_path))
    assert "is empty" in out

    (tmp_path / "a_dir").mkdir()
    (tmp_path / "b.txt").write_text("ok", encoding="utf-8")

    out = await tool.execute(str(tmp_path))
    lines = out.splitlines()
    assert len(lines) == 2

    # Sorted order, and suffix matches the item names.
    assert lines[0].endswith("a_dir")
    assert lines[1].endswith("b.txt")


@pytest.mark.asyncio
async def test_list_dir_missing_and_not_a_directory(tmp_path) -> None:
    tool = ListDirTool()

    missing = tmp_path / "missing"
    out = await tool.execute(str(missing))
    assert "Error: Directory not found" in out

    f = tmp_path / "e.txt"
    f.write_text("ok", encoding="utf-8")
    out = await tool.execute(str(f))
    assert "Error: Not a directory" in out
