"""Outbound message dispatching for chat channels."""

from __future__ import annotations

import asyncio

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.channels.policy import should_deliver_message
from nanobot.config.schema import Config


class OutboundDispatcher:
    """Consume outbound messages and send them to the matching channel."""

    def __init__(
        self,
        config: Config,
        bus: MessageBus,
        channels: dict[str, BaseChannel],
    ) -> None:
        self.config = config
        self.bus = bus
        self.channels = channels

    def _should_dispatch(self, message: OutboundMessage) -> bool:
        return should_deliver_message(self.config.channels, message.metadata)

    async def run(self) -> None:
        """Dispatch outbound messages to the appropriate channel."""
        logger.info("Outbound dispatcher started")

        while True:
            try:
                message = await asyncio.wait_for(self.bus.consume_outbound(), timeout=1.0)

                if not self._should_dispatch(message):
                    continue

                channel = self.channels.get(message.channel)
                if channel:
                    try:
                        await channel.send(message)
                    except Exception as error:
                        logger.error("Error sending to {}: {}", message.channel, error)
                else:
                    logger.warning("Unknown channel: {}", message.channel)

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
