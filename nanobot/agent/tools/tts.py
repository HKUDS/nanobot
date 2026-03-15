"""Text-to-speech tool — converts text to audio and sends as a voice message."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from nanobot.agent.tools.base import Tool
from nanobot.bus.events import OutboundMessage


class TTSTool(Tool):
    """
    Converts text to speech using Groq PlayAI and sends the audio to the user.

    The agent calls speak(text) and the user receives an MP3 voice message on
    whichever channel they are on (Telegram, Discord, etc.).
    """

    def __init__(
        self,
        groq_api_key: str,
        send_callback: Callable[[OutboundMessage], Awaitable[None]] | None = None,
        default_channel: str = "",
        default_chat_id: str = "",
        message_tool: Any = None,
    ):
        self._groq_api_key = groq_api_key
        self._send_callback = send_callback
        self._default_channel = default_channel
        self._default_chat_id = default_chat_id
        self._message_tool = message_tool

    def set_context(self, channel: str, chat_id: str) -> None:
        """Set the current message routing context (called on each incoming message)."""
        self._default_channel = channel
        self._default_chat_id = chat_id

    def set_message_tool(self, message_tool: Any) -> None:
        """Link to MessageTool so a successful voice send marks the turn as delivered."""
        self._message_tool = message_tool

    def set_send_callback(self, callback: Callable[[OutboundMessage], Awaitable[None]]) -> None:
        self._send_callback = callback

    @property
    def name(self) -> str:
        return "speak"

    @property
    def description(self) -> str:
        return (
            "Convert text to speech and send it as a voice audio message to the user. "
            "Use this when the user asks you to 'speak', 'say', or 'read aloud' something, "
            "or when a voice reply feels more natural than text."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The text to convert to speech and send as audio.",
                },
                "voice": {
                    "type": "string",
                    "description": (
                        "Optional Orpheus voice name. "
                        "Options: tara, leah, jess, leo, dan, mia, zac, zoe. "
                        "Defaults to tara."
                    ),
                },
            },
            "required": ["text"],
        }

    async def execute(
        self,
        text: str,
        voice: str = "tara",
        **kwargs: Any,
    ) -> str:
        if not self._groq_api_key:
            return "Error: Groq API key not configured for TTS"

        if not self._send_callback or not self._default_channel or not self._default_chat_id:
            return "Error: No message routing context set — cannot send voice message"

        from nanobot.providers.tts import GroqTTSProvider

        provider = GroqTTSProvider(api_key=self._groq_api_key)
        file_path = await provider.synthesize(text, voice=voice)

        if not file_path:
            return "Error: TTS generation failed — falling back to text"

        msg = OutboundMessage(
            channel=self._default_channel,
            chat_id=self._default_chat_id,
            content="",
            media=[str(file_path)],
        )

        try:
            await self._send_callback(msg)
            # Mark the turn as delivered so the agent loop suppresses fallback text
            if self._message_tool is not None:
                self._message_tool._sent_in_turn = True
            return f"Voice message sent ({len(text)} chars, voice={voice})"
        except Exception as e:
            return f"Error sending voice message: {e}"
