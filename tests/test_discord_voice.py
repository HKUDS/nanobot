"""Tests for Discord voice-in (transcription) and voice-out (voice message flags)."""

import asyncio
import base64
import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.discord import (
    DiscordChannel,
    DiscordConfig,
    _generate_waveform,
    _get_ogg_duration,
)


def _make_config(**kwargs) -> DiscordConfig:
    return DiscordConfig(
        enabled=True,
        token="Bot-test-token",
        allow_from=["*"],
        **kwargs,
    )


def _make_channel(groq_api_key: str = "test-groq-key") -> DiscordChannel:
    ch = DiscordChannel(_make_config(), MessageBus(), groq_api_key=groq_api_key)
    ch._http = MagicMock()  # replaced per test
    return ch


class _FakeStreamResponse:
    def __init__(self, content: bytes):
        self._content = content

    def raise_for_status(self):
        return None

    async def aread(self) -> bytes:
        return self._content


class _FakeStreamContext:
    def __init__(self, content: bytes):
        self._resp = _FakeStreamResponse(content)

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _make_stream_http(content: bytes) -> MagicMock:
    fake_http = MagicMock()
    fake_http.stream = MagicMock(side_effect=lambda method, url: _FakeStreamContext(content))
    return fake_http


# ---------------------------------------------------------------------------
# Unit tests for module-level helpers
# ---------------------------------------------------------------------------

def test_generate_waveform_returns_base64_64_bytes():
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
        # write 640 bytes so each of the 64 chunks has 10 bytes
        f.write(bytes(range(256)) * 3)  # 768 bytes
        tmp = Path(f.name)
    try:
        result = _generate_waveform(tmp, num_bars=64)
        decoded = base64.b64decode(result)
        assert len(decoded) == 64
        assert all(0 <= b <= 255 for b in decoded)
    finally:
        tmp.unlink(missing_ok=True)


def test_generate_waveform_empty_file():
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
        f.write(b"")
        tmp = Path(f.name)
    try:
        result = _generate_waveform(tmp, num_bars=64)
        decoded = base64.b64decode(result)
        assert len(decoded) == 64
        assert all(b == 0 for b in decoded)
    finally:
        tmp.unlink(missing_ok=True)


def test_get_ogg_duration_falls_back_on_ffprobe_failure():
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
        f.write(b"\x00" * 32000)  # 32000 bytes → 32000/16000 = 2.0 s estimate
        tmp = Path(f.name)
    try:
        with patch("nanobot.channels.discord.subprocess.run", side_effect=FileNotFoundError):
            duration = _get_ogg_duration(tmp)
        assert duration == pytest.approx(2.0, rel=0.01)
    finally:
        tmp.unlink(missing_ok=True)


def test_get_ogg_duration_uses_ffprobe_when_available():
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
        f.write(b"\x00" * 100)
        tmp = Path(f.name)
    try:
        fake_result = MagicMock()
        fake_result.stdout = "3.14\n"
        with patch("nanobot.channels.discord.subprocess.run", return_value=fake_result):
            duration = _get_ogg_duration(tmp)
        assert duration == pytest.approx(3.14)
    finally:
        tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Voice-in: transcription on incoming audio attachments
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_voice_in_transcribes_ogg_attachment(tmp_path, monkeypatch):
    """OGG attachment → GroqTranscriptionProvider called → [transcription: ...] in content."""
    ch = _make_channel(groq_api_key="gk-123")

    # Fake HTTP: download returns audio bytes
    ch._http = _make_stream_http(b"fake-ogg-data")

    # Redirect media_dir to tmp_path
    monkeypatch.setattr("nanobot.channels.discord.get_media_dir", lambda channel=None: tmp_path / (channel or ""))

    # Fake transcription provider
    mock_transcribe = AsyncMock(return_value="hello from voice")

    captured: dict[str, Any] = {}

    async def fake_handle_message(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(ch, "_handle_message", fake_handle_message)
    monkeypatch.setattr(ch, "_start_typing", AsyncMock())

    with patch("nanobot.providers.transcription.GroqTranscriptionProvider") as MockProvider:
        MockProvider.return_value.transcribe = mock_transcribe

        payload = {
            "author": {"id": "user123", "bot": False},
            "channel_id": "chan456",
            "content": "",
            "attachments": [{
                "id": "att1",
                "url": "https://cdn.discord.com/voice.ogg",
                "filename": "voice.ogg",
                "size": 1000,
            }],
        }
        await ch._handle_message_create(payload)

    assert "[transcription: hello from voice]" in captured["content"]
    MockProvider.assert_called_once_with(api_key="gk-123")
    mock_transcribe.assert_called_once()


@pytest.mark.asyncio
async def test_voice_in_skips_transcription_without_api_key(tmp_path, monkeypatch):
    """No GROQ key → audio attachment treated as regular [attachment: ...], no crash."""
    ch = _make_channel(groq_api_key="")  # no key

    ch._http = _make_stream_http(b"fake-ogg-data")

    monkeypatch.setattr("nanobot.channels.discord.get_media_dir", lambda channel=None: tmp_path / (channel or ""))

    captured: dict[str, Any] = {}

    async def fake_handle_message(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(ch, "_handle_message", fake_handle_message)
    monkeypatch.setattr(ch, "_start_typing", AsyncMock())

    payload = {
        "author": {"id": "user123", "bot": False},
        "channel_id": "chan456",
        "content": "",
        "attachments": [{
            "id": "att1",
            "url": "https://cdn.discord.com/voice.ogg",
            "filename": "voice.ogg",
            "size": 1000,
        }],
    }
    await ch._handle_message_create(payload)

    assert "[transcription:" not in captured["content"]
    assert "[attachment:" in captured["content"]


@pytest.mark.asyncio
async def test_voice_in_non_audio_attachment_not_transcribed(tmp_path, monkeypatch):
    """A .png attachment should NOT trigger transcription."""
    ch = _make_channel(groq_api_key="gk-123")

    ch._http = _make_stream_http(b"fake-png-data")

    monkeypatch.setattr("nanobot.channels.discord.get_media_dir", lambda channel=None: tmp_path / (channel or ""))

    captured: dict[str, Any] = {}

    async def fake_handle_message(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(ch, "_handle_message", fake_handle_message)
    monkeypatch.setattr(ch, "_start_typing", AsyncMock())

    with patch("nanobot.providers.transcription.GroqTranscriptionProvider") as MockProvider:
        payload = {
            "author": {"id": "user123", "bot": False},
            "channel_id": "chan456",
            "content": "",
            "attachments": [{
                "id": "att1",
                "url": "https://cdn.discord.com/image.png",
                "filename": "image.png",
                "size": 500,
            }],
        }
        await ch._handle_message_create(payload)
        MockProvider.assert_not_called()

    assert "[attachment:" in captured["content"]
    assert "[transcription:" not in captured["content"]


@pytest.mark.asyncio
async def test_voice_in_failed_transcription_falls_back_to_attachment(tmp_path, monkeypatch):
    """If transcription returns empty string, fall back to [attachment: ...]."""
    ch = _make_channel(groq_api_key="gk-123")

    ch._http = _make_stream_http(b"fake-ogg-data")

    monkeypatch.setattr("nanobot.channels.discord.get_media_dir", lambda channel=None: tmp_path / (channel or ""))

    captured: dict[str, Any] = {}

    async def fake_handle_message(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(ch, "_handle_message", fake_handle_message)
    monkeypatch.setattr(ch, "_start_typing", AsyncMock())

    with patch("nanobot.providers.transcription.GroqTranscriptionProvider") as MockProvider:
        MockProvider.return_value.transcribe = AsyncMock(return_value="")  # empty

        payload = {
            "author": {"id": "user123", "bot": False},
            "channel_id": "chan456",
            "content": "",
            "attachments": [{
                "id": "att1",
                "url": "https://cdn.discord.com/voice.ogg",
                "filename": "voice.ogg",
                "size": 1000,
            }],
        }
        await ch._handle_message_create(payload)

    assert "[attachment:" in captured["content"]
    assert "[transcription:" not in captured["content"]


# ---------------------------------------------------------------------------
# Voice-out: _send_voice_message sends IS_VOICE_MESSAGE flag
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_voice_message_sets_flag_8192(tmp_path):
    """_send_voice_message posts with flags=8192 and waveform metadata."""
    ch = _make_channel()

    ogg = tmp_path / "tts_test.ogg"
    ogg.write_bytes(b"\x00" * 1600)  # 1600 bytes → ~0.1s estimate

    captured_data: dict[str, Any] = {}

    async def fake_post(url, headers, files, data):
        captured_data["payload_json"] = json.loads(data["payload_json"])
        captured_data["files"] = files
        resp = MagicMock()
        resp.status_code = 200
        return resp

    fake_http = MagicMock()
    fake_http.post = fake_post
    ch._http = fake_http

    with patch("nanobot.channels.discord.subprocess.run", side_effect=FileNotFoundError):
        success = await ch._send_voice_message(
            "https://discord.com/api/v10/channels/123/messages",
            {"Authorization": "Bot test"},
            ogg,
        )

    assert success is True
    pj = captured_data["payload_json"]
    assert pj["flags"] == 8192
    assert len(pj["attachments"]) == 1
    att = pj["attachments"][0]
    assert att["filename"] == "tts_test.ogg"
    assert "duration_secs" in att
    assert "waveform" in att
    # waveform must be valid base64
    base64.b64decode(att["waveform"])


@pytest.mark.asyncio
async def test_send_voice_message_falls_back_on_failure(tmp_path):
    """If Discord returns non-200, _send_voice_message returns False."""
    ch = _make_channel()

    ogg = tmp_path / "tts_test.ogg"
    ogg.write_bytes(b"\x00" * 100)

    async def fake_post(url, headers, files, data):
        resp = MagicMock()
        resp.status_code = 400
        resp.text = "Bad Request"
        return resp

    fake_http = MagicMock()
    fake_http.post = fake_post
    ch._http = fake_http

    with patch("nanobot.channels.discord.subprocess.run", side_effect=FileNotFoundError):
        success = await ch._send_voice_message(
            "https://discord.com/api/v10/channels/123/messages",
            {"Authorization": "Bot test"},
            ogg,
        )

    assert success is False


# ---------------------------------------------------------------------------
# send() routing: OGG → voice message, others → file attachment
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_routes_ogg_to_voice_message(tmp_path):
    """OutboundMessage with .ogg media → _send_voice_message called, not _send_with_files."""
    ch = _make_channel()

    ogg = tmp_path / "tts_123.ogg"
    ogg.write_bytes(b"\x00" * 1600)

    voice_calls: list[Path] = []
    file_calls: list[list[str]] = []

    async def fake_voice(url, headers, path):
        voice_calls.append(path)
        return True

    async def fake_files(url, headers, text, paths, reply_to=None):
        file_calls.append(paths)
        return True

    ch._send_voice_message = fake_voice
    ch._send_with_files = fake_files
    ch._stop_typing = AsyncMock()

    msg = OutboundMessage(
        channel="discord",
        chat_id="chan123",
        content="",
        media=[str(ogg)],
    )
    await ch.send(msg)

    assert len(voice_calls) == 1
    assert voice_calls[0] == ogg
    assert file_calls == []


@pytest.mark.asyncio
async def test_send_routes_non_ogg_to_file_attachment(tmp_path):
    """OutboundMessage with .png media → _send_with_files, not voice message."""
    ch = _make_channel()

    png = tmp_path / "image.png"
    png.write_bytes(b"\x89PNG")

    voice_calls: list[Path] = []
    file_calls: list[list[str]] = []

    async def fake_voice(url, headers, path):
        voice_calls.append(path)
        return True

    async def fake_files(url, headers, text, paths, reply_to=None):
        file_calls.append(paths)
        return True

    ch._send_voice_message = fake_voice
    ch._send_with_files = fake_files
    ch._stop_typing = AsyncMock()

    msg = OutboundMessage(
        channel="discord",
        chat_id="chan123",
        content="Here's an image",
        media=[str(png)],
    )
    await ch.send(msg)

    assert voice_calls == []
    assert len(file_calls) == 1
    assert str(png) in file_calls[0]


@pytest.mark.asyncio
async def test_send_ogg_falls_back_to_file_on_voice_failure(tmp_path):
    """If _send_voice_message fails twice, OGG is sent via _send_with_files as fallback."""
    ch = _make_channel()

    ogg = tmp_path / "tts_fail.ogg"
    ogg.write_bytes(b"\x00" * 100)

    file_calls: list[list[str]] = []

    async def fake_voice(url, headers, path):
        return False  # always fails

    async def fake_files(url, headers, text, paths, reply_to=None):
        file_calls.append(paths)
        return True

    async def fake_resolve(chat_id):
        return chat_id  # no DM resolution needed

    ch._send_voice_message = fake_voice
    ch._send_with_files = fake_files
    ch._resolve_channel_id = fake_resolve
    ch._stop_typing = AsyncMock()

    msg = OutboundMessage(
        channel="discord",
        chat_id="chan123",
        content="",
        media=[str(ogg)],
    )
    await ch.send(msg)

    # Should fall back to file upload
    assert any(str(ogg) in (p if isinstance(p, str) else "") for paths in file_calls for p in paths)


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------

def test_constructor_stores_groq_api_key():
    ch = DiscordChannel(_make_config(), MessageBus(), groq_api_key="secret-key")
    assert ch.groq_api_key == "secret-key"


def test_constructor_defaults_groq_api_key_to_empty():
    ch = DiscordChannel(_make_config(), MessageBus())
    assert ch.groq_api_key == ""
