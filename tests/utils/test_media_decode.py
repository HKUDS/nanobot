"""Tests for ``nanobot.utils.media_decode``."""

from __future__ import annotations

import base64

import pytest

from nanobot.utils.media_decode import (
    DEFAULT_MAX_BYTES,
    FileSizeExceeded,
    MAX_FILE_SIZE,
    save_base64_data_url,
)


def _data_url(payload: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(payload).decode()}"


def test_saves_png_with_correct_extension(tmp_path) -> None:
    result = save_base64_data_url(_data_url(b"fake png"), tmp_path)
    assert result is not None
    assert result.endswith(".png")
    assert (tmp_path / result.split("/")[-1]).read_bytes() == b"fake png"


def test_returns_none_for_malformed_data_url(tmp_path) -> None:
    assert save_base64_data_url("not-a-data-url", tmp_path) is None


def test_returns_none_for_broken_base64(tmp_path) -> None:
    # Python's b64decode strips non-alphabet chars by default, so we need a
    # payload whose alphabet-filtered length breaks padding.
    assert save_base64_data_url("data:image/png;base64,not-valid-base64!!!", tmp_path) is None


def test_unknown_mime_falls_back_to_bin(tmp_path) -> None:
    result = save_base64_data_url(_data_url(b"xyz", mime="unknown/type"), tmp_path)
    assert result is not None
    assert result.endswith(".bin")


def test_default_limit_is_10mb(tmp_path) -> None:
    """Backwards-compatible default — the API path depends on this."""
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
