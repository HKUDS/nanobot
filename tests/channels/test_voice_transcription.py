"""Tests for voice transcription flow in channels."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.channels.base import BaseChannel
from nanobot.config.schema import TranscriptionConfig

# ---------------------------------------------------------------------------
# Concrete test channel
# ---------------------------------------------------------------------------


class _TestChannel(BaseChannel):
    name = "test"
    display_name = "Test"

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send(self, msg: Any) -> None:
        pass


def _make_channel(
    *,
    transcription_config: TranscriptionConfig | None = None,
    provider: str = "groq",
    api_key: str = "",
    api_base: str = "",
    language: str | None = None,
) -> _TestChannel:
    bus = MagicMock()
    ch = _TestChannel({"enabled": True, "allowFrom": ["*"]}, bus)
    if transcription_config is not None:
        ch._transcription_config = transcription_config
    else:
        ch.transcription_provider = provider
        ch.transcription_api_key = api_key
        ch.transcription_api_base = api_base
        ch.transcription_language = language
    return ch


# ---------------------------------------------------------------------------
# transcription_available property
# ---------------------------------------------------------------------------


class TestTranscriptionAvailable:
    def test_available_with_config_and_key(self):
        ch = _make_channel(
            transcription_config=TranscriptionConfig(
                provider="groq", api_key="k"
            )
        )
        assert ch.transcription_available is True

    def test_unavailable_when_disabled(self):
        ch = _make_channel(
            transcription_config=TranscriptionConfig(
                enabled=False, provider="groq", api_key="k"
            )
        )
        assert ch.transcription_available is False

    def test_unavailable_without_key(self):
        ch = _make_channel(
            transcription_config=TranscriptionConfig(provider="groq")
        )
        assert ch.transcription_available is False

    def test_local_available_with_base(self):
        ch = _make_channel(
            transcription_config=TranscriptionConfig(
                provider="local",
                api_base="http://localhost:8080/v1/audio/transcriptions",
            )
        )
        assert ch.transcription_available is True

    def test_local_unavailable_without_base(self):
        ch = _make_channel(
            transcription_config=TranscriptionConfig(provider="local")
        )
        assert ch.transcription_available is False

    def test_legacy_flat_available(self):
        ch = _make_channel(provider="groq", api_key="k")
        assert ch.transcription_available is True

    def test_legacy_flat_unavailable(self):
        ch = _make_channel(provider="groq", api_key="")
        assert ch.transcription_available is False


# ---------------------------------------------------------------------------
# transcribe_audio method
# ---------------------------------------------------------------------------


class TestTranscribeAudio:
    @pytest.mark.asyncio
    async def test_transcribe_with_config(self, tmp_path: Path):
        ch = _make_channel(
            transcription_config=TranscriptionConfig(
                provider="groq", api_key="k"
            )
        )
        audio = tmp_path / "voice.ogg"
        audio.write_bytes(b"\x00" * 100)

        with patch(
            "nanobot.providers.transcription.WhisperTranscriptionProvider.transcribe",
            new_callable=AsyncMock,
            return_value="hello",
        ):
            result = await ch.transcribe_audio(audio)

        assert result == "hello"

    @pytest.mark.asyncio
    async def test_transcribe_disabled_returns_empty(self, tmp_path: Path):
        ch = _make_channel(
            transcription_config=TranscriptionConfig(
                enabled=False, provider="groq", api_key="k"
            )
        )
        audio = tmp_path / "voice.ogg"
        audio.write_bytes(b"\x00" * 100)
        result = await ch.transcribe_audio(audio)
        assert result == ""

    @pytest.mark.asyncio
    async def test_transcribe_unavailable_returns_empty(self, tmp_path: Path):
        ch = _make_channel(
            transcription_config=TranscriptionConfig(provider="groq")
        )
        audio = tmp_path / "voice.ogg"
        audio.write_bytes(b"\x00" * 100)
        result = await ch.transcribe_audio(audio)
        assert result == ""

    @pytest.mark.asyncio
    async def test_graceful_failure_message(self, tmp_path: Path):
        """When transcription fails, the channel should return empty string (not crash)."""
        ch = _make_channel(
            transcription_config=TranscriptionConfig(
                provider="groq", api_key="k"
            )
        )
        audio = tmp_path / "voice.ogg"
        audio.write_bytes(b"\x00" * 100)

        with patch(
            "nanobot.providers.transcription.WhisperTranscriptionProvider.transcribe",
            new_callable=AsyncMock,
            side_effect=Exception("network error"),
        ):
            result = await ch.transcribe_audio(audio)

        assert result == ""


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


class TestTranscriptionConfig:
    def test_valid_language(self):
        cfg = TranscriptionConfig(language="en")
        assert cfg.language == "en"

    def test_valid_three_letter_language(self):
        cfg = TranscriptionConfig(language="ara")
        assert cfg.language == "ara"

    def test_invalid_language_rejected(self):
        with pytest.raises(Exception):
            TranscriptionConfig(language="english")

    def test_max_duration_minimum(self):
        with pytest.raises(Exception):
            TranscriptionConfig(max_duration_seconds=5)

    def test_defaults(self):
        cfg = TranscriptionConfig()
        assert cfg.enabled is True
        assert cfg.provider == "groq"
        assert cfg.model is None
        assert cfg.api_key is None
        assert cfg.max_duration_seconds == 300
