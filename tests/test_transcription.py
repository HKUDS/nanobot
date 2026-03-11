"""Tests for transcription service."""

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.config.schema import Config, ProvidersConfig, TranscriptionConfig
from nanobot.providers.transcription import TranscriptionProvider, create_transcription_service


def test_create_transcription_service_no_config():
    """Test that service creation returns None when not configured."""
    config = Config(
        transcription=TranscriptionConfig(provider="", model=""), providers=ProvidersConfig()
    )
    service = create_transcription_service(config)
    assert service is None


def test_create_transcription_service_missing_provider():
    """Test that service creation fails when provider is missing."""
    config = Config(
        transcription=TranscriptionConfig(provider="", model="whisper-large-v3"),
        providers=ProvidersConfig(),
    )
    service = create_transcription_service(config)
    assert service is None


def test_create_transcription_service_missing_model():
    """Test that service creation fails when model is missing."""
    config = Config(
        transcription=TranscriptionConfig(provider="groq", model=""), providers=ProvidersConfig()
    )
    service = create_transcription_service(config)
    assert service is None


def test_create_transcription_service_unknown_provider():
    """Test that service creation fails for unknown provider."""
    config = Config(
        transcription=TranscriptionConfig(provider="unknown", model="model"),
        providers=ProvidersConfig(),
    )
    service = create_transcription_service(config)
    assert service is None


def test_create_transcription_service_missing_api_key():
    """Test that service creation fails when API key is missing."""
    config = Config(
        transcription=TranscriptionConfig(provider="groq", model="whisper-large-v3"),
        providers=ProvidersConfig(),
    )
    config.providers.groq = MagicMock()
    config.providers.groq.api_key = ""
    service = create_transcription_service(config)
    assert service is None


def test_create_transcription_service_success():
    """Test successful service creation."""
    config = Config(
        transcription=TranscriptionConfig(provider="groq", model="whisper-large-v3"),
        providers=ProvidersConfig(),
    )
    config.providers.groq = MagicMock()
    config.providers.groq.api_key = "test_key"
    config.providers.groq.api_base = ""
    service = create_transcription_service(config)
    assert service is not None
    assert service._use_litellm is True
    assert service._api_key == "test_key"
    assert service._model == "whisper-large-v3"


@pytest.mark.asyncio
async def test_transcribe_litellm_provider():
    """Test transcription via LiteLLM for supported providers."""
    provider = TranscriptionProvider(
        use_litellm=True, api_key="test_key", base_url=None, model="whisper-large-v3"
    )

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        tmp.write(b"fake audio data")
        tmp_path = tmp.name

    try:
        with patch(
            "nanobot.providers.transcription.litellm.atranscription", new_callable=AsyncMock
        ) as mock_litellm:
            mock_response = MagicMock()
            mock_response.text = "test transcription"
            mock_litellm.return_value = mock_response

            result = await provider.transcribe(tmp_path)
            assert result == "test transcription"

            mock_litellm.assert_called_once()
            call_args = mock_litellm.call_args
            assert call_args[1]["model"] == "whisper-large-v3"
            assert call_args[1]["api_key"] == "test_key"
    finally:
        os.unlink(tmp_path)


@pytest.mark.asyncio
async def test_transcribe_direct_client():
    """Test transcription via direct client for unsupported providers."""
    with patch("nanobot.providers.transcription.AsyncOpenAI") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client

        provider = TranscriptionProvider(
            use_litellm=False,
            api_key="test_key",
            base_url="https://api.mistral.ai/v1",
            model="mistral-large-latest",
        )

        mock_client_class.assert_called_once_with(
            api_key="test_key", base_url="https://api.mistral.ai/v1"
        )

        mock_response = MagicMock()
        mock_response.text = "test transcription"
        mock_client.audio.transcriptions.create.return_value = mock_response

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp.write(b"fake audio data")
            tmp_path = tmp.name

        try:
            result = await provider.transcribe(tmp_path)
            assert result == "test transcription"

            assert mock_client.audio.transcriptions.create.called
            call_args = mock_client.audio.transcriptions.create.call_args
            assert call_args[1]["model"] == "mistral-large-latest"
        finally:
            os.unlink(tmp_path)


@pytest.mark.asyncio
async def test_transcribe_file_not_found():
    """Test transcription with non-existent file."""
    provider = TranscriptionProvider(
        use_litellm=True, api_key="test_key", base_url=None, model="whisper-large-v3"
    )
    result = await provider.transcribe("/nonexistent/file.ogg")
    assert result == ""


@pytest.mark.asyncio
async def test_transcribe_error_handling():
    """Test transcription error handling."""
    provider = TranscriptionProvider(
        use_litellm=True, api_key="test_key", base_url=None, model="whisper-large-v3"
    )

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        tmp.write(b"fake audio data")
        tmp_path = tmp.name

    try:
        with patch(
            "nanobot.providers.transcription.litellm.atranscription", new_callable=AsyncMock
        ) as mock_litellm:
            mock_litellm.side_effect = Exception("Test error")

            result = await provider.transcribe(tmp_path)
            assert result == ""
    finally:
        os.unlink(tmp_path)


@pytest.mark.asyncio
async def test_channel_integration():
    """Test channel integration with transcription service."""
    from nanobot.bus.queue import MessageBus
    from nanobot.channels.base import BaseChannel

    provider = TranscriptionProvider(
        use_litellm=True, api_key="test_key", base_url=None, model="whisper-large-v3"
    )

    mock_channel_config = MagicMock()
    mock_channel_config.allow_from = ["*"]

    bus = MessageBus()

    class TestChannel(BaseChannel):
        def __init__(self, config, bus, transcription_service):
            super().__init__(config, bus, transcription_service)
            self.name = "test"
            self.display_name = "Test"

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def send(self, msg):
            pass

    channel = TestChannel(mock_channel_config, bus, provider)

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        tmp.write(b"fake audio data")
        tmp_path = tmp.name

    try:
        with patch(
            "nanobot.providers.transcription.litellm.atranscription", new_callable=AsyncMock
        ) as mock_litellm:
            mock_response = MagicMock()
            mock_response.text = "test transcription from channel"
            mock_litellm.return_value = mock_response

            result = await channel.transcribe_audio(tmp_path)
            assert result == "test transcription from channel"

            mock_litellm.assert_called_once()
    finally:
        os.unlink(tmp_path)
