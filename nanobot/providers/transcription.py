"""Voice transcription provider using Groq."""

from __future__ import annotations

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
        env_key = os.environ.get("GROQ_API_KEY")
        # Prefer GROQ_API_KEY env var; fall back to explicit api_key only if it
        # looks like a genuine Groq key (starts with "gsk_") to avoid using a
        # misplaced key from another provider (e.g. xAI stored in the groq slot).
        if env_key:
            self.api_key: str | None = env_key
        elif api_key and api_key.startswith("gsk_"):
            self.api_key = api_key
        else:
            if api_key:
                logger.warning(
                    "Groq transcription key does not look like a Groq key "
                    "(expected gsk_... prefix). Set GROQ_API_KEY env var or fix "
                    "providers.groq.api_key in config."
                )
            self.api_key = None
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
                    files: dict[str, tuple[str | None, bytes | str]] = {
                        "file": (path.name, f.read()),
                        "model": (None, "whisper-large-v3"),
                    }
                    headers = {
                        "Authorization": f"Bearer {self.api_key}",
                    }

                    response = await client.post(
                        self.api_url,
                        headers=headers,
                        files=files,
                        timeout=60.0,  # type: ignore[arg-type]
                    )

                response.raise_for_status()
                data = response.json()
                return str(data.get("text", ""))
        except Exception as e:  # crash-barrier: third-party HTTP transcription
            logger.error("Groq transcription error: {}", e)
            return ""
