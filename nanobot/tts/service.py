"""TTS service layer — trigger logic + provider management + temp files."""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from .base import TTSError
from .factory import create_provider

if TYPE_CHECKING:
    from nanobot.config.schema import TTSConfig


class TTSService:
    """TTS service: decides whether to trigger, calls provider, manages temp files."""

    def __init__(self, config: TTSConfig):
        self.config = config
        self._temp_dir = Path(tempfile.gettempdir()) / "nanobot_tts"
        self._temp_dir.mkdir(exist_ok=True)

    def should_trigger(self, session_tts: bool = False, skill_meta: dict[str, Any] | None = None) -> bool:
        """Check if TTS should be triggered for this response."""
        if not self.config.enabled:
            return False
        if session_tts:
            return True
        if skill_meta and skill_meta.get("tts"):
            return True
        return False

    async def synthesize(self, text: str, voice: str | None = None) -> Path | None:
        """Generate audio. Returns file path on success, None on failure (never blocks text)."""
        if not text or not text.strip():
            return None

        if len(text) > self.config.max_text_length:
            text = text[:self.config.max_text_length]

        output_path = self._temp_dir / f"tts_{uuid.uuid4().hex[:8]}.mp3"

        try:
            provider = create_provider(self.config, voice_override=voice)
            result = await provider.synthesize(text, output_path)
            logger.info("TTS generated: {} ({} bytes)", result.name, result.stat().st_size)
            return result
        except TTSError as e:
            logger.error("TTS synthesis failed: {}", e)
            return None
        except Exception as e:
            logger.error("Unexpected TTS error: {}", e)
            return None
