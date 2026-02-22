"""Voice transcription providers using Groq and Mistral."""

import os
from pathlib import Path

import httpx
from loguru import logger


class TranscriptionProvider:
    def __init__(self, api_key: str, api_url: str, model: str):
        self.api_key = api_key
        self.api_url = api_url
        self.model = model

    async def transcribe(self, file_path: str | Path) -> str:
        """
        Transcribe an audio file using one of the providers.

        Args:
            file_path: Path to the audio file.

        Returns:
            Transcribed text.
        """
        path = Path(file_path)
        if not path.exists():
            logger.error("Audio file not found: {}", file_path)
            return ""
        try:
            async with httpx.AsyncClient() as client:
                with open(path, "rb") as f:
                    response = await client.post(
                        self.api_url,
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        files={"file": (path.name, f), "model": (None, self.model)},
                        timeout=60.0,
                    )
                    response.raise_for_status()
                    return response.json().get("text", "")
        except Exception as e:
            logger.error("Transcription error: {}", e)
            return ""

def create_transcription_service(providers_config) -> TranscriptionProvider | None:
    """
    Create the relevant Audio Transcription provider.
    - Groq offers extremely fast transcription with a generous free tier.
    - Voxtral is free at experiment tier. Advanced features are available, but keep it simple for consistency.
    """

    groq_key = providers_config.groq.api_key or os.environ.get("GROQ_API_KEY")
    if groq_key:
        return TranscriptionProvider(
            api_key=groq_key,
            api_url="https://api.groq.com/openai/v1/audio/transcriptions",
            model="whisper-large-v3",
        )

    mistral_key = providers_config.mistral.api_key or os.environ.get("MISTRAL_API_KEY")
    if mistral_key:
        return TranscriptionProvider(
            api_key=mistral_key,
            api_url="https://api.mistral.ai/v1/audio/transcriptions",
            model="voxtral-mini-latest",
        )

    logger.debug("No transcription provider configured, skipping voice transcription")
    return None
