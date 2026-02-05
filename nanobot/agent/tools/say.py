"""Say tool for text-to-speech generation using DeepDub."""

import os
from pathlib import Path
from typing import Any, Awaitable, Callable

from nanobot.agent.tools.base import Tool
from nanobot.bus.events import OutboundMessage
from nanobot.providers.tts import DeepDubTTSProvider, OutputFormat, SUPPORTED_SAMPLE_RATES


class SayTool(Tool):
    """
    Tool to convert text to speech using DeepDub TTS.
    
    Uses a persistent WebSocket connection for efficient repeated calls.
    Can send audio directly to a channel via send_callback.
    """
    
    def __init__(
        self,
        api_key: str | None = None,
        voice_prompt_id: str | None = None,
        model: str = "dd-etts-3.0",
        locale: str = "en-US",
        output_dir: str | None = None,
        send_callback: Callable[[OutboundMessage], Awaitable[None]] | None = None,
    ):
        """
        Initialize the say tool.
        
        Args:
            api_key: DeepDub API key (falls back to DEEPDUB_API_KEY env var).
            voice_prompt_id: Default voice prompt ID to use.
            model: TTS model (default: dd-etts-3.0).
            locale: Default locale (default: en-US).
            output_dir: Directory to save audio files. Defaults to workspace/audio.
            send_callback: Async callback to send OutboundMessage (for direct audio sending).
        """
        self._api_key = api_key
        self._voice_prompt_id = voice_prompt_id
        self._model = model
        self._locale = locale
        self._output_dir = output_dir
        self._provider: DeepDubTTSProvider | None = None
        self._send_callback = send_callback
        
        # Context for sending audio
        self._channel: str | None = None
        self._chat_id: str | None = None
    
    def set_context(self, channel: str, chat_id: str) -> None:
        """
        Set the current channel and chat context for audio sending.
        
        Args:
            channel: The channel name (e.g., 'telegram').
            chat_id: The chat ID to send audio to.
        """
        self._channel = channel
        self._chat_id = chat_id
    
    def _get_provider(self) -> DeepDubTTSProvider:
        """Get or create the TTS provider (lazy initialization)."""
        if self._provider is None:
            self._provider = DeepDubTTSProvider(
                api_key=self._api_key,
                voice_prompt_id=self._voice_prompt_id,
                model=self._model,
                locale=self._locale,
            )
        return self._provider
    
    def set_config(
        self,
        api_key: str | None = None,
        voice_prompt_id: str | None = None,
        model: str | None = None,
        locale: str | None = None,
        output_dir: str | None = None,
    ) -> None:
        """Update configuration. Resets the provider if key settings change."""
        reset_provider = False
        
        if api_key is not None and api_key != self._api_key:
            self._api_key = api_key
            reset_provider = True
        if voice_prompt_id is not None:
            self._voice_prompt_id = voice_prompt_id
        if model is not None and model != self._model:
            self._model = model
            reset_provider = True
        if locale is not None:
            self._locale = locale
        if output_dir is not None:
            self._output_dir = output_dir
        
        if reset_provider and self._provider is not None:
            # Close existing provider and create new one on next call
            import asyncio
            try:
                asyncio.get_event_loop().run_until_complete(self._provider.close())
            except Exception:
                pass
            self._provider = None
    
    @property
    def name(self) -> str:
        return "say"
    
    @property
    def description(self) -> str:
        return (
            "Convert text to speech audio. Generates high-quality speech using DeepDub TTS. "
            "Returns the path to the saved audio file."
        )
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The text to convert to speech"
                },
                "filename": {
                    "type": "string",
                    "description": (
                        "Output filename (e.g., 'greeting.mp3'). Extension determines format. "
                        "Supported: .mp3, .opus. If not provided, uses auto-generated name."
                    )
                },
                "voice_prompt_id": {
                    "type": "string",
                    "description": "Voice prompt ID (overrides default)"
                },
                "locale": {
                    "type": "string",
                    "description": "Locale for speech (e.g., 'en-US', 'es-ES'). Default: en-US"
                },
                "sample_rate": {
                    "type": "integer",
                    "description": f"Sample rate in Hz. Options: {SUPPORTED_SAMPLE_RATES}. Default: 48000 (8000 for mulaw)",
                    "enum": SUPPORTED_SAMPLE_RATES
                },
                "send_to_channel": {
                    "type": "boolean",
                    "description": "If true, send the audio directly to the current chat channel. Default: true"
                }
            },
            "required": ["text"]
        }
    
    async def execute(
        self,
        text: str,
        filename: str | None = None,
        voice_prompt_id: str | None = None,
        locale: str | None = None,
        sample_rate: int | None = None,
        send_to_channel: bool = True,
        **kwargs: Any
    ) -> str:
        """
        Execute text-to-speech conversion.
        
        Args:
            text: Text to convert to speech.
            filename: Output filename (auto-generated if not provided).
            voice_prompt_id: Voice prompt ID (overrides default).
            locale: Locale for speech (overrides default).
            sample_rate: Sample rate in Hz. Default: 48000 (8000 for mulaw).
            send_to_channel: If True, send audio directly to the channel. Default: True.
        
        Returns:
            Path to the saved audio file or error message.
        """
        # Check API key
        api_key = self._api_key or os.environ.get("DEEPDUB_API_KEY")
        if not api_key:
            return "Error: DeepDub API key not configured. Set DEEPDUB_API_KEY or configure in settings."
        
        # Check voice prompt
        voice_id = voice_prompt_id or self._voice_prompt_id
        if not voice_id:
            return "Error: No voice_prompt_id provided. Please specify a voice."
        
        # Determine output format from filename
        output_format = OutputFormat.MP3
        if filename:
            ext = Path(filename).suffix.lower()
            format_map = {
                ".mp3": OutputFormat.MP3,
                ".opus": OutputFormat.OPUS,
                ".ogg": OutputFormat.OPUS,  # Use opus for ogg container
            }
            if ext in format_map:
                output_format = format_map[ext]
            elif ext:
                return f"Error: Unsupported format '{ext}'. Use .mp3 or .opus"
        
        # Determine output path
        output_dir = Path(self._output_dir) if self._output_dir else Path.cwd() / "audio"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        if filename:
            output_path = output_dir / filename
        else:
            # Auto-generate filename
            import hashlib
            import time
            text_hash = hashlib.md5(text.encode()).hexdigest()[:8]
            timestamp = int(time.time())
            output_path = output_dir / f"tts_{timestamp}_{text_hash}.{output_format.value}"
        
        try:
            provider = self._get_provider()
            
            # Determine actual sample rate (default: 8000 for mulaw, 48000 otherwise)
            actual_sample_rate = sample_rate
            if actual_sample_rate is None:
                actual_sample_rate = 8000 if output_format == OutputFormat.MULAW else 48000
            
            # Generate speech - returns bytes directly
            import asyncio
            try:
                audio_bytes = await asyncio.wait_for(
                    provider.say(
                        text=text,
                        voice_prompt_id=voice_id,
                        locale=locale or self._locale,
                        output_format=output_format,
                        sample_rate=sample_rate,
                    ),
                    timeout=8.0
                )
            except asyncio.TimeoutError:
                return "Error: TTS request timed out after 8 seconds."
            
            # Save audio bytes to file
            with open(output_path, "wb") as f:
                f.write(audio_bytes)
            
            # Send audio to channel if requested
            if send_to_channel and self._send_callback and self._channel and self._chat_id:
                await self._send_callback(OutboundMessage(
                    channel=self._channel,
                    chat_id=self._chat_id,
                    content="",  # No text content, just audio
                    media=[str(output_path)]
                ))
                return (
                    f"Audio generated and sent to channel.\n"
                    f"File: {output_path}\n"
                    f"Format: {output_format.value}\n"
                    f"Sample rate: {actual_sample_rate}Hz\n"
                    f"Size: {len(audio_bytes)} bytes"
                )
            
            # Return success with file info
            return (
                f"Audio saved to: {output_path}\n"
                f"Format: {output_format.value}\n"
                f"Sample rate: {actual_sample_rate}Hz\n"
                f"Size: {len(audio_bytes)} bytes"
            )
            
        except ValueError as e:
            return f"Error: {e}"
        except ConnectionError as e:
            return f"Connection error: {e}"
        except Exception as e:
            return f"TTS error: {e}"
    
    async def close(self) -> None:
        """Close the TTS provider connection."""
        if self._provider is not None:
            await self._provider.close()
            self._provider = None
