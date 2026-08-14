"""Tests for context builder media handling.

The ContextBuilder.build_user_content method should ONLY handle images.
The processing layer turns non-image media into attachment path references;
document contents are read on demand through ``read_file``.
"""

from __future__ import annotations

from pathlib import Path

from nanobot.agent.context import ContextBuilder


def _make_builder(tmp_path: Path) -> ContextBuilder:
    """Create a minimal ContextBuilder for testing."""
    return ContextBuilder(workspace=tmp_path, timezone="UTC")


def test_build_user_content_with_no_media_returns_string(tmp_path: Path) -> None:
    builder = _make_builder(tmp_path)
    result = builder.build_user_content("hello", None)
    assert result == "hello"


def test_build_user_content_with_image_returns_list(tmp_path: Path) -> None:
    """Image files should produce base64 content blocks."""
    builder = _make_builder(tmp_path)
    png = tmp_path / "test.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    result = builder.build_user_content("describe this", [str(png)])
    assert isinstance(result, list)
    types = [b["type"] for b in result]
    assert "image_url" in types
    assert "text" in types


def test_build_user_content_ignores_non_image_files(tmp_path: Path) -> None:
    """Non-image files should be silently skipped — extraction is not context builder's job."""
    builder = _make_builder(tmp_path)
    txt = tmp_path / "notes.txt"
    txt.write_text("some text", encoding="utf-8")
    result = builder.build_user_content("summarize", [str(txt)])
    assert result == "summarize"


def test_build_user_content_mixed_image_and_non_image(tmp_path: Path) -> None:
    """Only images should be included; non-image files are skipped."""
    builder = _make_builder(tmp_path)
    png = tmp_path / "chart.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    txt = tmp_path / "report.txt"
    txt.write_text("report text", encoding="utf-8")

    result = builder.build_user_content("analyze", [str(png), str(txt)])
    assert isinstance(result, list)
    assert any(b["type"] == "image_url" for b in result)
    text_parts = [b.get("text", "") for b in result if b.get("type") == "text"]
    assert all("report text" not in t for t in text_parts)
