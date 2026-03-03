"""Tests for ReadFileTool PDF support."""

from pathlib import Path

import pymupdf

from nanobot.agent.tools.filesystem import ReadFileTool, _MAX_READ_CHARS


def _create_pdf(path: Path, pages: list[str]) -> None:
    """Create a PDF with the given page texts using pymupdf."""
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_textbox(page.rect, text, fontsize=8)
    doc.save(str(path))
    doc.close()


async def test_read_pdf_extracts_text(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    _create_pdf(pdf_path, ["Hello from page one", "Page two content"])

    tool = ReadFileTool()
    result = await tool.execute(path=str(pdf_path))

    assert "--- Page 1 ---" in result
    assert "Hello from page one" in result
    assert "--- Page 2 ---" in result
    assert "Page two content" in result


async def test_read_pdf_truncation(tmp_path: Path) -> None:
    pdf_path = tmp_path / "big.pdf"
    # insert_textbox fits ~5000 chars per page, so ~25 pages exceeds _MAX_READ_CHARS (100k).
    page_text = "x" * 5000
    num_pages = (_MAX_READ_CHARS // 5000) + 5
    _create_pdf(pdf_path, [page_text] * num_pages)

    tool = ReadFileTool()
    result = await tool.execute(path=str(pdf_path))

    assert "[Truncated" in result


async def test_read_pdf_file_not_found(tmp_path: Path) -> None:
    tool = ReadFileTool()
    result = await tool.execute(path=str(tmp_path / "nonexistent.pdf"))

    assert "Error: File not found" in result


async def test_read_pdf_empty_no_text(tmp_path: Path) -> None:
    pdf_path = tmp_path / "empty.pdf"
    _create_pdf(pdf_path, [""])  # page with no text

    tool = ReadFileTool()
    result = await tool.execute(path=str(pdf_path))

    assert "no extractable text" in result


async def test_read_text_file_still_works(tmp_path: Path) -> None:
    txt_path = tmp_path / "hello.txt"
    txt_path.write_text("plain text content", encoding="utf-8")

    tool = ReadFileTool()
    result = await tool.execute(path=str(txt_path))

    assert result == "plain text content"


async def test_read_text_file_truncation(tmp_path: Path) -> None:
    txt_path = tmp_path / "big.txt"
    txt_path.write_text("y" * (_MAX_READ_CHARS + 500), encoding="utf-8")

    tool = ReadFileTool()
    result = await tool.execute(path=str(txt_path))

    assert "[Truncated" in result
