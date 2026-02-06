"""Text-to-speech provider using multiple backends."""

import asyncio
import os
from pathlib import Path
from typing import Literal

import httpx
from loguru import logger


class TTSProvider:
    """
    Text-to-speech provider supporting multiple backends.

    Supports: OpenAI (tts-1, tts-1-hd)
    """

    # OpenAI TTS limits
    DEFAULT_MAX_TEXT_LENGTH = 4000
    DEFAULT_TIMEOUT = 60.0
    DEFAULT_MODEL = "tts-1"

    def __init__(
        self,
        provider: Literal["openai"] = "openai",
        api_key: str | None = None,
        voice: str | None = None,
        model: str | None = None,
        max_text_length: int | None = None,
        timeout: float | None = None,
    ):
        """
        Initialize the TTS provider.

        Args:
            provider: TTS provider name ("openai").
            api_key: API key for the provider (overrides env var).
            voice: Voice ID to use.
            model: TTS model to use (e.g., "tts-1", "tts-1-hd").
            max_text_length: Maximum characters to synthesize (truncates if longer).
            timeout: HTTP request timeout in seconds.
        """
        self.provider = provider.lower()
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.voice = voice or self._default_voice(provider)
        self.model = model or self.DEFAULT_MODEL
        self.max_text_length = max_text_length or self.DEFAULT_MAX_TEXT_LENGTH
        self.timeout = timeout or self.DEFAULT_TIMEOUT

    def _default_voice(self, provider: str) -> str:
        """Get default voice for provider."""
        return {
            "openai": "alloy",
        }.get(provider.lower(), "alloy")

    async def synthesize(self, text: str, output_path: str | Path) -> tuple[bool, str | None]:
        """
        Convert text to speech.

        Args:
            text: Text to synthesize.
            output_path: Where to save the audio file.

        Returns:
            Tuple of (success, warning_message).
            Warning message is set if text was truncated.
        """
        if self.provider == "openai":
            return await self._synthesize_openai(text, output_path)
        else:
            logger.error(f"Unknown TTS provider: {self.provider}")
            return False, None

    async def _synthesize_openai(self, text: str, output_path: Path) -> tuple[bool, str | None]:
        """
        Synthesize using OpenAI's TTS API.

        Args:
            text: Text to synthesize.
            output_path: Where to save the audio file.

        Returns:
            Tuple of (success, warning_message).
        """
        if not self.api_key:
            logger.error("OpenAI API key not configured for TTS")
            return False, None

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Check text length and warn if truncating
        warning = None
        original_length = len(text)
        if original_length > self.max_text_length:
            truncated_chars = original_length - self.max_text_length
            warning = f"Text truncated by {truncated_chars} characters ({original_length} -> {self.max_text_length})"
            logger.warning(f"TTS: {warning}")
            text = text[:self.max_text_length]

        text_preview = text[:100] + "..." if len(text) > 100 else text

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    "https://api.openai.com/v1/audio/speech",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": self.model,
                        "input": text,
                        "voice": self.voice,
                    },
                )
                response.raise_for_status()

                # Write audio file asynchronously (non-blocking)
                await asyncio.to_thread(output_path.write_bytes, response.content)

                logger.info(
                    f"TTS audio saved to {output_path} ({len(text)} chars, "
                    f"model={self.model}, voice={self.voice})"
                )
                return True, warning

        except httpx.HTTPStatusError as e:
            logger.error(
                f"OpenAI TTS HTTP error: {e.response.status_code} - "
                f"{e.response.text[:200]} (text: {text_preview})"
            )
            return False, None
        except httpx.TimeoutException:
            logger.error(
                f"OpenAI TTS timeout after {self.timeout}s (text: {text_preview})"
            )
            return False, None
        except Exception as e:
            logger.error(
                f"OpenAI TTS error: {e} (text: {text_preview})"
            )
            return False, None

    def is_enabled(self) -> bool:
        """Check if TTS is properly configured."""
        return bool(self.api_key)

    def get_available_voices(self) -> list[str]:
        """Get list of available voices for the current provider."""
        return {
            "openai": ["alloy", "echo", "fable", "onyx", "nova", "shimmer"],
        }.get(self.provider.lower(), [])

    def get_available_models(self) -> list[str]:
        """Get list of available models for the current provider."""
        return {
            "openai": ["tts-1", "tts-1-hd"],
        }.get(self.provider.lower(), [])
