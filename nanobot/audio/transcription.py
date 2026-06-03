"""Application-level audio transcription service.

This module owns nanobot's transcription behavior: config resolution,
legacy channel fallback, upload validation, temporary-file handling, and
dispatch to provider adapters. It deliberately does not know provider-specific
HTTP details; those live in ``nanobot.providers.transcription``.
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from loguru import logger

from nanobot.config.paths import get_media_dir
from nanobot.utils.media_decode import FileSizeExceeded, save_base64_data_url

TranscriptionProviderName = Literal["groq", "openai", "openrouter", "xiaomi_mimo"]

_DEFAULT_PROVIDER: TranscriptionProviderName = "groq"
_DEFAULT_MODELS: dict[TranscriptionProviderName, str] = {
    "groq": "whisper-large-v3",
    "openai": "whisper-1",
    "openrouter": "openai/whisper-1",
    "xiaomi_mimo": "mimo-v2.5-asr",
}
_PROVIDER_ALIASES: dict[str, TranscriptionProviderName] = {
    "mimo": "xiaomi_mimo",
    "xiaomi": "xiaomi_mimo",
}
_MAX_AUDIO_BYTES_FALLBACK = 25 * 1024 * 1024
_AUDIO_MIME_ALLOWED: frozenset[str] = frozenset({
    "audio/aac",
    "audio/flac",
    "audio/m4a",
    "audio/mp4",
    "audio/mpeg",
    "audio/ogg",
    "audio/wav",
    "audio/webm",
    "audio/x-m4a",
    "audio/x-wav",
})


@dataclass(frozen=True)
class EffectiveTranscriptionConfig:
    enabled: bool
    provider: TranscriptionProviderName
    model: str
    language: str | None
    api_key: str = field(repr=False)
    api_base: str
    max_duration_sec: int
    max_upload_mb: int

    @property
    def configured(self) -> bool:
        return bool(self.api_key)


class TranscriptionIngressError(Exception):
    """Stable transcription upload error surfaced to WebUI clients."""

    def __init__(self, detail: str, **extra: Any):
        super().__init__(detail)
        self.detail = detail
        self.extra = extra


def _as_provider(value: Any) -> TranscriptionProviderName | None:
    if isinstance(value, str):
        name = value.strip().lower()
        if name in _PROVIDER_ALIASES:
            return _PROVIDER_ALIASES[name]
        if name in _DEFAULT_MODELS:
            return name  # type: ignore[return-value]
    return None


def _provider_config(config: Any, provider: str) -> Any:
    return getattr(getattr(config, "providers", None), provider, None)


def _extract_data_url_mime(url: str) -> str | None:
    header, _, _ = url.partition(",")
    if not header.startswith("data:") or ";base64" not in header:
        return None
    return header[5:].split(";", 1)[0].strip().lower() or None


def resolve_transcription_config(config: Any) -> EffectiveTranscriptionConfig:
    """Resolve top-level transcription settings with legacy channel fallback."""
    top = getattr(config, "transcription", None)
    channels = getattr(config, "channels", None)
    provider = (
        _as_provider(getattr(top, "provider", None))
        or _as_provider(getattr(channels, "transcription_provider", None))
        or _DEFAULT_PROVIDER
    )
    provider_cfg = _provider_config(config, provider)
    return EffectiveTranscriptionConfig(
        enabled=bool(getattr(top, "enabled", True)),
        provider=provider,
        model=(getattr(top, "model", None) or _DEFAULT_MODELS[provider]).strip(),
        language=getattr(top, "language", None) or getattr(channels, "transcription_language", None),
        api_key=getattr(provider_cfg, "api_key", None) or "",
        api_base=getattr(provider_cfg, "api_base", None) or "",
        max_duration_sec=int(getattr(top, "max_duration_sec", 120)),
        max_upload_mb=int(getattr(top, "max_upload_mb", 25)),
    )


async def transcribe_audio_data_url(
    data_url: Any,
    config: EffectiveTranscriptionConfig,
    *,
    duration_ms: Any = None,
) -> str:
    """Validate, persist, transcribe, and remove a WebUI audio data URL."""
    if not isinstance(data_url, str) or not data_url:
        raise TranscriptionIngressError("missing_audio")
    if not config.enabled:
        raise TranscriptionIngressError("disabled")
    if not config.configured:
        raise TranscriptionIngressError("not_configured", provider=config.provider)
    if (
        isinstance(duration_ms, (int, float))
        and duration_ms > (config.max_duration_sec * 1000 + 1000)
    ):
        raise TranscriptionIngressError("duration")
    if _extract_data_url_mime(data_url) not in _AUDIO_MIME_ALLOWED:
        raise TranscriptionIngressError("mime")

    audio_path: str | None = None
    max_bytes = max(
        1,
        config.max_upload_mb * 1024 * 1024 if config.max_upload_mb else _MAX_AUDIO_BYTES_FALLBACK,
    )
    try:
        audio_path = save_base64_data_url(
            data_url,
            get_media_dir("webui-transcription"),
            max_bytes=max_bytes,
        )
    except FileSizeExceeded as exc:
        raise TranscriptionIngressError("size") from exc
    except Exception as exc:
        logger.warning("transcription audio decode failed: {}", exc)
    if not audio_path:
        raise TranscriptionIngressError("decode")

    try:
        text = await transcribe_audio_file(audio_path, config)
    finally:
        with suppress(OSError):
            Path(audio_path).unlink(missing_ok=True)
    if not text:
        raise TranscriptionIngressError("empty")
    return text


async def transcribe_audio_file(
    file_path: str | Path,
    config: EffectiveTranscriptionConfig,
) -> str:
    """Transcribe *file_path* using the already-resolved transcription config."""
    if not config.enabled or not config.configured:
        return ""
    if config.provider == "openai":
        from nanobot.providers.transcription import OpenAITranscriptionProvider

        provider = OpenAITranscriptionProvider(
            api_key=config.api_key,
            api_base=config.api_base or None,
            language=config.language,
            model=config.model,
        )
    elif config.provider == "openrouter":
        from nanobot.providers.transcription import OpenRouterTranscriptionProvider

        provider = OpenRouterTranscriptionProvider(
            api_key=config.api_key,
            api_base=config.api_base or None,
            language=config.language,
            model=config.model,
        )
    elif config.provider == "xiaomi_mimo":
        from nanobot.providers.transcription import XiaomiMiMoTranscriptionProvider

        provider = XiaomiMiMoTranscriptionProvider(
            api_key=config.api_key,
            api_base=config.api_base or None,
            language=config.language,
            model=config.model,
        )
    else:
        from nanobot.providers.transcription import GroqTranscriptionProvider

        provider = GroqTranscriptionProvider(
            api_key=config.api_key,
            api_base=config.api_base or None,
            language=config.language,
            model=config.model,
        )
    return await provider.transcribe(file_path)
