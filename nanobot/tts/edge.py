"""Edge TTS provider (free, no API key required)."""

from pathlib import Path

import edge_tts

from .base import TTSError, TTSProvider


class EdgeTTSProvider(TTSProvider):
    """Microsoft Edge TTS — free, high-quality, same voices as Azure."""

    def __init__(self, voice: str = "zh-CN-XiaoxiaoNeural"):
        self.voice = voice

    async def synthesize(self, text: str, output_path: Path) -> Path:
        if not text or not text.strip():
            raise TTSError("Empty text")
        try:
            communicate = edge_tts.Communicate(text, self.voice)
            await communicate.save(str(output_path))
            if not output_path.exists() or output_path.stat().st_size == 0:
                raise TTSError("Output file empty after synthesis")
            return output_path
        except TTSError:
            raise
        except Exception as e:
            raise TTSError(f"Edge TTS failed: {e}") from e

    @property
    def name(self) -> str:
        return "edge"
