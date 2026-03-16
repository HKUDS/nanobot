"""Tests for WhatsApp channel send() — text and media routing."""

import json

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.whatsapp import WhatsAppChannel
from nanobot.config.schema import WhatsAppConfig


def _make_channel() -> tuple[WhatsAppChannel, list[str]]:
    """Return a channel wired to a fake WebSocket that records sent payloads."""
    config = WhatsAppConfig(enabled=True, bridge_url="ws://localhost:3001", allow_from=["*"])
    channel = WhatsAppChannel(config, MessageBus())

    sent: list[str] = []

    class _FakeWS:
        async def send(self, data: str) -> None:
            sent.append(data)

    channel._ws = _FakeWS()
    channel._connected = True
    return channel, sent


@pytest.mark.asyncio
async def test_send_text_only() -> None:
    channel, sent = _make_channel()
    await channel.send(OutboundMessage(channel="whatsapp", chat_id="123@lid", content="hello"))

    assert len(sent) == 1
    payload = json.loads(sent[0])
    assert payload == {"type": "send", "to": "123@lid", "text": "hello"}


@pytest.mark.asyncio
async def test_send_image_produces_send_media_payload() -> None:
    channel, sent = _make_channel()
    await channel.send(OutboundMessage(
        channel="whatsapp",
        chat_id="123@lid",
        content="check this out",
        media=["/tmp/photo.jpg"],
    ))

    assert len(sent) == 1
    payload = json.loads(sent[0])
    assert payload == {
        "type": "send_media",
        "to": "123@lid",
        "path": "/tmp/photo.jpg",
        "caption": "check this out",
    }


@pytest.mark.asyncio
async def test_send_multiple_media_sends_one_payload_per_file() -> None:
    channel, sent = _make_channel()
    await channel.send(OutboundMessage(
        channel="whatsapp",
        chat_id="123@lid",
        content="two files",
        media=["/tmp/a.jpg", "/tmp/b.png"],
    ))

    assert len(sent) == 2
    for raw, path in zip(sent, ["/tmp/a.jpg", "/tmp/b.png"]):
        payload = json.loads(raw)
        assert payload["type"] == "send_media"
        assert payload["path"] == path
        assert payload["caption"] == "two files"


@pytest.mark.asyncio
async def test_send_media_with_empty_content_uses_empty_caption() -> None:
    channel, sent = _make_channel()
    await channel.send(OutboundMessage(
        channel="whatsapp",
        chat_id="123@lid",
        content="",
        media=["/tmp/img.png"],
    ))

    payload = json.loads(sent[0])
    assert payload["caption"] == ""


@pytest.mark.asyncio
async def test_send_does_nothing_when_not_connected() -> None:
    channel, sent = _make_channel()
    channel._connected = False

    await channel.send(OutboundMessage(channel="whatsapp", chat_id="123@lid", content="hi"))

    assert sent == []


@pytest.mark.asyncio
async def test_send_does_nothing_when_ws_is_none() -> None:
    channel, sent = _make_channel()
    channel._ws = None

    await channel.send(OutboundMessage(channel="whatsapp", chat_id="123@lid", content="hi"))

    assert sent == []
