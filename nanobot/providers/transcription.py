"""Voice transcription provider using Groq."""

import os
from pathlib import Path

import httpx
from loguru import logger


class GroqTranscriptionProvider:
    """
    Voice transcription provider using Groq's Whisper API.

    Groq offers extremely fast transcription with a generous free tier.
    """

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("GROQ_API_KEY")
        self.api_url = "https://api.groq.com/openai/v1/audio/transcriptions"

    async def transcribe(self, file_path: str | Path) -> str:
        """
        Transcribe an audio file using Groq.

        Args:
            file_path: Path to the audio file.

        Returns:
            Transcribed text.
        """
        if not self.api_key:
            logger.warning("Groq API key not configured for transcription")
            return ""

        path = Path(file_path)
        if not path.exists():
            logger.error("Audio file not found: {}", file_path)
            return ""

        try:
            async with httpx.AsyncClient() as client:
                with open(path, "rb") as f:
                    files = {
                        "file": (path.name, f),
                        "model": (None, "whisper-large-v3"),
                    }
                    headers = {
                        "Authorization": f"Bearer {self.api_key}",
                    }

                    response = await client.post(
                        self.api_url,
                        headers=headers,
                        files=files,
                        timeout=60.0
                    )

                    response.raise_for_status()
                    data = response.json()
                    return data.get("text", "")

        except Exception as e:
            logger.error("Groq transcription error: {}", e)
            return ""


from typing import Any

class SpeachesTranscriptionProvider:
    """
    Voice transcription provider using Speaches/local Whisper node.
    """

    def __init__(self, api_base: str, model: str = "whisper-large-v3"):
        self.api_url = f"{api_base.rstrip('/')}/audio/transcriptions"
        self.model = model

    async def transcribe(self, file_path: str | Path) -> str:
        path = Path(file_path)
        if not path.exists():
            logger.error("Audio file not found: {}", file_path)
            return ""

        try:
            async with httpx.AsyncClient() as client:
                with open(path, "rb") as f:
                    files = {
                        "file": (path.name, f),
                        "model": (None, self.model),
                    }
                    response = await client.post(
                        self.api_url,
                        files=files,
                        timeout=90.0
                    )

                    response.raise_for_status()
                    data = response.json()
                    return data.get("text", "")

        except Exception as e:
            logger.error("Speaches transcription error: {}", e)
            return ""


def get_transcription_provider(stt_config: Any) -> Any:
    """Factory to get the configured transcription provider."""
    provider_type = getattr(stt_config, "provider", "groq")
    if provider_type == "speaches":
        base = getattr(stt_config, "api_base", "") or "http://localhost:8000/v1"
        model = getattr(stt_config, "model", "whisper-large-v3")
        return SpeachesTranscriptionProvider(api_base=base, model=model)
    else:
        key = getattr(stt_config, "api_key", None)
        return GroqTranscriptionProvider(api_key=key)
