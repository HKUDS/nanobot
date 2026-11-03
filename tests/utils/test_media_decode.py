from __future__ import annotations

import base64
from pathlib import Path

import pytest

from nanobot.utils.media_decode import (
    DEFAULT_MAX_BYTES,
    MAX_FILE_SIZE,
    FileSizeExceeded,
    save_base64_data_url,
)


def _data_url(payload: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(payload).decode()}"


def test_saves_png_with_correct_extension(tmp_path) -> None:
    result = save_base64_data_url(_data_url(b"fake png"), tmp_path)
    assert result is not None
    assert result.endswith(".png")
    assert (tmp_path / result.split("/")[-1]).read_bytes() == b"fake png"


@pytest.mark.parametrize("mime", [
    "audio/webm;codecs=opus",
    "audio/webm;codecs=opus;name=voice.webm",
])
def test_saves_data_url_with_mime_parameters(tmp_path, mime: str) -> None:
    result = save_base64_data_url(_data_url(b"voice", mime=mime), tmp_path)
    assert result is not None
    assert result.endswith(".webm")
    assert (tmp_path / result.split("/")[-1]).read_bytes() == b"voice"


@pytest.mark.parametrize(
    ("mime", "suffix"),
    [
        ("audio/webm", ".webm"),
        ("video/webm", ".webm"),
        ("audio/ogg", ".ogg"),
        ("audio/wav", ".wav"),
        ("audio/mpga", ".mpga"),
    ],
)
def test_saves_common_audio_with_api_friendly_extension(
    tmp_path, mime: str, suffix: str
) -> None:
    result = save_base64_data_url(_data_url(b"voice", mime=mime), tmp_path)
    assert result is not None
    assert result.endswith(suffix)


def test_saves_document_with_safe_original_name(tmp_path) -> None:
    result = save_base64_data_url(
        _data_url(b"%PDF-1.4", mime="application/pdf"),
        tmp_path,
        filename="quarterly report.pdf",
    )
    assert result is not None
    assert result.endswith("_quarterly report.pdf")
    assert Path(result).read_bytes() == b"%PDF-1.4"


@pytest.mark.parametrize("stem", ["报告" * 40, "📄" * 60], ids=["cjk", "emoji"])
def test_saves_document_with_long_unicode_name(tmp_path: Path, stem: str) -> None:
    payload = b"%PDF-1.4"
    result = save_base64_data_url(
        _data_url(payload, mime="application/pdf"),
        tmp_path,
        filename=f"{stem}.pdf",
    )

    assert result is not None
    saved = Path(result)
    assert saved.parent == tmp_path
    assert saved.suffix == ".pdf"
    assert len(saved.name.encode("utf-8")) <= 255
    assert "�" not in saved.name
    assert saved.read_bytes() == payload


def test_document_filename_cannot_escape_media_dir(tmp_path) -> None:
    result = save_base64_data_url(
        _data_url(b"%PDF-1.4", mime="application/pdf"),
        tmp_path,
        filename="../../escape.pdf",
    )
    assert result is not None
    saved = Path(result)
    assert saved.parent == tmp_path
    assert saved.suffix == ".pdf"
    assert saved.read_bytes() == b"%PDF-1.4"


@pytest.mark.parametrize("data_url", [
    "not-a-data-url",
    "data:;base64,eA==",
    "data:image/png,eA==",
    "data:image/png;base64=1,eA==",
    "data:image/png;base64",
])
def test_returns_none_for_malformed_data_url(tmp_path, data_url: str) -> None:
    assert save_base64_data_url(data_url, tmp_path) is None
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("marker", ["BASE64", "Base64"])
def test_saves_data_url_when_base64_marker_case_varies(tmp_path: Path, marker: str) -> None:
    """RFC 2397 treats the base64 token as case-insensitive."""
    payload = b"hello"
    encoded = base64.b64encode(payload).decode()
    result = save_base64_data_url(
        f"data:text/plain;charset=utf-8;{marker},{encoded}",
        tmp_path,
    )
    assert result is not None
    assert Path(result).read_bytes() == payload


@pytest.mark.parametrize("marker", ["base64", "BASE64"])
@pytest.mark.parametrize("payload", ["not-valid-base64!!!", "@@@@"])
def test_returns_none_for_broken_base64(tmp_path, payload: str, marker: str) -> None:
    assert save_base64_data_url(f"data:image/png;{marker},{payload}", tmp_path) is None
    assert list(tmp_path.iterdir()) == []


def test_unknown_mime_falls_back_to_bin(tmp_path) -> None:
    result = save_base64_data_url(_data_url(b"xyz", mime="unknown/type"), tmp_path)
    assert result is not None
    assert result.endswith(".bin")


def test_default_limit_is_10mb(tmp_path) -> None:
    assert DEFAULT_MAX_BYTES == 10 * 1024 * 1024
    assert MAX_FILE_SIZE == 10 * 1024 * 1024

    oversized = b"x" * (11 * 1024 * 1024)
    with pytest.raises(FileSizeExceeded, match="10MB limit"):
        save_base64_data_url(_data_url(oversized), tmp_path)


def test_explicit_max_bytes_overrides_default(tmp_path) -> None:
    """WS channel passes 8 MB; a 9 MB payload should be rejected there even
    though it would pass the 10 MB API limit."""
    payload = b"y" * (9 * 1024 * 1024)
    with pytest.raises(FileSizeExceeded, match="8MB limit"):
        save_base64_data_url(_data_url(payload), tmp_path, max_bytes=8 * 1024 * 1024)


def test_saved_file_lives_under_media_dir(tmp_path) -> None:
    result = save_base64_data_url(_data_url(b"ok"), tmp_path)
    assert result is not None
    assert result.startswith(str(tmp_path))


def test_legacy_symbols_reexported_from_api_server() -> None:
    """Existing tests import ``_save_base64_data_url`` / ``_FileSizeExceeded``
    from ``nanobot.api.server`` — keep the aliases working."""
    from nanobot.api import server

    assert server._save_base64_data_url is save_base64_data_url
    assert server._FileSizeExceeded is FileSizeExceeded
    assert server.MAX_FILE_SIZE == MAX_FILE_SIZE
