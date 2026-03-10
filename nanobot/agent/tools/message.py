"""Message tool for sending messages to users."""

import os
import tempfile
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

import httpx
from loguru import logger

from nanobot.agent.tools.base import Tool
from nanobot.bus.events import OutboundMessage

# Fallback extensions from Content-Type when URL path has none
_MIME_TO_EXT: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg",
    "video/mp4": ".mp4",
    "application/pdf": ".pdf",
}


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
                }
            },
            "required": ["content"]
        }

    @staticmethod
    def _is_url(path: str) -> bool:
        return path.startswith("http://") or path.startswith("https://")

    @staticmethod
    async def _download_to_temp(url: str) -> str | None:
        """Download a URL to a temporary file and return its path."""
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
                resp = await client.get(url)
                resp.raise_for_status()

            # Determine file extension
            parsed = urlparse(url)
            _, ext = os.path.splitext(parsed.path)
            if not ext or len(ext) > 6:
                ct = resp.headers.get("content-type", "").split(";")[0].strip()
                ext = _MIME_TO_EXT.get(ct, ".bin")

            fd, tmp_path = tempfile.mkstemp(suffix=ext)
            try:
                os.write(fd, resp.content)
            finally:
                os.close(fd)
            return tmp_path
        except Exception as e:
            logger.warning("Failed to download media URL {}: {}", url, e)
            return None

    async def _resolve_media(self, media: list[str]) -> list[str]:
        """Download any URLs in media list to temp files, pass local paths through."""
        resolved: list[str] = []
        for item in media:
            if self._is_url(item):
                path = await self._download_to_temp(item)
                if path:
                    resolved.append(path)
                else:
                    logger.warning("Skipping undownloadable media: {}", item)
            else:
                resolved.append(item)
        return resolved

    async def execute(
        self,
        content: str,
        channel: str | None = None,
        chat_id: str | None = None,
        message_id: str | None = None,
        media: list[str] | None = None,
        **kwargs: Any
    ) -> str:
        channel = channel or self._default_channel
        chat_id = chat_id or self._default_chat_id
        message_id = message_id or self._default_message_id

        if not channel or not chat_id:
            return "Error: No target channel/chat specified"

        if not self._send_callback:
            return "Error: Message sending not configured"

        resolved_media = await self._resolve_media(media) if media else []

        msg = OutboundMessage(
            channel=channel,
            chat_id=chat_id,
            content=content,
            media=resolved_media,
            metadata={
                "message_id": message_id,
            }
        )

        try:
            await self._send_callback(msg)
            if channel == self._default_channel and chat_id == self._default_chat_id:
                self._sent_in_turn = True
            media_info = f" with {len(resolved_media)} attachments" if resolved_media else ""
            return f"Message sent to {channel}:{chat_id}{media_info}"
        except Exception as e:
            return f"Error sending message: {str(e)}"
