"""Tests for context builder document handling."""

from __future__ import annotations

import pytest
from pathlib import Path

from nanobot.agent.context import ContextBuilder


def _make_builder(tmp_path: Path) -> ContextBuilder:
    """Create a minimal ContextBuilder for testing."""
    return ContextBuilder(workspace=tmp_path, timezone="UTC")


def test_build_user_content_with_no_media_returns_string(tmp_path: Path) -> None:
    builder = _make_builder(tmp_path)
    result = builder._build_user_content("hello", None)
    assert result == "hello"


def test_build_user_content_with_image_returns_list(tmp_path: Path) -> None:
    """Image files should produce base64 content blocks."""
    builder = _make_builder(tmp_path)
    png = tmp_path / "test.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    result = builder._build_user_content("describe this", [str(png)])
    assert isinstance(result, list)
    types = [b["type"] for b in result]
    assert "image_url" in types
    assert "text" in types


def test_build_user_content_with_docx_includes_extracted_text(tmp_path: Path) -> None:
    """Document files should have their text extracted and included."""
    from docx import Document

    doc = Document()
    doc.add_paragraph("Quarterly revenue is $5M")
    docx_path = tmp_path / "report.docx"
    doc.save(docx_path)

    builder = _make_builder(tmp_path)
    result = builder._build_user_content("summarize this", [str(docx_path)])
    assert isinstance(result, str)
    assert "Quarterly revenue" in result


def test_build_user_content_mixed_image_and_document(tmp_path: Path) -> None:
    """Mix of images and documents: images as base64, docs as text."""
    from docx import Document

    png = tmp_path / "chart.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    doc = Document()
    doc.add_paragraph("Report text here")
    docx = tmp_path / "report.docx"
    doc.save(docx)

    builder = _make_builder(tmp_path)
    result = builder._build_user_content("analyze both", [str(png), str(docx)])
    assert isinstance(result, list)
    assert any(b["type"] == "image_url" for b in result)
    text_parts = [b.get("text", "") for b in result if b.get("type") == "text"]
    assert any("Report text here" in t for t in text_parts)
