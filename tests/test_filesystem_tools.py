"""Tests for enhanced filesystem tools: ReadFileTool, EditFileTool, ListDirTool."""

import pytest

from nanobot.agent.tools.filesystem import (
    EditFileTool,
    ListDirTool,
    ReadFileTool,
    _find_match,
)


# ---------------------------------------------------------------------------
# ReadFileTool
# ---------------------------------------------------------------------------

class TestReadFileTool:

    @pytest.fixture()
    def tool(self, tmp_path):
        return ReadFileTool(workspace=tmp_path)

    @pytest.fixture()
    def sample_file(self, tmp_path):
        f = tmp_path / "sample.txt"
        f.write_text("\n".join(f"line {i}" for i in range(1, 21)), encoding="utf-8")
        return f

    @pytest.mark.asyncio
    async def test_basic_read_has_line_numbers(self, tool, sample_file):
        result = await tool.execute(path=str(sample_file))
        assert "1| line 1" in result
        assert "20| line 20" in result

    @pytest.mark.asyncio
    async def test_offset_and_limit(self, tool, sample_file):
        result = await tool.execute(path=str(sample_file), offset=5, limit=3)
        assert "5| line 5" in result
        assert "7| line 7" in result
        assert "8| line 8" not in result
        assert "Use offset=8 to continue" in result

    @pytest.mark.asyncio
    async def test_offset_beyond_end(self, tool, sample_file):
        result = await tool.execute(path=str(sample_file), offset=999)
        assert "Error" in result
        assert "beyond end" in result

    @pytest.mark.asyncio
    async def test_end_of_file_marker(self, tool, sample_file):
        result = await tool.execute(path=str(sample_file), offset=1, limit=9999)
        assert "End of file" in result

    @pytest.mark.asyncio
    async def test_empty_file(self, tool, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("", encoding="utf-8")
        result = await tool.execute(path=str(f))
        assert "Empty file" in result

    @pytest.mark.asyncio
    async def test_file_not_found(self, tool, tmp_path):
        result = await tool.execute(path=str(tmp_path / "nope.txt"))
        assert "Error" in result
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_char_budget_trims(self, tool, tmp_path):
        """When the selected slice exceeds _MAX_CHARS the output is trimmed."""
        f = tmp_path / "big.txt"
        # Each line is ~110 chars, 2000 lines ≈ 220 KB > 128 KB limit
        f.write_text("\n".join("x" * 110 for _ in range(2000)), encoding="utf-8")
        result = await tool.execute(path=str(f))
        assert len(result) <= ReadFileTool._MAX_CHARS + 500  # small margin for footer
        assert "Use offset=" in result


# ---------------------------------------------------------------------------
# _find_match  (unit tests for the helper)
# ---------------------------------------------------------------------------

class TestFindMatch:

    def test_exact_match(self):
        match, count = _find_match("hello world", "world")
        assert match == "world"
        assert count == 1

    def test_exact_no_match(self):
        match, count = _find_match("hello world", "xyz")
        assert match is None
        assert count == 0

    def test_crlf_normalisation(self):
        # Caller normalises CRLF before calling _find_match, so test with
        # pre-normalised content to verify exact match still works.
        content = "line1\nline2\nline3"
        old_text = "line1\nline2\nline3"
        match, count = _find_match(content, old_text)
        assert match is not None
        assert count == 1

    def test_line_trim_fallback(self):
        content = "    def foo():\n        pass\n"
        old_text = "def foo():\n    pass"
        match, count = _find_match(content, old_text)
        assert match is not None
        assert count == 1
        # The returned match should be the *original* indented text
        assert "    def foo():" in match

    def test_line_trim_multiple_candidates(self):
        content = "  a\n  b\n  a\n  b\n"
        old_text = "a\nb"
        match, count = _find_match(content, old_text)
        assert count == 2

    def test_empty_old_text(self):
        match, count = _find_match("hello", "")
        # Empty string is always "in" any string via exact match
        assert match == ""


# ---------------------------------------------------------------------------
# EditFileTool
# ---------------------------------------------------------------------------

class TestEditFileTool:

    @pytest.fixture()
    def tool(self, tmp_path):
        return EditFileTool(workspace=tmp_path)

    @pytest.mark.asyncio
    async def test_exact_match(self, tool, tmp_path):
        f = tmp_path / "a.py"
        f.write_text("hello world", encoding="utf-8")
        result = await tool.execute(path=str(f), old_text="world", new_text="earth")
        assert "Successfully" in result
        assert f.read_text() == "hello earth"

    @pytest.mark.asyncio
    async def test_crlf_normalisation(self, tool, tmp_path):
        f = tmp_path / "crlf.py"
        f.write_bytes(b"line1\r\nline2\r\nline3")
        result = await tool.execute(
            path=str(f), old_text="line1\nline2", new_text="LINE1\nLINE2",
        )
        assert "Successfully" in result
        raw = f.read_bytes()
        assert b"LINE1" in raw
        # CRLF line endings should be preserved throughout the file
        assert b"\r\n" in raw

    @pytest.mark.asyncio
    async def test_trim_fallback(self, tool, tmp_path):
        f = tmp_path / "indent.py"
        f.write_text("    def foo():\n        pass\n", encoding="utf-8")
        result = await tool.execute(
            path=str(f), old_text="def foo():\n    pass", new_text="def bar():\n    return 1",
        )
        assert "Successfully" in result
        assert "bar" in f.read_text()

    @pytest.mark.asyncio
    async def test_ambiguous_match(self, tool, tmp_path):
        f = tmp_path / "dup.py"
        f.write_text("aaa\nbbb\naaa\nbbb\n", encoding="utf-8")
        result = await tool.execute(path=str(f), old_text="aaa\nbbb", new_text="xxx")
        assert "appears" in result.lower() or "Warning" in result

    @pytest.mark.asyncio
    async def test_replace_all(self, tool, tmp_path):
        f = tmp_path / "multi.py"
        f.write_text("foo bar foo bar foo", encoding="utf-8")
        result = await tool.execute(
            path=str(f), old_text="foo", new_text="baz", replace_all=True,
        )
        assert "Successfully" in result
        assert f.read_text() == "baz bar baz bar baz"

    @pytest.mark.asyncio
    async def test_not_found(self, tool, tmp_path):
        f = tmp_path / "nf.py"
        f.write_text("hello", encoding="utf-8")
        result = await tool.execute(path=str(f), old_text="xyz", new_text="abc")
        assert "Error" in result
        assert "not found" in result


# ---------------------------------------------------------------------------
# ListDirTool
# ---------------------------------------------------------------------------

class TestListDirTool:

    @pytest.fixture()
    def tool(self, tmp_path):
        return ListDirTool(workspace=tmp_path)

    @pytest.fixture()
    def populated_dir(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("pass")
        (tmp_path / "src" / "utils.py").write_text("pass")
        (tmp_path / "README.md").write_text("hi")
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("x")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "pkg").mkdir()
        return tmp_path

    @pytest.mark.asyncio
    async def test_basic_list(self, tool, populated_dir):
        result = await tool.execute(path=str(populated_dir))
        assert "README.md" in result
        assert "src" in result
        # .git and node_modules should be ignored
        assert ".git" not in result
        assert "node_modules" not in result

    @pytest.mark.asyncio
    async def test_recursive(self, tool, populated_dir):
        result = await tool.execute(path=str(populated_dir), recursive=True)
        # Normalize path separators for cross-platform compatibility
        normalized = result.replace("\\", "/")
        assert "src/main.py" in normalized
        assert "src/utils.py" in normalized
        assert "README.md" in result
        # Ignored dirs should not appear
        assert ".git" not in result
        assert "node_modules" not in result

    @pytest.mark.asyncio
    async def test_max_entries_truncation(self, tool, tmp_path):
        for i in range(10):
            (tmp_path / f"file_{i}.txt").write_text("x")
        result = await tool.execute(path=str(tmp_path), max_entries=3)
        assert "truncated" in result
        assert "3 of 10" in result

    @pytest.mark.asyncio
    async def test_empty_dir(self, tool, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        result = await tool.execute(path=str(d))
        assert "empty" in result.lower()

    @pytest.mark.asyncio
    async def test_not_found(self, tool, tmp_path):
        result = await tool.execute(path=str(tmp_path / "nope"))
        assert "Error" in result
        assert "not found" in result
