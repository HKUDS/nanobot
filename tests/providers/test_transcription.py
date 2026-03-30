"""Tests for voice transcription providers."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.providers.transcription import Qwen3ASRTranscriptionProvider

# ---------------------------------------------------------------------------
# Qwen3ASRTranscriptionProvider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_qwen3_asr_no_api_key_returns_empty():
    provider = Qwen3ASRTranscriptionProvider(api_key=None)
    result = await provider.transcribe("/tmp/audio.mp3")
    assert result == ""


@pytest.mark.asyncio
async def test_qwen3_asr_file_not_found_returns_empty(tmp_path):
    provider = Qwen3ASRTranscriptionProvider(api_key="test-key")
    result = await provider.transcribe(tmp_path / "nonexistent.mp3")
    assert result == ""


@pytest.mark.asyncio
async def test_qwen3_asr_import_error_returns_empty(tmp_path):
    audio_file = tmp_path / "audio.mp3"
    audio_file.write_bytes(b"fake audio data")

    provider = Qwen3ASRTranscriptionProvider(api_key="test-key")

    with patch.dict("sys.modules", {"dashscope": None}):
        result = await provider.transcribe(audio_file)

    assert result == ""


@pytest.mark.asyncio
async def test_qwen3_asr_non_200_returns_empty(tmp_path):
    audio_file = tmp_path / "audio.wav"
    audio_file.write_bytes(b"fake wav data")

    provider = Qwen3ASRTranscriptionProvider(api_key="test-key")

    mock_response = SimpleNamespace(status_code=400, message="Bad Request")
    mock_dashscope = MagicMock()
    mock_dashscope.MultiModalConversation.call.return_value = mock_response

    with patch.dict("sys.modules", {"dashscope": mock_dashscope}):
        with patch("asyncio.to_thread", new=AsyncMock(return_value=mock_response)):
            result = await provider.transcribe(audio_file)

    assert result == ""


@pytest.mark.asyncio
async def test_qwen3_asr_empty_choices_returns_empty(tmp_path):
    audio_file = tmp_path / "audio.wav"
    audio_file.write_bytes(b"fake wav data")

    provider = Qwen3ASRTranscriptionProvider(api_key="test-key")

    mock_response = SimpleNamespace(
        status_code=200,
        output=SimpleNamespace(choices=[]),
    )

    mock_dashscope = MagicMock()
    with patch.dict("sys.modules", {"dashscope": mock_dashscope}):
        with patch("asyncio.to_thread", new=AsyncMock(return_value=mock_response)):
            result = await provider.transcribe(audio_file)

    assert result == ""


@pytest.mark.asyncio
async def test_qwen3_asr_happy_path(tmp_path):
    audio_file = tmp_path / "audio.ogg"
    audio_file.write_bytes(b"fake ogg data")

    provider = Qwen3ASRTranscriptionProvider(api_key="test-key")

    mock_response = SimpleNamespace(
        status_code=200,
        output=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=[{"text": "你好，世界"}])
                )
            ]
        ),
    )

    mock_dashscope = MagicMock()
    with patch.dict("sys.modules", {"dashscope": mock_dashscope}):
        with patch("asyncio.to_thread", new=AsyncMock(return_value=mock_response)):
            result = await provider.transcribe(audio_file)

    assert result == "你好，世界"


@pytest.mark.asyncio
async def test_qwen3_asr_passes_api_key_per_call(tmp_path):
    """Ensure api_key is passed as a per-call kwarg to MultiModalConversation.call."""
    audio_file = tmp_path / "audio.mp3"
    audio_file.write_bytes(b"data")

    provider = Qwen3ASRTranscriptionProvider(api_key="my-secret-key")

    mock_response = SimpleNamespace(
        status_code=200,
        output=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=[{"text": "hello"}]))]
        ),
    )

    captured: list[dict] = []

    async def fake_to_thread(fn, **kwargs):
        captured.append(kwargs)
        return mock_response

    mock_dashscope = MagicMock()
    with patch.dict("sys.modules", {"dashscope": mock_dashscope}):
        with patch("asyncio.to_thread", side_effect=fake_to_thread):
            result = await provider.transcribe(audio_file)

    assert result == "hello"
    # api_key must appear as a kwarg in the call, not set globally
    assert captured, "asyncio.to_thread was not called"
    assert captured[0].get("api_key") == "my-secret-key"


@pytest.mark.asyncio
async def test_qwen3_asr_missing_content_returns_empty(tmp_path):
    audio_file = tmp_path / "audio.wav"
    audio_file.write_bytes(b"data")

    provider = Qwen3ASRTranscriptionProvider(api_key="test-key")

    mock_response = SimpleNamespace(
        status_code=200,
        output=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=None))]
        ),
    )

    mock_dashscope = MagicMock()
    with patch.dict("sys.modules", {"dashscope": mock_dashscope}):
        with patch("asyncio.to_thread", new=AsyncMock(return_value=mock_response)):
            result = await provider.transcribe(audio_file)

    assert result == ""


# ---------------------------------------------------------------------------
# BaseChannel.transcribe_audio — provider dispatch
# ---------------------------------------------------------------------------


class _DummyChannel(BaseChannel):
    name = "dummy"

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send(self, msg: OutboundMessage) -> None:
        return None


@pytest.mark.asyncio
async def test_transcribe_audio_no_key_returns_empty(tmp_path):
    channel = _DummyChannel(SimpleNamespace(), MessageBus())
    channel.transcription_api_key = ""
    result = await channel.transcribe_audio(tmp_path / "audio.mp3")
    assert result == ""


@pytest.mark.asyncio
async def test_transcribe_audio_dispatches_groq(tmp_path):
    channel = _DummyChannel(SimpleNamespace(), MessageBus())
    channel.transcription_api_key = "groq-key"
    channel.transcription_provider = "groq"

    with patch(
        "nanobot.providers.transcription.GroqTranscriptionProvider.transcribe",
        new=AsyncMock(return_value="hello from groq"),
    ):
        result = await channel.transcribe_audio(tmp_path / "audio.mp3")

    assert result == "hello from groq"


@pytest.mark.asyncio
async def test_transcribe_audio_dispatches_qwen3_asr(tmp_path):
    channel = _DummyChannel(SimpleNamespace(), MessageBus())
    channel.transcription_api_key = "dashscope-key"
    channel.transcription_provider = "qwen3-asr"

    with patch(
        "nanobot.providers.transcription.Qwen3ASRTranscriptionProvider.transcribe",
        new=AsyncMock(return_value="你好"),
    ):
        result = await channel.transcribe_audio(tmp_path / "audio.ogg")

    assert result == "你好"
