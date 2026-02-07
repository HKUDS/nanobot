"""Message tool for sending messages to users via Pulsing point-to-point."""

from typing import Any

from nanobot.agent.tools.base import Tool, ToolContext
from nanobot.channels.manager import get_channel_actor


class MessageTool(Tool):
    """Tool to send messages to users on chat channels.

    Resolves the channel actor by name (channel.{name}) and calls send_text.
    """

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
            },
            "required": ["content"],
        }

    async def execute(
        self,
        ctx: ToolContext,
        content: str,
        channel: str | None = None,
        chat_id: str | None = None,
        **kwargs: Any,
    ) -> str:
        channel = channel or ctx.channel
        chat_id = chat_id or ctx.chat_id

        if not channel or not chat_id:
            return "Error: No target channel/chat specified"

        try:
            ch = await get_channel_actor(channel)
        except Exception:
            return f"Error: Channel '{channel}' not available"

        try:
            await ch.send_text(chat_id, content)
            return f"Message sent to {channel}:{chat_id}"
        except Exception as e:
            return f"Error sending message: {str(e)}"
