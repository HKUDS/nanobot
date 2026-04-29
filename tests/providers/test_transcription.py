"""Tests for the unified WhisperTranscriptionProvider."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from nanobot.providers.transcription import (
    GroqTranscriptionProvider,
    OpenAITranscriptionProvider,
    WhisperTranscriptionProvider,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(text: str = "hello world", status: int = 200) -> httpx.Response:
    """Build a fake httpx.Response with a JSON body."""
    return httpx.Response(
        status_code=status,
        json={"text": text},
        request=httpx.Request("POST", "https://fake"),
    )


def _audio_file(tmp_path: Path, size: int = 1024) -> Path:
    """Create a small dummy audio file."""
    p = tmp_path / "voice.ogg"
    p.write_bytes(b"\x00" * size)
    return p


# ---------------------------------------------------------------------------
# Provider defaults
# ---------------------------------------------------------------------------


class TestProviderDefaults:
    def test_groq_defaults(self):
        p = WhisperTranscriptionProvider("groq", api_key="k")
        assert "groq.com" in p.api_url
        assert p.model == "whisper-large-v3"

    def test_openai_defaults(self):
        p = WhisperTranscriptionProvider("openai", api_key="k")
        assert "openai.com" in p.api_url
        assert p.model == "whisper-1"

    def test_local_defaults(self):
        p = WhisperTranscriptionProvider("local", api_base="http://localhost:8080/v1/audio/transcriptions")
        assert p.api_url == "http://localhost:8080/v1/audio/transcriptions"
        assert p.model == "whisper-large-v3"
        assert p.api_key is None

    def test_custom_model(self):
        p = WhisperTranscriptionProvider("local", api_base="http://x", model="base.en")
        assert p.model == "base.en"

    def test_unknown_provider_falls_back_to_groq_defaults(self):
        p = WhisperTranscriptionProvider("unknown", api_key="k")
        assert "groq.com" in p.api_url


# ---------------------------------------------------------------------------
# Availability checks
# ---------------------------------------------------------------------------


class TestAvailability:
    def test_groq_available_with_key(self):
        p = WhisperTranscriptionProvider("groq", api_key="k")
        assert p.is_available is True
        assert p.unavailable_reason == ""

    def test_groq_unavailable_without_key(self):
        p = WhisperTranscriptionProvider("groq")
        assert p.is_available is False
        assert "API key" in p.unavailable_reason

    def test_local_available_with_base(self):
        p = WhisperTranscriptionProvider("local", api_base="http://localhost:8080/v1/audio/transcriptions")
        assert p.is_available is True

    def test_local_unavailable_without_base(self):
        p = WhisperTranscriptionProvider("local")
        assert p.is_available is False
        assert "api_base" in p.unavailable_reason


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------


class TestTranscribe:
    @pytest.mark.asyncio
    async def test_successful_transcription(self, tmp_path: Path):
        p = WhisperTranscriptionProvider("groq", api_key="test-key")
        audio = _audio_file(tmp_path)

        mock_resp = _mock_response("transcribed text")
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("nanobot.providers.transcription.httpx.AsyncClient", return_value=mock_client):
            result = await p.transcribe(audio)

        assert result == "transcribed text"
        call_kwargs = mock_client.post.call_args
        assert "groq.com" in call_kwargs.args[0]
        assert "Bearer test-key" in call_kwargs.kwargs["headers"]["Authorization"]

    @pytest.mark.asyncio
    async def test_missing_api_key_returns_empty(self, tmp_path: Path):
        p = WhisperTranscriptionProvider("groq")
        audio = _audio_file(tmp_path)
        result = await p.transcribe(audio)
        assert result == ""

    @pytest.mark.asyncio
    async def test_missing_file_returns_empty(self):
        p = WhisperTranscriptionProvider("groq", api_key="k")
        result = await p.transcribe("/nonexistent/file.ogg")
        assert result == ""

    @pytest.mark.asyncio
    async def test_language_hint_passed(self, tmp_path: Path):
        p = WhisperTranscriptionProvider("groq", api_key="k", language="ar")
        audio = _audio_file(tmp_path)

        mock_resp = _mock_response("مرحبا")
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("nanobot.providers.transcription.httpx.AsyncClient", return_value=mock_client):
            result = await p.transcribe(audio)

        assert result == "مرحبا"
        call_kwargs = mock_client.post.call_args
        files = call_kwargs.kwargs["files"]
        assert "language" in files

    @pytest.mark.asyncio
    async def test_local_provider_no_auth_header(self, tmp_path: Path):
        p = WhisperTranscriptionProvider("local", api_base="http://localhost:8080/v1/audio/transcriptions")
        audio = _audio_file(tmp_path)

        mock_resp = _mock_response("local result")
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("nanobot.providers.transcription.httpx.AsyncClient", return_value=mock_client):
            result = await p.transcribe(audio)

        assert result == "local result"
        call_kwargs = mock_client.post.call_args
        headers = call_kwargs.kwargs["headers"]
        assert "Authorization" not in headers

    @pytest.mark.asyncio
    async def test_http_error_returns_empty(self, tmp_path: Path):
        p = WhisperTranscriptionProvider("groq", api_key="k")
        audio = _audio_file(tmp_path)

        mock_resp = httpx.Response(
            status_code=500,
            request=httpx.Request("POST", "https://fake"),
        )
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("nanobot.providers.transcription.httpx.AsyncClient", return_value=mock_client):
            result = await p.transcribe(audio)

        assert result == ""

    @pytest.mark.asyncio
    async def test_max_duration_rejects_large_file(self, tmp_path: Path):
        p = WhisperTranscriptionProvider("groq", api_key="k", max_duration_seconds=10)
        # 16_000 bytes/s * 10s = 160KB threshold; create 500KB file
        audio = _audio_file(tmp_path, size=500_000)
        result = await p.transcribe(audio)
        assert result == ""


# ---------------------------------------------------------------------------
# Backward-compat aliases
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    def test_groq_alias_is_whisper_provider(self):
        p = GroqTranscriptionProvider(api_key="k")
        assert isinstance(p, WhisperTranscriptionProvider)
        assert p.provider == "groq"

    def test_openai_alias_is_whisper_provider(self):
        p = OpenAITranscriptionProvider(api_key="k")
        assert isinstance(p, WhisperTranscriptionProvider)
        assert p.provider == "openai"

    @pytest.mark.asyncio
    async def test_groq_alias_transcribes(self, tmp_path: Path):
        p = GroqTranscriptionProvider(api_key="k")
        audio = _audio_file(tmp_path)

        mock_resp = _mock_response("alias works")
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("nanobot.providers.transcription.httpx.AsyncClient", return_value=mock_client):
            result = await p.transcribe(audio)

        assert result == "alias works"
