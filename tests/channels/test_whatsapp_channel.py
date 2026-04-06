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

    # Simulate bridge ack: when send() is called, resolve the pending ack future
    original_send = ch._ws.send

    async def _mock_send(data, **kwargs):
        await original_send(data, **kwargs)
        payload = json.loads(data)
        msg_id = payload.get("msg_id")
        if msg_id and msg_id in ch._pending_acks:
            ch._pending_acks[msg_id].set_result(None)

    ch._ws.send = AsyncMock(side_effect=_mock_send)
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
async def test_send_when_disconnected_raises():
    ch = _make_channel()
    ch._connected = False

    msg = OutboundMessage(
        channel="whatsapp",
        chat_id="123@s.whatsapp.net",
        content="hello",
        media=["/tmp/x.jpg"],
    )
    with pytest.raises(ConnectionError, match="not connected"):
        await ch.send(msg)

    ch._ws.send.assert_not_called()


@pytest.mark.asyncio
async def test_send_raises_on_bridge_error():
    """When the bridge returns an error, send() should raise RuntimeError."""
    bus = MagicMock()
    ch = WhatsAppChannel({"enabled": True}, bus)
    ch._ws = AsyncMock()
    ch._connected = True

    # Simulate bridge error: when send() is called, resolve the pending ack with an error
    async def _mock_send_error(data, **kwargs):
        payload = json.loads(data)
        msg_id = payload.get("msg_id")
        if msg_id and msg_id in ch._pending_acks:
            ch._pending_acks[msg_id].set_exception(
                RuntimeError("WhatsApp bridge error: sendMediaMessage is not a function")
            )

    ch._ws.send = AsyncMock(side_effect=_mock_send_error)

    msg = OutboundMessage(
        channel="whatsapp",
        chat_id="123@s.whatsapp.net",
        content="check this",
        media=["/tmp/photo.jpg"],
    )
    with pytest.raises(RuntimeError, match="sendMediaMessage is not a function"):
        await ch.send(msg)


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
    await ch._start_typing("chat1@lid")
    # Let the typing loop run once
    await asyncio.sleep(0.05)
    await ch._stop_typing("chat1@lid")
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
    await ch._start_typing("chat1@lid")
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
    await ch._start_typing("chat1@lid")
    assert "chat1@lid" in ch._typing_tasks

    await ch._stop_typing("chat1@lid")
    assert "chat1@lid" not in ch._typing_tasks


# ── Identity resolution tests ────────────────────────────────────────────────


def _make_identity_channel(lid_map=None, sender_map=None, allow_from=None):
    """Create a channel with identity_resolution enabled and pre-loaded maps."""
    bus = MagicMock()
    config = {
        "enabled": True,
        "identity_resolution": True,
        "allow_from": allow_from or [],
    }
    ch = WhatsAppChannel(config, bus)
    ch._ws = AsyncMock()
    ch._connected = True
    ch._lid_map = lid_map or {}
    ch._sender_map = sender_map or {}
    ch._lid_map_loaded = True
    return ch


class TestIsAllowedWithLid:
    def test_phone_in_allow_from(self):
        ch = _make_identity_channel(allow_from=["14125550002"])
        assert ch.is_allowed("14125550002") is True

    def test_lid_maps_to_allowed_phone(self):
        ch = _make_identity_channel(
            allow_from=["14125550002"],
            lid_map={"914125550002": {"phone": "14125550002"}},
        )
        assert ch.is_allowed("914125550002") is True

    def test_lid_maps_to_disallowed_phone(self):
        ch = _make_identity_channel(
            allow_from=["14125550002"],
            lid_map={"999999": {"phone": "99999999"}},
        )
        assert ch.is_allowed("999999") is False

    def test_unknown_lid_denied(self):
        ch = _make_identity_channel(allow_from=["14125550002"])
        assert ch.is_allowed("999999") is False


class TestResolveSenderName:
    def test_resolves_from_sender_map(self):
        ch = _make_identity_channel(sender_map={"14125550002": "Emeka"})
        assert ch._resolve_sender_name("14125550002", "s1") == "Emeka"

    def test_resolves_lid_via_cross_reference(self):
        ch = _make_identity_channel(
            sender_map={"14125550002": "Emeka"},
            lid_map={"914125550002": {"phone": "14125550002"}},
        )
        assert ch._resolve_sender_name("914125550002", "s1") == "Emeka"

    def test_resolves_lid_with_direct_name(self):
        ch = _make_identity_channel(
            lid_map={"914125550002": {"phone": "14125550002", "name": "Emeka Direct"}},
        )
        assert ch._resolve_sender_name("914125550002", "s1") == "Emeka Direct"

    def test_returns_none_for_unknown(self):
        ch = _make_identity_channel()
        assert ch._resolve_sender_name("999999", "s1") is None

    def test_only_injects_once_per_session(self):
        ch = _make_identity_channel(sender_map={"14125550002": "Emeka"})
        assert ch._resolve_sender_name("14125550002", "s1") == "Emeka"
        assert ch._resolve_sender_name("14125550002", "s1") is None  # second time

    def test_no_greet_mark_when_name_not_found(self):
        """If name isn't found, session should NOT be marked as greeted."""
        ch = _make_identity_channel()
        assert ch._resolve_sender_name("999999", "s1") is None
        # Now add the mapping — should resolve on retry
        ch._sender_map["999999"] = "Late Joiner"
        assert ch._resolve_sender_name("999999", "s1") == "Late Joiner"


@pytest.mark.asyncio
async def test_sender_name_injected_in_content():
    """When identity_resolution is on, first message should have [Sender:] prefix."""
    ch = _make_identity_channel(
        allow_from=["14125550002"],
        sender_map={"14125550002": "Emeka"},
    )
    ch._handle_message = AsyncMock()

    await ch._handle_bridge_message(json.dumps({
        "type": "message",
        "id": "m1",
        "sender": "14125550002@s.whatsapp.net",
        "pn": "",
        "content": "Hello!",
        "timestamp": 1,
    }))

    ch._handle_message.assert_awaited_once()
    content = ch._handle_message.await_args.kwargs["content"]
    assert content.startswith("[Sender: Emeka]")
    assert "Hello!" in content


@pytest.mark.asyncio
async def test_sender_name_not_injected_for_commands():
    """Slash commands should not get [Sender:] prefix."""
    ch = _make_identity_channel(
        allow_from=["14125550002"],
        sender_map={"14125550002": "Emeka"},
    )
    ch._handle_message = AsyncMock()

    await ch._handle_bridge_message(json.dumps({
        "type": "message",
        "id": "m2",
        "sender": "14125550002@s.whatsapp.net",
        "pn": "",
        "content": "/status",
        "timestamp": 1,
    }))

    ch._handle_message.assert_awaited_once()
    content = ch._handle_message.await_args.kwargs["content"]
    assert content == "/status"


@pytest.mark.asyncio
async def test_sender_name_not_injected_for_media_only():
    """Media-only messages (empty content) should not get phantom text."""
    ch = _make_identity_channel(
        allow_from=["14125550002"],
        sender_map={"14125550002": "Emeka"},
    )
    ch._handle_message = AsyncMock()

    await ch._handle_bridge_message(json.dumps({
        "type": "message",
        "id": "m3",
        "sender": "14125550002@s.whatsapp.net",
        "pn": "",
        "content": "",
        "timestamp": 1,
    }))

    ch._handle_message.assert_awaited_once()
    content = ch._handle_message.await_args.kwargs["content"]
    assert "[Sender:" not in content


@pytest.mark.asyncio
async def test_lid_learned_from_inbound_pn():
    """When pn and sender differ, lid_map should be updated."""
    ch = _make_identity_channel(allow_from=["14125550002"])
    ch._handle_message = AsyncMock()

    await ch._handle_bridge_message(json.dumps({
        "type": "message",
        "id": "m4",
        "sender": "914125550002@lid",
        "pn": "14125550002@s.whatsapp.net",
        "content": "hello",
        "timestamp": 1,
    }))

    assert "914125550002" in ch._lid_map
    assert ch._lid_map["914125550002"]["phone"] == "14125550002"


@pytest.mark.asyncio
async def test_typing_not_started_for_disallowed_sender():
    """Typing indicator should NOT start for senders not in allow_from."""
    bus = MagicMock()
    ch = WhatsAppChannel({"enabled": True, "allow_from": ["99999"]}, bus)
    ch._ws = AsyncMock()
    ch._connected = True
    ch._handle_message = AsyncMock()

    await ch._handle_bridge_message(
        json.dumps({
            "type": "message",
            "id": "m1",
            "sender": "other@lid",
            "pn": "12345@s.whatsapp.net",
            "content": "hello",
            "timestamp": 1,
        })
    )

    # Typing should NOT have been started for a disallowed sender
    assert "other@lid" not in ch._typing_tasks
    # No composing=true should have been sent
    composing_calls = [
        c for c in ch._ws.send.call_args_list
        if "composing" in (c[0][0] if c[0] else "")
        and '"composing": true' in (c[0][0] if c[0] else "")
    ]
    assert len(composing_calls) == 0
