"""Tests for advanced EditFileTool enhancements inspired by claude-code:
- Delete-line newline cleanup
- Smart quote normalization (curly ↔ straight)
- Quote style preservation in replacements
- Indentation preservation when fallback match is trimmed
- Trailing whitespace stripping for new_text
- File size protection
- Stale detection with content-equality fallback
"""

import os
import time

import pytest

from nanobot.agent.tools.filesystem import EditFileTool, ReadFileTool, _find_match
from nanobot.agent.tools import file_state


@pytest.fixture(autouse=True)
def _clear_file_state():
    file_state.clear()
    yield
    file_state.clear()


# ---------------------------------------------------------------------------
# Delete-line newline cleanup
# ---------------------------------------------------------------------------


class TestDeleteLineCleanup:
    """When new_text='' and deleting a line, trailing newline should be consumed."""

    @pytest.fixture()
    def tool(self, tmp_path):
        return EditFileTool(workspace=tmp_path)

    @pytest.mark.asyncio
    async def test_delete_line_consumes_trailing_newline(self, tool, tmp_path):
        f = tmp_path / "a.py"
        f.write_text("line1\nline2\nline3\n", encoding="utf-8")
        result = await tool.execute(path=str(f), old_text="line2", new_text="")
        assert "Successfully" in result
        content = f.read_text()
        # Should not leave a blank line where line2 was
        assert content == "line1\nline3\n"

    @pytest.mark.asyncio
    async def test_delete_line_with_explicit_newline_in_old_text(self, tool, tmp_path):
        f = tmp_path / "a.py"
        f.write_text("line1\nline2\nline3\n", encoding="utf-8")
        result = await tool.execute(path=str(f), old_text="line2\n", new_text="")
        assert "Successfully" in result
        assert f.read_text() == "line1\nline3\n"

    @pytest.mark.asyncio
    async def test_delete_preserves_content_when_not_trailing_newline(self, tool, tmp_path):
        """Deleting a word mid-line should not consume extra characters."""
        f = tmp_path / "a.py"
        f.write_text("hello world here\n", encoding="utf-8")
        result = await tool.execute(path=str(f), old_text="world ", new_text="")
        assert "Successfully" in result
        assert f.read_text() == "hello here\n"


# ---------------------------------------------------------------------------
# Smart quote normalization
# ---------------------------------------------------------------------------


class TestSmartQuoteNormalization:
    """_find_match should handle curly ↔ straight quote fallback."""

    def test_curly_double_quotes_match_straight(self):
        content = 'She said \u201chello\u201d to him'
        old_text = 'She said "hello" to him'
        match, count = _find_match(content, old_text)
        assert match is not None
        assert count == 1
        # Returned match should be the ORIGINAL content with curly quotes
        assert "\u201c" in match

    def test_curly_single_quotes_match_straight(self):
        content = "it\u2019s a test"
        old_text = "it's a test"
        match, count = _find_match(content, old_text)
        assert match is not None
        assert count == 1
        assert "\u2019" in match

    def test_straight_matches_curly_in_old_text(self):
        content = 'x = "hello"'
        old_text = 'x = \u201chello\u201d'
        match, count = _find_match(content, old_text)
        assert match is not None
        assert count == 1

    def test_exact_match_still_preferred_over_quote_normalization(self):
        content = 'x = "hello"'
        old_text = 'x = "hello"'
        match, count = _find_match(content, old_text)
        assert match == old_text
        assert count == 1


class TestQuoteStylePreservation:
    """When quote-normalized matching occurs, replacement should preserve actual quote style."""

    @pytest.fixture()
    def tool(self, tmp_path):
        return EditFileTool(workspace=tmp_path)

    @pytest.mark.asyncio
    async def test_replacement_preserves_curly_double_quotes(self, tool, tmp_path):
        f = tmp_path / "quotes.txt"
        f.write_text('message = “hello”\n', encoding="utf-8")
        result = await tool.execute(
            path=str(f),
            old_text='message = "hello"',
            new_text='message = "goodbye"',
        )
        assert "Successfully" in result
        assert f.read_text(encoding="utf-8") == 'message = “goodbye”\n'

    @pytest.mark.asyncio
    async def test_replacement_preserves_curly_apostrophe(self, tool, tmp_path):
        f = tmp_path / "apostrophe.txt"
        f.write_text("it’s fine\n", encoding="utf-8")
        result = await tool.execute(
            path=str(f),
            old_text="it's fine",
            new_text="it's better",
        )
        assert "Successfully" in result
        assert f.read_text(encoding="utf-8") == "it’s better\n"


# ---------------------------------------------------------------------------
# Indentation preservation
# ---------------------------------------------------------------------------


class TestIndentationPreservation:
    """Replacement should keep outer indentation when trim fallback matched."""

    @pytest.fixture()
    def tool(self, tmp_path):
        return EditFileTool(workspace=tmp_path)

    @pytest.mark.asyncio
    async def test_trim_fallback_preserves_outer_indentation(self, tool, tmp_path):
        f = tmp_path / "indent.py"
        f.write_text(
            "if True:\n"
            "    def foo():\n"
            "        pass\n",
            encoding="utf-8",
        )
        result = await tool.execute(
            path=str(f),
            old_text="def foo():\n    pass",
            new_text="def bar():\n    return 1",
        )
        assert "Successfully" in result
        assert f.read_text(encoding="utf-8") == (
            "if True:\n"
            "    def bar():\n"
            "        return 1\n"
        )


# ---------------------------------------------------------------------------
# Failure diagnostics
# ---------------------------------------------------------------------------


class TestEditDiagnostics:
    """Failure paths should offer actionable hints."""

    @pytest.fixture()
    def tool(self, tmp_path):
        return EditFileTool(workspace=tmp_path)

    @pytest.mark.asyncio
    async def test_ambiguous_match_reports_candidate_lines(self, tool, tmp_path):
        f = tmp_path / "dup.py"
        f.write_text("aaa\nbbb\naaa\nbbb\n", encoding="utf-8")
        result = await tool.execute(path=str(f), old_text="aaa\nbbb", new_text="xxx")
        assert "appears 2 times" in result.lower()
        assert "line 1" in result.lower()
        assert "line 3" in result.lower()
        assert "replace_all=true" in result

    @pytest.mark.asyncio
    async def test_not_found_reports_whitespace_hint(self, tool, tmp_path):
        f = tmp_path / "space.py"
        f.write_text("value =  1\n", encoding="utf-8")
        result = await tool.execute(path=str(f), old_text="value = 1", new_text="value = 2")
        assert "Error" in result
        assert "whitespace" in result.lower()

    @pytest.mark.asyncio
    async def test_not_found_reports_case_hint(self, tool, tmp_path):
        f = tmp_path / "case.py"
        f.write_text("HelloWorld\n", encoding="utf-8")
        result = await tool.execute(path=str(f), old_text="helloworld", new_text="goodbye")
        assert "Error" in result
        assert "letter case differs" in result.lower()


# ---------------------------------------------------------------------------
# Advanced fallback replacement behavior
# ---------------------------------------------------------------------------


class TestAdvancedReplaceAll:
    """replace_all should work correctly for fallback-based matches too."""

    @pytest.fixture()
    def tool(self, tmp_path):
        return EditFileTool(workspace=tmp_path)

    @pytest.mark.asyncio
    async def test_replace_all_preserves_each_match_indentation(self, tool, tmp_path):
        f = tmp_path / "indent_multi.py"
        f.write_text(
            "if a:\n"
            "    def foo():\n"
            "        pass\n"
            "if b:\n"
            "        def foo():\n"
            "            pass\n",
            encoding="utf-8",
        )
        result = await tool.execute(
            path=str(f),
            old_text="def foo():\n    pass",
            new_text="def bar():\n    return 1",
            replace_all=True,
        )
        assert "Successfully" in result
        assert f.read_text(encoding="utf-8") == (
            "if a:\n"
            "    def bar():\n"
            "        return 1\n"
            "if b:\n"
            "        def bar():\n"
            "            return 1\n"
        )

    @pytest.mark.asyncio
    async def test_trim_and_quote_fallback_match_succeeds(self, tool, tmp_path):
        f = tmp_path / "quote_indent.py"
        f.write_text("    message = “hello”\n", encoding="utf-8")
        result = await tool.execute(
            path=str(f),
            old_text='message = "hello"',
            new_text='message = "goodbye"',
        )
        assert "Successfully" in result
        assert f.read_text(encoding="utf-8") == "    message = “goodbye”\n"


# ---------------------------------------------------------------------------
# Advanced fallback replacement behavior
# ---------------------------------------------------------------------------


class TestAdvancedReplaceAll:
    """replace_all should work correctly for fallback-based matches too."""

    @pytest.fixture()
    def tool(self, tmp_path):
        return EditFileTool(workspace=tmp_path)

    @pytest.mark.asyncio
    async def test_replace_all_preserves_each_match_indentation(self, tool, tmp_path):
        f = tmp_path / "indent_multi.py"
        f.write_text(
            "if a:\n"
            "    def foo():\n"
            "        pass\n"
            "if b:\n"
            "        def foo():\n"
            "            pass\n",
            encoding="utf-8",
        )
        result = await tool.execute(
            path=str(f),
            old_text="def foo():\n    pass",
            new_text="def bar():\n    return 1",
            replace_all=True,
        )
        assert "Successfully" in result
        assert f.read_text(encoding="utf-8") == (
            "if a:\n"
            "    def bar():\n"
            "        return 1\n"
            "if b:\n"
            "        def bar():\n"
            "            return 1\n"
        )

    @pytest.mark.asyncio
    async def test_trim_and_quote_fallback_match_succeeds(self, tool, tmp_path):
        f = tmp_path / "quote_indent.py"
        f.write_text("    message = “hello”\n", encoding="utf-8")
        result = await tool.execute(
            path=str(f),
            old_text='message = "hello"',
            new_text='message = "goodbye"',
        )
        assert "Successfully" in result
        assert f.read_text(encoding="utf-8") == "    message = “goodbye”\n"


# ---------------------------------------------------------------------------
# Trailing whitespace stripping on new_text
# ---------------------------------------------------------------------------


class TestTrailingWhitespaceStrip:
    """new_text trailing whitespace should be stripped (except .md files)."""

    @pytest.fixture()
    def tool(self, tmp_path):
        return EditFileTool(workspace=tmp_path)

    @pytest.mark.asyncio
    async def test_strips_trailing_whitespace_from_new_text(self, tool, tmp_path):
        f = tmp_path / "a.py"
        f.write_text("x = 1\n", encoding="utf-8")
        result = await tool.execute(
            path=str(f), old_text="x = 1", new_text="x = 2   \ny = 3  ",
        )
        assert "Successfully" in result
        content = f.read_text()
        assert "x = 2\ny = 3\n" == content

    @pytest.mark.asyncio
    async def test_preserves_trailing_whitespace_in_markdown(self, tool, tmp_path):
        f = tmp_path / "doc.md"
        f.write_text("# Title\n", encoding="utf-8")
        # Markdown uses trailing double-space for line breaks
        result = await tool.execute(
            path=str(f), old_text="# Title", new_text="# Title  \nSubtitle  ",
        )
        assert "Successfully" in result
        content = f.read_text()
        # Trailing spaces should be preserved for markdown
        assert "Title  " in content
        assert "Subtitle  " in content


# ---------------------------------------------------------------------------
# File size protection
# ---------------------------------------------------------------------------


class TestFileSizeProtection:
    """Editing extremely large files should be rejected."""

    @pytest.fixture()
    def tool(self, tmp_path):
        return EditFileTool(workspace=tmp_path)

    @pytest.mark.asyncio
    async def test_rejects_file_over_size_limit(self, tool, tmp_path):
        f = tmp_path / "huge.txt"
        f.write_text("x", encoding="utf-8")
        # Monkey-patch the file size check by creating a stat mock
        original_stat = f.stat

        class FakeStat:
            def __init__(self, real_stat):
                self._real = real_stat

            def __getattr__(self, name):
                return getattr(self._real, name)

            @property
            def st_size(self):
                return 2 * 1024 * 1024 * 1024  # 2 GiB

        import unittest.mock
        with unittest.mock.patch.object(type(f), 'stat', return_value=FakeStat(f.stat())):
            result = await tool.execute(path=str(f), old_text="x", new_text="y")
        assert "Error" in result
        assert "too large" in result.lower() or "size" in result.lower()


# ---------------------------------------------------------------------------
# Stale detection with content-equality fallback
# ---------------------------------------------------------------------------


class TestStaleDetectionContentFallback:
    """When mtime changed but file content is unchanged, edit should proceed without warning."""

    @pytest.fixture()
    def read_tool(self, tmp_path):
        return ReadFileTool(workspace=tmp_path)

    @pytest.fixture()
    def edit_tool(self, tmp_path):
        return EditFileTool(workspace=tmp_path)

    @pytest.mark.asyncio
    async def test_mtime_bump_same_content_no_warning(self, read_tool, edit_tool, tmp_path):
        f = tmp_path / "a.py"
        f.write_text("hello world", encoding="utf-8")
        await read_tool.execute(path=str(f))

        # Touch the file to bump mtime without changing content
        time.sleep(0.05)
        original_content = f.read_text()
        f.write_text(original_content, encoding="utf-8")

        result = await edit_tool.execute(path=str(f), old_text="world", new_text="earth")
        assert "Successfully" in result
        # Should NOT warn about modification since content is the same
        assert "modified" not in result.lower()
