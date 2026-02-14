"""Message tool for sending messages to users."""

from pathlib import Path
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
        return (
            "Send a message to the user. Use this when you want to communicate something. "
            "You can also send images and files by providing the file_path."
        )
    
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
                    "description": "Optional: target channel (telegram, discord, feishu, etc.)"
                },
                "chat_id": {
                    "type": "string",
                    "description": "Optional: target chat/user ID"
                },
                "file_path": {
                    "type": "string",
                    "description": "Optional: path to a file or image to send. Supports images (.png, .jpg, .jpeg, .gif) and files."
                },
                "file_type": {
                    "type": "string",
                    "description": "Optional: type of file to send. 'image' for images, 'file' for other files. Auto-detected if not specified.",
                    "enum": ["image", "file"]
                }
            },
            "required": ["content"]
        }
    
    async def execute(
        self,
        content: str = "",
        channel: str | None = None,
        chat_id: str | None = None,
        file_path: str | None = None,
        file_type: str | None = None,
        **kwargs: Any
    ) -> str:
        from loguru import logger
        logger.debug(f"MessageTool.execute: content={content[:30] if content else 'EMPTY'}, file_path={file_path}, kwargs={kwargs}")

        # Handle camelCase parameters from some LLMs
        if not file_path:
            file_path = kwargs.pop("filePath", None) or kwargs.pop("filepath", None)
        if not file_type:
            file_type = kwargs.pop("fileType", None) or kwargs.pop("filetype", None)

        # Validate required parameter
        if not content:
            return "Error: 'content' parameter is required"

        channel = channel or self._default_channel
        chat_id = chat_id or self._default_chat_id

        if not channel or not chat_id:
            return "Error: No target channel/chat specified"

        if not self._send_callback:
            return "Error: Message sending not configured"
        
        # Build media info if file_path provided
        media = None
        if file_path:
            path = Path(file_path)
            if not path.exists():
                return f"Error: File not found: {file_path}"
            
            # Auto-detect file type if not specified
            if not file_type:
                ext = path.suffix.lower()
                if ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp']:
                    file_type = "image"
                else:
                    file_type = "file"
            
            media = {
                "type": file_type,
                "path": str(path.absolute()),
                "name": path.name
            }
        
        msg = OutboundMessage(
            channel=channel,
            chat_id=chat_id,
            content=content,
            media=media
        )
        
        try:
            await self._send_callback(msg)
            if media:
                return f"Message with {media['type']} sent to {channel}:{chat_id}"
            return f"Message sent to {channel}:{chat_id}"
        except Exception as e:
            return f"Error sending message: {str(e)}"
