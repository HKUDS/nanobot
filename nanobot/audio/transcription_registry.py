"""Registry for speech-to-text providers.

Provider-specific HTTP adapters live in ``nanobot.providers.transcription``.
This module is the app-level source of truth for provider names, aliases,
default models, and adapter class paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol


class TranscriptionProviderAdapter(Protocol):
    """Runtime protocol implemented by provider-specific transcription adapters."""

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        language: str | None = None,
        model: str | None = None,
    ) -> None: ...

    async def transcribe(self, file_path: str | Path) -> str: ...


@dataclass(frozen=True)
class TranscriptionProviderSpec:
    name: str
    default_model: str
    adapter: str
    aliases: tuple[str, ...] = ()

    def load_adapter(self) -> type[TranscriptionProviderAdapter]:
        module_name, _, class_name = self.adapter.partition(":")
        if not module_name or not class_name:
            raise RuntimeError(f"Invalid transcription adapter path: {self.adapter}")
        adapter = getattr(import_module(module_name), class_name)
        return adapter


TRANSCRIPTION_PROVIDERS: tuple[TranscriptionProviderSpec, ...] = (
    TranscriptionProviderSpec(
        name="groq",
        default_model="whisper-large-v3",
        adapter="nanobot.providers.transcription:GroqTranscriptionProvider",
    ),
    TranscriptionProviderSpec(
        name="openai",
        default_model="whisper-1",
        adapter="nanobot.providers.transcription:OpenAITranscriptionProvider",
    ),
    TranscriptionProviderSpec(
        name="openrouter",
        default_model="openai/whisper-1",
        adapter="nanobot.providers.transcription:OpenRouterTranscriptionProvider",
    ),
    TranscriptionProviderSpec(
        name="xiaomi_mimo",
        default_model="mimo-v2.5-asr",
        adapter="nanobot.providers.transcription:XiaomiMiMoTranscriptionProvider",
        aliases=("mimo", "xiaomi"),
    ),
    TranscriptionProviderSpec(
        name="assemblyai",
        default_model="universal-3-pro,universal-2",
        adapter="nanobot.providers.transcription:AssemblyAITranscriptionProvider",
    ),
)

_BY_NAME = {spec.name: spec for spec in TRANSCRIPTION_PROVIDERS}
_BY_ALIAS = {alias: spec for spec in TRANSCRIPTION_PROVIDERS for alias in spec.aliases}


def transcription_provider_names() -> tuple[str, ...]:
    return tuple(spec.name for spec in TRANSCRIPTION_PROVIDERS)


def get_transcription_provider(name: str) -> TranscriptionProviderSpec | None:
    return _BY_NAME.get(name)


def resolve_transcription_provider(value: Any) -> TranscriptionProviderSpec | None:
    if not isinstance(value, str):
        return None
    name = value.strip().lower()
    return _BY_NAME.get(name) or _BY_ALIAS.get(name)
