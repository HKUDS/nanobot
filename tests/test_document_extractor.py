from __future__ import annotations

from pathlib import Path

from nanobot.utils.document_extractor import _TEXT_READ_CHUNK_SIZE, _extract_text_file


class _TrackingReader:
    def __init__(self, handle, tracker: dict[str, int | bool]) -> None:
        self._handle = handle
        self._tracker = tracker

    def __enter__(self):
        self._handle.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        return self._handle.__exit__(exc_type, exc, tb)

    def read(self, size: int = -1):
        if size == -1:
            self._tracker["saw_unbounded_read"] = True
        data = self._handle.read(size)
        self._tracker["bytes_read"] += len(data)
        return data

    def __getattr__(self, name: str):
        return getattr(self._handle, name)


def test_extract_text_file_limits_reads_for_large_text(tmp_path, monkeypatch) -> None:
    path = tmp_path / "large.log"
    content = ("line-1234567890\n" * 2000).strip()
    path.write_text(content, encoding="utf-8")

    tracker: dict[str, int | bool] = {"bytes_read": 0, "saw_unbounded_read": False}
    original_open = Path.open

    def _tracking_open(self: Path, *args, **kwargs):
        handle = original_open(self, *args, **kwargs)
        if self == path and args[:1] == ("rb",):
            return _TrackingReader(handle, tracker)
        return handle

    monkeypatch.setattr(Path, "open", _tracking_open)

    result = _extract_text_file(path, max_chars=100)

    assert result is not None
    assert result.text == content[:100]
    assert result.extractor == "text:utf-8"
    assert result.truncated is True
    assert tracker["saw_unbounded_read"] is False
    assert tracker["bytes_read"] < path.stat().st_size


def test_extract_text_file_limits_reads_for_large_trailing_whitespace(tmp_path, monkeypatch) -> None:
    path = tmp_path / "padded.log"
    content = "header" + (" " * 20000)
    path.write_text(content, encoding="utf-8")

    tracker: dict[str, int | bool] = {"bytes_read": 0, "saw_unbounded_read": False}
    original_open = Path.open

    def _tracking_open(self: Path, *args, **kwargs):
        handle = original_open(self, *args, **kwargs)
        if self == path and args[:1] == ("rb",):
            return _TrackingReader(handle, tracker)
        return handle

    monkeypatch.setattr(Path, "open", _tracking_open)
    monkeypatch.setattr("nanobot.utils.document_extractor._TEXT_READ_CHUNK_SIZE", 64)

    result = _extract_text_file(path, max_chars=100)

    assert result is not None
    assert result.text == "header"
    assert result.extractor == "text:utf-8"
    assert result.truncated is True
    assert tracker["saw_unbounded_read"] is False
    assert tracker["bytes_read"] < path.stat().st_size + _TEXT_READ_CHUNK_SIZE


def test_extract_text_file_keeps_encoding_fallbacks(tmp_path) -> None:
    path = tmp_path / "sample.csv"
    content = ("café niño jalapeño résumé,1\n" * 8).strip()
    path.write_bytes(content.encode("latin-1"))

    result = _extract_text_file(path, max_chars=100)

    assert result is not None
    assert result.text == content[:100]
    assert result.extractor == "text:cp1252"
    assert result.truncated is True


def test_extract_text_file_detects_utf16le_without_bom(tmp_path) -> None:
    path = tmp_path / "utf16le.txt"
    content = ("Hello world from Windows text files.\nSecond line stays readable.\n" * 6).strip()
    path.write_bytes(content.encode("utf-16-le"))

    result = _extract_text_file(path, max_chars=100)

    assert result is not None
    assert result.text == content[:100]
    assert result.extractor == "text:utf-16-le"
    assert result.truncated is True


def test_extract_text_file_detects_utf16le_cjk_without_bom(tmp_path) -> None:
    path = tmp_path / "utf16le-cjk.txt"
    content = ("这是一个更长一点的中文段落，用来测试无 BOM 的 UTF-16LE 文本是否能被正确检测。\n" * 6).strip()
    path.write_bytes(content.encode("utf-16-le"))

    result = _extract_text_file(path, max_chars=100)

    assert result is not None
    assert result.text == content[:100]
    assert result.extractor == "text:utf-16-le"
    assert result.truncated is True
