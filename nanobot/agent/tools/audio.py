"""Audio generation tool using ElevenLabs TTS."""

from typing import Any, Callable, Awaitable

from loguru import logger

from nanobot.agent.tools.base import Tool
from nanobot.bus.events import OutboundMessage


class AudioGeneratorTool(Tool):
    """
    Tool to generate audio from text using ElevenLabs TTS.

    The generated audio can be sent as a voice message to users.
    """

    def __init__(
        self,
        api_key: str = "",
        voice_id: str = "",
        send_callback: Callable[[OutboundMessage], Awaitable[None]] | None = None,
        default_channel: str = "",
        default_chat_id: str = "",
    ):
        self._api_key = api_key
        self._voice_id = voice_id
        self._send_callback = send_callback
        self._default_channel = default_channel
        self._default_chat_id = default_chat_id
        self._provider = None

    def _get_provider(self):
        """Lazy initialization of ElevenLabs provider."""
        if self._provider is None:
            from nanobot.providers.elevenlabs import ElevenLabsProvider
            self._provider = ElevenLabsProvider(
                api_key=self._api_key,
                voice_id=self._voice_id if self._voice_id else None,
            )
        return self._provider

    def set_context(self, channel: str, chat_id: str) -> None:
        """Set the current message context."""
        self._default_channel = channel
        self._default_chat_id = chat_id

    def set_send_callback(self, callback: Callable[[OutboundMessage], Awaitable[None]]) -> None:
        """Set the callback for sending messages."""
        self._send_callback = callback

    @property
    def name(self) -> str:
        return "generate_audio"

    @property
    def description(self) -> str:
        return (
            "Generate audio speech from text using ElevenLabs TTS. "
            "Use this to send voice messages or create audio content. "
            "The generated audio will be sent as a voice message to the user."
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
                "send_to_user": {
                    "type": "boolean",
                    "description": "Whether to send the audio as a voice message (default: true)"
                },
            },
            "required": ["text"]
        }

    async def execute(
        self,
        text: str,
        send_to_user: bool = True,
        **kwargs: Any
    ) -> str:
        if not text.strip():
            return "Error: No text provided for audio generation"

        provider = self._get_provider()
        if not provider.api_key:
            return "Error: ElevenLabs API key not configured"

        try:
            # Generate audio
            audio_path = await provider.text_to_speech(
                text=text,
                output_format="mp3_44100_128",  # Good quality MP3
            )

            if not audio_path:
                return "Error: Failed to generate audio"

            # Send as voice message if requested
            if send_to_user and self._send_callback:
                channel = self._default_channel
                chat_id = self._default_chat_id

                if channel and chat_id:
                    msg = OutboundMessage(
                        channel=channel,
                        chat_id=chat_id,
                        content="",  # Audio message, no text
                        media=[str(audio_path)]
                    )
                    await self._send_callback(msg)
                    return f"Audio generated and sent as voice message: {audio_path}"

            return f"Audio generated: {audio_path}"

        except Exception as e:
            logger.error(f"Audio generation failed: {e}")
            return f"Error generating audio: {str(e)}"
