"""ElevenLabs text-to-speech provider."""

import os
from pathlib import Path
from typing import Any

import httpx
from loguru import logger


class ElevenLabsProvider:
    """
    Text-to-speech provider using ElevenLabs API.

    Generates high-quality voice audio from text.
    """

    DEFAULT_BASE_URL = "https://api.elevenlabs.io"
    DEFAULT_VOICE_ID = "pMsXgVXv3BLzUgSXRplE"  # Default voice (Serena)
    DEFAULT_MODEL_ID = "eleven_multilingual_v2"

    def __init__(
        self,
        api_key: str | None = None,
        voice_id: str | None = None,
        model_id: str | None = None,
        stability: float = 0.5,
        similarity_boost: float = 0.75,
        style: float = 0.0,
        speed: float = 1.0,
    ):
        self.api_key = api_key or os.environ.get("ELEVENLABS_API_KEY") or os.environ.get("XI_API_KEY")
        self.voice_id = voice_id or self.DEFAULT_VOICE_ID
        self.model_id = model_id or self.DEFAULT_MODEL_ID
        self.stability = stability
        self.similarity_boost = similarity_boost
        self.style = style
        self.speed = speed

    async def text_to_speech(
        self,
        text: str,
        output_path: str | Path | None = None,
        output_format: str = "mp3_44100_128",
        voice_id: str | None = None,
    ) -> Path | None:
        """
        Convert text to speech using ElevenLabs API.

        Args:
            text: Text to convert to speech.
            output_path: Path to save audio file. If None, generates temp file.
            output_format: Audio format (mp3_44100_128, opus_48000_64, pcm_22050).
            voice_id: Override voice ID for this request.

        Returns:
            Path to generated audio file, or None on error.
        """
        if not self.api_key:
            logger.warning("ElevenLabs API key not configured")
            return None

        if not text.strip():
            logger.warning("Empty text for TTS")
            return None

        voice = voice_id or self.voice_id
        url = f"{self.DEFAULT_BASE_URL}/v1/text-to-speech/{voice}"

        # Add output format as query parameter
        if output_format:
            url = f"{url}?output_format={output_format}"

        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }

        body = {
            "text": text,
            "model_id": self.model_id,
            "voice_settings": {
                "stability": self.stability,
                "similarity_boost": self.similarity_boost,
                "style": self.style,
                "speed": self.speed,
            },
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers=headers,
                    json=body,
                    timeout=60.0
                )

                response.raise_for_status()

                # Determine output path
                if output_path:
                    path = Path(output_path)
                else:
                    import time
                    media_dir = Path.home() / ".nanobot" / "media" / "generated"
                    media_dir.mkdir(parents=True, exist_ok=True)

                    # Determine extension from format
                    ext = ".mp3"
                    if "opus" in output_format:
                        ext = ".ogg"
                    elif "pcm" in output_format:
                        ext = ".wav"

                    path = media_dir / f"tts_{int(time.time())}{ext}"

                # Save audio
                with open(path, "wb") as f:
                    f.write(response.content)

                logger.info(f"Generated TTS audio: {path} ({len(response.content)} bytes)")
                return path

        except httpx.HTTPStatusError as e:
            logger.error(f"ElevenLabs API error ({e.response.status_code}): {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"ElevenLabs TTS error: {e}")
            return None

    async def list_voices(self) -> list[dict[str, Any]]:
        """List available voices."""
        if not self.api_key:
            return []

        url = f"{self.DEFAULT_BASE_URL}/v1/voices"
        headers = {"xi-api-key": self.api_key}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, timeout=30.0)
                response.raise_for_status()
                data = response.json()
                return data.get("voices", [])
        except Exception as e:
            logger.error(f"Failed to list voices: {e}")
            return []
