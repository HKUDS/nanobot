"""Tests for WhatsApp channel outbound media support."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.channels.whatsapp import WhatsAppChannel


def _make_channel() -> WhatsAppChannel:
    bus = MagicMock()
    ch = WhatsAppChannel({"enabled": True}, bus)
    ch._ws = AsyncMock()
    ch._connected = True
    return ch


@pytest.mark.asyncio
async def test_send_text_only():
    ch = _make_channel()
    msg = OutboundMessage(channel="whatsapp", chat_id="123@s.whatsapp.net", content="hello")

    await ch.send(msg)

    ch._ws.send.assert_called_once()
    payload = json.loads(ch._ws.send.call_args[0][0])
    assert payload["type"] == "send"
    assert payload["text"] == "hello"


@pytest.mark.asyncio
async def test_send_media_dispatches_send_media_command():
    ch = _make_channel()
    msg = OutboundMessage(
        channel="whatsapp",
        chat_id="123@s.whatsapp.net",
        content="check this out",
        media=["/tmp/photo.jpg"],
    )

    await ch.send(msg)

    assert ch._ws.send.call_count == 2
    text_payload = json.loads(ch._ws.send.call_args_list[0][0][0])
    media_payload = json.loads(ch._ws.send.call_args_list[1][0][0])

    assert text_payload["type"] == "send"
    assert text_payload["text"] == "check this out"

    assert media_payload["type"] == "send_media"
    assert media_payload["filePath"] == "/tmp/photo.jpg"
    assert media_payload["mimetype"] == "image/jpeg"
    assert media_payload["fileName"] == "photo.jpg"


@pytest.mark.asyncio
async def test_send_media_only_no_text():
    ch = _make_channel()
    msg = OutboundMessage(
        channel="whatsapp",
        chat_id="123@s.whatsapp.net",
        content="",
        media=["/tmp/doc.pdf"],
    )

    await ch.send(msg)

    ch._ws.send.assert_called_once()
    payload = json.loads(ch._ws.send.call_args[0][0])
    assert payload["type"] == "send_media"
    assert payload["mimetype"] == "application/pdf"


@pytest.mark.asyncio
async def test_send_multiple_media():
    ch = _make_channel()
    msg = OutboundMessage(
        channel="whatsapp",
        chat_id="123@s.whatsapp.net",
        content="",
        media=["/tmp/a.png", "/tmp/b.mp4"],
    )

    await ch.send(msg)

    assert ch._ws.send.call_count == 2
    p1 = json.loads(ch._ws.send.call_args_list[0][0][0])
    p2 = json.loads(ch._ws.send.call_args_list[1][0][0])
    assert p1["mimetype"] == "image/png"
    assert p2["mimetype"] == "video/mp4"


@pytest.mark.asyncio
async def test_send_when_disconnected_is_noop():
    ch = _make_channel()
    ch._connected = False

    msg = OutboundMessage(
        channel="whatsapp",
        chat_id="123@s.whatsapp.net",
        content="hello",
        media=["/tmp/x.jpg"],
    )
    await ch.send(msg)

    ch._ws.send.assert_not_called()
