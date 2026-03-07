from __future__ import annotations

from pathlib import Path

from nanobot.utils.document_extractor import _extract_text_file


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
    assert result.extractor == "text:utf-8-sig"
    assert result.truncated is True
    assert tracker["saw_unbounded_read"] is False
    assert tracker["bytes_read"] < path.stat().st_size


def test_extract_text_file_keeps_encoding_fallbacks(tmp_path) -> None:
    path = tmp_path / "sample.csv"
    content = "café,1\nniño,2"
    path.write_bytes(content.encode("latin-1"))

    result = _extract_text_file(path, max_chars=100)

    assert result is not None
    assert result.text == content
    assert result.extractor == "text:latin-1"
    assert result.truncated is False


def test_extract_text_file_detects_utf16le_without_bom(tmp_path) -> None:
    path = tmp_path / "utf16le.txt"
    content = "Hello, world!\nSecond line."
    path.write_bytes(content.encode("utf-16-le"))

    result = _extract_text_file(path, max_chars=100)

    assert result is not None
    assert result.text == content
    assert result.extractor == "text:utf-16-le"
    assert result.truncated is False
