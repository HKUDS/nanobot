"""Message tool for sending messages and media to users."""

import mimetypes
from pathlib import Path
from typing import Any, Callable, Awaitable

from loguru import logger

from nanobot.agent.tools.base import Tool
from nanobot.bus.events import OutboundMessage


# Supported media MIME types
SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
SUPPORTED_DOCUMENT_TYPES = {"application/pdf", "text/plain", "application/zip"}
SUPPORTED_MEDIA_TYPES = SUPPORTED_IMAGE_TYPES | SUPPORTED_DOCUMENT_TYPES

# Maximum media file size (10MB)
MAX_MEDIA_SIZE = 10 * 1024 * 1024


class MessageTool(Tool):
    """
    Tool to send messages and media to users on chat channels.

    Supports:
    - Text messages
    - Images (jpg, png, gif, webp)
    - Documents (pdf, txt, zip)

    Media files are validated for existence, type, and size before sending.
    """

    def __init__(
        self,
        send_callback: Callable[[OutboundMessage], Awaitable[None]] | None = None,
        default_channel: str = "",
        default_chat_id: str = ""
    ):
        """
        Initialize the message tool.

        Args:
            send_callback: Async function to send OutboundMessage.
            default_channel: Default channel for messages.
            default_chat_id: Default chat ID for messages.
        """
        self._send_callback = send_callback
        self._default_channel = default_channel
        self._default_chat_id = default_chat_id

    def set_context(self, channel: str, chat_id: str) -> None:
        """Set the current message context (channel and chat_id)."""
        self._default_channel = channel
        self._default_chat_id = chat_id

    def set_send_callback(self, callback: Callable[[OutboundMessage], Awaitable[None]]) -> None:
        """Set the callback for sending messages."""
        self._send_callback = callback

    @property
    def name(self) -> str:
        return "message"

    @property
    def description(self) -> str:
        return (
            "Send a message to the user, optionally with media attachments (images, documents). "
            "Use media_paths to attach files like screenshots. "
            "The content will be sent as the caption for media messages."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The message text to send. Used as caption when sending media."
                },
                "media_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional list of file paths to send as media attachments. "
                        "Supports images (jpg, png, gif) and documents (pdf, txt). "
                        "Example: [\"/path/to/screenshot.png\"]"
                    )
                },
                "channel": {
                    "type": "string",
                    "description": "Optional: target channel (telegram, whatsapp, etc.)"
                },
                "chat_id": {
                    "type": "string",
                    "description": "Optional: target chat/user ID"
                }
            },
            "required": ["content"]
        }

    async def execute(
        self,
        content: str,
        media_paths: list[str] | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
        **kwargs: Any
    ) -> str:
        """
        Send a message, optionally with media attachments.

        Args:
            content: Message text content.
            media_paths: Optional list of file paths to attach.
            channel: Target channel (uses default if not specified).
            chat_id: Target chat ID (uses default if not specified).

        Returns:
            Success or error message.
        """
        # Use defaults if not specified
        channel = channel or self._default_channel
        chat_id = chat_id or self._default_chat_id

        # Validate required fields
        if not channel or not chat_id:
            return "Error: No target channel/chat specified. Cannot send message."

        if not self._send_callback:
            return "Error: Message sending not configured. Internal error."

        # Validate and filter media paths
        validated_media: list[str] = []
        media_errors: list[str] = []

        if media_paths:
            for path_str in media_paths:
                validation_result = self._validate_media_file(path_str)
                if validation_result is None:
                    validated_media.append(path_str)
                else:
                    media_errors.append(validation_result)

        # Build outbound message
        msg = OutboundMessage(
            channel=channel,
            chat_id=chat_id,
            content=content,
            media=validated_media,
            metadata={
                "has_media": len(validated_media) > 0,
                "media_count": len(validated_media)
            }
        )

        # Send the message
        try:
            await self._send_callback(msg)

            # Build response
            result_parts = [f"Message sent to {channel}:{chat_id}"]

            if validated_media:
                result_parts.append(f"Attached {len(validated_media)} media file(s)")

            if media_errors:
                result_parts.append(f"Skipped {len(media_errors)} invalid file(s):")
                for error in media_errors:
                    result_parts.append(f"  - {error}")

            return "\n".join(result_parts)

        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            return f"Error sending message: {str(e)}"

    def _validate_media_file(self, path_str: str) -> str | None:
        """
        Validate a media file for sending.

        Args:
            path_str: Path to the file.

        Returns:
            None if valid, error message if invalid.
        """
        try:
            path = Path(path_str).expanduser().resolve()

            # Check existence
            if not path.exists():
                return f"File not found: {path_str}"

            if not path.is_file():
                return f"Not a file: {path_str}"

            # Check file size
            file_size = path.stat().st_size
            if file_size == 0:
                return f"File is empty: {path_str}"

            if file_size > MAX_MEDIA_SIZE:
                size_mb = file_size / 1024 / 1024
                return f"File too large ({size_mb:.1f}MB > 10MB): {path_str}"

            # Check MIME type
            mime_type, _ = mimetypes.guess_type(str(path))
            if mime_type is None:
                # Allow files with common image extensions even without MIME detection
                ext = path.suffix.lower()
                if ext in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
                    return None  # Accept based on extension
                return f"Unknown file type: {path_str}"

            if mime_type not in SUPPORTED_MEDIA_TYPES:
                return f"Unsupported file type ({mime_type}): {path_str}"

            return None  # Valid

        except Exception as e:
            return f"Error validating file: {str(e)}"

    @staticmethod
    def is_image(path: str) -> bool:
        """Check if a file path points to an image."""
        mime_type, _ = mimetypes.guess_type(path)
        return mime_type in SUPPORTED_IMAGE_TYPES if mime_type else False

    @staticmethod
    def is_document(path: str) -> bool:
        """Check if a file path points to a document."""
        mime_type, _ = mimetypes.guess_type(path)
        return mime_type in SUPPORTED_DOCUMENT_TYPES if mime_type else False
