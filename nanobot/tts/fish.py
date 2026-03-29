"""Fish Audio TTS provider (voice cloning supported)."""

from __future__ import annotations

from pathlib import Path

import httpx
from loguru import logger

from .base import TTSError, TTSProvider

FISH_API_BASE = "https://api.fish.audio"


class FishTTSProvider(TTSProvider):
    """Fish Audio TTS — high-quality Chinese voice cloning."""

    def __init__(self, api_key: str, reference_id: str, model: str = "s2-pro"):
        self.api_key = api_key
        self.reference_id = reference_id
        self.model = model

    async def synthesize(self, text: str, output_path: Path) -> Path:
        if not text or not text.strip():
            raise TTSError("Empty text")

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{FISH_API_BASE}/v1/tts",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                        "model": self.model,
                    },
                    json={
                        "text": text,
                        "reference_id": self.reference_id,
                        "format": "mp3",
                    },
                )

                if response.status_code == 401:
                    raise TTSError("Fish Audio: invalid API key")
                if response.status_code == 402:
                    raise TTSError("Fish Audio: insufficient balance")
                response.raise_for_status()

                output_path.write_bytes(response.content)

                if output_path.stat().st_size == 0:
                    raise TTSError("Fish Audio: empty response")

                return output_path

        except TTSError:
            raise
        except httpx.HTTPStatusError as e:
            raise TTSError(f"Fish Audio HTTP error: {e.response.status_code}") from e
        except Exception as e:
            raise TTSError(f"Fish Audio failed: {e}") from e

    @property
    def name(self) -> str:
        return "fish"
