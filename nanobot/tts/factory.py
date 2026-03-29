"""TTS provider factory."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import TTSProvider

if TYPE_CHECKING:
    from nanobot.config.schema import TTSConfig


def create_provider(config: TTSConfig, voice_override: str | None = None) -> TTSProvider:
    """Create a TTS provider from config."""
    voice = voice_override or config.voice

    if config.provider == "edge":
        from .edge import EdgeTTSProvider
        return EdgeTTSProvider(voice=voice)

    raise ValueError(f"Unknown TTS provider: {config.provider}")
