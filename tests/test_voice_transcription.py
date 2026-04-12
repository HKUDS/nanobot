"""Tests for voice message transcription — WhatsApp and Telegram channels."""

from __future__ import annotations

import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.bus.queue import MessageBus
from nanobot.channels.whatsapp import WhatsAppChannel
from nanobot.channels.whatsapp import WhatsAppConfig
from nanobot.providers.transcription import (
    TranscriptionProvider,
    VoiceTranscriptionProvider,
    create_transcription_provider,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_whatsapp_channel(
    transcribe_return: str | None = None,
) -> tuple[WhatsAppChannel, list[dict]]:
    config = WhatsAppConfig(enabled=True, bridge_url="ws://localhost:3001", allow_from=["*"])
    channel = WhatsAppChannel(config, MessageBus())

    # Mock transcribe_audio on the channel instance
    if transcribe_return is not None:
        channel.transcribe_audio = AsyncMock(return_value=transcribe_return)  # type: ignore[method-assign]
    else:
        channel.transcribe_audio = AsyncMock(return_value="")  # type: ignore[method-assign]

    published: list[dict] = []

    async def _fake_publish(msg):
        published.append({"content": msg.content, "sender_id": msg.sender_id})

    channel.bus.publish_inbound = _fake_publish  # type: ignore[method-assign]

    class _FakeWS:
        async def send(self, data: str) -> None:
            pass

    channel._ws = _FakeWS()
    channel._connected = True
    return channel, published


def _voice_bridge_message(
    sender: str = "123456789@s.whatsapp.net",
    media_path: str = "/tmp/voice_001.ogg",
) -> str:
    """Build a bridge message representing a voice message in the new format.

    The bridge now sends content='[Voice Message]' and media=['/path/to/file'].
    """
    return json.dumps({
        "type": "message",
        "id": "msg-001",
        "sender": sender,
        "pn": "",
        "content": "[Voice Message]",
        "timestamp": 1700000000,
        "isGroup": False,
        "media": [media_path],
    })


# ── TranscriptionProvider protocol ────────────────────────────────────────────

class TestTranscriptionProviderProtocol:
    def test_voice_transcription_provider_satisfies_protocol(self) -> None:
        p = VoiceTranscriptionProvider(model="gemini/gemini-2.5-flash", api_key="key")
        assert isinstance(p, TranscriptionProvider)

    def test_custom_provider_satisfies_protocol(self) -> None:
        class MyProvider:
            async def transcribe(self, audio_bytes, mime_type="audio/ogg", duration_seconds=None):
                return "ok"

        assert isinstance(MyProvider(), TranscriptionProvider)


# ── create_transcription_provider factory ─────────────────────────────────────

class TestCreateTranscriptionProvider:
    def test_returns_none_when_no_model_configured(self) -> None:
        # Transcription is opt-in — no config means disabled
        with patch.dict("os.environ", {}, clear=True):
            p = create_transcription_provider()
        assert p is None

    def test_returns_provider_with_explicit_model(self) -> None:
        p = create_transcription_provider(model="openai/gpt-4o")
        assert isinstance(p, VoiceTranscriptionProvider)
        assert p.model == "openai/gpt-4o"

    def test_reads_model_from_env(self) -> None:
        with patch.dict("os.environ", {"VOICE_TRANSCRIPTION_MODEL": "openai/gpt-4o-mini"}):
            p = create_transcription_provider()
        assert isinstance(p, VoiceTranscriptionProvider)
        assert p.model == "openai/gpt-4o-mini"

    def test_explicit_model_overrides_env(self) -> None:
        with patch.dict("os.environ", {"VOICE_TRANSCRIPTION_MODEL": "openai/gpt-4o-mini"}):
            p = create_transcription_provider(model="gemini/gemini-2.5-flash")
        assert p.model == "gemini/gemini-2.5-flash"

    def test_returns_none_when_disabled(self) -> None:
        assert create_transcription_provider(model="disabled") is None

    def test_disabled_case_insensitive(self) -> None:
        assert create_transcription_provider(model="DISABLED") is None

    def test_api_key_passed_through(self) -> None:
        p = create_transcription_provider(model="gemini/gemini-2.5-flash", api_key="my-key")
        assert p.api_key == "my-key"

    def test_no_api_key_leaves_none(self) -> None:
        p = create_transcription_provider(model="gemini/gemini-2.5-flash")
        assert p.api_key is None


# ── VoiceTranscriptionProvider unit tests ─────────────────────────────────────

class TestVoiceTranscriptionProvider:
    @pytest.mark.asyncio
    async def test_returns_transcript_on_success(self) -> None:
        provider = VoiceTranscriptionProvider(model="gemini/gemini-2.5-flash", api_key="fake-key")

        fake_response = MagicMock()
        fake_response.choices[0].message.content = "  Hello world  "

        with patch("litellm.acompletion", new=AsyncMock(return_value=fake_response)):
            result = await provider.transcribe(b"\x00" * 50, mime_type="audio/ogg")

        assert result == "Hello world"

    @pytest.mark.asyncio
    async def test_passes_model_and_messages_to_litellm(self) -> None:
        provider = VoiceTranscriptionProvider(model="openai/gpt-4o", api_key="k")

        fake_response = MagicMock()
        fake_response.choices[0].message.content = "transcript"

        with patch("litellm.acompletion", new=AsyncMock(return_value=fake_response)) as mock_call:
            await provider.transcribe(b"\x00" * 10, mime_type="audio/mpeg")

        call_kwargs = mock_call.call_args.kwargs
        assert call_kwargs["model"] == "openai/gpt-4o"
        assert call_kwargs["api_key"] == "k"
        messages = call_kwargs["messages"]
        assert messages[0]["role"] == "user"
        content = messages[0]["content"]
        # First part is the text prompt, second is the audio data URI
        assert content[0]["type"] == "text"
        assert content[1]["type"] == "image_url"
        assert content[1]["image_url"]["url"].startswith("data:audio/mpeg;base64,")

    @pytest.mark.asyncio
    async def test_omits_api_key_kwarg_when_none(self) -> None:
        provider = VoiceTranscriptionProvider(model="gemini/gemini-2.5-flash", api_key=None)

        fake_response = MagicMock()
        fake_response.choices[0].message.content = "ok"

        with patch("litellm.acompletion", new=AsyncMock(return_value=fake_response)) as mock_call:
            await provider.transcribe(b"\x00" * 10)

        assert "api_key" not in mock_call.call_args.kwargs

    @pytest.mark.asyncio
    async def test_returns_too_long_sentinel(self) -> None:
        provider = VoiceTranscriptionProvider(model="gemini/gemini-2.5-flash", api_key="k")
        result = await provider.transcribe(b"\x00" * 50, duration_seconds=301.0)
        assert result == "[Voice message too long - please type it out]"

    @pytest.mark.asyncio
    async def test_accepts_exactly_5_minutes(self) -> None:
        provider = VoiceTranscriptionProvider(model="gemini/gemini-2.5-flash", api_key="k")
        fake_response = MagicMock()
        fake_response.choices[0].message.content = "Exactly five minutes"

        with patch("litellm.acompletion", new=AsyncMock(return_value=fake_response)):
            result = await provider.transcribe(b"\x00" * 50, duration_seconds=300.0)

        assert result == "Exactly five minutes"

    @pytest.mark.asyncio
    async def test_returns_failure_sentinel_on_error(self) -> None:
        provider = VoiceTranscriptionProvider(model="gemini/gemini-2.5-flash", api_key="k")

        with patch("litellm.acompletion", new=AsyncMock(side_effect=Exception("API down"))):
            result = await provider.transcribe(b"\x00" * 50)

        assert result == "[Voice message - transcription failed]"


# ── WhatsApp channel integration tests ────────────────────────────────────────

class TestWhatsAppVoiceTranscription:
    @pytest.mark.asyncio
    async def test_voice_message_replaced_with_transcript(self) -> None:
        channel, published = _make_whatsapp_channel(transcribe_return="Hi, this is a test.")

        await channel._handle_bridge_message(_voice_bridge_message())

        assert len(published) == 1
        # The transcribed content plus media tag
        assert "Hi, this is a test." in published[0]["content"]
        channel.transcribe_audio.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_transcription_returns_failure_placeholder(self) -> None:
        # When transcribe_audio returns empty string, content becomes failure sentinel
        channel, published = _make_whatsapp_channel(transcribe_return="")

        await channel._handle_bridge_message(_voice_bridge_message())

        assert len(published) == 1
        assert "[Voice Message: Transcription failed]" in published[0]["content"]

    @pytest.mark.asyncio
    async def test_normal_text_not_transcribed(self) -> None:
        channel, published = _make_whatsapp_channel(transcribe_return="should not appear")

        raw = json.dumps({
            "type": "message", "id": "msg-002", "sender": "123@s.whatsapp.net",
            "pn": "", "content": "Hello there", "timestamp": 1700000001, "isGroup": False,
        })

        await channel._handle_bridge_message(raw)

        assert published[0]["content"] == "Hello there"
        channel.transcribe_audio.assert_not_called()

    @pytest.mark.asyncio
    async def test_voice_no_media_returns_audio_not_available(self) -> None:
        channel, published = _make_whatsapp_channel(transcribe_return="ok")

        # Voice message with no media paths
        raw = json.dumps({
            "type": "message", "id": "msg-003", "sender": "123@s.whatsapp.net",
            "pn": "", "content": "[Voice Message]", "timestamp": 1700000002, "isGroup": False,
        })

        await channel._handle_bridge_message(raw)

        assert "[Voice Message: Audio not available]" in published[0]["content"]

    @pytest.mark.asyncio
    async def test_transcribe_audio_receives_file_path(self) -> None:
        channel, _ = _make_whatsapp_channel(transcribe_return="ok")

        await channel._handle_bridge_message(
            _voice_bridge_message(media_path="/tmp/test_audio.ogg")
        )

        channel.transcribe_audio.assert_called_once_with("/tmp/test_audio.ogg")
