"""Tests for the explicit opt-in transcription provider."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.config.schema import TranscriptionConfig, ProviderConfig, ProvidersConfig
from nanobot.providers.transcription import create_transcription_service, TranscriptionProvider


def _providers(**kwargs) -> ProvidersConfig:
    cfg = ProvidersConfig()
    for name, api_key in kwargs.items():
        setattr(cfg, name, ProviderConfig(api_key=api_key))
    return cfg


def test_groq_routes_via_litellm():
    """Groq has supports_litellm_transcription=True in registry."""
    transcription = TranscriptionConfig(provider="groq", model="groq/whisper-large-v3")
    providers = _providers(groq="gsk_test")
    svc = create_transcription_service(transcription, providers)
    assert isinstance(svc, TranscriptionProvider)
    assert svc._use_litellm is True
    assert svc._model == "groq/whisper-large-v3"


def test_mistral_routes_via_direct_client():
    """Mistral has supports_litellm_transcription=False — uses registry default_api_base."""
    transcription = TranscriptionConfig(provider="mistral", model="voxtral-mini-latest")
    svc = create_transcription_service(transcription, _providers(mistral="mk_test"))
    assert isinstance(svc, TranscriptionProvider)
    assert svc._use_litellm is False
    assert svc._model == "voxtral-mini-latest"


def test_model_used_as_is():
    transcription = TranscriptionConfig(provider="groq", model="groq/whisper-large-v3-turbo")
    providers = _providers(groq="gsk_test")
    svc = create_transcription_service(transcription, providers)
    assert svc._model == "groq/whisper-large-v3-turbo"


def test_no_transcription_config_disables():
    svc = create_transcription_service(None, _providers(groq="gsk_test"))
    assert svc is None


def test_empty_config_silently_disables():
    """Empty provider and model (default scaffold) silently returns None."""
    transcription = TranscriptionConfig()
    svc = create_transcription_service(transcription, _providers(groq="gsk_test"))
    assert svc is None


def test_partial_config_warns():
    """Only provider or only model set is a misconfiguration."""
    svc = create_transcription_service(TranscriptionConfig(provider="groq"), _providers(groq="gsk_test"))
    assert svc is None
    svc = create_transcription_service(TranscriptionConfig(model="groq/whisper-large-v3"), _providers(groq="gsk_test"))
    assert svc is None


def test_missing_api_key_returns_none():
    transcription = TranscriptionConfig(provider="groq", model="groq/whisper-large-v3")
    svc = create_transcription_service(transcription, ProvidersConfig())
    assert svc is None


def test_anthropic_llm_groq_transcription_independent():
    transcription = TranscriptionConfig(provider="groq", model="groq/whisper-large-v3")
    providers = _providers(anthropic="sk-ant-test", groq="gsk_test")
    svc = create_transcription_service(transcription, providers)
    assert isinstance(svc, TranscriptionProvider)
    assert svc._use_litellm is True
