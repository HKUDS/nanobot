import os

import pytest

from nanobot.agent.tools.filesystem import EditFileTool, ReadFileTool


class TestDeleteLineCleanup:

    @pytest.fixture()
    def tool(self, tmp_path):
        return EditFileTool(workspace=tmp_path)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
    @pytest.mark.parametrize("prefix", ["", "line1\n"], ids=["first-line", "later-line"])
    @pytest.mark.parametrize("indent", ["", "    "], ids=["unindented", "indented"])
    async def test_delete_line_consumes_trailing_newline(
        self, tool, tmp_path, newline, prefix, indent,
    ):
        f = tmp_path / "a.py"
        content = f"{prefix}{indent}line2\nline3\n"
        f.write_bytes(content.replace("\n", newline).encode("utf-8"))
        result = await tool.execute(path=str(f), old_text=f"{indent}line2", new_text="")
        assert "Patch applied:" in result
        assert f.read_bytes() == f"{prefix}line3\n".replace("\n", newline).encode("utf-8")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
    @pytest.mark.parametrize("prefix", ["", "header = 0\n"], ids=["first-line", "later-line"])
    @pytest.mark.parametrize("old_text", ["  # obsolete", "  # obsolete\n# extra comment"])
    async def test_delete_inline_suffix_preserves_trailing_newline(
        self, tool, tmp_path, newline, prefix, old_text,
    ):
        f = tmp_path / "a.py"
        content = f"{prefix}x = 1{old_text}\ny = 2\n"
        f.write_bytes(content.replace("\n", newline).encode("utf-8"))
        result = await tool.execute(path=str(f), old_text=old_text, new_text="")
        assert "Patch applied:" in result
        expected = f"{prefix}x = 1\ny = 2\n"
        assert f.read_bytes() == expected.replace("\n", newline).encode("utf-8")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
    async def test_delete_all_distinguishes_inline_suffixes_from_whole_lines(
        self, tool, tmp_path, newline,
    ):
        f = tmp_path / "a.py"
        content = "x = 1  # obsolete\n  # obsolete\ny = 2  # obsolete\nz = 3\n"
        f.write_bytes(content.replace("\n", newline).encode("utf-8"))
        result = await tool.execute(
            path=str(f), old_text="  # obsolete", new_text="", replace_all=True,
        )
        assert "Patch applied:" in result
        expected = "x = 1\ny = 2\nz = 3\n"
        assert f.read_bytes() == expected.replace("\n", newline).encode("utf-8")

    @pytest.mark.asyncio
    async def test_delete_line_with_explicit_newline_in_old_text(self, tool, tmp_path):
        f = tmp_path / "a.py"
        f.write_text("line1\nline2\nline3\n", encoding="utf-8")
        result = await tool.execute(path=str(f), old_text="line2\n", new_text="")
        assert "Patch applied:" in result
        assert f.read_text() == "line1\nline3\n"

    @pytest.mark.asyncio
    async def test_delete_preserves_content_when_not_trailing_newline(self, tool, tmp_path):
        f = tmp_path / "a.py"
        f.write_text("hello world here\n", encoding="utf-8")
        result = await tool.execute(path=str(f), old_text="world ", new_text="")
        assert "Patch applied:" in result
        assert f.read_text() == "hello here\n"


class TestQuoteStylePreservation:

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
        assert "Patch applied:" in result
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
        assert "Patch applied:" in result
        assert f.read_text(encoding="utf-8") == "it’s better\n"


class TestIndentationPreservation:

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
        assert "Patch applied:" in result
        assert f.read_text(encoding="utf-8") == (
            "if True:\n"
            "    def bar():\n"
            "        return 1\n"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
    @pytest.mark.parametrize("ending", ["", "\n"], ids=["no-request-newline", "request-newline"])
    @pytest.mark.parametrize(
        "tail", ["\nnext_step()\n", "\n", ""],
        ids=["followed-by-code", "terminated-eof", "unterminated-eof"],
    )
    async def test_trim_fallback_preserves_indentation_and_line_endings(
        self, tool, tmp_path, newline, ending, tail,
    ):
        f = tmp_path / "indent.py"
        content = "if ready:\n    x = 1\n    y = 2" + tail
        f.write_bytes(content.replace("\n", newline).encode("utf-8"))
        result = await tool.execute(
            path=str(f),
            old_text=("x = 1\ny = 2" + ending).replace("\n", newline),
            new_text=("x = 3\ny = 4" + ending).replace("\n", newline),
        )
        assert "Patch applied:" in result
        expected = "if ready:\n    x = 3\n    y = 4" + (tail or ending)
        assert f.read_bytes() == expected.replace("\n", newline).encode("utf-8")
        compile(f.read_text(encoding="utf-8"), str(f), "exec")


class TestEditDiagnostics:

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


class TestAdvancedReplaceAll:

    @pytest.fixture()
    def tool(self, tmp_path):
        return EditFileTool(workspace=tmp_path)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("ending", ["", "\n"], ids=["no-request-newline", "request-newline"])
    async def test_replace_all_preserves_each_match_indentation(self, tool, tmp_path, ending):
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
            old_text="def foo():\n    pass" + ending,
            new_text="def bar():\n    return 1" + ending,
            replace_all=True,
        )
        assert "Patch applied:" in result
        assert f.read_text(encoding="utf-8") == (
            "if a:\n"
            "    def bar():\n"
            "        return 1\n"
            "if b:\n"
            "        def bar():\n"
            "            return 1\n"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("ending", ["", "\n"], ids=["no-request-newline", "request-newline"])
    async def test_trim_and_quote_fallback_match_succeeds(self, tool, tmp_path, ending):
        f = tmp_path / "quote_indent.py"
        f.write_text("    message = “hello”\n", encoding="utf-8")
        result = await tool.execute(
            path=str(f),
            old_text='message = "hello"' + ending,
            new_text='message = "goodbye"' + ending,
        )
        assert "Patch applied:" in result
        assert f.read_text(encoding="utf-8") == "    message = “goodbye”\n"


class TestTrailingWhitespaceStrip:

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
        assert "Patch applied:" in result
        content = f.read_text()
        assert "x = 2\ny = 3\n" == content

    @pytest.mark.asyncio
    @pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
    @pytest.mark.parametrize(
        "before,old_text,new_text,expected",
        [
            ("return value\n", "return ", "yield ", "yield value\n"),
            ("return value\n", "return ", "yield\t", "yield\tvalue\n"),
            ("hello-world\n", "-", " ", "hello world\n"),
            (
                "return value\n", "return ", "ready = True  \nyield ",
                "ready = True\nyield value\n",
            ),
        ],
        ids=["space", "tab", "whitespace-only", "multiline"],
    )
    async def test_inline_replacement_preserves_separator(
        self, tool, tmp_path, newline, before, old_text, new_text, expected,
    ):
        f = tmp_path / "inline.py"
        f.write_bytes(before.replace("\n", newline).encode("utf-8"))
        result = await tool.execute(
            path=str(f), old_text=old_text.replace("\n", newline),
            new_text=new_text.replace("\n", newline),
        )
        assert "Patch applied:" in result
        assert f.read_bytes() == expected.replace("\n", newline).encode("utf-8")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
    async def test_replace_all_cleans_only_actual_line_endings(self, tool, tmp_path, newline):
        f = tmp_path / "mixed.txt"
        f.write_bytes("old value\nold \nold    \nold ".replace("\n", newline).encode("utf-8"))
        result = await tool.execute(
            path=str(f), old_text="old ", new_text="new ", replace_all=True,
        )
        assert "Patch applied:" in result
        expected = "new value\nnew\nnew   \nnew"
        assert f.read_bytes() == expected.replace("\n", newline).encode("utf-8")

    @pytest.mark.asyncio
    async def test_preserves_trailing_whitespace_in_markdown(self, tool, tmp_path):
        f = tmp_path / "doc.md"
        f.write_text("# Title\n", encoding="utf-8")
        # Markdown uses trailing double-space for line breaks
        result = await tool.execute(
            path=str(f), old_text="# Title", new_text="# Title  \nSubtitle  ",
        )
        assert "Patch applied:" in result
        content = f.read_text()
        assert "Title  " in content
        assert "Subtitle  " in content


class TestFileSizeProtection:

    @pytest.fixture()
    def tool(self, tmp_path):
        return EditFileTool(workspace=tmp_path)

    @pytest.mark.asyncio
    async def test_rejects_file_over_size_limit(self, tool, tmp_path):
        f = tmp_path / "huge.txt"
        f.write_text("x", encoding="utf-8")

        class FakeStat:
            def __init__(self, real_stat):
                self._real = real_stat

            def __getattr__(self, name):
                return getattr(self._real, name)

            @property
            def st_size(self):
                return 2 * 1024 * 1024 * 1024

        import unittest.mock
        with unittest.mock.patch.object(type(f), 'stat', return_value=FakeStat(f.stat())):
            result = await tool.execute(path=str(f), old_text="x", new_text="y")
        assert "Error" in result
        assert "too large" in result.lower() or "size" in result.lower()


class TestStaleDetectionContentFallback:

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

        stat = f.stat()
        os.utime(f, (stat.st_atime, stat.st_mtime + 10))

        result = await edit_tool.execute(path=str(f), old_text="world", new_text="earth")
        assert "Patch applied:" in result
        assert "modified" not in result.lower()
