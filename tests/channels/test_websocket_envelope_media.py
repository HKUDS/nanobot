"""Tests for WS envelope media handling (client image upload path).

Exercises ``WebSocketChannel._dispatch_envelope`` for the ``message`` branch:
decoding base64 data URLs, rejecting malformed / oversized / non-whitelisted
payloads, preserving backward compatibility with media-less frames, and
forwarding saved paths to ``_handle_message``.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.channels.websocket import (
    WebSocketChannel,
    _extract_data_url_mime,
)


def _tiny_png_data_url() -> str:
    """A 1-pixel PNG prefixed as a data URL — just enough for magic-bytes sniffing."""
    # 1x1 transparent PNG
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00"
        b"\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx"
        b"\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01\x00\x18\xdd\x8d\xb4\x00"
        b"\x00\x00\x00IEND\xaeB`\x82"
    )
    return f"data:image/png;base64,{base64.b64encode(png).decode()}"


def _data_url(mime: str, payload: bytes) -> str:
    return f"data:{mime};base64,{base64.b64encode(payload).decode()}"


def _make_channel() -> WebSocketChannel:
    bus = MagicMock()
    bus.publish_inbound = AsyncMock()
    channel = WebSocketChannel(
        {"enabled": True, "allowFrom": ["*"], "websocketRequiresToken": False},
        bus,
    )
    channel._handle_message = AsyncMock()  # type: ignore[method-assign]
    return channel


# -- Pure helpers --------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("data:image/png;base64,AAAA", "image/png"),
        ("data:image/jpeg;base64,AAAA", "image/jpeg"),
        ("data:IMAGE/PNG;base64,AAAA", "image/png"),
        ("data:image/svg+xml;base64,AAAA", "image/svg+xml"),
        ("data:text/plain;base64,AAAA", "text/plain"),
        ("http://evil.example/x.png", None),
        ("data:image/png,AAAA", None),  # missing `;base64`
        ("", None),
        (None, None),
    ],
)
def test_extract_data_url_mime(url: Any, expected: str | None) -> None:
    assert _extract_data_url_mime(url) == expected


# -- max_message_bytes bump ----------------------------------------------------


def test_max_message_bytes_default_supports_multi_image_frame() -> None:
    """Default 36 MB must comfortably hold 4 × 6 MB base64-encoded images."""
    from nanobot.channels.websocket import WebSocketConfig

    default = WebSocketConfig().max_message_bytes
    # 4 images × 6 MB × 1.37 base64 overhead ≈ 33 MB
    assert default >= 33 * 1024 * 1024
    # Upper bound 40 MB matches plan
    with pytest.raises(Exception):
        WebSocketConfig(max_message_bytes=41_943_040 + 1)


# -- _dispatch_envelope message branch + media --------------------------------


@pytest.mark.asyncio
async def test_message_without_media_backward_compatible() -> None:
    """Existing clients that don't send ``media`` keep working unchanged."""
    channel = _make_channel()
    mock_conn = AsyncMock()
    envelope = {"type": "message", "chat_id": "abc123", "content": "hello"}

    await channel._dispatch_envelope(mock_conn, "client-1", envelope)

    channel._handle_message.assert_awaited_once()
    call = channel._handle_message.call_args
    assert call.kwargs["chat_id"] == "abc123"
    assert call.kwargs["content"] == "hello"
    # When no media, we pass ``media=None`` so downstream treats it as absent.
    assert call.kwargs["media"] is None


@pytest.mark.asyncio
async def test_message_with_single_image_forwards_saved_path(tmp_path) -> None:
    channel = _make_channel()
    mock_conn = AsyncMock()
    envelope = {
        "type": "message",
        "chat_id": "abc123",
        "content": "look at this",
        "media": [{"data_url": _tiny_png_data_url(), "name": "shot.png"}],
    }

    with patch(
        "nanobot.channels.websocket.get_media_dir", return_value=tmp_path
    ):
        await channel._dispatch_envelope(mock_conn, "client-1", envelope)

    channel._handle_message.assert_awaited_once()
    paths = channel._handle_message.call_args.kwargs["media"]
    assert isinstance(paths, list) and len(paths) == 1
    saved = Path(paths[0])
    assert saved.exists()
    assert saved.suffix == ".png"
    assert saved.is_relative_to(tmp_path)


@pytest.mark.asyncio
async def test_message_with_multiple_images(tmp_path) -> None:
    channel = _make_channel()
    mock_conn = AsyncMock()
    envelope = {
        "type": "message",
        "chat_id": "abc123",
        "content": "a couple",
        "media": [
            {"data_url": _tiny_png_data_url()},
            {"data_url": _tiny_png_data_url()},
            {"data_url": _tiny_png_data_url()},
        ],
    }

    with patch(
        "nanobot.channels.websocket.get_media_dir", return_value=tmp_path
    ):
        await channel._dispatch_envelope(mock_conn, "client-1", envelope)

    paths = channel._handle_message.call_args.kwargs["media"]
    assert len(paths) == 3
    # Saved filenames must be unique.
    assert len({Path(p).name for p in paths}) == 3


@pytest.mark.asyncio
async def test_image_only_message_allows_empty_text(tmp_path) -> None:
    """When media is attached, empty text is acceptable."""
    channel = _make_channel()
    mock_conn = AsyncMock()
    envelope = {
        "type": "message",
        "chat_id": "abc123",
        "content": "",
        "media": [{"data_url": _tiny_png_data_url()}],
    }

    with patch(
        "nanobot.channels.websocket.get_media_dir", return_value=tmp_path
    ):
        await channel._dispatch_envelope(mock_conn, "client-1", envelope)

    channel._handle_message.assert_awaited_once()
    # Error event NOT sent.
    mock_conn.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_message_rejected_when_more_than_four_images(tmp_path) -> None:
    channel = _make_channel()
    mock_conn = AsyncMock()
    envelope = {
        "type": "message",
        "chat_id": "abc123",
        "content": "hi",
        "media": [{"data_url": _tiny_png_data_url()}] * 5,
    }

    with patch(
        "nanobot.channels.websocket.get_media_dir", return_value=tmp_path
    ):
        await channel._dispatch_envelope(mock_conn, "client-1", envelope)

    channel._handle_message.assert_not_awaited()
    mock_conn.send.assert_awaited_once()
    err = json.loads(mock_conn.send.call_args[0][0])
    assert err["event"] == "error"
    assert err["detail"] == "image_rejected"
    assert err["reason"] == "too_many_images"


@pytest.mark.asyncio
async def test_message_rejected_on_oversize_payload(tmp_path) -> None:
    channel = _make_channel()
    mock_conn = AsyncMock()
    oversized = b"x" * (9 * 1024 * 1024)  # > 8 MB WS limit
    envelope = {
        "type": "message",
        "chat_id": "abc123",
        "content": "big",
        "media": [{"data_url": _data_url("image/png", oversized)}],
    }

    with patch(
        "nanobot.channels.websocket.get_media_dir", return_value=tmp_path
    ):
        await channel._dispatch_envelope(mock_conn, "client-1", envelope)

    channel._handle_message.assert_not_awaited()
    err = json.loads(mock_conn.send.call_args[0][0])
    assert err["detail"] == "image_rejected"
    assert err["reason"] == "size"


@pytest.mark.asyncio
async def test_message_rejected_on_non_image_mime(tmp_path) -> None:
    channel = _make_channel()
    mock_conn = AsyncMock()
    envelope = {
        "type": "message",
        "chat_id": "abc123",
        "content": "pdf?",
        "media": [{"data_url": _data_url("application/pdf", b"%PDF-1.4")}],
    }

    with patch(
        "nanobot.channels.websocket.get_media_dir", return_value=tmp_path
    ):
        await channel._dispatch_envelope(mock_conn, "client-1", envelope)

    channel._handle_message.assert_not_awaited()
    err = json.loads(mock_conn.send.call_args[0][0])
    assert err["detail"] == "image_rejected"
    assert err["reason"] == "mime"


@pytest.mark.asyncio
async def test_message_rejected_on_svg_mime(tmp_path) -> None:
    """SVG is explicitly rejected — XSS surface inside embedded scripts."""
    channel = _make_channel()
    mock_conn = AsyncMock()
    envelope = {
        "type": "message",
        "chat_id": "abc123",
        "content": "svg",
        "media": [{"data_url": _data_url("image/svg+xml", b"<svg/>")}],
    }

    with patch(
        "nanobot.channels.websocket.get_media_dir", return_value=tmp_path
    ):
        await channel._dispatch_envelope(mock_conn, "client-1", envelope)

    channel._handle_message.assert_not_awaited()
    err = json.loads(mock_conn.send.call_args[0][0])
    assert err["reason"] == "mime"


@pytest.mark.asyncio
async def test_message_rejected_on_malformed_data_url(tmp_path) -> None:
    channel = _make_channel()
    mock_conn = AsyncMock()
    envelope = {
        "type": "message",
        "chat_id": "abc123",
        "content": "nope",
        "media": [{"data_url": "http://evil.example/image.png"}],
    }

    with patch(
        "nanobot.channels.websocket.get_media_dir", return_value=tmp_path
    ):
        await channel._dispatch_envelope(mock_conn, "client-1", envelope)

    channel._handle_message.assert_not_awaited()
    err = json.loads(mock_conn.send.call_args[0][0])
    assert err["reason"] == "decode"


@pytest.mark.asyncio
async def test_message_rejected_on_broken_base64(tmp_path) -> None:
    channel = _make_channel()
    mock_conn = AsyncMock()
    envelope = {
        "type": "message",
        "chat_id": "abc123",
        "content": "nope",
        "media": [{"data_url": "data:image/png;base64,not-valid-base64!!!"}],
    }

    with patch(
        "nanobot.channels.websocket.get_media_dir", return_value=tmp_path
    ):
        await channel._dispatch_envelope(mock_conn, "client-1", envelope)

    channel._handle_message.assert_not_awaited()
    err = json.loads(mock_conn.send.call_args[0][0])
    assert err["reason"] == "decode"


@pytest.mark.asyncio
async def test_message_rejected_when_media_item_shape_wrong(tmp_path) -> None:
    channel = _make_channel()
    mock_conn = AsyncMock()
    envelope = {
        "type": "message",
        "chat_id": "abc123",
        "content": "huh",
        # Not a dict — plain string at the top level.
        "media": ["data:image/png;base64,XXXX"],
    }

    with patch(
        "nanobot.channels.websocket.get_media_dir", return_value=tmp_path
    ):
        await channel._dispatch_envelope(mock_conn, "client-1", envelope)

    channel._handle_message.assert_not_awaited()
    err = json.loads(mock_conn.send.call_args[0][0])
    assert err["reason"] == "malformed"


@pytest.mark.asyncio
async def test_message_rejected_when_media_field_is_not_list() -> None:
    channel = _make_channel()
    mock_conn = AsyncMock()
    envelope = {
        "type": "message",
        "chat_id": "abc123",
        "content": "huh",
        "media": "not-a-list",
    }

    await channel._dispatch_envelope(mock_conn, "client-1", envelope)

    channel._handle_message.assert_not_awaited()
    err = json.loads(mock_conn.send.call_args[0][0])
    assert err["detail"] == "image_rejected"
    assert err["reason"] == "malformed"


@pytest.mark.asyncio
async def test_failed_media_does_not_partially_persist(tmp_path) -> None:
    """If the second image is invalid, the first must not be forwarded."""
    channel = _make_channel()
    mock_conn = AsyncMock()
    envelope = {
        "type": "message",
        "chat_id": "abc123",
        "content": "mixed",
        "media": [
            {"data_url": _tiny_png_data_url()},
            {"data_url": _data_url("application/pdf", b"%PDF-1.4")},
        ],
    }

    with patch(
        "nanobot.channels.websocket.get_media_dir", return_value=tmp_path
    ):
        await channel._dispatch_envelope(mock_conn, "client-1", envelope)

    channel._handle_message.assert_not_awaited()
    # The first image was saved to disk (we don't roll it back — the caller
    # is expected to not reference it) but the agent never sees the paths.
    # That's the important invariant: no partial publish.
    err = json.loads(mock_conn.send.call_args[0][0])
    assert err["reason"] == "mime"


@pytest.mark.asyncio
async def test_rejects_empty_text_without_media() -> None:
    """When no media is attached, whitespace-only content is still rejected
    (matches the existing behavior for backward compat)."""
    channel = _make_channel()
    mock_conn = AsyncMock()
    envelope = {
        "type": "message",
        "chat_id": "abc123",
        "content": "   ",
    }

    await channel._dispatch_envelope(mock_conn, "client-1", envelope)

    channel._handle_message.assert_not_awaited()
    err = json.loads(mock_conn.send.call_args[0][0])
    assert err["detail"] == "missing content"


@pytest.mark.asyncio
async def test_non_string_content_still_rejected() -> None:
    channel = _make_channel()
    mock_conn = AsyncMock()
    envelope = {
        "type": "message",
        "chat_id": "abc123",
        "content": 42,
    }

    await channel._dispatch_envelope(mock_conn, "client-1", envelope)

    channel._handle_message.assert_not_awaited()
    err = json.loads(mock_conn.send.call_args[0][0])
    assert err["detail"] == "missing content"
