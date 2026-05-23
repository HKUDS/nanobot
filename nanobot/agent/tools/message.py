"""Message tool for sending messages to users."""

import time
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
        default_message_id: str | None = None,
        fs_peers: list[str] | None = None,
        fs_min_send_interval_seconds: float = 0.0,
    ):
        self._send_callback = send_callback
        self._default_channel = default_channel
        self._default_chat_id = default_chat_id
        self._default_message_id = default_message_id
        self._fs_peers = list(fs_peers or [])
        self._fs_min_send_interval_seconds = max(0.0, fs_min_send_interval_seconds)
        self._fs_last_send_at: dict[str, float] = {}
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
        base = "Send a message to the user. Use this when you want to communicate something."
        if self._fs_peers:
            peers = ", ".join(repr(p) for p in self._fs_peers)
            base += (
                f" To message a peer bot via the filesystem channel, set channel='fs' "
                f"and chat_id to one of: {peers}."
            )
        return base

    @property
    def parameters(self) -> dict[str, Any]:
        chat_id_desc = (
            "Optional: target chat/user ID. Required whenever 'channel' is explicitly set "
            "(otherwise it would default to the chat from a different channel)."
        )
        if self._fs_peers:
            chat_id_desc += f" For channel='fs', use one of: {self._fs_peers}."
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The message content to send"
                },
                "channel": {
                    "type": "string",
                    "description": "Optional: target channel (telegram, discord, fs, etc.)"
                },
                "chat_id": {
                    "type": "string",
                    "description": chat_id_desc,
                },
                "media": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional: list of file paths to attach (images, audio, documents)"
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
        **kwargs: Any
    ) -> str:
        # Reject crossed-streams routing: an explicit channel that doesn't match
        # the default must come with an explicit chat_id, or the defaulted chat_id
        # (belonging to a different channel) would be silently misrouted.
        if channel and channel != self._default_channel and not chat_id:
            return (
                f"Error: chat_id is required when channel={channel!r} is set explicitly. "
                f"Default chat_id={self._default_chat_id!r} belongs to "
                f"channel={self._default_channel!r}."
            )

        channel = channel or self._default_channel
        chat_id = chat_id or self._default_chat_id
        message_id = message_id or self._default_message_id

        if not channel or not chat_id:
            return "Error: No target channel/chat specified"

        if channel == "fs":
            if self._fs_peers and chat_id not in self._fs_peers:
                return (
                    f"Error: unknown fs peer {chat_id!r}. Known peers: {self._fs_peers}"
                )
            if self._fs_min_send_interval_seconds > 0:
                now = time.monotonic()
                last = self._fs_last_send_at.get(chat_id, 0.0)
                if last:
                    delta = now - last
                    if delta < self._fs_min_send_interval_seconds:
                        wait = self._fs_min_send_interval_seconds - delta
                        return (
                            f"Error: rate-limited fs send to {chat_id!r}; "
                            f"wait {wait:.1f}s before sending again. "
                            "Reply only when the peer asks a question, requests "
                            "action, or you have substantive new information."
                        )

        if not self._send_callback:
            return "Error: Message sending not configured"

        msg = OutboundMessage(
            channel=channel,
            chat_id=chat_id,
            content=content,
            media=media or [],
            metadata={
                "message_id": message_id,
                # Mark this as a proactive/intentional send so channels with
                # auto_reply_enabled=False (e.g. fs) still deliver it.
                "force_send": True,
            }
        )

        try:
            await self._send_callback(msg)
            if channel == self._default_channel and chat_id == self._default_chat_id:
                self._sent_in_turn = True
            if channel == "fs":
                self._fs_last_send_at[chat_id] = time.monotonic()
            media_info = f" with {len(media)} attachments" if media else ""
            preview = content[:200] + "..." if len(content) > 200 else content
            return f"Message sent to {channel}:{chat_id}{media_info}: \"{preview}\""
        except Exception as e:
            return f"Error sending message: {str(e)}"
