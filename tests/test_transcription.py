from pathlib import Path

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.providers.transcription import CustomTranscriptionProvider


class _DummyChannel(BaseChannel):
    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send(self, msg: OutboundMessage) -> None:
        return None


@pytest.mark.asyncio
async def test_transcribe_audio_uses_selected_openai_provider(monkeypatch, tmp_path) -> None:
    channel = _DummyChannel(config={}, bus=MessageBus())
    channel.transcription_provider = "openai"
    channel.transcription_model = "whisper-1"
    channel.transcription_provider_configs = {
        "openai": {"api_key": "openai-key", "api_base": "https://api.openai.com/v1"},
    }

    seen: list[tuple[str, str, str]] = []

    async def fake_transcribe(self, file_path: str | Path) -> str:
        seen.append((self.provider_name, self.api_url, self.model))
        return "hello from openai"

    monkeypatch.setattr("nanobot.providers.transcription.OpenAITranscriptionProvider.transcribe", fake_transcribe)

    text = await channel.transcribe_audio(tmp_path / "audio.wav")

    assert text == "hello from openai"
    assert seen == [("openai", "https://api.openai.com/v1/audio/transcriptions", "whisper-1")]


@pytest.mark.asyncio
async def test_transcribe_audio_falls_back_to_openai_when_groq_missing(monkeypatch, tmp_path) -> None:
    channel = _DummyChannel(config={}, bus=MessageBus())
    channel.transcription_provider = "groq"
    channel.transcription_provider_configs = {
        "groq": {"api_key": "", "api_base": "https://api.groq.com/openai/v1"},
        "openai": {"api_key": "openai-key", "api_base": "https://api.openai.com/v1"},
    }

    async def fake_transcribe(self, file_path: str | Path) -> str:
        return f"used:{self.provider_name}"

    monkeypatch.setattr("nanobot.providers.transcription.OpenAITranscriptionProvider.transcribe", fake_transcribe)

    text = await channel.transcribe_audio(tmp_path / "audio.wav")

    assert text == "used:openai"


def test_custom_transcription_provider_normalizes_audio_url() -> None:
    provider = CustomTranscriptionProvider(api_base="https://example.com/v1", extra_headers={"X-Test": "1"})
    assert provider.api_url == "https://example.com/v1/audio/transcriptions"
    assert provider.is_configured() is True
