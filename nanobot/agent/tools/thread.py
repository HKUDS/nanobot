"""Tool for creating and managing Telegram forum topics (threads)."""

from typing import Any, Callable, Awaitable
from nanobot.agent.tools.base import Tool


class CreateThreadTool(Tool):
    """Create a new forum topic (thread) in Telegram."""
    
    name = "create_thread"
    description = "Create a new discussion thread in Telegram. Each thread has its own isolated conversation context."
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name for the thread (1-128 characters)"
            },
            "icon_color": {
                "type": "integer",
                "description": "Color of the topic icon (1-6 for Telegram's preset colors). Optional.",
                "minimum": 1,
                "maximum": 6
            }
        },
        "required": ["name"]
    }
    
    def __init__(
        self,
        channel: str = "telegram",
        chat_id: str = "",
        create_callback: Callable[[int, str, int | None], Awaitable[dict | None]] | None = None,
    ):
        self.channel = channel
        self.chat_id = chat_id
        self.create_callback = create_callback
    
    def set_context(self, channel: str, chat_id: str) -> None:
        """Set the current channel and chat_id context."""
        self.channel = channel
        self.chat_id = chat_id
    
    def set_callback(self, callback: Callable[[int, str, int | None], Awaitable[dict | None]]) -> None:
        """Set the callback for creating threads."""
        self.create_callback = callback
    
    async def execute(self, name: str, icon_color: int | None = None, **kwargs: Any) -> str:
        """Execute the tool to create a thread."""
        # This tool only works for Telegram
        if self.channel != "telegram":
            return "Error: Thread creation is only supported for Telegram channel."
        
        if not self.chat_id:
            return "Error: No chat context available. Cannot create thread."
        
        if not self.create_callback:
            return "Error: Thread creation callback not configured."
        
        try:
            result = await self.create_callback(int(self.chat_id), name, icon_color)
            
            if result and "message_thread_id" in result:
                thread_id = result["message_thread_id"]
                return f"Created thread '{name}' (ID: {thread_id}). Messages in this thread will have their own conversation context."
            else:
                return f"Failed to create thread. Make sure the bot has permission to manage topics."
        except Exception as e:
            return f"Error creating thread: {str(e)}"


class ListThreadsTool(Tool):
    """List all forum topics (threads) in the current chat."""
    
    name = "list_threads"
    description = "List all discussion threads in the current Telegram chat."
    parameters = {
        "type": "object",
        "properties": {}
    }
    
    def __init__(
        self,
        channel: str = "telegram",
        chat_id: str = "",
        list_callback: Callable[[int], Awaitable[dict]] | None = None,
    ):
        self.channel = channel
        self.chat_id = chat_id
        self.list_callback = list_callback
    
    def set_context(self, channel: str, chat_id: str) -> None:
        """Set the current channel and chat_id context."""
        self.channel = channel
        self.chat_id = chat_id
    
    def set_callback(self, callback: Callable[[int], Awaitable[dict]]) -> None:
        """Set the callback for listing threads."""
        self.list_callback = callback
    
    async def execute(self, **kwargs: Any) -> str:
        """Execute the tool to list threads."""
        if self.channel != "telegram":
            return "Error: Threads are only supported for Telegram channel."
        
        if not self.chat_id:
            return "Error: No chat context available."
        
        if not self.list_callback:
            return "Error: Thread listing callback not configured."
        
        try:
            result = await self.list_callback(int(self.chat_id))
            
            if result and "threads" in result:
                threads = result["threads"]
                if not threads:
                    return "No threads found in this chat."
                
                lines = ["Threads in this chat:"]
                for tid, info in threads.items():
                    lines.append(f"  • {info.get('name', 'Unknown')} (ID: {tid})")
                return "\n".join(lines)
            else:
                return "No threads found or unable to list threads."
        except Exception as e:
            return f"Error listing threads: {str(e)}"