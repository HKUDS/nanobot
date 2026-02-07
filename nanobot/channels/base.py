"""Base channel interface for chat platforms."""

from abc import ABC, abstractmethod
from typing import Any

from loguru import logger

class BaseChannel(ABC):
    """
    Abstract base class for chat channel implementations.

    Each channel (Telegram, Discord, etc.) should implement this interface.
    Channels call the agent actor directly and send responses themselves.
    """

    name: str = "base"

    def __init__(self, config: Any, agent_name: str = "agent"):
        """
        Initialize the channel.

        Args:
            config: Channel-specific configuration.
            agent_name: Name of the AgentActor to resolve via Pulsing.
        """
        self.config = config
        self.agent_name = agent_name
        self._running = False

    @abstractmethod
    async def start(self) -> None:
        """Start the channel and begin listening for messages."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop the channel and clean up resources."""
        pass

    @abstractmethod
    async def send_text(self, chat_id: str, content: str) -> None:
        """
        Send a text message through this channel.

        Args:
            chat_id: The chat/channel identifier.
            content: The message text to send.
        """
        pass

    def is_allowed(self, sender_id: str) -> bool:
        """Check if a sender is allowed to use this bot."""
        allow_list = getattr(self.config, "allow_from", [])

        if not allow_list:
            return True

        sender_str = str(sender_id)
        if sender_str in allow_list:
            return True
        if "|" in sender_str:
            for part in sender_str.split("|"):
                if part and part in allow_list:
                    return True
        return False

    async def _get_agent(self):
        """Resolve the AgentActor via Pulsing."""
        from nanobot.actor.agent import AgentActor

        return await AgentActor.resolve(self.agent_name)

    async def _handle_message(
        self,
        sender_id: str,
        chat_id: str,
        content: str,
        media: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Handle an incoming message from the chat platform.

        Checks permissions, calls the agent, and sends the response back.
        """
        if not self.is_allowed(sender_id):
            logger.warning(
                f"Access denied for sender {sender_id} on channel {self.name}. "
                f"Add them to allowFrom list in config to grant access."
            )
            return

        try:
            agent = await self._get_agent()
            response = await agent.process(
                channel=self.name,
                sender_id=str(sender_id),
                chat_id=str(chat_id),
                content=content,
                media=media or [],
            )
            if response:
                await self.send_text(str(chat_id), response)
        except Exception as e:
            logger.error(f"Error processing message on {self.name}: {e}")
            try:
                await self.send_text(
                    str(chat_id), f"Sorry, I encountered an error: {str(e)}"
                )
            except Exception:
                pass

    @property
    def is_running(self) -> bool:
        """Check if the channel is running."""
        return self._running
