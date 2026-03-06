"""P2P message tool for sending messages to peer agents."""

from typing import Any, Awaitable, Callable

from nanobot.agent.tools.base import Tool
from nanobot.bus.events import OutboundMessage


class P2PTool(Tool):
    """Tool to send messages to P2P peers."""

    def __init__(
        self,
        send_callback: Callable[[OutboundMessage], Awaitable[None]] | None = None,
    ):
        self._send_callback = send_callback

    def set_send_callback(self, callback: Callable[[OutboundMessage], Awaitable[None]]) -> None:
        """Set the callback for sending messages."""
        self._send_callback = callback

    @property
    def name(self) -> str:
        return "p2p_message"

    @property
    def description(self) -> str:
        return "Send a message to another nanobot peer over P2P network. Use this to communicate with other nanobot agents. You can find available peers by checking the context."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "peer_id": {
                    "type": "string",
                    "description": "The peer ID to send the message to (e.g., 'peer_a', 'peer_b')"
                },
                "content": {
                    "type": "string",
                    "description": "The message content to send"
                }
            },
            "required": ["peer_id", "content"]
        }

    async def execute(
        self,
        peer_id: str,
        content: str,
        **kwargs: Any
    ) -> str:
        if not peer_id:
            return "Error: No peer_id specified"

        if not content:
            return "Error: No content specified"

        if not self._send_callback:
            return "Error: P2P messaging not configured"

        msg = OutboundMessage(
            channel="p2p",
            chat_id=peer_id,
            content=content,
        )

        try:
            await self._send_callback(msg)
            return f"Message sent to P2P peer: {peer_id}"
        except Exception as e:
            return f"Error sending P2P message: {str(e)}"
