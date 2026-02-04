"""Voice transcription providers supporting multiple backends."""

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import httpx
from loguru import logger


class BaseTranscriptionProvider(ABC):
    """Base class for transcription providers."""
    
    @abstractmethod
    async def transcribe(self, file_path: str | Path) -> str:
        """Transcribe an audio file.
        
        Args:
            file_path: Path to the audio file.
            
        Returns:
            Transcribed text.
        """
        pass


class GroqTranscriptionProvider(BaseTranscriptionProvider):
    """
    Voice transcription provider using Groq's Whisper API.
    
    Groq offers extremely fast transcription with a generous free tier.
    """
    
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("GROQ_API_KEY")
        self.api_url = "https://api.groq.com/openai/v1/audio/transcriptions"
    
    async def transcribe(self, file_path: str | Path) -> str:
        """Transcribe an audio file using Groq."""
        if not self.api_key:
            logger.warning("Groq API key not configured for transcription")
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
            logger.error(f"Groq transcription error: {e}")
            return ""


class GeminiTranscriptionProvider(BaseTranscriptionProvider):
    """
    Voice transcription provider using Google's Gemini API.
    
    Gemini supports audio input and can transcribe with its multimodal capabilities.
    Free tier available with generous limits.
    """
    
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self.api_url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
    
    async def transcribe(self, file_path: str | Path) -> str:
        """Transcribe an audio file using Gemini."""
        if not self.api_key:
            logger.warning("Gemini API key not configured for transcription")
            return ""
        
        path = Path(file_path)
        if not path.exists():
            logger.error(f"Audio file not found: {file_path}")
            return ""
        
        try:
            import base64
            
            # Read and encode the audio file
            with open(path, "rb") as f:
                audio_data = base64.b64encode(f.read()).decode("utf-8")
            
            # Determine MIME type
            mime_type = self._get_mime_type(path)
            
            async with httpx.AsyncClient() as client:
                payload = {
                    "contents": [{
                        "parts": [
                            {
                                "inline_data": {
                                    "mime_type": mime_type,
                                    "data": audio_data
                                }
                            },
                            {
                                "text": "Transcribe this audio. Return only the transcription text, nothing else."
                            }
                        ]
                    }]
                }
                
                response = await client.post(
                    f"{self.api_url}?key={self.api_key}",
                    json=payload,
                    timeout=60.0
                )
                
                response.raise_for_status()
                data = response.json()
                
                # Extract text from Gemini response
                candidates = data.get("candidates", [])
                if candidates:
                    content = candidates[0].get("content", {})
                    parts = content.get("parts", [])
                    if parts:
                        return parts[0].get("text", "").strip()
                
                return ""
                    
        except Exception as e:
            logger.error(f"Gemini transcription error: {e}")
            return ""
    
    def _get_mime_type(self, path: Path) -> str:
        """Get MIME type based on file extension."""
        ext = path.suffix.lower()
        mime_map = {
            ".ogg": "audio/ogg",
            ".mp3": "audio/mpeg",
            ".m4a": "audio/mp4",
            ".wav": "audio/wav",
            ".webm": "audio/webm",
            ".flac": "audio/flac",
        }
        return mime_map.get(ext, "audio/ogg")


def _create_provider(
    provider: str,
    groq_api_key: str | None = None,
    gemini_api_key: str | None = None,
) -> BaseTranscriptionProvider | None:
    """Create a single transcription provider by name."""
    provider = provider.lower()
    
    if provider == "gemini" or provider == "google":
        if gemini_api_key:
            return GeminiTranscriptionProvider(api_key=gemini_api_key)
        return None
    elif provider == "groq":
        if groq_api_key:
            return GroqTranscriptionProvider(api_key=groq_api_key)
        return None
    return None


class FallbackTranscriptionProvider(BaseTranscriptionProvider):
    """
    Transcription provider with automatic fallback.
    
    Tries the primary provider first, and if it fails or returns empty,
    automatically tries the fallback provider.
    """
    
    def __init__(
        self,
        primary: BaseTranscriptionProvider,
        fallback: BaseTranscriptionProvider | None = None,
    ):
        self.primary = primary
        self.fallback = fallback
        # Log configuration at creation time
        primary_name = type(primary).__name__
        fallback_name = type(fallback).__name__ if fallback else "None"
        logger.info(f"Transcription configured - Primary: {primary_name}, Fallback: {fallback_name}")
    
    async def transcribe(self, file_path: str | Path) -> str:
        """Transcribe with automatic fallback on failure."""
        primary_name = type(self.primary).__name__
        
        # Try primary provider
        logger.info(f"Attempting transcription with primary provider: {primary_name}")
        try:
            result = await self.primary.transcribe(file_path)
            if result:
                logger.info(f"Transcription successful with primary provider: {primary_name}")
                return result
            logger.warning(f"Primary provider {primary_name} returned empty result")
        except Exception as e:
            logger.warning(f"Primary provider {primary_name} failed: {e}")
        
        # Try fallback if available
        if self.fallback:
            fallback_name = type(self.fallback).__name__
            logger.info(f"Trying fallback provider: {fallback_name}")
            try:
                result = await self.fallback.transcribe(file_path)
                if result:
                    logger.info(f"Transcription successful with fallback provider: {fallback_name}")
                    return result
                logger.warning(f"Fallback provider {fallback_name} returned empty result")
            except Exception as e:
                logger.error(f"Fallback provider {fallback_name} also failed: {e}")
        
        return ""


def get_transcription_provider(
    provider: str = "groq",
    fallback: str | None = None,
    groq_api_key: str | None = None,
    gemini_api_key: str | None = None,
) -> BaseTranscriptionProvider:
    """
    Factory function to get a transcription provider with optional fallback.
    
    Args:
        provider: Name of the primary provider ("groq" or "gemini")
        fallback: Optional name of fallback provider to use if primary fails
        groq_api_key: API key for Groq
        gemini_api_key: API key for Gemini
        
    Returns:
        Configured transcription provider instance with fallback support
        
    Example:
        # Gemini as primary, Groq as fallback:
        provider = get_transcription_provider(
            provider="gemini",
            fallback="groq", 
            gemini_api_key="...",
            groq_api_key="..."
        )
    """
    # Create primary provider
    primary = _create_provider(provider, groq_api_key, gemini_api_key)
    
    if not primary:
        # If primary can't be created (missing API key), try fallback as primary
        logger.warning(f"Primary provider '{provider}' not available (missing API key?)")
        if fallback:
            logger.info(f"Promoting fallback '{fallback}' to primary provider")
            primary = _create_provider(fallback, groq_api_key, gemini_api_key)
        
        if not primary:
            # Last resort: return a Groq provider (may fail later if no API key)
            logger.warning("No valid transcription provider configured, defaulting to Groq")
            return FallbackTranscriptionProvider(
                primary=GroqTranscriptionProvider(api_key=groq_api_key),
                fallback=None
            )
    
    # Create fallback provider if specified
    fallback_provider = None
    if fallback and fallback.lower() != provider.lower():
        fallback_provider = _create_provider(fallback, groq_api_key, gemini_api_key)
        if not fallback_provider:
            logger.warning(f"Fallback provider '{fallback}' not available (missing API key?)")
    
    # Wrap with fallback support
    return FallbackTranscriptionProvider(primary=primary, fallback=fallback_provider)
