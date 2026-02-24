"""Message tool for sending messages to users."""

from pathlib import Path
from typing import Any, Awaitable, Callable

from nanobot.agent.tools.base import Tool
from nanobot.bus.events import OutboundMessage


class MessageTool(Tool):
    """Tool to send messages to users on chat channels."""

    def __init__(
        self,
        send_callback: Callable[[OutboundMessage], Awaitable[None]] | None = None,
        default_channel: str = "",
        default_chat_id: str = "",
        default_metadata: dict[str, Any] | None = None,
        default_message_id: str | int | None = None,
    ):
        self._send_callback = send_callback
        self._default_channel = default_channel
        self._default_chat_id = default_chat_id
        self._default_metadata: dict[str, Any] = default_metadata or {}
        self._default_message_id = default_message_id
        self._sent_in_turn: bool = False

    def set_context(
        self,
        channel: str,
        chat_id: str,
        context: dict[str, Any] | str | int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Set the current message context.

        Compatible with both call patterns:
        - set_context(channel, chat_id, message_id)
        - set_context(channel, chat_id, metadata_dict)
        """
        self._default_channel = channel
        self._default_chat_id = chat_id

        merged_metadata: dict[str, Any] = {}
        message_id: str | int | None = None

        if isinstance(context, dict):
            merged_metadata.update(context)
            message_id = context.get("message_id")
        else:
            message_id = context

        if metadata:
            merged_metadata.update(metadata)
            if message_id is None:
                message_id = metadata.get("message_id")

        self._default_metadata = merged_metadata
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
        return (
            "Send a message to the user. Use this when you want to communicate something. "
            "You can optionally attach images by providing local file paths in the media parameter. "
            "For Telegram, you can also send a sticker with sticker_id. "
            "For Telegram, you can also add a reaction emoji to a message with reaction and message_id."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The message content to send",
                },
                "channel": {
                    "type": "string",
                    "description": "Optional: target channel (telegram, discord, etc.)",
                },
                "chat_id": {
                    "type": "string",
                    "description": "Optional: target chat/user ID",
                },
                "media": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional: list of file paths to attach (images, audio, documents)",
                },
                "sticker_id": {
                    "type": "string",
                    "description": "Optional: Telegram sticker file_id to send",
                },
                "reaction": {
                    "type": "string",
                    "description": (
                        "Optional: emoji reaction to add to a message "
                        "(only support: '👍', '❤️', '🔥', '🤬'， '👎', '🥰', '👏'). Requires message_id."
                    ),
                },
                "message_id": {
                    "type": "integer",
                    "description": "Optional: target message ID for reaction",
                },
            },
            "required": [],
        }

    async def execute(
        self,
        content: str = "",
        channel: str | None = None,
        chat_id: str | None = None,
        message_id: str | int | None = None,
        media: list[str] | None = None,
        sticker_id: str | None = None,
        reaction: str | None = None,
        **kwargs: Any,
    ) -> str:
        channel = channel or self._default_channel
        chat_id = chat_id or self._default_chat_id
        text = content or ""
        sticker_id = (sticker_id or "").strip() or None
        reaction = (reaction or "").strip() or None

        resolved_message_id = message_id if message_id is not None else self._default_message_id

        if not channel or not chat_id:
            return "Error: No target channel/chat specified"

        if not self._send_callback:
            return "Error: Message sending not configured"

        if not text and not media and not sticker_id and not reaction:
            return "Error: Provide at least one of content, media, sticker_id, or reaction"

        if sticker_id and channel != "telegram":
            return "Error: sticker_id is only supported on telegram channel"

        if reaction and not resolved_message_id:
            return "Error: reaction requires message_id"

        if reaction and channel != "telegram":
            return "Error: reaction is only supported on telegram channel"

        reaction_target_id: int | None = None
        if reaction and resolved_message_id is not None:
            try:
                reaction_target_id = int(resolved_message_id)
            except (TypeError, ValueError):
                return "Error: message_id must be an integer for reaction"

        resolved_media = [str(Path(p).expanduser()) for p in media] if media else []

        metadata = dict(self._default_metadata)
        if resolved_message_id is not None:
            metadata["message_id"] = resolved_message_id
        if reaction:
            # Keep metadata keys for backward compatibility with existing channel handlers.
            metadata["reaction"] = reaction
            metadata["reaction_message_id"] = reaction_target_id

        msg = OutboundMessage(
            channel=channel,
            chat_id=chat_id,
            content=text,
            media=resolved_media,
            sticker_id=sticker_id,
            reaction=reaction,
            reaction_message_id=reaction_target_id,
            metadata=metadata,
        )

        try:
            await self._send_callback(msg)
            self._sent_in_turn = True
            parts = [f"Message delivered to {channel}:{chat_id}"]
            if reaction:
                parts.append(f" with reaction {reaction} on message {reaction_target_id}")
            if sticker_id:
                parts.append(" with 1 sticker")
            if resolved_media:
                parts.append(f" with {len(resolved_media)} attachment(s)")
            return "".join(parts)
        except Exception as e:
            return f"Error sending message: {str(e)}"
