"""Text-to-speech provider using multiple backends."""

import os
from pathlib import Path

import httpx
from loguru import logger


class TTSProvider:
    """
    Text-to-speech provider supporting multiple backends.

    Supports: OpenAI (tts-1, tts-1-hd)
    """

    def __init__(
        self,
        provider: str = "openai",
        api_key: str | None = None,
        voice: str | None = None,
    ):
        """
        Initialize the TTS provider.

        Args:
            provider: TTS provider name ("openai").
            api_key: API key for the provider (overrides env var).
            voice: Voice ID to use.
        """
        self.provider = provider.lower()
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.voice = voice or self._default_voice(provider)

    def _default_voice(self, provider: str) -> str:
        """Get default voice for provider."""
        return {
            "openai": "alloy",
        }.get(provider.lower(), "alloy")

    async def synthesize(self, text: str, output_path: str | Path) -> bool:
        """
        Convert text to speech.

        Args:
            text: Text to synthesize.
            output_path: Where to save the audio file.

        Returns:
            True if successful, False otherwise.
        """
        if self.provider == "openai":
            return await self._synthesize_openai(text, output_path)
        else:
            logger.error(f"Unknown TTS provider: {self.provider}")
            return False

    async def _synthesize_openai(self, text: str, output_path: Path) -> bool:
        """
        Synthesize using OpenAI's TTS API.

        Uses the tts-1 model for fast, low-latency synthesis.
        """
        if not self.api_key:
            logger.error("OpenAI API key not configured for TTS")
            return False

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Truncate text if too long (OpenAI limit is ~4000 characters)
        if len(text) > 4000:
            logger.warning(f"Text too long ({len(text)} chars), truncating to 4000")
            text = text[:4000]

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    "https://api.openai.com/v1/audio/speech",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": "tts-1",
                        "input": text,
                        "voice": self.voice,
                    },
                )
                response.raise_for_status()

                # Write audio file
                with open(output_path, "wb") as f:
                    f.write(response.content)

                logger.info(f"TTS audio saved to {output_path} ({len(text)} chars)")
                return True

        except httpx.HTTPStatusError as e:
            logger.error(f"OpenAI TTS HTTP error: {e.response.status_code} - {e.response.text}")
            return False
        except Exception as e:
            logger.error(f"OpenAI TTS error: {e}")
            return False

    def is_enabled(self) -> bool:
        """Check if TTS is properly configured."""
        return bool(self.api_key)

    def get_available_voices(self) -> list[str]:
        """Get list of available voices for the current provider."""
        return {
            "openai": ["alloy", "echo", "fable", "onyx", "nova", "shimmer"],
        }.get(self.provider.lower(), [])
