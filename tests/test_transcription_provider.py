from types import SimpleNamespace

from nanobot.config.schema import Config
from nanobot.providers.transcription import (
    GroqTranscriptionProvider,
    LocalFasterWhisperTranscriptionProvider,
    resolve_transcription_provider,
)


def test_config_accepts_transcriber_and_transcription_settings() -> None:
    config = Config.model_validate(
        {
            "agents": {"defaults": {"transcriber": "faster-whisper"}},
            "transcription": {
                "fasterWhisper": {
                    "model": "base",
                    "device": "cpu",
                    "computeType": "int8",
                    "beamSize": 3,
                }
            },
        }
    )

    assert config.agents.defaults.transcriber == "faster-whisper"
    assert config.transcription.faster_whisper.model == "base"
    assert config.transcription.faster_whisper.device == "cpu"
    assert config.transcription.faster_whisper.compute_type == "int8"
    assert config.transcription.faster_whisper.beam_size == 3


def test_auto_prefers_faster_whisper_when_available(monkeypatch) -> None:
    config = Config()
    monkeypatch.setattr(
        LocalFasterWhisperTranscriptionProvider,
        "is_available",
        staticmethod(lambda: True),
    )

    provider = resolve_transcription_provider(config)

    assert isinstance(provider, LocalFasterWhisperTranscriptionProvider)


def test_auto_falls_back_to_groq_when_faster_whisper_unavailable() -> None:
    config = Config.model_validate(
        {
            "providers": {"groq": {"apiKey": "secret"}},
        }
    )
    original = LocalFasterWhisperTranscriptionProvider.is_available
    LocalFasterWhisperTranscriptionProvider.is_available = staticmethod(lambda: False)
    try:
        provider = resolve_transcription_provider(config)
    finally:
        LocalFasterWhisperTranscriptionProvider.is_available = original

    assert isinstance(provider, GroqTranscriptionProvider)


def test_manual_faster_whisper_without_dependency_returns_none(monkeypatch) -> None:
    config = Config.model_validate(
        {
            "agents": {"defaults": {"transcriber": "faster-whisper"}},
        }
    )
    monkeypatch.setattr(
        LocalFasterWhisperTranscriptionProvider,
        "is_available",
        staticmethod(lambda: False),
    )

    assert resolve_transcription_provider(config) is None


def test_manual_groq_requires_api_key() -> None:
    config = SimpleNamespace(
        agents=SimpleNamespace(defaults=SimpleNamespace(transcriber="groq")),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
        transcription=SimpleNamespace(groq=SimpleNamespace()),
    )

    assert resolve_transcription_provider(config) is None
