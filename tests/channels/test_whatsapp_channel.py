"""Tests for WhatsApp channel outbound media support."""

import asyncio
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


def _sent_payloads(ch) -> list[dict]:
    """Extract all JSON payloads sent via the websocket."""
    return [json.loads(call[0][0]) for call in ch._ws.send.call_args_list]


def _sent_payloads_by_type(ch, msg_type: str) -> list[dict]:
    return [p for p in _sent_payloads(ch) if p.get("type") == msg_type]


@pytest.mark.asyncio
async def test_send_text_only():
    ch = _make_channel()
    msg = OutboundMessage(channel="whatsapp", chat_id="123@s.whatsapp.net", content="hello")

    await ch.send(msg)

    payloads = _sent_payloads(ch)
    # composing=false (paused) + actual send
    assert len(payloads) == 2
    assert payloads[0] == {"type": "typing", "to": "123@s.whatsapp.net", "composing": False}
    assert payloads[1]["type"] == "send"
    assert payloads[1]["text"] == "hello"


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

    media_sends = _sent_payloads_by_type(ch, "send_media")
    assert len(media_sends) == 1
    assert media_sends[0]["filePath"] == "/tmp/photo.jpg"
    assert media_sends[0]["mimetype"] == "image/jpeg"
    assert media_sends[0]["fileName"] == "photo.jpg"
    assert media_sends[0]["caption"] == "check this out"


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

    media_sends = _sent_payloads_by_type(ch, "send_media")
    assert len(media_sends) == 1
    assert media_sends[0]["mimetype"] == "application/pdf"


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

    media_sends = _sent_payloads_by_type(ch, "send_media")
    assert len(media_sends) == 2
    assert media_sends[0]["mimetype"] == "image/png"
    assert media_sends[1]["mimetype"] == "video/mp4"


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


@pytest.mark.asyncio
async def test_group_policy_mention_skips_unmentioned_group_message():
    ch = WhatsAppChannel({"enabled": True, "groupPolicy": "mention"}, MagicMock())
    ch._handle_message = AsyncMock()

    await ch._handle_bridge_message(
        json.dumps(
            {
                "type": "message",
                "id": "m1",
                "sender": "12345@g.us",
                "pn": "user@s.whatsapp.net",
                "content": "hello group",
                "timestamp": 1,
                "isGroup": True,
                "wasMentioned": False,
            }
        )
    )

    ch._handle_message.assert_not_called()


@pytest.mark.asyncio
async def test_group_policy_mention_accepts_mentioned_group_message():
    ch = WhatsAppChannel({"enabled": True, "groupPolicy": "mention"}, MagicMock())
    ch._handle_message = AsyncMock()

    await ch._handle_bridge_message(
        json.dumps(
            {
                "type": "message",
                "id": "m1",
                "sender": "12345@g.us",
                "pn": "user@s.whatsapp.net",
                "content": "hello @bot",
                "timestamp": 1,
                "isGroup": True,
                "wasMentioned": True,
            }
        )
    )

    ch._handle_message.assert_awaited_once()
    kwargs = ch._handle_message.await_args.kwargs
    assert kwargs["chat_id"] == "12345@g.us"
    assert kwargs["sender_id"] == "user"


# ── Typing indicator tests ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_typing_sends_composing_true():
    """_start_typing should send composing=true to the bridge."""
    ch = _make_channel()
    ch._start_typing("chat1@lid")
    # Let the typing loop run once
    await asyncio.sleep(0.05)
    ch._stop_typing("chat1@lid")
    await asyncio.sleep(0.05)

    payloads = _sent_payloads(ch)
    composing_true = [p for p in payloads if p.get("composing") is True]
    assert len(composing_true) >= 1
    assert composing_true[0]["to"] == "chat1@lid"


@pytest.mark.asyncio
async def test_send_clears_typing_indicator():
    """send() must send composing=false before the actual message."""
    ch = _make_channel()
    # Start typing as if an inbound message arrived
    ch._start_typing("chat1@lid")
    await asyncio.sleep(0.05)

    # Now send the response
    msg = OutboundMessage(channel="whatsapp", chat_id="chat1@lid", content="reply")
    await ch.send(msg)

    payloads = _sent_payloads(ch)
    # Find the composing=false that comes right before the send
    paused = [i for i, p in enumerate(payloads) if p.get("composing") is False]
    sends = [i for i, p in enumerate(payloads) if p.get("type") == "send"]
    assert len(paused) >= 1, "composing=false must be sent"
    assert len(sends) == 1, "message must be sent"
    # composing=false must come before the send
    assert paused[-1] < sends[0], "composing=false must precede the message send"


@pytest.mark.asyncio
async def test_send_paused_without_active_typing():
    """send() should send composing=false even if no typing was active."""
    ch = _make_channel()
    msg = OutboundMessage(channel="whatsapp", chat_id="chat1@lid", content="hi")
    await ch.send(msg)

    payloads = _sent_payloads(ch)
    assert payloads[0] == {"type": "typing", "to": "chat1@lid", "composing": False}
    assert payloads[1]["type"] == "send"


@pytest.mark.asyncio
async def test_typing_task_cancelled_on_stop():
    """_stop_typing should cancel the typing loop task."""
    ch = _make_channel()
    ch._start_typing("chat1@lid")
    assert "chat1@lid" in ch._typing_tasks

    ch._stop_typing("chat1@lid")
    assert "chat1@lid" not in ch._typing_tasks
