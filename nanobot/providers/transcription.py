"""Voice transcription providers."""

import os
from pathlib import Path

import httpx
from loguru import logger


class OpenAICompatibleTranscriptionProvider:
    """Generic OpenAI-compatible audio transcription provider."""

    provider_name = "openai-compatible"
    env_key: str | None = None
    default_api_base = ""
    default_model = "whisper-1"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_base: str | None = None,
        model: str = "",
        extra_headers: dict[str, str] | None = None,
    ):
        self.api_key = api_key or (os.environ.get(self.env_key) if self.env_key else None) or ""
        self.api_url = self._normalize_api_url(api_base or self.default_api_base)
        self.model = model or self.default_model
        self.extra_headers = extra_headers or {}

    @staticmethod
    def _normalize_api_url(api_base: str) -> str:
        base = (api_base or "").rstrip("/")
        if base.endswith("/audio/transcriptions"):
            return base
        return f"{base}/audio/transcriptions" if base else ""

    def is_configured(self) -> bool:
        """Return whether the provider has enough config to attempt a request."""
        if not self.api_url:
            return False
        return bool(self.api_key or self.extra_headers or self.provider_name == "custom")

    async def transcribe(self, file_path: str | Path) -> str:
        """Transcribe an audio file using an OpenAI-compatible endpoint."""
        if not self.is_configured():
            logger.warning("{} transcription not configured", self.provider_name)
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
                        "model": (None, self.model),
                    }
                    headers = dict(self.extra_headers)
                    if self.api_key:
                        headers["Authorization"] = f"Bearer {self.api_key}"

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
            logger.error("{} transcription error: {}", self.provider_name, e)
            return ""


class GroqTranscriptionProvider(OpenAICompatibleTranscriptionProvider):
    """
    Voice transcription provider using Groq's Whisper API.

    Groq offers extremely fast transcription with a generous free tier.
    """

    provider_name = "groq"
    env_key = "GROQ_API_KEY"
    default_api_base = "https://api.groq.com/openai/v1"
    default_model = "whisper-large-v3"


class OpenAITranscriptionProvider(OpenAICompatibleTranscriptionProvider):
    """Voice transcription provider using OpenAI's audio transcription API."""

    provider_name = "openai"
    env_key = "OPENAI_API_KEY"
    default_api_base = "https://api.openai.com/v1"
    default_model = "whisper-1"


class CustomTranscriptionProvider(OpenAICompatibleTranscriptionProvider):
    """Voice transcription provider for user-supplied OpenAI-compatible endpoints."""

    provider_name = "custom"
