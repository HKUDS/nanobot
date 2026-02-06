"""Tests for TTSProvider text-to-speech functionality."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx

from nanobot.providers.tts import TTSProvider


class TestTTSProvider:
    """Test TTSProvider initialization and configuration."""

    def test_initialization_with_defaults(self):
        """Test provider with default settings."""
        provider = TTSProvider()

        assert provider.provider == "openai"
        assert provider.voice == "alloy"
        assert provider.model == "tts-1"
        assert provider.max_text_length == 4000
        assert provider.timeout == 60.0

    def test_initialization_with_custom_values(self):
        """Test provider with custom settings."""
        provider = TTSProvider(
            provider="openai",
            api_key="test-key",
            voice="nova",
            model="tts-1-hd",
            max_text_length=2000,
            timeout=30.0,
        )

        assert provider.api_key == "test-key"
        assert provider.voice == "nova"
        assert provider.model == "tts-1-hd"
        assert provider.max_text_length == 2000
        assert provider.timeout == 30.0

    def test_is_enabled_returns_true_with_api_key(self):
        """Test that is_enabled returns True when API key is set."""
        provider = TTSProvider(api_key="test-key")
        assert provider.is_enabled() is True

    def test_is_enabled_returns_false_without_api_key(self):
        """Test that is_enabled returns False when no API key."""
        # Set environment variable to None for test
        with patch.dict("os.environ", {}, clear=True):
            provider = TTSProvider(api_key=None)
            assert provider.is_enabled() is False

    def test_get_available_voices_for_openai(self):
        """Test getting available voices for OpenAI."""
        provider = TTSProvider(provider="openai")
        voices = provider.get_available_voices()

        assert "alloy" in voices
        assert "nova" in voices
        assert "shimmer" in voices
        assert len(voices) == 6

    def test_get_available_models_for_openai(self):
        """Test getting available models for OpenAI."""
        provider = TTSProvider(provider="openai")
        models = provider.get_available_models()

        assert "tts-1" in models
        assert "tts-1-hd" in models

    def test_unknown_provider_defaults_to_alloy(self):
        """Test that unknown provider uses default voice."""
        provider = TTSProvider(provider="unknown")
        assert provider.voice == "alloy"


class TestTTSSynthesis:
    """Test TTS synthesis functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.provider = TTSProvider(api_key="test-key")
        self.temp_dir = Path(tempfile.mkdtemp())

    def teardown_method(self):
        """Clean up test fixtures."""
        if self.temp_dir.exists():
            import shutil
            shutil.rmtree(self.temp_dir)

    @pytest.mark.asyncio
    async def test_synthesize_returns_success_on_valid_response(self):
        """Test successful synthesis returns (True, None)."""
        # Mock the HTTP response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"fake audio data"

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            output_path = self.temp_dir / "output.mp3"
            success, warning = await self.provider.synthesize("Hello world", output_path)

        assert success is True
        assert warning is None
        assert output_path.exists()
        assert output_path.read_bytes() == b"fake audio data"

    @pytest.mark.asyncio
    async def test_synthesize_truncates_long_text(self):
        """Test that long text is truncated and warning is returned."""
        # Create text longer than max_text_length
        long_text = "a" * 5000

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"audio"

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            output_path = self.temp_dir / "output.mp3"
            success, warning = await self.provider.synthesize(long_text, output_path)

        assert success is True
        assert warning is not None
        assert "truncated" in warning.lower()
        assert "4000" in warning

        # Verify the API call was made with truncated text
        call_args = mock_client.post.call_args
        assert len(call_args[1]["json"]["input"]) == 4000

    @pytest.mark.asyncio
    async def test_synthesize_creates_parent_directory(self):
        """Test that synthesis creates parent directories if needed."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"audio data"

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            output_path = self.temp_dir / "subdir" / "output.mp3"
            success, warning = await self.provider.synthesize("test", output_path)

        assert success is True
        assert output_path.exists()
        assert output_path.parent.is_dir()

    @pytest.mark.asyncio
    async def test_synthesize_without_api_key_returns_false(self):
        """Test that synthesis fails gracefully without API key."""
        provider = TTSProvider(api_key=None)
        with patch.dict("os.environ", {}, clear=True):
            output_path = self.temp_dir / "output.mp3"
            success, warning = await provider.synthesize("test", output_path)

        assert success is False
        assert warning is None
        assert not output_path.exists()

    @pytest.mark.asyncio
    async def test_synthesize_handles_http_errors(self):
        """Test that HTTP errors are handled gracefully."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Unauthorized", request=MagicMock(), response=mock_response
        )

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            output_path = self.temp_dir / "output.mp3"
            success, warning = await self.provider.synthesize("test", output_path)

        assert success is False
        assert warning is None
        assert not output_path.exists()

    @pytest.mark.asyncio
    async def test_synthesize_handles_timeout(self):
        """Test that timeouts are handled gracefully."""
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post = AsyncMock(
            side_effect=httpx.TimeoutException("Request timeout")
        )

        with patch("httpx.AsyncClient", return_value=mock_client):
            output_path = self.temp_dir / "output.mp3"
            success, warning = await self.provider.synthesize("test", output_path)

        assert success is False
        assert warning is None
        assert not output_path.exists()

    @pytest.mark.asyncio
    async def test_synthesize_uses_correct_api_endpoint(self):
        """Test that synthesis calls the correct OpenAI endpoint."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"audio"

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            output_path = self.temp_dir / "output.mp3"
            await self.provider.synthesize("test", output_path)

        # Verify the API call
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "https://api.openai.com/v1/audio/speech"
        assert call_args[1]["headers"]["Authorization"] == "Bearer test-key"

    @pytest.mark.asyncio
    async def test_synthesize_includes_correct_parameters(self):
        """Test that synthesis includes all required parameters."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"audio"

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            output_path = self.temp_dir / "output.mp3"
            await self.provider.synthesize("Hello world", output_path)

        call_args = mock_client.post.call_args
        json_data = call_args[1]["json"]
        assert json_data["model"] == "tts-1"
        assert json_data["voice"] == "alloy"
        assert json_data["input"] == "Hello world"

    @pytest.mark.asyncio
    async def test_synthesize_respects_timeout_setting(self):
        """Test that the configured timeout is used."""
        provider = TTSProvider(api_key="test-key", timeout=123.0)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"audio"

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client) as mock_client_class:
            output_path = self.temp_dir / "output.mp3"
            await provider.synthesize("test", output_path)

        # Verify timeout was passed to AsyncClient constructor
        call_args = mock_client_class.call_args
        assert call_args[1]["timeout"] == 123.0


class TestTTSProviderErrors:
    """Test TTSProvider error handling."""

    def setup_method(self):
        """Set up test fixtures."""
        self.provider = TTSProvider(api_key="test-key")
        self.temp_dir = Path(tempfile.mkdtemp())

    def teardown_method(self):
        """Clean up test fixtures."""
        if self.temp_dir.exists():
            import shutil
            shutil.rmtree(self.temp_dir)

    @pytest.mark.asyncio
    async def test_synthesize_unknown_provider_returns_false(self):
        """Test that unknown provider returns error."""
        provider = TTSProvider(provider="unknown", api_key="test-key")

        output_path = self.temp_dir / "output.mp3"
        success, warning = await provider.synthesize("test", output_path)

        assert success is False
        assert warning is None

    @pytest.mark.asyncio
    async def test_synthesize_handles_generic_exceptions(self):
        """Test that unexpected exceptions are handled."""
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post = AsyncMock(side_effect=Exception("Unexpected error"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            output_path = self.temp_dir / "output.mp3"
            success, warning = await self.provider.synthesize("test", output_path)

        assert success is False
        assert warning is None
        assert not output_path.exists()
