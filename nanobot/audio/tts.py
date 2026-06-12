"""Application-level text-to-speech service.

This module owns nanobot's TTS behavior: config resolution,
text validation, temporary-file handling, and dispatch to provider adapters.
It deliberately does not know provider-specific HTTP details; those live in
``nanobot.providers.tts``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.audio.tts_registry import (
    get_tts_provider,
    resolve_tts_provider,
)
from nanobot.config.paths import get_media_dir

TTSProviderName = str

_DEFAULT_PROVIDER: TTSProviderName = "openai"


@dataclass(frozen=True)
class EffectiveTTSConfig:
    enabled: bool
    provider: TTSProviderName
    model: str
    voice: str
    speed: float
    max_char_length: int
    api_key: str = field(repr=False)
    api_base: str
    response_format: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key)


class TTSIngressError(Exception):
    """Stable TTS error surfaced to callers."""

    def __init__(self, detail: str, **extra: Any):
        super().__init__(detail)
        self.detail = detail
        self.extra = extra


_SENTINEL = object()


def _getattr(obj: Any, name: str, default: Any = None) -> Any:
    """Read an attribute from *obj*, supporting both objects and dicts."""
    # Object-style (e.g. pydantic model or SimpleNamespace)
    val = getattr(obj, name, _SENTINEL)
    if val is not _SENTINEL:
        return val
    # Dict-style (e.g. plain JSON config loaded as dict)
    if isinstance(obj, dict):
        return obj.get(name, default)
    return default


def _as_provider(value: Any) -> TTSProviderName | None:
    spec = resolve_tts_provider(value)
    return spec.name if spec else None


def _provider_config(config: Any, provider: str) -> Any:
    providers = _getattr(config, "providers", None)
    return _getattr(providers, provider, None) if providers else None


def _provider_default_api_base(provider: str) -> str | None:
    from nanobot.providers.registry import find_by_name

    spec = find_by_name(provider)
    return spec.default_api_base if spec else None


def _resolve_tts_api_key(provider: str, provider_cfg: Any) -> str:
    api_key = _getattr(provider_cfg, "api_key", None) if provider_cfg else None
    if api_key:
        return api_key

    from nanobot.providers.registry import find_by_name

    spec = find_by_name(provider)

    # ElevenLabs uses its own env key
    if provider == "elevenlabs":
        env_key = os.environ.get("ELEVENLABS_API_KEY")
        if env_key:
            return env_key

    env_key = spec.env_key if spec else ""
    return os.environ.get(env_key) if env_key else ""


def _resolve_tts_api_base(provider: str, provider_cfg: Any) -> str:
    api_base = _getattr(provider_cfg, "api_base", None) if provider_cfg else None
    if api_base:
        return api_base
    return _provider_default_api_base(provider) or ""


def resolve_tts_config(config: Any) -> EffectiveTTSConfig:
    """Resolve top-level TTS settings."""
    top = _getattr(config, "tts", None)
    provider = _as_provider(_getattr(top, "provider", None)) or _DEFAULT_PROVIDER
    spec = get_tts_provider(provider)
    if spec is None:
        logger.warning("Unknown TTS provider {}; falling back to {}", provider, _DEFAULT_PROVIDER)
        provider = _DEFAULT_PROVIDER
        spec = get_tts_provider(provider)
    default_model = spec.default_model if spec else ""
    default_voice = spec.default_voice if spec else ""
    provider_cfg = _provider_config(config, provider)
    return EffectiveTTSConfig(
        enabled=bool(_getattr(top, "enabled", True)),
        provider=provider,
        model=(_getattr(top, "model", None) or default_model).strip(),
        voice=(_getattr(top, "voice", None) or default_voice).strip(),
        speed=float(_getattr(top, "speed", 1.0)),
        max_char_length=int(_getattr(top, "max_char_length", 4096)),
        api_key=_resolve_tts_api_key(provider, provider_cfg),
        api_base=_resolve_tts_api_base(provider, provider_cfg),
        response_format=_getattr(top, "response_format", None),
    )


async def synthesize_speech(
    text: str,
    config: EffectiveTTSConfig,
    *,
    output_dir: str | Path | None = None,
) -> str:
    """Synthesize speech from text using the resolved TTS config.

    Returns the path to the generated audio file.
    """
    if not config.enabled:
        raise TTSIngressError("disabled")
    if not config.configured:
        raise TTSIngressError("not_configured", provider=config.provider)
    if not text or not text.strip():
        raise TTSIngressError("empty_text")
    if len(text) > config.max_char_length:
        raise TTSIngressError("text_too_long", max_length=config.max_char_length, actual=len(text))

    spec = get_tts_provider(config.provider)
    if spec is None:
        raise TTSIngressError("unknown_provider", provider=config.provider)

    if output_dir is None:
        output_dir = get_media_dir("tts")
    out_path = Path(output_dir) / "tts_output.mp3"

    provider = spec.load_adapter()(
        api_key=config.api_key,
        api_base=config.api_base or None,
        model=config.model,
        voice=config.voice,
        response_format=config.response_format,
    )
    result_path = await provider.synthesize(text, str(out_path))
    if not result_path or not Path(result_path).exists():
        raise TTSIngressError("synthesis_failed")
    return result_path
