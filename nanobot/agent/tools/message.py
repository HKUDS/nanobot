"""Message tool for sending messages to users."""

from typing import Any, Callable, Awaitable

from nanobot.agent.tools.base import Tool
from nanobot.bus.events import OutboundMessage


class MessageTool(Tool):
    """Tool to send messages to users on chat channels."""
    
    def __init__(
        self, 
        send_callback: Callable[[OutboundMessage], Awaitable[None]] | None = None,
        default_channel: str = "",
        default_chat_id: str = ""
    ):
        self._send_callback = send_callback
        self._default_channel = default_channel
        self._default_chat_id = default_chat_id
    
    def set_context(self, channel: str, chat_id: str) -> None:
        """Set the current message context."""
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
        return "Send a message to the user with optional media attachments. Use this when you want to communicate something."
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The message content to send"
                },
                "media_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of file paths to attach (images, documents)"
                },
                "channel": {
                    "type": "string",
                    "description": "Optional: target channel (telegram, discord, etc.)"
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
        channel = channel or self._default_channel
        chat_id = chat_id or self._default_chat_id
        
        if not channel or not chat_id:
            return "Error: No target channel/chat specified"
        
        if not self._send_callback:
            return "Error: Message sending not configured"
        
        # Validate media paths
        media_files = []
        if media_paths:
            for path in media_paths:
                if len(path) > 500:
                    return f"Error: Media path too long: {path[:50]}..."
                if not os.path.exists(path):
                    return f"Error: Media file not found: {path}"
                media_files.append(path)
        
        msg = OutboundMessage(
            channel=channel,
            chat_id=chat_id,
            content=content,
            media=media_files
        )
        
        try:
            await self._send_callback(msg)
            media_count = len(media_files) if media_files else 0
            return f"Message sent to {channel}:{chat_id}" + (f" with {media_count} media files" if media_count else "")
        except Exception as e:
            return f"Error sending message: {str(e)}"
