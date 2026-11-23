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


def test_build_user_content_ignores_non_image_files(tmp_path: Path) -> None:
    builder = _make_builder(tmp_path)
    txt = tmp_path / "notes.txt"
    txt.write_text("some text", encoding="utf-8")
    result = builder.build_user_content("summarize", [str(txt)])
    assert result == "summarize"


def test_build_user_content_mixed_image_and_non_image(tmp_path: Path) -> None:
    builder = _make_builder(tmp_path)
    png = tmp_path / "chart.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    txt = tmp_path / "report.txt"
    txt.write_text("report text", encoding="utf-8")

    result = builder.build_user_content("analyze", [str(png), str(txt)])
    assert isinstance(result, list)
    assert any(b["type"] == "image_url" for b in result)
    text_parts = [b.get("text", "") for b in result if b.get("type") == "text"]
    assert text_parts == ["analyze"]
