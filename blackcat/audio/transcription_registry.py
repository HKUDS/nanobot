"""Registry for speech-to-text providers.

Provider-specific HTTP adapters live in ``blackcat.providers.transcription``.
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
    env_key: str = ""
    default_api_base: str = ""

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
        adapter="blackcat.providers.transcription:GroqTranscriptionProvider",
        env_key="GROQ_API_KEY",
        default_api_base="https://api.groq.com/openai/v1",
    ),
    TranscriptionProviderSpec(
        name="openai",
        default_model="whisper-1",
        adapter="blackcat.providers.transcription:OpenAITranscriptionProvider",
        env_key="OPENAI_API_KEY",
        default_api_base="https://api.openai.com/v1",
    ),
    TranscriptionProviderSpec(
        name="openrouter",
        default_model="openai/whisper-1",
        adapter="blackcat.providers.transcription:OpenRouterTranscriptionProvider",
        env_key="OPENROUTER_API_KEY",
        default_api_base="https://openrouter.ai/api/v1",
    ),
    TranscriptionProviderSpec(
        name="siliconflow",
        default_model="FunAudioLLM/SenseVoiceSmall",
        adapter="blackcat.providers.transcription:OpenAITranscriptionProvider",
        aliases=("silicon",),
        env_key="SILICONFLOW_API_KEY",
        default_api_base="https://api.siliconflow.cn/v1",
    ),
    TranscriptionProviderSpec(
        name="xiaomi_mimo",
        default_model="mimo-v2.5-asr",
        adapter="blackcat.providers.transcription:XiaomiMiMoTranscriptionProvider",
        aliases=("mimo", "xiaomi"),
        env_key="XIAOMIMIMO_API_KEY",
        default_api_base="https://api.xiaomimimo.com/v1",
    ),
    TranscriptionProviderSpec(
        name="stepfun",
        default_model="stepaudio-2.5-asr",
        adapter="blackcat.providers.transcription:StepFunTranscriptionProvider",
        env_key="STEPFUN_API_KEY",
        default_api_base="https://api.stepfun.com/v1",
    ),
    TranscriptionProviderSpec(
        name="stepfun",
        default_model="stepaudio-2.5-asr",
        adapter="blackcat.providers.transcription:StepFunTranscriptionProvider",
    ),
    TranscriptionProviderSpec(
        name="assemblyai",
        default_model="universal-3-pro,universal-2",
        adapter="blackcat.providers.transcription:AssemblyAITranscriptionProvider",
        env_key="ASSEMBLYAI_API_KEY",
        default_api_base="https://api.assemblyai.com/v2",
    ),
    TranscriptionProviderSpec(
        name="siliconflow",
        default_model="FunAudioLLM/SenseVoiceSmall",
        adapter="blackcat.providers.transcription:OpenAITranscriptionProvider",
        aliases=("silicon",),
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
