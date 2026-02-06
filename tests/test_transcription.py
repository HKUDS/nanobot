"""Tests for the multi-provider transcription system."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from nanobot.config.schema import TranscriptionConfig
from nanobot.providers.transcription import (
    BaseTranscriptionProvider,
    GroqTranscriptionProvider,
    GeminiTranscriptionProvider,
    FallbackTranscriptionProvider,
    get_transcription_provider,
    _create_provider,
)


# =============================================================================
# TranscriptionConfig Tests
# =============================================================================

class TestTranscriptionConfig:
    """Tests for TranscriptionConfig schema."""
    
    def test_default_provider_is_groq(self):
        """Default transcription provider should be groq for backward compatibility."""
        config = TranscriptionConfig()
        assert config.provider == "groq"
        assert config.fallback is None
    
    def test_can_set_gemini_as_provider(self):
        """Should be able to set gemini as the provider."""
        config = TranscriptionConfig(provider="gemini")
        assert config.provider == "gemini"
    
    def test_can_set_fallback_provider(self):
        """Should be able to set a fallback provider."""
        config = TranscriptionConfig(provider="gemini", fallback="groq")
        assert config.provider == "gemini"
        assert config.fallback == "groq"
    
    def test_fallback_can_be_none(self):
        """Fallback should be optional."""
        config = TranscriptionConfig(provider="groq", fallback=None)
        assert config.fallback is None


# =============================================================================
# Provider Creation Tests
# =============================================================================

class TestCreateProvider:
    """Tests for _create_provider factory function."""
    
    def test_create_groq_provider_with_key(self):
        """Should create GroqTranscriptionProvider when groq_api_key is provided."""
        provider = _create_provider("groq", groq_api_key="test-key")
        assert isinstance(provider, GroqTranscriptionProvider)
        assert provider.api_key == "test-key"
    
    def test_create_groq_provider_without_key_returns_none(self):
        """Should return None when groq is requested but no API key provided."""
        provider = _create_provider("groq", groq_api_key=None)
        assert provider is None
    
    def test_create_gemini_provider_with_key(self):
        """Should create GeminiTranscriptionProvider when gemini_api_key is provided."""
        provider = _create_provider("gemini", gemini_api_key="test-key")
        assert isinstance(provider, GeminiTranscriptionProvider)
        assert provider.api_key == "test-key"
    
    def test_create_gemini_provider_without_key_returns_none(self):
        """Should return None when gemini is requested but no API key provided."""
        provider = _create_provider("gemini", gemini_api_key=None)
        assert provider is None
    
    def test_google_alias_creates_gemini(self):
        """'google' should be an alias for 'gemini'."""
        provider = _create_provider("google", gemini_api_key="test-key")
        assert isinstance(provider, GeminiTranscriptionProvider)
    
    def test_unknown_provider_returns_none(self):
        """Unknown provider names should return None."""
        provider = _create_provider("unknown", groq_api_key="key", gemini_api_key="key")
        assert provider is None
    
    def test_provider_name_is_case_insensitive(self):
        """Provider names should be case-insensitive."""
        provider = _create_provider("GROQ", groq_api_key="test-key")
        assert isinstance(provider, GroqTranscriptionProvider)
        
        provider = _create_provider("Gemini", gemini_api_key="test-key")
        assert isinstance(provider, GeminiTranscriptionProvider)


# =============================================================================
# get_transcription_provider Factory Tests
# =============================================================================

class TestGetTranscriptionProvider:
    """Tests for get_transcription_provider factory function."""
    
    def test_creates_provider_with_fallback(self):
        """Should create a FallbackTranscriptionProvider with both primary and fallback."""
        provider = get_transcription_provider(
            provider="gemini",
            fallback="groq",
            gemini_api_key="gemini-key",
            groq_api_key="groq-key",
        )
        assert isinstance(provider, FallbackTranscriptionProvider)
        assert isinstance(provider.primary, GeminiTranscriptionProvider)
        assert isinstance(provider.fallback, GroqTranscriptionProvider)
    
    def test_creates_provider_without_fallback(self):
        """Should create provider without fallback when not specified."""
        provider = get_transcription_provider(
            provider="groq",
            fallback=None,
            groq_api_key="groq-key",
        )
        assert isinstance(provider, FallbackTranscriptionProvider)
        assert isinstance(provider.primary, GroqTranscriptionProvider)
        assert provider.fallback is None
    
    def test_uses_fallback_as_primary_when_primary_key_missing(self):
        """When primary provider key is missing, should use fallback as primary."""
        provider = get_transcription_provider(
            provider="gemini",
            fallback="groq",
            gemini_api_key=None,  # No gemini key
            groq_api_key="groq-key",
        )
        assert isinstance(provider, FallbackTranscriptionProvider)
        assert isinstance(provider.primary, GroqTranscriptionProvider)
    
    def test_same_provider_and_fallback_no_duplicate(self):
        """When provider == fallback, should not create duplicate fallback."""
        provider = get_transcription_provider(
            provider="groq",
            fallback="groq",
            groq_api_key="groq-key",
        )
        assert isinstance(provider, FallbackTranscriptionProvider)
        assert provider.fallback is None  # No duplicate


# =============================================================================
# FallbackTranscriptionProvider Tests
# =============================================================================

class TestFallbackTranscriptionProvider:
    """Tests for FallbackTranscriptionProvider fallback logic."""
    
    @pytest.mark.asyncio
    async def test_returns_primary_result_on_success(self):
        """Should return primary provider result when successful."""
        primary = AsyncMock(spec=BaseTranscriptionProvider)
        primary.transcribe = AsyncMock(return_value="Primary transcription")
        fallback = AsyncMock(spec=BaseTranscriptionProvider)
        
        provider = FallbackTranscriptionProvider(primary=primary, fallback=fallback)
        result = await provider.transcribe("/path/to/audio.ogg")
        
        assert result == "Primary transcription"
        primary.transcribe.assert_called_once_with("/path/to/audio.ogg")
        fallback.transcribe.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_uses_fallback_when_primary_returns_empty(self):
        """Should use fallback when primary returns empty string."""
        primary = AsyncMock(spec=BaseTranscriptionProvider)
        primary.transcribe = AsyncMock(return_value="")
        fallback = AsyncMock(spec=BaseTranscriptionProvider)
        fallback.transcribe = AsyncMock(return_value="Fallback transcription")
        
        provider = FallbackTranscriptionProvider(primary=primary, fallback=fallback)
        result = await provider.transcribe("/path/to/audio.ogg")
        
        assert result == "Fallback transcription"
        primary.transcribe.assert_called_once()
        fallback.transcribe.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_uses_fallback_when_primary_raises_exception(self):
        """Should use fallback when primary raises an exception."""
        primary = AsyncMock(spec=BaseTranscriptionProvider)
        primary.transcribe = AsyncMock(side_effect=Exception("API Error"))
        fallback = AsyncMock(spec=BaseTranscriptionProvider)
        fallback.transcribe = AsyncMock(return_value="Fallback transcription")
        
        provider = FallbackTranscriptionProvider(primary=primary, fallback=fallback)
        result = await provider.transcribe("/path/to/audio.ogg")
        
        assert result == "Fallback transcription"
        fallback.transcribe.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_returns_empty_when_both_fail(self):
        """Should return empty string when both providers fail."""
        primary = AsyncMock(spec=BaseTranscriptionProvider)
        primary.transcribe = AsyncMock(side_effect=Exception("Primary Error"))
        fallback = AsyncMock(spec=BaseTranscriptionProvider)
        fallback.transcribe = AsyncMock(side_effect=Exception("Fallback Error"))
        
        provider = FallbackTranscriptionProvider(primary=primary, fallback=fallback)
        result = await provider.transcribe("/path/to/audio.ogg")
        
        assert result == ""
    
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_fallback_and_primary_fails(self):
        """Should return empty when primary fails and no fallback configured."""
        primary = AsyncMock(spec=BaseTranscriptionProvider)
        primary.transcribe = AsyncMock(return_value="")
        
        provider = FallbackTranscriptionProvider(primary=primary, fallback=None)
        result = await provider.transcribe("/path/to/audio.ogg")
        
        assert result == ""


# =============================================================================
# GroqTranscriptionProvider Tests
# =============================================================================

class TestGroqTranscriptionProvider:
    """Tests for GroqTranscriptionProvider."""
    
    def test_init_with_api_key(self):
        """Should initialize with provided API key."""
        provider = GroqTranscriptionProvider(api_key="test-key")
        assert provider.api_key == "test-key"
        assert provider.api_url == "https://api.groq.com/openai/v1/audio/transcriptions"
    
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_api_key(self):
        """Should return empty string when no API key configured."""
        provider = GroqTranscriptionProvider(api_key=None)
        result = await provider.transcribe("/path/to/audio.ogg")
        assert result == ""
    
    @pytest.mark.asyncio
    async def test_returns_empty_when_file_not_found(self):
        """Should return empty string when audio file doesn't exist."""
        provider = GroqTranscriptionProvider(api_key="test-key")
        result = await provider.transcribe("/nonexistent/path/audio.ogg")
        assert result == ""


# =============================================================================
# GeminiTranscriptionProvider Tests
# =============================================================================

class TestGeminiTranscriptionProvider:
    """Tests for GeminiTranscriptionProvider."""
    
    def test_init_with_api_key(self):
        """Should initialize with provided API key."""
        provider = GeminiTranscriptionProvider(api_key="test-key")
        assert provider.api_key == "test-key"
        assert "generativelanguage.googleapis.com" in provider.api_url
    
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_api_key(self):
        """Should return empty string when no API key configured."""
        provider = GeminiTranscriptionProvider(api_key=None)
        result = await provider.transcribe("/path/to/audio.ogg")
        assert result == ""
    
    @pytest.mark.asyncio
    async def test_returns_empty_when_file_not_found(self):
        """Should return empty string when audio file doesn't exist."""
        provider = GeminiTranscriptionProvider(api_key="test-key")
        result = await provider.transcribe("/nonexistent/path/audio.ogg")
        assert result == ""
    
    def test_get_mime_type_for_common_formats(self):
        """Should return correct MIME types for common audio formats."""
        provider = GeminiTranscriptionProvider(api_key="test-key")
        
        assert provider._get_mime_type(Path("audio.ogg")) == "audio/ogg"
        assert provider._get_mime_type(Path("audio.mp3")) == "audio/mpeg"
        assert provider._get_mime_type(Path("audio.m4a")) == "audio/mp4"
        assert provider._get_mime_type(Path("audio.wav")) == "audio/wav"
        assert provider._get_mime_type(Path("audio.webm")) == "audio/webm"
        assert provider._get_mime_type(Path("audio.flac")) == "audio/flac"
    
    def test_get_mime_type_defaults_to_ogg(self):
        """Should default to audio/ogg for unknown formats."""
        provider = GeminiTranscriptionProvider(api_key="test-key")
        assert provider._get_mime_type(Path("audio.xyz")) == "audio/ogg"
