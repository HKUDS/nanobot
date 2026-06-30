"""Tests for WhatsApp channel outbound media support."""

import json
import os
import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

from blackcat.bus.events import OutboundMessage
from blackcat.channels.whatsapp import (
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
async def test_group_policy_mention_accepts_reply_to_bot_message():
    ch = WhatsAppChannel({"enabled": True, "allowFrom": ["*"], "groupPolicy": "mention"}, MagicMock())
    ch._handle_message = AsyncMock()

    await ch._handle_bridge_message(
        json.dumps(
            {
                "type": "message",
                "id": "m-reply",
                "sender": "12345@g.us",
                "pn": "user@s.whatsapp.net",
                "content": "replying to bot",
                "timestamp": 1,
                "isGroup": True,
                "wasMentioned": False,
                "isReplyToBot": True,
            }
        )
    )

    ch._handle_message.assert_awaited_once()
    kwargs = ch._handle_message.await_args.kwargs
    assert kwargs["metadata"]["is_reply_to_bot"] is True


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
async def test_group_sender_id_uses_participant_when_phone_jid_missing():
    """Group messages should identify the participant, not the group chat JID."""
    ch = WhatsAppChannel({"enabled": True, "allowFrom": ["SENDERLID"]}, MagicMock())
    ch._handle_message = AsyncMock()

    await ch._handle_bridge_message(
        json.dumps({
            "type": "message",
            "id": "group-lid",
            "sender": "12345@g.us",
            "pn": "",
            "participant": "SENDERLID@lid.whatsapp.net",
            "content": "hi",
            "timestamp": 1,
            "isGroup": True,
        })
    )

    kwargs = ch._handle_message.await_args.kwargs
    assert kwargs["sender_id"] == "SENDERLID"
    assert kwargs["metadata"]["participant"] == "SENDERLID@lid.whatsapp.net"


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
async def test_forwarded_voice_message_preserves_metadata_after_transcription():
    ch = WhatsAppChannel({"enabled": True, "allowFrom": ["*"]}, MagicMock())
    ch._handle_message = AsyncMock()
    ch.transcribe_audio = AsyncMock(return_value="Forwarded audio text")

    await ch._handle_bridge_message(
        json.dumps({
            "type": "message",
            "id": "v-forwarded",
            "sender": "12345@s.whatsapp.net",
            "pn": "",
            "content": "[Voice Message]",
            "timestamp": 1,
            "media": ["/tmp/voice.ogg"],
            "isForwarded": True,
        })
    )

    kwargs = ch._handle_message.await_args.kwargs
    assert kwargs["content"] == "Forwarded audio text"
    assert kwargs["metadata"]["is_forwarded"] is True


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
    monkeypatch.setattr("blackcat.channels.whatsapp._bridge_token_path", lambda: token_path)
    ch = WhatsAppChannel({"enabled": True, "bridgeToken": "manual-secret"}, MagicMock())

    assert ch._effective_bridge_token() == "manual-secret"
    assert not token_path.exists()


@pytest.mark.asyncio
async def test_login_exports_effective_bridge_token(monkeypatch, tmp_path):
    token_path = tmp_path / "whatsapp-auth" / "bridge-token"
    bridge_dir = tmp_path / "bridge"
    bridge_dir.mkdir()
    calls = []

    monkeypatch.setattr("blackcat.channels.whatsapp._bridge_token_path", lambda: token_path)
    monkeypatch.setattr("blackcat.channels.whatsapp._ensure_bridge_setup", lambda: bridge_dir)
    monkeypatch.setattr("blackcat.channels.whatsapp.shutil.which", lambda _: "/usr/bin/npm")

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return MagicMock()

    monkeypatch.setattr("blackcat.channels.whatsapp.subprocess.run", fake_run)
    ch = WhatsAppChannel({"enabled": True}, MagicMock())

    assert await ch.login() is True
    assert len(calls) == 1

    _, kwargs = calls[0]
    assert kwargs["cwd"] == bridge_dir
    assert kwargs["env"]["AUTH_DIR"] == str(token_path.parent)
    assert kwargs["env"]["BRIDGE_TOKEN"] == token_path.read_text(encoding="utf-8")


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

    monkeypatch.setattr("blackcat.channels.whatsapp._bridge_token_path", lambda: token_path)
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


# ---------------------------------------------------------------------------
# LID -> phone mapping seeding (startup): static config + bridge reverse files.
# ---------------------------------------------------------------------------


def test_lid_mappings_from_config():
    ch = WhatsAppChannel(
        {"enabled": True, "lidMappings": {"123456789012345": "15551234567"}},
        MagicMock(),
    )
    assert ch._lid_to_phone["123456789012345"] == "15551234567"


def test_lid_mappings_from_bridge_reverse_files(tmp_path, monkeypatch):
    auth_dir = tmp_path / "whatsapp-auth"
    auth_dir.mkdir()
    (auth_dir / "lid-mapping-999888777666555_reverse.json").write_text(
        json.dumps("15559998888"), encoding="utf-8"
    )
    # malformed / empty files must be ignored, not crash startup
    (auth_dir / "lid-mapping-broken_reverse.json").write_text("{not json", encoding="utf-8")
    (auth_dir / "lid-mapping-empty_reverse.json").write_text(json.dumps(""), encoding="utf-8")

    monkeypatch.setattr(
        "nanobot.config.paths.get_runtime_subdir", lambda name: auth_dir
    )

    ch = WhatsAppChannel({"enabled": True}, MagicMock())
    assert ch._lid_to_phone == {"999888777666555": "15559998888"}


def test_lid_mappings_config_takes_precedence_over_files(tmp_path, monkeypatch):
    auth_dir = tmp_path / "whatsapp-auth"
    auth_dir.mkdir()
    (auth_dir / "lid-mapping-555_reverse.json").write_text(
        json.dumps("from-file"), encoding="utf-8"
    )
    monkeypatch.setattr(
        "nanobot.config.paths.get_runtime_subdir", lambda name: auth_dir
    )

    ch = WhatsAppChannel(
        {"enabled": True, "lidMappings": {"555": "from-config"}}, MagicMock()
    )
    assert ch._lid_to_phone["555"] == "from-config"


def test_lid_mappings_empty_when_no_auth_dir(tmp_path, monkeypatch):
    missing = tmp_path / "does-not-exist"
    monkeypatch.setattr(
        "nanobot.config.paths.get_runtime_subdir", lambda name: missing
    )
    ch = WhatsAppChannel({"enabled": True}, MagicMock())
    assert ch._lid_to_phone == {}
