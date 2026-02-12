"""Text-to-Speech (TTS) provider implementations."""

import abc
import os
from pathlib import Path
from typing import Literal

from loguru import logger
import httpx


class TTSProvider(abc.ABC):
    """Abstract base class for TTS providers."""

    @abc.abstractmethod
    async def generate_speech(self, text: str, output_path: Path) -> Path | None:
        """
        Generate speech from text and save to output_path.
        
        Args:
            text: Text to convert to speech.
            output_path: Path to save the audio file.
            
        Returns:
            Path to the saved audio file, or None if failed.
        """
        pass


class OpenAITTSProvider(TTSProvider):
    """OpenAI TTS provider."""

    def __init__(self, api_key: str, model: str = "tts-1", voice: str = "alloy", speed: float = 1.0):
        self.api_key = api_key
        self.model = model
        self.voice = voice
        self.speed = speed
        self.api_url = "https://api.openai.com/v1/audio/speech"

    async def generate_speech(self, text: str, output_path: Path) -> Path | None:
        if not self.api_key:
            logger.warning("OpenAI API key not configured for TTS")
            return None

        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            data = {
                "model": self.model,
                "input": text,
                "voice": self.voice,
                "speed": self.speed,
                "response_format": "mp3",
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(self.api_url, headers=headers, json=data, timeout=60.0)
                if response.status_code != 200:
                    logger.error(f"OpenAI TTS failed: {response.text}")
                    return None

                with open(output_path, "wb") as f:
                    f.write(response.content)

                return output_path

        except Exception as e:
            logger.error(f"OpenAI TTS error: {e}")
            return None


class EdgeTTSProvider(TTSProvider):
    """Edge TTS provider (free, using edge-tts library)."""

    def __init__(self, voice: str = "en-US-ChristopherNeural", rate: str = "+0%"):
        self.voice = voice
        self.rate = rate

    async def generate_speech(self, text: str, output_path: Path) -> Path | None:
        try:
            import edge_tts
        except ImportError:
            logger.error("edge-tts not installed. Run: pip install edge-tts")
            return None

        try:
            communicate = edge_tts.Communicate(text, self.voice, rate=self.rate)
            await communicate.save(str(output_path))
            return output_path
        except Exception as e:
            logger.error(f"Edge TTS error: {e}")
            return None
