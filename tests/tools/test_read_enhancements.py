"""Tests for ReadFileTool enhancements: description fix, read dedup, PDF support, device blacklist."""

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
