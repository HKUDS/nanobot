"""Tests for voice transcription provider protocol and factory."""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.providers.transcription import (
    TranscriptionProvider,
    VoiceTranscriptionProvider,
    create_transcription_provider,
)


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
