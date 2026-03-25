"""Message tool for sending messages to users."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, ClassVar

from nanobot.bus.events import DeliveryResult, OutboundMessage
from nanobot.tools.base import Tool, ToolResult


class MessageTool(Tool):
    """Tool to send messages to users on chat channels.

    SEC-08: By default the tool is restricted to the session's channel/chat_id
    pair set via ``set_context()``.  Additional destinations can be explicitly
    whitelisted via ``allow_destination()`` so that legitimate cross-channel
    sends (e.g. email reports) are possible without opening an open relay.
    """

    def __init__(
        self,
        send_callback: Callable[[OutboundMessage], Awaitable[DeliveryResult | None]] | None = None,
        default_channel: str = "",
        default_chat_id: str = "",
        default_message_id: str | None = None,
    ):
        self._send_callback = send_callback
        self._default_channel = default_channel
        self._default_chat_id = default_chat_id
        self._default_message_id = default_message_id
        self._sent_in_turn: bool = False
        # SEC-08: explicit allowlist of (channel, chat_id) pairs the agent may
        # send to in addition to the current session context.
        self._allowed_destinations: set[tuple[str, str]] = set()

    def set_context(
        self, channel: str = "", chat_id: str = "", message_id: str | None = None, **kwargs: Any
    ) -> None:
        """Set the current message context."""
        self._default_channel = channel
        self._default_chat_id = chat_id
        self._default_message_id = message_id

    def allow_destination(self, channel: str, chat_id: str) -> None:
        """Whitelist an additional (channel, chat_id) destination (SEC-08)."""
        self._allowed_destinations.add((channel, chat_id))

    def set_send_callback(
        self, callback: Callable[[OutboundMessage], Awaitable[DeliveryResult | None]]
    ) -> None:
        """Set the callback for sending messages."""
        self._send_callback = callback

    @property
    def sent_in_turn(self) -> bool:
        """Whether a message was sent during this turn."""
        return self._sent_in_turn

    def on_turn_start(self) -> None:
        """Reset per-turn send tracking."""
        self._sent_in_turn = False

    name = "message"
    description = (
        "Send a message to a destination channel/chat. "
        "For email delivery, set channel='email' and chat_id to the recipient email address."
    )
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "The message content to send"},
            "channel": {
                "type": "string",
                "description": "Optional: target channel (telegram, discord, email, etc.)",
            },
            "chat_id": {
                "type": "string",
                "description": "Optional: target chat/user ID. For email, this would be the recipient's email address.",
            },
            "media": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional: list of file paths to attach (images, audio, documents)",
            },
        },
        "required": ["content"],
    }

    async def execute(  # type: ignore[override]
        self,
        content: str,
        channel: str | None = None,
        chat_id: str | None = None,
        message_id: str | None = None,
        media: list[str] | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        channel = channel or self._default_channel
        chat_id = chat_id or self._default_chat_id
        message_id = message_id or self._default_message_id

        if not channel or not chat_id:
            return ToolResult.fail("Error: No target channel/chat specified")

        # SEC-08: block relay to destinations outside the session context
        is_session_dest = channel == self._default_channel and chat_id == self._default_chat_id
        if not is_session_dest and (channel, chat_id) not in self._allowed_destinations:
            return ToolResult.fail(
                f"Error: Sending to {channel}:{chat_id} is not permitted. "
                "Only the current session destination is allowed by default."
            )

        if not self._send_callback:
            return ToolResult.fail("Error: Message sending not configured")

        msg = OutboundMessage(
            channel=channel,
            chat_id=chat_id,
            content=content,
            media=media or [],
            metadata={
                "message_id": message_id,
            },
        )

        try:
            result = await self._send_callback(msg)
            if isinstance(result, DeliveryResult):
                if result.success:
                    self._sent_in_turn = True
                    media_info = f" with {len(media)} attachments" if media else ""
                    return ToolResult.ok(f"Message delivered to {channel}:{chat_id}{media_info}")
                return ToolResult.fail(f"Delivery failed: {result.error}")
            # Fallback for legacy callbacks that return None (e.g. bus.publish_outbound)
            self._sent_in_turn = True
            media_info = f" with {len(media)} attachments" if media else ""
            return ToolResult.ok(f"Message sent to {channel}:{chat_id}{media_info}")
        except Exception as e:  # crash-barrier: user send callback
            return ToolResult.fail(f"Error sending message: {str(e)}")
