import base64
import codecs
import hashlib
import os
import sys
import tracemalloc
from unittest.mock import patch

import pytest

from nanobot.agent.tools import file_state
from nanobot.agent.tools.filesystem import ReadFileTool, WriteFileTool
from nanobot.utils.document import (
    DocumentExtractionError,
    DocumentLineSource,
    LocatedDocumentLine,
)


class _ReadStreamWrapper:
    def __init__(self, stream):
        self.stream = stream

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return self.stream.__exit__(*args)


def _document_source(text: str) -> DocumentLineSource:
    lines = (
        LocatedDocumentLine(line, line_no, "")
        for line_no, line in enumerate(text.splitlines(), 1)
    )
    return DocumentLineSource(lines)


class TestReadDescriptionFix:

    def test_description_mentions_image_support(self):
        tool = ReadFileTool()
        assert "image" in tool.description.lower()


class TestReadDedup:

    @pytest.fixture()
    def tool(self, tmp_path):
        return ReadFileTool(workspace=tmp_path)

    @pytest.fixture()
    def write_tool(self, tmp_path):
        return WriteFileTool(workspace=tmp_path)

    @pytest.mark.asyncio
    async def test_second_read_returns_unchanged_stub(self, tool, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("\n".join(f"line {i}" for i in range(100)), encoding="utf-8")
        with file_state.file_read_context("read-1", lambda: {}):
            first = await tool.execute(path=str(f))
        assert "line 0" in first
        with file_state.file_read_context("read-2", lambda: {"read-1": first}):
            second = await tool.execute(path=str(f))
        assert "unchanged" in second.lower()
        assert "line 0" not in second

    @pytest.mark.asyncio
    async def test_visible_unchanged_receipt_skips_text_parsing(self, tool, tmp_path, monkeypatch):
        f = tmp_path / "data.txt"
        f.write_text("one\ntwo\n", encoding="utf-8")
        with file_state.file_read_context("read-1", lambda: {}):
            first = await tool.execute(path=str(f), limit=1)

        def fail_parse(*_args):
            raise AssertionError("unchanged content must not be parsed again")

        monkeypatch.setattr(tool, "_read_text", fail_parse)
        with file_state.file_read_context("read-2", lambda: {"read-1": first}):
            second = await tool.execute(path=str(f), limit=1)
        assert second == f"[File unchanged since last read: {f}]"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("case", ["fresh", "force", "not_visible", "different_range"])
    async def test_read_without_a_usable_receipt_makes_one_pass(
        self, tool, tmp_path, monkeypatch, case,
    ):
        f = tmp_path / "data.txt"
        raw = b"first\n" + b"x" * 80 + b"\nlast\n"
        f.write_bytes(raw)
        if case != "fresh":
            with file_state.file_read_context("read-1", lambda: {}):
                first = await tool.execute(path=str(f), limit=1)
        else:
            first = ""
        real_fdopen = os.fdopen
        counts = {"bytes": 0, "seeks": 0}

        class CountingStream(_ReadStreamWrapper):
            def read(self, size):
                chunk = self.stream.read(size)
                counts["bytes"] += len(chunk)
                return chunk

            def seek(self, *args):
                counts["seeks"] += 1
                return self.stream.seek(*args)

        monkeypatch.setattr(
            "nanobot.agent.tools.filesystem.os.fdopen",
            lambda *args, **kwargs: CountingStream(real_fdopen(*args, **kwargs)),
        )
        visible = {} if case == "not_visible" else {"read-1": first}
        offset = 2 if case == "different_range" else 1
        with file_state.file_read_context("read-2", lambda: visible):
            result = await tool.execute(path=str(f), offset=offset, limit=1, force=case == "force")

        assert result.startswith(f"{offset}| ")
        assert counts == {"bytes": len(raw), "seeks": 0}
        assert tool._file_states.get(f).content_hash == hashlib.sha256(raw).hexdigest()

    @pytest.mark.asyncio
    async def test_read_after_external_modification_returns_full(self, tool, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("original", encoding="utf-8")
        with file_state.file_read_context("read-1", lambda: {}):
            first = await tool.execute(path=str(f))
        f.write_text("modified content", encoding="utf-8")
        with file_state.file_read_context("read-2", lambda: {"read-1": first}):
            second = await tool.execute(path=str(f))
        assert "modified content" in second

    @pytest.mark.asyncio
    async def test_different_offset_returns_full(self, tool, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("\n".join(f"line {i}" for i in range(1, 21)), encoding="utf-8")
        with file_state.file_read_context("read-1", lambda: {}):
            first = await tool.execute(path=str(f), offset=1, limit=5)
        with file_state.file_read_context("read-2", lambda: {"read-1": first}):
            second = await tool.execute(path=str(f), offset=6, limit=5)
        assert "line 6" in second

    @pytest.mark.asyncio
    async def test_first_read_after_write_returns_full_content(self, tool, write_tool, tmp_path):
        f = tmp_path / "fresh.txt"
        result = await write_tool.execute(path=str(f), content="hello")
        assert "Successfully" in result
        read_result = await tool.execute(path=str(f))
        assert "hello" in read_result
        assert "unchanged" not in read_result.lower()

    @pytest.mark.asyncio
    async def test_repeated_image_reads_return_full_content(self, tool, tmp_path):
        f = tmp_path / "img.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\nfake-png-data")
        first = await tool.execute(path=str(f))
        second = await tool.execute(path=str(f))

        assert second == first
        assert second[0]["type"] == "image_url"
        encoded = base64.b64encode(f.read_bytes()).decode("ascii")
        assert second[0]["image_url"]["url"] == f"data:image/png;base64,{encoded}"
        assert second[0]["_meta"]["path"] == str(f)
        assert second[1] == {"type": "text", "text": f"(Image file: {f})"}

    @pytest.mark.asyncio
    async def test_known_text_extension_falls_back_to_latin1(self, tool, tmp_path):
        f = tmp_path / "legacy.csv"
        f.write_bytes("name\ncafé".encode("latin-1"))

        result = await tool.execute(path=str(f))

        assert "1| name" in result
        assert "2| café" in result

    @pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "utf-32"])
    @pytest.mark.asyncio
    async def test_bom_marked_unicode_text_uses_declared_encoding(
        self,
        tool,
        tmp_path,
        encoding,
    ):
        f = tmp_path / "unicode.txt"
        f.write_bytes("Hello 世界\nSecond line".encode(encoding))

        result = await tool.execute(path=str(f))

        assert "1| Hello 世界" in result
        assert "2| Second line" in result
        assert "\x00" not in result

    @pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "utf-32"])
    @pytest.mark.asyncio
    async def test_bom_only_unicode_text_is_empty_file(self, tool, tmp_path, encoding):
        f = tmp_path / "empty.txt"
        f.write_bytes("".encode(encoding))

        result = await tool.execute(path=str(f))

        assert result == f"(Empty file: {f})"


# Cross-session isolation (issue #3571)
# Each session must keep its own read cache. When session A reads a file,
# session B reading the same file must still receive the full content, not
# the "[File unchanged since last read]" dedup stub. Within each session,
# the original result must also remain in the current model context.

class TestReadDedupSessionIsolation:

    @pytest.mark.asyncio
    async def test_separate_sessions_do_not_share_dedup_state(self, tmp_path):
        f = tmp_path / "shared.txt"
        f.write_text("\n".join(f"line {i}" for i in range(10)), encoding="utf-8")

        session_a_tool = ReadFileTool(workspace=tmp_path)
        session_b_tool = ReadFileTool(workspace=tmp_path)

        first = await session_a_tool.execute(path=str(f))
        assert "line 0" in first

        second = await session_b_tool.execute(path=str(f))
        assert "unchanged" not in second.lower(), (
            "Session B should not inherit session A's read-dedup state. "
            f"Got: {second!r}"
        )
        assert "line 0" in second

    @pytest.mark.asyncio
    async def test_shared_loop_tool_uses_bound_session_state(self, tmp_path):
        f = tmp_path / "shared.txt"
        f.write_text("\n".join(f"line {i}" for i in range(10)), encoding="utf-8")

        # AgentLoop registers one shared ReadFileTool instance. The session
        # boundary is the task-local FileStates binding, not the tool object.
        shared_tool = ReadFileTool(workspace=tmp_path)
        session_a = file_state.FileStates()
        session_b = file_state.FileStates()

        token = file_state.bind_file_states(session_a)
        try:
            with file_state.file_read_context("read-a1", lambda: {}):
                first = await shared_tool.execute(path=str(f))
            with file_state.file_read_context("read-a2", lambda: {"read-a1": first}):
                repeat = await shared_tool.execute(path=str(f))
        finally:
            file_state.reset_file_states(token)

        assert "line 0" in first
        assert "unchanged" in repeat.lower()

        token = file_state.bind_file_states(session_b)
        try:
            second_session_read = await shared_tool.execute(path=str(f))
        finally:
            file_state.reset_file_states(token)

        assert "unchanged" not in second_session_read.lower()
        assert "line 0" in second_session_read


class TestReadPdf:

    @pytest.fixture()
    def tool(self, tmp_path, monkeypatch):
        monkeypatch.setattr("nanobot.config.loader._current_config_path", tmp_path / "config.json")
        return ReadFileTool(workspace=tmp_path)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("page_count", [2, 3])
    async def test_pdf_character_limit_preserves_pages_across_continuation(
        self, tool, tmp_path, monkeypatch, page_count,
    ):
        import re

        fitz = pytest.importorskip("pymupdf")
        pdf_path = tmp_path / "report.pdf"
        doc = fitz.open()
        markers = []
        for number in range(1, page_count + 1):
            marker = f"END_OF_PAGE_{number}"
            markers.append(marker)
            page = doc.new_page()
            page.insert_text((72, 72), "Report details " * 4 + "\n" + marker)
        doc.save(pdf_path)
        doc.close()
        monkeypatch.setattr(tool, "_MAX_CHARS", 130)

        outputs = []
        pages = None
        for _ in range(page_count):
            result = await tool.execute(path=str(pdf_path), pages=pages)
            outputs.append(result)
            continuation = re.search(r"Use pages='([^']+)'", result)
            if continuation is None:
                break
            pages = continuation[1]

        combined = "\n".join(outputs)
        for marker in markers:
            assert combined.count(marker) == 1
        assert "truncated" not in combined
        assert "Use pages=" not in outputs[-1]

    @pytest.mark.asyncio
    async def test_pdf_oversized_page_reports_unreturned_text(
        self, tool, tmp_path, monkeypatch,
    ):
        fitz = pytest.importorskip("pymupdf")
        pdf_path = tmp_path / "dense.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "\n".join(["Dense page content " * 3] * 8))
        page = doc.new_page()
        page.insert_text((72, 72), "Second page complete")
        doc.save(pdf_path)
        doc.close()
        monkeypatch.setattr(tool, "_MAX_CHARS", 130)

        result = await tool.execute(path=str(pdf_path))

        assert "Page 1 was truncated" in result
        assert "remaining text on this page is not shown" in result
        assert "Use pages='2-2'" in result
        second = await tool.execute(path=str(pdf_path), pages="2")
        assert "Second page complete" in second
        assert "truncated" not in second

    @pytest.mark.asyncio
    async def test_pdf_returns_text_content(self, tool, tmp_path):
        fitz = pytest.importorskip("fitz")
        pdf_path = tmp_path / "test.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Hello PDF World")
        doc.save(str(pdf_path))
        doc.close()

        result = await tool.execute(path=str(pdf_path))
        assert "Hello PDF World" in result

    @pytest.mark.asyncio
    async def test_pdf_pages_parameter(self, tool, tmp_path):
        fitz = pytest.importorskip("fitz")
        pdf_path = tmp_path / "multi.pdf"
        doc = fitz.open()
        for i in range(5):
            page = doc.new_page()
            page.insert_text((72, 72), f"Page {i + 1} content")
        doc.save(str(pdf_path))
        doc.close()

        result = await tool.execute(path=str(pdf_path), pages="2-3")
        assert "Page 2 content" in result
        assert "Page 3 content" in result
        assert "Page 1 content" not in result

    @pytest.mark.asyncio
    async def test_pdf_rejects_invalid_page_range(self, tool, tmp_path):
        fitz = pytest.importorskip("fitz")
        pdf_path = tmp_path / "test.pdf"
        doc = fitz.open()
        doc.new_page()
        doc.save(str(pdf_path))
        doc.close()

        result = await tool.execute(path=str(pdf_path), pages="bad")

        assert "Invalid page range" in result

        out_of_bounds = await tool.execute(path=str(pdf_path), pages="99")
        assert out_of_bounds == (
            "Error: Invalid page range '99': document has 1 page; "
            "use a page number or range within 1-1."
        )

    @pytest.mark.asyncio
    async def test_pdf_file_not_found_error(self, tool, tmp_path):
        result = await tool.execute(path=str(tmp_path / "nope.pdf"))
        assert "Error" in result
        assert "not found" in result


@pytest.mark.skipif(sys.platform == "win32", reason="/dev directory doesn't exist on Windows")
class TestReadDeviceBlacklist:

    @pytest.fixture()
    def tool(self):
        return ReadFileTool()

    @pytest.mark.asyncio
    async def test_dev_random_blocked(self, tool):
        result = await tool.execute(path="/dev/random")
        assert "Error" in result
        assert "blocked" in result.lower() or "device" in result.lower()

    @pytest.mark.asyncio
    async def test_dev_urandom_blocked(self, tool):
        result = await tool.execute(path="/dev/urandom")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_dev_zero_blocked(self, tool):
        result = await tool.execute(path="/dev/zero")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_proc_fd_blocked(self, tool):
        result = await tool.execute(path="/proc/self/fd/0")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_symlink_to_dev_zero_blocked(self, tmp_path):
        tool = ReadFileTool(workspace=tmp_path)
        link = tmp_path / "zero-link"
        link.symlink_to("/dev/zero")
        result = await tool.execute(path=str(link))
        assert "Error" in result
        assert "blocked" in result.lower() or "device" in result.lower()


class TestFileStateHashFallback:

    async def test_read_returns_changed_content_when_mtime_same(self, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("original", encoding="utf-8")
        tool = ReadFileTool(workspace=tmp_path)
        with file_state.file_read_context("read-1", lambda: {}):
            first = await tool.execute(path=str(f))
        original_mtime = os.path.getmtime(f)

        f.write_text("modified", encoding="utf-8")
        os.utime(f, (original_mtime, original_mtime))
        assert os.path.getmtime(f) == original_mtime

        with file_state.file_read_context("read-2", lambda: {"read-1": first}):
            second = await tool.execute(path=str(f))
        assert "modified" in second
        assert "unchanged" not in second.lower()


# Line-ending normalization
# ReadFileTool normalizes CRLF -> LF before line-splitting. This primarily
# helps Windows users whose checkouts carry CRLF line endings and whose
# subsequent StrReplace edits would otherwise miss on `\r` boundaries. The
# normalization applies on all platforms; these tests lock that in so the
# behavior is intentional and discoverable, not accidental.

class TestReadFileLineEndingNormalization:

    @pytest.fixture()
    def tool(self, tmp_path):
        return ReadFileTool(workspace=tmp_path)

    @pytest.mark.asyncio
    async def test_crlf_is_normalized_to_lf(self, tool, tmp_path):
        f = tmp_path / "crlf.txt"
        f.write_bytes(b"alpha\r\nbeta\r\ngamma\r\n")
        result = await tool.execute(path=str(f))
        assert "\r" not in result
        assert "alpha" in result and "beta" in result and "gamma" in result

    @pytest.mark.asyncio
    async def test_lf_only_is_preserved(self, tool, tmp_path):
        f = tmp_path / "lf.txt"
        f.write_bytes(b"alpha\nbeta\ngamma\n")
        result = await tool.execute(path=str(f))
        assert "\r" not in result
        assert "alpha" in result and "beta" in result and "gamma" in result


class TestReadOfficeDocuments:

    @pytest.fixture()
    def tool(self, tmp_path):
        return ReadFileTool(workspace=tmp_path)

    @pytest.mark.asyncio
    async def test_docx_returns_extracted_text(self, tool, tmp_path):
        with patch(
            "nanobot.utils.document.open_document_line_source",
            return_value=_document_source("Title\n\nParagraph 1"),
        ):
            f = tmp_path / "test.docx"
            f.write_bytes(b"PK")
            result = await tool.execute(path=str(f))
        assert "Title" in result
        assert "Paragraph 1" in result
        assert "Error" not in result

    @pytest.mark.asyncio
    async def test_xlsx_returns_extracted_text(self, tool, tmp_path):
        with patch(
            "nanobot.utils.document.open_document_line_source",
            return_value=_document_source("--- Sheet: Sheet1 ---\nName\tAge\nAlice\t30"),
        ):
            f = tmp_path / "test.xlsx"
            f.write_bytes(b"PK")
            result = await tool.execute(path=str(f))
        assert "Sheet1" in result
        assert "Alice" in result

    @pytest.mark.asyncio
    async def test_office_documents_support_extracted_line_ranges(self, tool, tmp_path):
        extracted = "--- Sheet: Sheet1 ---\nName\tAge\nAlice\t30\nBob\t25"
        with patch(
            "nanobot.utils.document.open_document_line_source",
            return_value=_document_source(extracted),
        ):
            f = tmp_path / "test.xlsx"
            f.write_bytes(b"PK")
            result = await tool.execute(path=str(f), offset=3, limit=1)

        assert "3| Alice\t30" in result
        assert "Name\tAge" not in result
        assert "Use offset=4 to continue" in result

    @pytest.mark.asyncio
    async def test_office_range_reaches_beyond_attachment_preview_limit(
        self,
        tool,
        tmp_path,
        monkeypatch,
    ):
        from openpyxl import Workbook

        from nanobot.utils import document as document_utils

        workbook_path = tmp_path / "long.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        for row in range(1, 20):
            sheet.append([f"ordinary-row-{row}"])
        sheet.append(["late-content"])
        workbook.save(workbook_path)
        workbook.close()
        monkeypatch.setattr(document_utils, "_MAX_TEXT_LENGTH", 50)

        preview = document_utils.extract_text(workbook_path)
        assert preview is not None
        assert "late-content" not in preview

        result = await tool.execute(path=str(workbook_path), offset=21, limit=1)

        assert "21| late-content" in result
        assert "beyond end" not in result

    @pytest.mark.asyncio
    async def test_pptx_returns_extracted_text(self, tool, tmp_path):
        with patch(
            "nanobot.utils.document.open_document_line_source",
            return_value=_document_source(
                "--- Slide 1 ---\nWelcome\n--- Slide 2 ---\nContent"
            ),
        ):
            f = tmp_path / "test.pptx"
            f.write_bytes(b"PK")
            result = await tool.execute(path=str(f))
        assert "Welcome" in result
        assert "Content" in result

    @pytest.mark.asyncio
    async def test_docx_missing_library(self, tool, tmp_path):
        with patch(
            "nanobot.utils.document.open_document_line_source",
            side_effect=DocumentExtractionError("python-docx not installed"),
        ):
            f = tmp_path / "test.docx"
            f.write_bytes(b"PK")
            result = await tool.execute(path=str(f))
        assert "Error" in result
        assert "python-docx not installed" in result

    @pytest.mark.asyncio
    async def test_docx_corrupt_file(self, tool, tmp_path):
        with patch(
            "nanobot.utils.document.open_document_line_source",
            side_effect=DocumentExtractionError("failed to extract DOCX: bad zip"),
        ):
            f = tmp_path / "test.docx"
            f.write_bytes(b"not-a-zip")
            result = await tool.execute(path=str(f))
        assert "Error" in result
        assert "failed to extract DOCX" in result

    @pytest.mark.asyncio
    async def test_unsupported_extension(self, tool, tmp_path):
        with patch("nanobot.utils.document.open_document_line_source", return_value=None):
            f = tmp_path / "test.docx"
            f.write_bytes(b"PK")
            result = await tool.execute(path=str(f))
        assert "Error" in result
        assert "Unsupported" in result

    @pytest.mark.asyncio
    async def test_empty_document_returns_descriptive_message(self, tool, tmp_path):
        with patch(
            "nanobot.utils.document.open_document_line_source",
            return_value=_document_source(""),
        ):
            f = tmp_path / "empty.docx"
            f.write_bytes(b"PK")
            result = await tool.execute(path=str(f))
        assert "no extractable text" in result


class TestOfficeDocTruncation:

    @pytest.fixture()
    def tool(self, tmp_path):
        return ReadFileTool(workspace=tmp_path)

    @pytest.mark.asyncio
    async def test_large_document_truncated(self, tool, tmp_path):
        with patch(
            "nanobot.utils.document.open_document_line_source",
            return_value=_document_source("x" * 200_000),
        ):
            f = tmp_path / "large.docx"
            f.write_bytes(b"PK")
            result = await tool.execute(path=str(f))
        assert len(result) <= ReadFileTool._MAX_CHARS + 100
        assert "truncated at ~128K chars" in result

    @pytest.mark.asyncio
    async def test_small_document_not_truncated(self, tool, tmp_path):
        with patch(
            "nanobot.utils.document.open_document_line_source",
            return_value=_document_source("Hello world"),
        ):
            f = tmp_path / "small.docx"
            f.write_bytes(b"PK")
            result = await tool.execute(path=str(f))
        assert "truncated" not in result
        assert "Hello world" in result

    @pytest.mark.asyncio
    async def test_error_response_not_truncated(self, tool, tmp_path):
        with patch(
            "nanobot.utils.document.open_document_line_source",
            side_effect=DocumentExtractionError(
                "failed to extract DOCX: something went wrong"
            ),
        ):
            f = tmp_path / "bad.docx"
            f.write_bytes(b"PK")
            result = await tool.execute(path=str(f))
        assert "Error" in result
        assert "truncated" not in result


class TestReadFileDescription:

    def test_description_mentions_documents(self):
        tool = ReadFileTool()
        desc = tool.description.lower()
        assert "document" in desc or "docx" in desc or "xlsx" in desc or "pptx" in desc


class TestBoundedTextReads:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("chunk_size", [16, 17])
    @pytest.mark.parametrize(
        ("encoding", "bom"),
        [
            ("utf-8", b""),
            ("utf-8", codecs.BOM_UTF8),
            ("utf-16-le", codecs.BOM_UTF16_LE),
            ("utf-16-be", codecs.BOM_UTF16_BE),
            ("utf-32-le", codecs.BOM_UTF32_LE),
            ("utf-32-be", codecs.BOM_UTF32_BE),
        ],
    )
    async def test_chunked_text_matches_splitlines_and_normalization(
        self, tmp_path, monkeypatch, encoding, bom, chunk_size,
    ):
        content = (
            "a" * 15 + "\r\n" + "prefix\r\r\nnext\rsolo\n"
            + "\v\f\x1c\x1d\x1e\x85\u2028\u2029界😀end"
        )
        f = tmp_path / "mixed.txt"
        f.write_bytes(bom + content.encode(encoding))
        tool = ReadFileTool(workspace=tmp_path)
        monkeypatch.setattr(tool, "_READ_CHUNK_SIZE", chunk_size)
        lines = content.replace("\r\n", "\n").splitlines()

        for offset, limit in [(1, 3), (4, 4), (len(lines), 1)]:
            end = min(offset - 1 + limit, len(lines))
            expected = "\n".join(
                f"{number}| {line}"
                for number, line in enumerate(lines[offset - 1:end], offset)
            )
            if end < len(lines):
                expected += (
                    f"\n\n(Showing lines {offset}-{end} of {len(lines)}. "
                    f"Use offset={end + 1} to continue.)"
                )
            else:
                expected += f"\n\n(End of file — {len(lines)} lines total)"
            assert await tool.execute(path=str(f), offset=offset, limit=limit, force=True) == expected
        result = await tool.execute(path=str(f), offset=len(lines) + 1, force=True)
        assert result == f"Error: offset {len(lines) + 1} is beyond end of file ({len(lines)} lines)"

    @pytest.mark.asyncio
    async def test_late_utf8_error_uses_latin1_for_the_entire_known_text_file(
        self, tmp_path, monkeypatch,
    ):
        raw = b"caf\xc3\xa9\n" + b"x" * 50 + b"\x85last\xff"
        tool = ReadFileTool(workspace=tmp_path)
        monkeypatch.setattr(tool, "_READ_CHUNK_SIZE", 16)
        text_file = tmp_path / "legacy.txt"
        text_file.write_bytes(raw)

        result = await tool.execute(path=str(text_file), limit=1)

        assert result == "1| cafÃ©\n\n(Showing lines 1-1 of 3. Use offset=2 to continue.)"
        assert tool._file_states.get(text_file).content_hash == hashlib.sha256(raw).hexdigest()

        binary = tmp_path / "data.bin"
        binary.write_bytes(raw)
        result = await tool.execute(path=str(binary), limit=1)
        assert result.is_error
        assert str(result).startswith(f"Error: Cannot read binary file {binary} (MIME:")
        assert tool._file_states.get(binary) is None

    @pytest.mark.asyncio
    async def test_latin1_fallback_preserves_prior_ascii_and_split_line_boundary(self, tmp_path, monkeypatch):
        f = tmp_path / "legacy.txt"
        raw = b"first\n" + b"a" * 9 + b"\r" + b"\xc3\xa9\xff\nlast\n"
        f.write_bytes(raw)
        tool = ReadFileTool(workspace=tmp_path)
        monkeypatch.setattr(tool, "_READ_CHUNK_SIZE", 16)

        result = await tool.execute(path=str(f), limit=4)

        assert result == "1| first\n2| aaaaaaaaa\n3| Ã©ÿ\n4| last\n\n(End of file — 4 lines total)"
        assert tool._file_states.get(f).content_hash == hashlib.sha256(raw).hexdigest()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("raw", "encoding"),
        [
            (codecs.BOM_UTF8 + b"a" * 40 + b"\xc3", "utf-8-sig"),
            (codecs.BOM_UTF8 + b"a" * 40 + b"\xfflater", "utf-8-sig"),
            (codecs.BOM_UTF16_LE + b"a\x00" * 20 + b"\x00", "utf-16"),
            (codecs.BOM_UTF32_BE + b"\x00\x00\x00a" * 10 + b"\x00\x11\x00\x00", "utf-32"),
        ],
    )
    async def test_malformed_bom_keeps_original_decode_error(
        self, tmp_path, monkeypatch, raw, encoding,
    ):
        f = tmp_path / "broken.txt"
        f.write_bytes(raw)
        tool = ReadFileTool(workspace=tmp_path)
        monkeypatch.setattr(tool, "_READ_CHUNK_SIZE", 17)
        with pytest.raises(UnicodeDecodeError) as exc:
            raw.decode(encoding)

        result = await tool.execute(path=str(f), limit=1)

        assert result.is_error
        assert result == f"Error reading file: {exc.value}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("filename", "raw", "mime"),
        [
            ("image.dat", b"\x89PNG\r\n\x1a\ncontents", "image/png"),
            ("image.png", b"plain text with image extension", "image/png"),
        ],
    )
    async def test_magic_and_extension_image_reads_are_unchanged(self, tmp_path, filename, raw, mime):
        f = tmp_path / filename
        f.write_bytes(raw)
        tool = ReadFileTool(workspace=tmp_path)

        result = await tool.execute(path=str(f), limit=1)

        assert result[0]["image_url"]["url"] == f"data:{mime};base64,{base64.b64encode(raw).decode()}"
        assert result[1] == {"type": "text", "text": f"(Image file: {f})"}

    @pytest.mark.asyncio
    async def test_image_growth_during_read_respects_size_limit(self, tmp_path, monkeypatch):
        f = tmp_path / "growing.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 16)
        tool = ReadFileTool(workspace=tmp_path)
        monkeypatch.setattr(tool, "_READ_CHUNK_SIZE", 16)
        monkeypatch.setattr(tool, "_MAX_FILE_SIZE_BYTES", 64)
        real_fdopen = os.fdopen

        class GrowingStream(_ReadStreamWrapper):
            def __init__(self, stream):
                super().__init__(stream)
                self.grown = False

            def read(self, size):
                chunk = self.stream.read(size)
                if not self.grown:
                    self.grown = True
                    with f.open("ab") as out:
                        out.write(b"y" * 64)
                return chunk

        monkeypatch.setattr(
            "nanobot.agent.tools.filesystem.os.fdopen",
            lambda *args, **kwargs: GrowingStream(real_fdopen(*args, **kwargs)),
        )
        result = await tool.execute(path=str(f))

        assert result.is_error
        assert "File too large to read" in result

    @pytest.mark.asyncio
    async def test_small_image_does_not_allocate_the_file_size_limit(self, tmp_path):
        if tracemalloc.is_tracing():
            pytest.skip("requires isolated tracemalloc accounting")
        f = tmp_path / "small.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\ncontents")
        tool = ReadFileTool(workspace=tmp_path)
        await tool.execute(path=str(f))

        tracemalloc.start()
        try:
            result = await tool.execute(path=str(f))
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()

        assert result[0]["type"] == "image_url"
        assert peak < 2 * 1024 * 1024

    @pytest.mark.asyncio
    async def test_hash_and_dedup_cover_changes_outside_selected_range(self, tmp_path, monkeypatch):
        f = tmp_path / "data.txt"
        raw = b"first\n" + b"x" * 100 + b"\nend-A\n"
        f.write_bytes(raw)
        tool = ReadFileTool(workspace=tmp_path)
        monkeypatch.setattr(tool, "_READ_CHUNK_SIZE", 16)
        with file_state.file_read_context("read-1", lambda: {}):
            first = await tool.execute(path=str(f), limit=1)
        assert tool._file_states.get(f).content_hash == hashlib.sha256(raw).hexdigest()
        with file_state.file_read_context("read-2", lambda: {"read-1": first}):
            assert "File unchanged" in await tool.execute(path=str(f), limit=1)

        mtime = f.stat().st_mtime_ns
        changed = raw.replace(b"end-A", b"end-B")
        f.write_bytes(changed)
        os.utime(f, ns=(mtime, mtime))
        with file_state.file_read_context("read-3", lambda: {"read-1": first}):
            reread = await tool.execute(path=str(f), limit=1)
        assert reread == first
        assert tool._file_states.get(f).content_hash == hashlib.sha256(changed).hexdigest()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("new_type", ["utf16", "image"])
    async def test_changed_file_is_redetected_and_hashed_after_precheck(
        self, tmp_path, monkeypatch, new_type,
    ):
        f = tmp_path / "data.txt"
        f.write_bytes(b"original\n")
        tool = ReadFileTool(workspace=tmp_path)
        with file_state.file_read_context("read-1", lambda: {}):
            first = await tool.execute(path=str(f))
        f.write_bytes(b"intermediate bytes\n")
        final = (
            "new text\n".encode("utf-16") if new_type == "utf16"
            else b"\x89PNG\r\n\x1a\nimage data"
        )
        real_fdopen = os.fdopen

        class ChangeAfterPrecheck(_ReadStreamWrapper):
            def __init__(self, stream):
                super().__init__(stream)
                self.changed = False

            def read(self, size):
                chunk = self.stream.read(size)
                if not chunk and not self.changed:
                    self.changed = True
                    f.write_bytes(final)
                return chunk

        monkeypatch.setattr(
            "nanobot.agent.tools.filesystem.os.fdopen",
            lambda *args, **kwargs: ChangeAfterPrecheck(real_fdopen(*args, **kwargs)),
        )
        with file_state.file_read_context("read-2", lambda: {"read-1": first}):
            second = await tool.execute(path=str(f))

        if new_type == "image":
            assert second[0]["image_url"]["url"] == (
                f"data:image/png;base64,{base64.b64encode(final).decode()}"
            )
            assert tool._file_states.get(f).content_hash == hashlib.sha256(b"original\n").hexdigest()
        else:
            assert second == "1| new text\n\n(End of file — 1 lines total)"
            assert tool._file_states.get(f).content_hash == hashlib.sha256(final).hexdigest()
            with file_state.file_read_context("read-3", lambda: {"read-2": second}):
                repeat = await tool.execute(path=str(f))
            assert repeat == f"[File unchanged since last read: {f}]"

    @pytest.mark.asyncio
    async def test_shrunk_image_after_receipt_check_does_not_allocate_old_file_size(self, tmp_path, monkeypatch):
        if tracemalloc.is_tracing():
            pytest.skip("requires isolated tracemalloc accounting")
        f = tmp_path / "data.txt"
        f.write_bytes(b"x" * (8 * 1024 * 1024))
        tool = ReadFileTool(workspace=tmp_path)
        with file_state.file_read_context("read-1", lambda: {}):
            first = await tool.execute(path=str(f), limit=1)
        with f.open("r+b") as out:
            out.seek(-1, os.SEEK_END)
            out.write(b"y")
        image = b"\x89PNG\r\n\x1a\nsmall"
        real_fdopen = os.fdopen

        class ChangeAfterPrecheck(_ReadStreamWrapper):
            def __init__(self, stream):
                super().__init__(stream)
                self.changed = False

            def read(self, size):
                chunk = self.stream.read(size)
                if not chunk and not self.changed:
                    self.changed = True
                    f.write_bytes(image)
                return chunk

        monkeypatch.setattr(
            "nanobot.agent.tools.filesystem.os.fdopen",
            lambda *args, **kwargs: ChangeAfterPrecheck(real_fdopen(*args, **kwargs)),
        )
        tracemalloc.start()
        try:
            with file_state.file_read_context("read-2", lambda: {"read-1": first}):
                result = await tool.execute(path=str(f), limit=1)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()

        assert result[0]["image_url"]["url"] == f"data:image/png;base64,{base64.b64encode(image).decode()}"
        assert peak < 3 * 1024 * 1024

    @pytest.mark.asyncio
    async def test_growth_during_hash_precheck_respects_size_limit(self, tmp_path, monkeypatch):
        f = tmp_path / "data.txt"
        raw = b"first\n" + b"x" * 20
        f.write_bytes(raw)
        tool = ReadFileTool(workspace=tmp_path)
        monkeypatch.setattr(tool, "_READ_CHUNK_SIZE", 16)
        monkeypatch.setattr(tool, "_MAX_FILE_SIZE_BYTES", 64)
        with file_state.file_read_context("read-1", lambda: {}):
            first = await tool.execute(path=str(f))
        real_fdopen = os.fdopen

        class GrowingStream(_ReadStreamWrapper):
            def __init__(self, stream):
                super().__init__(stream)
                self.grown = False

            def read(self, size):
                chunk = self.stream.read(size)
                if not self.grown:
                    self.grown = True
                    with f.open("ab") as out:
                        out.write(b"y" * 64)
                return chunk

        monkeypatch.setattr(
            "nanobot.agent.tools.filesystem.os.fdopen",
            lambda *args, **kwargs: GrowingStream(real_fdopen(*args, **kwargs)),
        )
        with file_state.file_read_context("read-2", lambda: {"read-1": first}):
            result = await tool.execute(path=str(f))

        assert result.is_error
        assert "File too large to read" in result
        assert tool._file_states.get(f).content_hash == hashlib.sha256(raw).hexdigest()

    @pytest.mark.asyncio
    async def test_file_at_size_limit_is_readable(self, tmp_path, monkeypatch):
        f = tmp_path / "exact.txt"
        raw = b"x" * 99 + b"\n"
        f.write_bytes(raw)
        tool = ReadFileTool(workspace=tmp_path)
        monkeypatch.setattr(tool, "_MAX_FILE_SIZE_BYTES", len(raw))
        monkeypatch.setattr(tool, "_READ_CHUNK_SIZE", 16)

        result = await tool.execute(path=str(f), limit=1)

        assert result == "1| " + "x" * 99 + "\n\n(End of file — 1 lines total)"
        assert tool._file_states.get(f).content_hash == hashlib.sha256(raw).hexdigest()

    @pytest.mark.asyncio
    async def test_opened_nonregular_file_is_not_read(self, tmp_path, monkeypatch):
        f = tmp_path / "replaced.txt"
        f.write_text("regular", encoding="utf-8")
        target = f.resolve()
        read_fd, write_fd = os.pipe()
        os.close(write_fd)
        real_open = os.open

        def open_replacement(path, flags, *args, **kwargs):
            if os.fspath(path) == os.fspath(target):
                return read_fd
            return real_open(path, flags, *args, **kwargs)

        tool = ReadFileTool()
        try:
            with monkeypatch.context() as scoped:
                scoped.setattr("nanobot.agent.tools.filesystem.os.open", open_replacement)
                result = await tool.execute(path=str(f))
        finally:
            try:
                os.close(read_fd)
            except OSError:
                pass

        assert result.is_error
        assert result == f"Error: Not a file: {f}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("exceeds_limit", [False, True])
    async def test_growth_after_open_is_read_once_and_respects_size_limit(
        self, tmp_path, monkeypatch, exceeds_limit,
    ):
        f = tmp_path / "growing.txt"
        original = b"first\n" + b"x" * 40 + b"\nlast\n"
        addition = b"extra\n" * (12 if exceeds_limit else 1)
        f.write_bytes(original)
        tool = ReadFileTool(workspace=tmp_path)
        monkeypatch.setattr(tool, "_READ_CHUNK_SIZE", 16)
        monkeypatch.setattr(tool, "_MAX_FILE_SIZE_BYTES", 100)
        read_text = tool._read_text

        def append_before_reading_rest(stream, first, *args):
            with f.open("ab") as out:
                out.write(addition)
            return read_text(stream, first, *args)

        monkeypatch.setattr(tool, "_read_text", append_before_reading_rest)
        result = await tool.execute(path=str(f), limit=1)

        if exceeds_limit:
            assert result.is_error
            assert "File too large to read" in result
            assert tool._file_states.get(f) is None
        else:
            assert result == "1| first\n\n(Showing lines 1-1 of 4. Use offset=2 to continue.)"
            assert tool._file_states.get(f).content_hash == hashlib.sha256(original + addition).hexdigest()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("offset", [1, 2])
    async def test_large_unbroken_line_has_bounded_python_allocations(self, tmp_path, offset):
        if tracemalloc.is_tracing():
            pytest.skip("requires isolated tracemalloc accounting")
        f = tmp_path / "large.txt"
        with f.open("wb") as out:
            out.write(b"first\n")
            for _ in range(128):
                out.write(b"x" * 65536)
            out.write(b"\nlast\n")
        tool = ReadFileTool(workspace=tmp_path)
        warmup = tmp_path / "warmup.txt"
        warmup.write_text("warmup", encoding="utf-8")
        await tool.execute(path=str(warmup))

        tracemalloc.start()
        try:
            result = await tool.execute(path=str(f), offset=offset, limit=1)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()

        assert "of 3. Use offset=" in result
        if offset == 2:
            assert "Line 2 truncated" in result
        assert peak < 3 * 1024 * 1024
