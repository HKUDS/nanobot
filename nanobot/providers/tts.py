"""Text-to-Speech provider using DeepDub's WebSocket API."""

import asyncio
import os
from enum import Enum
from typing import Any

from audiosample import AudioSample
from deepdub import DeepdubClient
from loguru import logger


class OutputFormat(Enum):
    """Supported audio output formats."""
    WAV = "wav"      # Uncompressed, best quality
    MP3 = "mp3"      # Compressed, widely compatible
    OGG = "ogg"      # Open format, good compression
    OPUS = "opus"    # Low latency, good for streaming


# Supported sample rates (Hz)
SUPPORTED_SAMPLE_RATES = [8000, 16000, 22050, 24000, 32000, 44100, 48000]


class DeepDubTTSProvider:
    """
    Text-to-Speech provider using DeepDub's WebSocket API.
    
    Features:
    - Persistent WebSocket connection (lazy initialization)
    - Auto-reconnect with exponential backoff on errors
    - Thread-safe connection management
    - Returns AudioSample for flexible format conversion
    
    Usage:
        tts = DeepDubTTSProvider(api_key="...", voice_prompt_id="...")
        audio = await tts.say("Hello world")
        audio.write("output.mp3")
        await tts.close()
    """
    
    def __init__(
        self,
        api_key: str | None = None,
        voice_prompt_id: str | None = None,
        model: str = "dd-etts-3.0",
        locale: str = "en-US",
    ):
        """
        Initialize the TTS provider.
        
        Args:
            api_key: DeepDub API key. Falls back to DEEPDUB_API_KEY env var.
            voice_prompt_id: Default voice prompt ID to use.
            model: TTS model to use. Default is "dd-etts-3.0".
            locale: Default locale for speech. Default is "en-US".
        """
        self.api_key = api_key or os.environ.get("DEEPDUB_API_KEY")
        self.voice_prompt_id = voice_prompt_id
        self.model = model
        self.locale = locale
        
        # Initialize the DeepDub client
        self.client = DeepdubClient(api_key=self.api_key)
        
        # Connection state
        self._connection: Any | None = None
        self._lock = asyncio.Lock()
        self._connected = False
        
        # Reconnection settings
        self._max_retries = 5
        self._base_delay = 1.0  # seconds
        self._max_delay = 30.0  # seconds
    
    async def _ensure_connected(self) -> Any:
        """
        Ensure we have an active WebSocket connection.
        
        Lazily connects on first call and reconnects on error with
        exponential backoff.
        
        Returns:
            The active async connection.
        """
        async with self._lock:
            if self._connection is not None and self._connected:
                return self._connection
            
            # Need to connect or reconnect
            retries = 0
            delay = self._base_delay
            
            while retries < self._max_retries:
                try:
                    logger.debug(f"Connecting to DeepDub WebSocket (attempt {retries + 1})")
                    self._connection = await self.client.async_connect().__aenter__()
                    self._connected = True
                    logger.info("Connected to DeepDub WebSocket")
                    return self._connection
                except Exception as e:
                    retries += 1
                    if retries >= self._max_retries:
                        logger.error(f"Failed to connect to DeepDub after {self._max_retries} attempts: {e}")
                        raise ConnectionError(f"Failed to connect to DeepDub: {e}") from e
                    
                    logger.warning(f"Connection attempt {retries} failed: {e}. Retrying in {delay}s...")
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, self._max_delay)  # Exponential backoff
            
            raise ConnectionError("Failed to connect to DeepDub")
    
    async def _reconnect(self) -> Any:
        """Force a reconnection, used when the connection is lost during a request."""
        async with self._lock:
            self._connected = False
            if self._connection is not None:
                try:
                    await self._connection.__aexit__(None, None, None)
                except Exception:
                    pass  # Ignore errors when closing broken connection
                self._connection = None
        
        return await self._ensure_connected()
    
    async def say(
        self,
        text: str,
        voice_prompt_id: str | None = None,
        model: str | None = None,
        locale: str | None = None,
        output_format: OutputFormat = OutputFormat.WAV,
        sample_rate: int = 48000,
    ) -> AudioSample:
        """
        Convert text to speech.
        
        Args:
            text: The text to convert to speech.
            voice_prompt_id: Voice prompt ID (overrides default).
            model: TTS model (overrides default).
            locale: Locale for speech (overrides default).
            output_format: Desired output format (wav, mp3, ogg, opus).
            sample_rate: Sample rate in Hz (8000-48000).
        
        Returns:
            AudioSample object that can be written to file or converted to bytes.
        
        Raises:
            ValueError: If required parameters are missing or invalid.
            ConnectionError: If unable to connect to DeepDub.
        """
        if not self.api_key:
            raise ValueError("DeepDub API key not configured")
        
        # Use provided values or fall back to defaults
        voice_id = voice_prompt_id or self.voice_prompt_id
        if not voice_id:
            raise ValueError("voice_prompt_id is required")
        
        use_model = model or self.model
        use_locale = locale or self.locale
        
        # Validate sample rate
        if sample_rate not in SUPPORTED_SAMPLE_RATES:
            raise ValueError(f"Sample rate must be one of {SUPPORTED_SAMPLE_RATES}")
        
        # Map output format to DeepDub format parameter
        format_map = {
            OutputFormat.WAV: None,  # Default, raw PCM
            OutputFormat.MP3: "mp3",
            OutputFormat.OGG: "opus",  # DeepDub uses opus for ogg
            OutputFormat.OPUS: "opus",
            OutputFormat.MULAW: "mulaw",
            OutputFormat.PCM: "s16le",
        }
        dd_format = format_map.get(output_format)
        
        # Try to use existing connection, reconnect on failure
        max_attempts = 2  # Try once, reconnect and try again if needed
        last_error = None
        
        for attempt in range(max_attempts):
            try:
                conn = await self._ensure_connected()
                
                # Build the request
                audio_chunks: list[AudioSample] = []
                
                # Use the async streaming TTS
                async for chunk in conn.async_tts(
                    text=text,
                    voicePromptId=voice_id,
                    model=use_model,
                    locale=use_locale,
                    format=dd_format,
                    sampleRate=sample_rate if dd_format else None,
                    realtime=True,
                ):
                    if chunk:
                        audio_chunks.append(chunk)
                
                # Combine all chunks into a single AudioSample
                if not audio_chunks:
                    raise RuntimeError("No audio data received from DeepDub")
                
                result = audio_chunks[0]
                for chunk in audio_chunks[1:]:
                    result += chunk
                
                logger.debug(f"TTS completed: {len(text)} chars -> {len(result)} samples")
                return result
                
            except (ConnectionError, OSError) as e:
                last_error = e
                if attempt < max_attempts - 1:
                    logger.warning(f"Connection error during TTS, reconnecting: {e}")
                    await self._reconnect()
                else:
                    raise
            except Exception as e:
                # For other errors, don't retry
                logger.error(f"TTS error: {e}")
                raise
        
        raise last_error or RuntimeError("TTS failed")
    
    async def close(self) -> None:
        """Close the WebSocket connection gracefully."""
        async with self._lock:
            if self._connection is not None:
                try:
                    await self._connection.__aexit__(None, None, None)
                    logger.info("Disconnected from DeepDub WebSocket")
                except Exception as e:
                    logger.warning(f"Error closing DeepDub connection: {e}")
                finally:
                    self._connection = None
                    self._connected = False
    
    async def __aenter__(self) -> "DeepDubTTSProvider":
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit - closes connection."""
        await self.close()
