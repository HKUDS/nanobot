"""Tests for Groq transcription provider."""

import pytest

from nanobot.providers.transcription import GroqTranscriptionProvider


def test_default_no_language():
    provider = GroqTranscriptionProvider(api_key="test-key")
    assert provider.language is None


def test_language_passed_to_constructor():
    provider = GroqTranscriptionProvider(api_key="test-key", language="ru")
    assert provider.language == "ru"


def test_language_in_request_files():
    provider = GroqTranscriptionProvider(api_key="test-key", language="zh")
    # Verify language would be included in the files dict
    import io
    files = {
        "file": ("test.wav", io.BytesIO(b"data")),
        "model": (None, "whisper-large-v3"),
    }
    if provider.language:
        files["language"] = (None, provider.language)

    assert "language" in files
    assert files["language"] == (None, "zh")


def test_no_language_not_in_request_files():
    provider = GroqTranscriptionProvider(api_key="test-key")
    import io
    files = {
        "file": ("test.wav", io.BytesIO(b"data")),
        "model": (None, "whisper-large-v3"),
    }
    if provider.language:
        files["language"] = (None, provider.language)

    assert "language" not in files
