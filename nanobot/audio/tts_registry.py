"""Registry for text-to-speech providers.

Provider-specific HTTP adapters live in ``nanobot.providers.tts``.
This module is the app-level source of truth for provider names, aliases,
default models, default voices, and adapter class paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol


class TTSProviderAdapter(Protocol):
    """Runtime protocol implemented by provider-specific TTS adapters."""

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        model: str | None = None,
        voice: str | None = None,
        response_format: str | None = None,
    ) -> None: ...

    async def synthesize(self, text: str, output_path: str | Path) -> str: ...


@dataclass(frozen=True)
class TTSProviderSpec:
    name: str
    default_model: str
    default_voice: str
    adapter: str
    default_response_format: str = "mp3"
    aliases: tuple[str, ...] = ()

    def load_adapter(self) -> type[TTSProviderAdapter]:
        module_name, _, class_name = self.adapter.partition(":")
        if not module_name or not class_name:
            raise RuntimeError(f"Invalid TTS adapter path: {self.adapter}")
        adapter = getattr(import_module(module_name), class_name)
        return adapter


TTS_PROVIDERS: tuple[TTSProviderSpec, ...] = (
    TTSProviderSpec(
        name="openai",
        default_model="tts-1",
        default_voice="alloy",
        adapter="nanobot.providers.tts:OpenAITTSProvider",
        default_response_format="mp3",
    ),
    TTSProviderSpec(
        name="groq",
        default_model="canopylabs/orpheus-v1-english",
        default_voice="autumn",
        adapter="nanobot.providers.tts:GroqTTSProvider",
        default_response_format="wav",
    ),
    TTSProviderSpec(
        name="elevenlabs",
        default_model="eleven_multilingual_v2",
        default_voice="Matilda",
        adapter="nanobot.providers.tts:ElevenLabsTTSProvider",
        aliases=("eleven",),
        default_response_format="mp3",
    ),
)

_BY_NAME = {spec.name: spec for spec in TTS_PROVIDERS}
_BY_ALIAS = {alias: spec for spec in TTS_PROVIDERS for alias in spec.aliases}


def tts_provider_names() -> tuple[str, ...]:
    return tuple(spec.name for spec in TTS_PROVIDERS)


def get_tts_provider(name: str) -> TTSProviderSpec | None:
    return _BY_NAME.get(name)


def resolve_tts_provider(value: Any) -> TTSProviderSpec | None:
    if not isinstance(value, str):
        return None
    name = value.strip().lower()
    return _BY_NAME.get(name) or _BY_ALIAS.get(name)
