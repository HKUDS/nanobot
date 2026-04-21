"""Tests for ReadFileTool enhancements: description fix, read dedup, PDF support, device blacklist, office docs."""

import os
import sys
from unittest.mock import patch

import pytest

from nanobot.agent.tools.filesystem import ReadFileTool, WriteFileTool
from nanobot.agent.tools import file_state


@pytest.fixture(autouse=True)
def _clear_file_state():
    file_state.clear()
    yield
    file_state.clear()


# ---------------------------------------------------------------------------
# Description fix
# ---------------------------------------------------------------------------

class TestReadDescriptionFix:

    def test_description_mentions_image_support(self):
        tool = ReadFileTool()
        assert "image" in tool.description.lower()

    def test_description_no_longer_says_cannot_read_images(self):
        tool = ReadFileTool()
        assert "cannot read binary files or images" not in tool.description.lower()


# ---------------------------------------------------------------------------
# Read deduplication
# ---------------------------------------------------------------------------

class TestReadDedup:
    """Same file + same offset/limit + unchanged mtime -> short stub."""

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
        first = await tool.execute(path=str(f))
        assert "line 0" in first
        second = await tool.execute(path=str(f))
        assert "unchanged" in second.lower()
        # Stub should not contain file content
        assert "line 0" not in second

    @pytest.mark.asyncio
    async def test_read_after_external_modification_returns_full(self, tool, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("original", encoding="utf-8")
        await tool.execute(path=str(f))
        # Modify the file externally
        f.write_text("modified content", encoding="utf-8")
        second = await tool.execute(path=str(f))
        assert "modified content" in second

    @pytest.mark.asyncio
    async def test_different_offset_returns_full(self, tool, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("\n".join(f"line {i}" for i in range(1, 21)), encoding="utf-8")
        await tool.execute(path=str(f), offset=1, limit=5)
        second = await tool.execute(path=str(f), offset=6, limit=5)
        # Different offset → full read, not stub
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
    async def test_dedup_does_not_apply_to_images(self, tool, tmp_path):
        f = tmp_path / "img.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\nfake-png-data")
        first = await tool.execute(path=str(f))
        assert isinstance(first, list)
        second = await tool.execute(path=str(f))
        # Images should always return full content blocks, not a stub
        assert isinstance(second, list)


# ---------------------------------------------------------------------------
# PDF support
# ---------------------------------------------------------------------------

class TestReadPdf:

    @pytest.fixture()
    def tool(self, tmp_path):
        return ReadFileTool(workspace=tmp_path)

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
    async def test_pdf_file_not_found_error(self, tool, tmp_path):
        result = await tool.execute(path=str(tmp_path / "nope.pdf"))
        assert "Error" in result
        assert "not found" in result


# ---------------------------------------------------------------------------
# Device path blacklist
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# file_state: mtime-unchanged / content-changed fallback
# ---------------------------------------------------------------------------
# On filesystems with coarse mtime resolution (NTFS ~100ms, FAT 2s) a fast
# write-after-read can leave mtime unchanged. The content-hash fallback is
# what protects against stale-read warnings being false-negative on those
# platforms. Lock that behavior down here so nobody reverts it silently.

class TestFileStateHashFallback:

    def test_check_read_warns_when_content_changed_but_mtime_same(self, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("original", encoding="utf-8")
        file_state.record_read(f)
        original_mtime = os.path.getmtime(f)

        f.write_text("modified", encoding="utf-8")
        os.utime(f, (original_mtime, original_mtime))
        assert os.path.getmtime(f) == original_mtime

        warning = file_state.check_read(f)
        assert warning is not None
        assert "modified" in warning.lower()

    def test_check_read_passes_when_content_and_mtime_unchanged(self, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("stable", encoding="utf-8")
        file_state.record_read(f)

        assert file_state.check_read(f) is None


# ---------------------------------------------------------------------------
# Line-ending normalization
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Office document support (DOCX, XLSX, PPTX)
# ---------------------------------------------------------------------------

class TestReadOfficeDocuments:

    @pytest.fixture()
    def tool(self, tmp_path):
        return ReadFileTool(workspace=tmp_path)

    @pytest.mark.asyncio
    async def test_docx_returns_extracted_text(self, tool, tmp_path):
        with patch("nanobot.utils.document.extract_text", return_value="Title\n\nParagraph 1"):
            f = tmp_path / "test.docx"
            f.write_bytes(b"PK")
            result = await tool.execute(path=str(f))
        assert "Title" in result
        assert "Paragraph 1" in result
        assert "Error" not in result

    @pytest.mark.asyncio
    async def test_xlsx_returns_extracted_text(self, tool, tmp_path):
        with patch("nanobot.utils.document.extract_text", return_value="--- Sheet: Sheet1 ---\nName\tAge\nAlice\t30"):
            f = tmp_path / "test.xlsx"
            f.write_bytes(b"PK")
            result = await tool.execute(path=str(f))
        assert "Sheet1" in result
        assert "Alice" in result

    @pytest.mark.asyncio
    async def test_pptx_returns_extracted_text(self, tool, tmp_path):
        with patch("nanobot.utils.document.extract_text", return_value="--- Slide 1 ---\nWelcome\n--- Slide 2 ---\nContent"):
            f = tmp_path / "test.pptx"
            f.write_bytes(b"PK")
            result = await tool.execute(path=str(f))
        assert "Welcome" in result
        assert "Content" in result

    @pytest.mark.asyncio
    async def test_docx_missing_library(self, tool, tmp_path):
        with patch("nanobot.utils.document.extract_text", return_value="[error: python-docx not installed]"):
            f = tmp_path / "test.docx"
            f.write_bytes(b"PK")
            result = await tool.execute(path=str(f))
        assert "Error" in result
        assert "python-docx not installed" in result

    @pytest.mark.asyncio
    async def test_docx_corrupt_file(self, tool, tmp_path):
        with patch("nanobot.utils.document.extract_text", return_value="[error: failed to extract DOCX: bad zip]"):
            f = tmp_path / "test.docx"
            f.write_bytes(b"not-a-zip")
            result = await tool.execute(path=str(f))
        assert "Error" in result
        assert "failed to extract DOCX" in result

    @pytest.mark.asyncio
    async def test_unsupported_extension(self, tool, tmp_path):
        with patch("nanobot.utils.document.extract_text", return_value=None):
            f = tmp_path / "test.docx"
            f.write_bytes(b"PK")
            result = await tool.execute(path=str(f))
        assert "Error" in result
        assert "Unsupported" in result

    @pytest.mark.asyncio
    async def test_empty_document_returns_descriptive_message(self, tool, tmp_path):
        with patch("nanobot.utils.document.extract_text", return_value=""):
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
        with patch("nanobot.utils.document.extract_text", return_value="x" * 200_000):
            f = tmp_path / "large.docx"
            f.write_bytes(b"PK")
            result = await tool.execute(path=str(f))
        assert len(result) <= ReadFileTool._MAX_CHARS + 100
        assert "truncated at ~128K chars" in result

    @pytest.mark.asyncio
    async def test_small_document_not_truncated(self, tool, tmp_path):
        with patch("nanobot.utils.document.extract_text", return_value="Hello world"):
            f = tmp_path / "small.docx"
            f.write_bytes(b"PK")
            result = await tool.execute(path=str(f))
        assert "truncated" not in result
        assert "Hello world" in result

    @pytest.mark.asyncio
    async def test_error_response_not_truncated(self, tool, tmp_path):
        with patch("nanobot.utils.document.extract_text", return_value="[error: failed to extract DOCX: something went wrong]"):
            f = tmp_path / "bad.docx"
            f.write_bytes(b"PK")
            result = await tool.execute(path=str(f))
        assert "Error" in result
        assert "truncated" not in result


class TestReadDescriptionUpdate:

    def test_description_mentions_documents(self):
        tool = ReadFileTool()
        desc = tool.description.lower()
        assert "document" in desc or "docx" in desc or "xlsx" in desc or "pptx" in desc

    def test_description_no_longer_says_cannot_read(self):
        tool = ReadFileTool()
        assert "cannot read" not in tool.description.lower()
