"""ChannelActor: Pulsing actor wrapper for chat channels.

Each channel instance is wrapped in a ChannelActor and registered
with a well-known name ``channel.{name}`` (e.g. ``channel.discord``).

Any actor in the system can send messages by resolving the name:

    ch = await ChannelActor.resolve("channel.discord")
    await ch.send_text(chat_id, content)

This eliminates the need to pass ``channel_manager`` object references
between actors -- pure point-to-point messaging via Pulsing.
"""

import pulsing as pul
from loguru import logger

from nanobot.channels.base import BaseChannel


@pul.remote(
    restart_policy="on-failure", max_restarts=10, min_backoff=1.0, max_backoff=60.0
)
class ChannelActor:
    """
    Pulsing actor wrapping a BaseChannel implementation.

    Supervision is handled by Pulsing's built-in restart policy:
    ``restart_policy="on-failure"`` with exponential backoff.
    No manual retry loop needed.

    Provides:
    - ``send_text(chat_id, content)`` callable from anywhere via resolve
    - ``run()`` to start the channel's event loop
    - ``stop()`` to gracefully shut down
    """

    def __init__(self, channel: BaseChannel):
        self._channel = channel

    async def send_text(self, chat_id: str, content: str) -> None:
        """Send a text message through this channel (point-to-point callable)."""
        await self._channel.send_text(chat_id, content)

    async def run(self) -> None:
        """Start the channel's event loop.

        If the channel crashes, Pulsing's supervision will restart the actor
        automatically with exponential backoff.
        """
        logger.info(f"channel.{self._channel.name}: starting")
        await self._channel.start()
        logger.info(f"channel.{self._channel.name}: clean shutdown")

    async def stop(self) -> None:
        """Stop the channel."""
        await self._channel.stop()

    @property
    def channel_name(self) -> str:
        return self._channel.name
