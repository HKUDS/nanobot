"""Voice transcription providers."""

import os
from pathlib import Path
from typing import Protocol

import httpx
from loguru import logger


class TranscriptionProvider(Protocol):
    """Interface for transcription providers."""

    async def transcribe(self, file_path: str | Path) -> str: ...


class OpenAITranscriptionProvider:
    """
    Voice transcription provider using OpenAI's Whisper API.
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        model: str = "gpt-4o-transcribe",
    ):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.api_url = f"{api_base or 'https://api.openai.com/v1'}/audio/transcriptions"
        self.model = model

    async def transcribe(self, file_path: str | Path) -> str:
        """
        Transcribe an audio file using OpenAI.
        """
        if not self.api_key:
            logger.warning("OpenAI API key not configured for transcription")
            return ""

        path = Path(file_path)
        if not path.exists():
            logger.error(f"Audio file not found: {file_path}")
            return ""

        try:
            async with httpx.AsyncClient() as client:
                with open(path, "rb") as f:
                    files = {
                        "file": (path.name, f),
                        "model": (None, self.model),
                    }
                    headers = {
                        "Authorization": f"Bearer {self.api_key}",
                    }

                    response = await client.post(
                        self.api_url, headers=headers, files=files, timeout=60.0
                    )

                    response.raise_for_status()
                    data = response.json()
                    return data.get("text", "")

        except Exception as e:
            logger.error(f"OpenAI transcription error: {e}")
            return ""
