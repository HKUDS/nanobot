"""TTS (text-to-speech) providers."""

import asyncio
import os
from pathlib import Path

from loguru import logger

from nanobot.config.schema import TTSConfig


class CosyVoiceTTSProvider:
    """
    TTS provider using Alibaba Cloud Bailian CosyVoice.

    Synthesises text to MP3 audio via dashscope.audio.tts_v3.SpeechSynthesizer.
    Requires: pip install dashscope  (included in qwen3-asr extra)
    API key: https://dashscope.console.aliyun.com/
    """

    def __init__(self, config: TTSConfig):
        self.config = config
        self.api_key = config.api_key or os.environ.get("DASHSCOPE_API_KEY", "")

    async def synthesize(self, text: str, output_path: Path) -> bool:
        """
        Synthesise text to audio and write to output_path.

        Returns True on success, False on any failure (non-fatal).
        """
        if not self.api_key:
            logger.warning("TTS: no api_key configured, skipping voice synthesis")
            return False

        try:
            from dashscope.audio.tts_v3 import SpeechSynthesizer
        except ImportError:
            logger.error("dashscope not installed. Run: pip install dashscope")
            return False

        try:
            result = await asyncio.to_thread(
                SpeechSynthesizer.call,
                model=self.config.model,
                text=text,
                voice=self.config.voice,
                format=self.config.format,
                api_key=self.api_key,
            )
            audio_data = result.get_audio_data()
            if not audio_data:
                logger.warning("TTS: CosyVoice returned empty audio for text length={}", len(text))
                return False
            Path(output_path).write_bytes(audio_data)
            logger.debug("TTS: synthesised {} bytes → {}", len(audio_data), output_path)
            return True
        except Exception as e:
            logger.warning("TTS synthesis failed: {}", e)
            return False
