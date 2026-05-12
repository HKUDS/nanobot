"""Tests for WhatsApp channel outbound media support."""

import asyncio
import json
import os
import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.channels.whatsapp import (
    WhatsAppChannel,
    _load_or_create_bridge_token,
)


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


@pytest.mark.asyncio
async def test_group_policy_mention_skips_unmentioned_group_message():
    ch = WhatsAppChannel({"enabled": True, "allowFrom": ["*"], "groupPolicy": "mention"}, MagicMock())
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
    ch = WhatsAppChannel({"enabled": True, "allowFrom": ["*"], "groupPolicy": "mention"}, MagicMock())
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


@pytest.mark.asyncio
async def test_sender_id_prefers_phone_jid_over_lid():
    """sender_id should resolve to phone number when @s.whatsapp.net JID is present."""
    ch = WhatsAppChannel({"enabled": True, "allowFrom": ["*"]}, MagicMock())
    ch._handle_message = AsyncMock()

    await ch._handle_bridge_message(
        json.dumps({
            "type": "message",
            "id": "lid1",
            "sender": "ABC123@lid.whatsapp.net",
            "pn": "5551234@s.whatsapp.net",
            "content": "hi",
            "timestamp": 1,
        })
    )

    kwargs = ch._handle_message.await_args.kwargs
    assert kwargs["sender_id"] == "5551234"


@pytest.mark.asyncio
async def test_lid_to_phone_cache_resolves_lid_only_messages():
    """When only LID is present, a cached LID→phone mapping should be used."""
    ch = WhatsAppChannel({"enabled": True, "allowFrom": ["*"]}, MagicMock())
    ch._handle_message = AsyncMock()

    # First message: both phone and LID → builds cache
    await ch._handle_bridge_message(
        json.dumps({
            "type": "message",
            "id": "c1",
            "sender": "LID99@lid.whatsapp.net",
            "pn": "5559999@s.whatsapp.net",
            "content": "first",
            "timestamp": 1,
        })
    )
    # Second message: only LID, no phone
    await ch._handle_bridge_message(
        json.dumps({
            "type": "message",
            "id": "c2",
            "sender": "LID99@lid.whatsapp.net",
            "pn": "",
            "content": "second",
            "timestamp": 2,
        })
    )

    second_kwargs = ch._handle_message.await_args_list[1].kwargs
    assert second_kwargs["sender_id"] == "5559999"


@pytest.mark.asyncio
async def test_voice_message_transcription_uses_media_path():
    """Voice messages are transcribed when media path is available."""
    ch = WhatsAppChannel({"enabled": True, "allowFrom": ["*"]}, MagicMock())
    ch.transcription_provider = "openai"
    ch.transcription_api_key = "sk-test"
    ch._handle_message = AsyncMock()
    ch.transcribe_audio = AsyncMock(return_value="Hello world")

    await ch._handle_bridge_message(
        json.dumps({
            "type": "message",
            "id": "v1",
            "sender": "12345@s.whatsapp.net",
            "pn": "",
            "content": "[Voice Message]",
            "timestamp": 1,
            "media": ["/tmp/voice.ogg"],
        })
    )

    ch.transcribe_audio.assert_awaited_once_with("/tmp/voice.ogg")
    kwargs = ch._handle_message.await_args.kwargs
    assert kwargs["content"].startswith("Hello world")


@pytest.mark.asyncio
async def test_unauthorized_voice_message_does_not_transcribe() -> None:
    ch = WhatsAppChannel({"enabled": True, "allowFrom": ["allowed"]}, MagicMock())
    ch._handle_message = AsyncMock()
    ch.transcribe_audio = AsyncMock(return_value="Hello world")

    await ch._handle_bridge_message(
        json.dumps({
            "type": "message",
            "id": "v-blocked",
            "sender": "blocked@s.whatsapp.net",
            "pn": "",
            "content": "[Voice Message]",
            "timestamp": 1,
            "media": ["/tmp/voice.ogg"],
        })
    )

    ch.transcribe_audio.assert_not_awaited()
    ch._handle_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_voice_message_no_media_shows_not_available():
    """Voice messages without media produce a fallback placeholder."""
    ch = WhatsAppChannel({"enabled": True, "allowFrom": ["*"]}, MagicMock())
    ch._handle_message = AsyncMock()

    await ch._handle_bridge_message(
        json.dumps({
            "type": "message",
            "id": "v2",
            "sender": "12345@s.whatsapp.net",
            "pn": "",
            "content": "[Voice Message]",
            "timestamp": 1,
        })
    )

    kwargs = ch._handle_message.await_args.kwargs
    assert kwargs["content"] == "[Voice Message: Audio not available]"


def test_load_or_create_bridge_token_persists_generated_secret(tmp_path):
    token_path = tmp_path / "whatsapp-auth" / "bridge-token"

    first = _load_or_create_bridge_token(token_path)
    second = _load_or_create_bridge_token(token_path)

    assert first == second
    assert token_path.read_text(encoding="utf-8") == first
    assert len(first) >= 32
    if os.name != "nt":
        assert token_path.stat().st_mode & 0o777 == 0o600


def test_configured_bridge_token_skips_local_token_file(monkeypatch, tmp_path):
    token_path = tmp_path / "whatsapp-auth" / "bridge-token"
    monkeypatch.setattr("nanobot.channels.whatsapp._bridge_token_path", lambda: token_path)
    ch = WhatsAppChannel({"enabled": True, "bridgeToken": "manual-secret"}, MagicMock())

    assert ch._effective_bridge_token() == "manual-secret"
    assert not token_path.exists()


@pytest.mark.asyncio
async def test_login_exports_effective_bridge_token(monkeypatch, tmp_path):
    token_path = tmp_path / "whatsapp-auth" / "bridge-token"
    bridge_dir = tmp_path / "bridge"
    bridge_dir.mkdir()
    calls = []

    monkeypatch.setattr("nanobot.channels.whatsapp._bridge_token_path", lambda: token_path)
    monkeypatch.setattr("nanobot.channels.whatsapp._ensure_bridge_setup", lambda: bridge_dir)
    monkeypatch.setattr("nanobot.channels.whatsapp.shutil.which", lambda _: "/usr/bin/npm")

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return MagicMock()

    monkeypatch.setattr("nanobot.channels.whatsapp.subprocess.run", fake_run)
    ch = WhatsAppChannel({"enabled": True}, MagicMock())

    assert await ch.login() is True
    assert len(calls) == 1

    _, kwargs = calls[0]
    assert kwargs["cwd"] == bridge_dir
    assert kwargs["env"]["AUTH_DIR"] == str(token_path.parent)
    assert kwargs["env"]["BRIDGE_TOKEN"] == token_path.read_text(encoding="utf-8")


# ── typing indicator ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_inbound_message_starts_typing():
    ch = WhatsAppChannel({"enabled": True, "allowFrom": ["*"]}, MagicMock())
    ch._ws = AsyncMock()
    ch._connected = True
    ch._handle_message = AsyncMock()

    await ch._handle_bridge_message(
        json.dumps({
            "type": "message",
            "id": "t1",
            "sender": "111@s.whatsapp.net",
            "pn": "",
            "content": "hello",
            "timestamp": 1,
        })
    )

    # A typing task must have been created for the chat
    assert "111@s.whatsapp.net" in ch._typing_tasks


@pytest.mark.asyncio
async def test_send_stops_typing():
    ch = _make_channel()
    ch._typing_tasks["123@s.whatsapp.net"] = asyncio.create_task(asyncio.sleep(60))

    msg = OutboundMessage(channel="whatsapp", chat_id="123@s.whatsapp.net", content="reply")
    await ch.send(msg)

    assert "123@s.whatsapp.net" not in ch._typing_tasks


@pytest.mark.asyncio
async def test_send_progress_message_does_not_stop_typing():
    ch = _make_channel()
    task = asyncio.create_task(asyncio.sleep(60))
    ch._typing_tasks["123@s.whatsapp.net"] = task

    msg = OutboundMessage(
        channel="whatsapp",
        chat_id="123@s.whatsapp.net",
        content="...",
        metadata={"_progress": True},
    )
    await ch.send(msg)

    assert "123@s.whatsapp.net" in ch._typing_tasks
    task.cancel()


@pytest.mark.asyncio
async def test_typing_loop_sends_composing_presence():
    ch = WhatsAppChannel({"enabled": True}, MagicMock())
    ch._ws = AsyncMock()
    ch._connected = True

    task = asyncio.create_task(ch._typing_loop("abc@s.whatsapp.net"))
    await asyncio.sleep(0.05)
    task.cancel()
    await asyncio.sleep(0)  # let the loop settle; _typing_loop suppresses CancelledError internally

    assert ch._ws.send.call_count >= 1
    payload = json.loads(ch._ws.send.call_args_list[0][0][0])
    assert payload == {"type": "presence", "to": "abc@s.whatsapp.net", "presence": "composing"}


@pytest.mark.asyncio
async def test_stop_cancels_typing_tasks():
    ch = WhatsAppChannel({"enabled": True}, MagicMock())
    task = asyncio.create_task(asyncio.sleep(60))
    ch._typing_tasks["x@s.whatsapp.net"] = task
    ch._ws = AsyncMock()

    await ch.stop()
    await asyncio.sleep(0)  # let the event loop process the cancellation

    assert task.cancelled()
    assert not ch._typing_tasks


# ── emoji reaction ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_inbound_message_sends_reaction():
    ch = WhatsAppChannel({"enabled": True, "allowFrom": ["*"]}, MagicMock())
    ch._ws = AsyncMock()
    ch._connected = True
    ch._handle_message = AsyncMock()

    await ch._handle_bridge_message(
        json.dumps({
            "type": "message",
            "id": "msg99",
            "sender": "222@s.whatsapp.net",
            "pn": "",
            "content": "hi",
            "timestamp": 1,
        })
    )

    sent_payloads = [json.loads(c[0][0]) for c in ch._ws.send.call_args_list]
    react_calls = [p for p in sent_payloads if p.get("type") == "react"]
    assert len(react_calls) == 1
    assert react_calls[0]["to"] == "222@s.whatsapp.net"
    assert react_calls[0]["messageId"] == "msg99"
    assert react_calls[0]["emoji"] == "👀"


@pytest.mark.asyncio
async def test_react_emoji_uses_config_value():
    ch = WhatsAppChannel({"enabled": True, "allowFrom": ["*"], "reactEmoji": "🔥"}, MagicMock())
    ch._ws = AsyncMock()
    ch._connected = True
    ch._handle_message = AsyncMock()

    await ch._handle_bridge_message(
        json.dumps({
            "type": "message",
            "id": "rx1",
            "sender": "333@s.whatsapp.net",
            "pn": "",
            "content": "fire",
            "timestamp": 1,
        })
    )

    sent_payloads = [json.loads(c[0][0]) for c in ch._ws.send.call_args_list]
    react_calls = [p for p in sent_payloads if p.get("type") == "react"]
    assert react_calls[0]["emoji"] == "🔥"


@pytest.mark.asyncio
async def test_group_message_reaction_includes_participant():
    """In groups, the reaction key needs the original sender's JID to bind correctly."""
    ch = WhatsAppChannel({"enabled": True, "allowFrom": ["*"], "groupPolicy": "open"}, MagicMock())
    ch._ws = AsyncMock()
    ch._connected = True
    ch._handle_message = AsyncMock()

    await ch._handle_bridge_message(
        json.dumps({
            "type": "message",
            "id": "gm1",
            "sender": "555@g.us",
            "pn": "user@s.whatsapp.net",
            "participant": "user@s.whatsapp.net",
            "content": "hi group",
            "timestamp": 1,
            "isGroup": True,
        })
    )

    sent_payloads = [json.loads(c[0][0]) for c in ch._ws.send.call_args_list]
    react = next(p for p in sent_payloads if p.get("type") == "react")
    assert react["to"] == "555@g.us"
    assert react["participant"] == "user@s.whatsapp.net"
    assert ch._handle_message.await_args.kwargs["metadata"]["participant"] == "user@s.whatsapp.net"


@pytest.mark.asyncio
async def test_dm_reaction_omits_participant():
    """For 1:1 chats there is no participant — the field must not be sent."""
    ch = WhatsAppChannel({"enabled": True, "allowFrom": ["*"]}, MagicMock())
    ch._ws = AsyncMock()
    ch._connected = True
    ch._handle_message = AsyncMock()

    await ch._handle_bridge_message(
        json.dumps({
            "type": "message",
            "id": "dm1",
            "sender": "777@s.whatsapp.net",
            "pn": "",
            "content": "hi",
            "timestamp": 1,
        })
    )

    sent_payloads = [json.loads(c[0][0]) for c in ch._ws.send.call_args_list]
    react = next(p for p in sent_payloads if p.get("type") == "react")
    assert "participant" not in react


@pytest.mark.asyncio
async def test_send_removes_reaction():
    """When the agent's final reply lands, the original 👀 reaction is cleared."""
    ch = _make_channel()
    msg = OutboundMessage(
        channel="whatsapp",
        chat_id="123@s.whatsapp.net",
        content="reply",
        metadata={"message_id": "msg42"},
    )

    await ch.send(msg)

    sent_payloads = [json.loads(c[0][0]) for c in ch._ws.send.call_args_list]
    react = next(p for p in sent_payloads if p.get("type") == "react")
    assert react["messageId"] == "msg42"
    assert react["emoji"] == ""  # empty text removes the bot's reaction


@pytest.mark.asyncio
async def test_send_removes_reaction_with_participant_in_groups():
    """In groups the removal must include participant so it targets the right message."""
    ch = _make_channel()
    msg = OutboundMessage(
        channel="whatsapp",
        chat_id="555@g.us",
        content="reply",
        metadata={"message_id": "gm1", "participant": "user@s.whatsapp.net"},
    )

    await ch.send(msg)

    sent_payloads = [json.loads(c[0][0]) for c in ch._ws.send.call_args_list]
    react = next(p for p in sent_payloads if p.get("type") == "react")
    assert react["participant"] == "user@s.whatsapp.net"
    assert react["emoji"] == ""


@pytest.mark.asyncio
async def test_send_progress_does_not_remove_reaction():
    """Streaming/progress messages should not clear the reaction prematurely."""
    ch = _make_channel()
    msg = OutboundMessage(
        channel="whatsapp",
        chat_id="123@s.whatsapp.net",
        content="...",
        metadata={"_progress": True, "message_id": "msg42"},
    )

    await ch.send(msg)

    sent_payloads = [json.loads(c[0][0]) for c in ch._ws.send.call_args_list]
    assert not any(p.get("type") == "react" for p in sent_payloads)


@pytest.mark.asyncio
async def test_send_without_message_id_skips_reaction_removal():
    """Outbound messages without an origin message_id (e.g. proactive sends) must not crash."""
    ch = _make_channel()
    msg = OutboundMessage(channel="whatsapp", chat_id="123@s.whatsapp.net", content="hi")

    await ch.send(msg)

    sent_payloads = [json.loads(c[0][0]) for c in ch._ws.send.call_args_list]
    assert not any(p.get("type") == "react" for p in sent_payloads)


@pytest.mark.asyncio
async def test_add_reaction_skipped_when_no_message_id():
    ch = _make_channel()
    await ch._add_reaction("abc@s.whatsapp.net", "", "👀")
    ch._ws.send.assert_not_called()


@pytest.mark.asyncio
async def test_add_reaction_skipped_when_no_emoji():
    ch = WhatsAppChannel({"enabled": True, "reactEmoji": ""}, MagicMock())
    ch._ws = AsyncMock()
    ch._connected = True
    ch._handle_message = AsyncMock()

    await ch._handle_bridge_message(
        json.dumps({
            "type": "message",
            "id": "nr1",
            "sender": "444@s.whatsapp.net",
            "pn": "",
            "content": "no react",
            "timestamp": 1,
        })
    )

    sent_payloads = [json.loads(c[0][0]) for c in ch._ws.send.call_args_list]
    assert not any(p.get("type") == "react" for p in sent_payloads)


@pytest.mark.asyncio
async def test_start_sends_auth_message_with_generated_token(monkeypatch, tmp_path):
    token_path = tmp_path / "whatsapp-auth" / "bridge-token"
    sent_messages: list[str] = []

    class FakeWS:
        def __init__(self) -> None:
            self.close = AsyncMock()

        async def send(self, message: str) -> None:
            sent_messages.append(message)
            ch._running = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class FakeConnect:
        def __init__(self, ws):
            self.ws = ws

        async def __aenter__(self):
            return self.ws

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("nanobot.channels.whatsapp._bridge_token_path", lambda: token_path)
    monkeypatch.setitem(
        sys.modules,
        "websockets",
        types.SimpleNamespace(connect=lambda url: FakeConnect(FakeWS())),
    )

    ch = WhatsAppChannel({"enabled": True, "bridgeUrl": "ws://localhost:3001"}, MagicMock())
    await ch.start()

    assert sent_messages == [
        json.dumps({"type": "auth", "token": token_path.read_text(encoding="utf-8")})
    ]
