"""Tests for nanobot.audio.tts_registry."""

import pytest

from nanobot.audio.tts_registry import (
    TTSProviderSpec,
    get_tts_provider,
    resolve_tts_provider,
    tts_provider_names,
)


class TestTTSProviderNames:
    def test_returns_tuple_of_names(self):
        names = tts_provider_names()
        assert isinstance(names, tuple)
        assert "openai" in names
        assert "groq" in names
        assert "elevenlabs" in names


class TestGetTTSProvider:
    def test_openai(self):
        spec = get_tts_provider("openai")
        assert spec is not None
        assert spec.name == "openai"
        assert spec.default_model == "tts-1"
        assert spec.default_voice == "alloy"

    def test_groq(self):
        spec = get_tts_provider("groq")
        assert spec is not None
        assert spec.name == "groq"
        assert spec.default_model == "canopylabs/orpheus-v1-english"
        assert spec.default_voice == "autumn"

    def test_elevenlabs(self):
        spec = get_tts_provider("elevenlabs")
        assert spec is not None
        assert spec.name == "elevenlabs"
        assert spec.default_model == "eleven_multilingual_v2"
        assert spec.default_voice == "Matilda"

    def test_unknown_returns_none(self):
        assert get_tts_provider("nonexistent") is None


class TestResolveTTSProvider:
    def test_exact_name(self):
        spec = resolve_tts_provider("groq")
        assert spec is not None
        assert spec.name == "groq"

    def test_case_insensitive(self):
        spec = resolve_tts_provider("OpenAI")
        assert spec is not None
        assert spec.name == "openai"

    def test_alias(self):
        spec = resolve_tts_provider("eleven")
        assert spec is not None
        assert spec.name == "elevenlabs"

    def test_unknown_returns_none(self):
        assert resolve_tts_provider("nonexistent") is None

    def test_non_string_returns_none(self):
        assert resolve_tts_provider(42) is None


class TestTTSProviderSpecLoadAdapter:
    def test_load_openai_adapter(self):
        spec = get_tts_provider("openai")
        adapter_cls = spec.load_adapter()
        from nanobot.providers.tts import OpenAITTSProvider

        assert adapter_cls is OpenAITTSProvider

    def test_load_groq_adapter(self):
        spec = get_tts_provider("groq")
        adapter_cls = spec.load_adapter()
        from nanobot.providers.tts import GroqTTSProvider

        assert adapter_cls is GroqTTSProvider

    def test_load_elevenlabs_adapter(self):
        spec = get_tts_provider("elevenlabs")
        adapter_cls = spec.load_adapter()
        from nanobot.providers.tts import ElevenLabsTTSProvider

        assert adapter_cls is ElevenLabsTTSProvider
