"""Message tool for sending messages to users."""

from typing import Any, Awaitable, Callable

from pydantic import BaseModel, ValidationError, field_validator

from nanobot.agent.tools.base import Tool
from nanobot.bus.events import OutboundMessage


class InlineButton(BaseModel):
    """Single inline button - label is the semantic content."""
    label: str

    @field_validator('label')
    @classmethod
    def label_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError('Button label cannot be empty')
        return v.strip()


class MessageTool(Tool):
    """Tool to send messages to users on chat channels."""

    def __init__(
        self,
        send_callback: Callable[[OutboundMessage], Awaitable[None]] | None = None,
        default_channel: str = "",
        default_chat_id: str = "",
        default_message_id: str | None = None,
    ):
        self._send_callback = send_callback
        self._default_channel = default_channel
        self._default_chat_id = default_chat_id
        self._default_message_id = default_message_id
        self._sent_in_turn: bool = False

    def set_context(self, channel: str, chat_id: str, message_id: str | None = None) -> None:
        """Set the current message context."""
        self._default_channel = channel
        self._default_chat_id = chat_id
        self._default_message_id = message_id

    def set_send_callback(self, callback: Callable[[OutboundMessage], Awaitable[None]]) -> None:
        """Set the callback for sending messages."""
        self._send_callback = callback

    def start_turn(self) -> None:
        """Reset per-turn send tracking."""
        self._sent_in_turn = False

    @property
    def name(self) -> str:
        return "message"

    @property
    def description(self) -> str:
        return "Send a message to the user. Use this when you want to communicate something."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The message content to send"
                },
                "channel": {
                    "type": "string",
                    "description": "Optional: target channel (telegram, discord, etc.)"
                },
                "chat_id": {
                    "type": "string",
                    "description": "Optional: target chat/user ID"
                },
                "media": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional: list of file paths to attach (images, audio, documents)"
                },
                "buttons": {
                    "type": "array",
                    "description": "Optional: inline keyboard buttons for Telegram. List of rows, each row is list of button labels.",
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "description": "Button label text"
                        }
                    }
                }
            },
            "required": ["content"]
        }

    async def execute(
        self,
        content: str,
        channel: str | None = None,
        chat_id: str | None = None,
        message_id: str | None = None,
        media: list[str] | None = None,
        buttons: list[list[str]] | None = None,
        **kwargs: Any
    ) -> str:
        channel = channel or self._default_channel
        chat_id = chat_id or self._default_chat_id
        message_id = message_id or self._default_message_id

        if not channel or not chat_id:
            return "Error: No target channel/chat specified"

        if not self._send_callback:
            return "Error: Message sending not configured"

        # Validate buttons
        validated_buttons: list[list[str]] = []
        if buttons:
            try:
                for row_idx, row in enumerate(buttons):
                    validated_row: list[str] = []
                    for btn_idx, label in enumerate(row):
                        try:
                            validated_btn = InlineButton(label=label)
                            validated_row.append(validated_btn.label)
                        except ValidationError as e:
                            return f"Button validation error (row {row_idx}, button {btn_idx}): {e}"
                    validated_buttons.append(validated_row)
            except Exception as e:
                return f"Button structure error: {str(e)}"

        msg = OutboundMessage(
            channel=channel,
            chat_id=chat_id,
            content=content,
            media=media or [],
            metadata={
                "message_id": message_id,
            },
            buttons=validated_buttons,
        )

        try:
            await self._send_callback(msg)
            if channel == self._default_channel and chat_id == self._default_chat_id:
                self._sent_in_turn = True
            media_info = f" with {len(media)} attachments" if media else ""
            buttons_info = f" with {sum(len(r) for r in validated_buttons)} buttons" if validated_buttons else ""
            return f"Message sent to {channel}:{chat_id}{media_info}{buttons_info}"
        except Exception as e:
            return f"Error sending message: {str(e)}"
