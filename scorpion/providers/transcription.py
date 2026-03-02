"""Voice transcription via ElevenLabs Scribe."""

from pathlib import Path

import httpx
from loguru import logger


class ElevenLabsTranscriptionProvider:
    """
    Voice transcription using ElevenLabs Scribe (scribe_v1).
    Primary and only transcription provider.
    """

    def __init__(self, api_key: str | None = None):
        if api_key:
            self.api_key = api_key
        else:
            from scorpion.config.loader import load_config
            try:
                self.api_key = load_config().providers.elevenlabs.api_key or ""
            except Exception:
                self.api_key = ""
        self.api_url = "https://api.elevenlabs.io/v1/speech-to-text"

    async def transcribe(self, file_path: str | Path) -> str:
        if not self.api_key:
            logger.warning("ElevenLabs API key not configured for transcription")
            return ""

        path = Path(file_path)
        if not path.exists():
            logger.error("Audio file not found: {}", file_path)
            return ""

        try:
            async with httpx.AsyncClient() as client:
                with open(path, "rb") as f:
                    # Both fields in files= to guarantee multipart form encoding
                    response = await client.post(
                        self.api_url,
                        headers={"xi-api-key": self.api_key},
                        files={
                            "file": (path.name, f, "audio/ogg"),
                            "model_id": (None, "scribe_v1"),
                        },
                        timeout=60.0,
                    )
                    response.raise_for_status()
                    result = response.json().get("text", "")
                    logger.info("ElevenLabs transcribed {} chars from {}", len(result), path.name)
                    return result
        except Exception as e:
            logger.error("ElevenLabs transcription error: {}", e)
            return ""
