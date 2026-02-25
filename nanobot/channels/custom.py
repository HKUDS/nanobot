"""
Custom generic channel for nanobot.

This is a skeleton channel - modify this file to implement your own
custom channel logic (WebSocket, HTTP, etc.).

See below for a WebSocket example implementation.
"""

import asyncio
import json

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel


class CustomChannel(BaseChannel):
    """
    Custom channel implementation.

    Modify the methods below to implement your own logic:
    - start(): Connect to your service and listen for messages
    - stop(): Clean up connections
    - send(): Forward outbound messages to your service
    """

    name = "custom"

    def __init__(self, config, bus: MessageBus):
        super().__init__(config, bus)
        # Add your own instance variables here
        # Example: self._ws = None, self._send_queue = asyncio.Queue()

    async def start(self) -> None:
        """
        Start the channel and begin listening for messages.

        This is called when nanobot starts. Implement your connection logic here.

        Common patterns:
        - WebSocket connection with asyncio.create_task() for recv/send
        - HTTP polling loop
        - Queue consumption for outbound messages
        """
        self._running = True

        # TODO: Implement your connection logic here
        # Example (WebSocket):
        #
        # async def drain_outbound():
        #     while True:
        #         msg = await self.bus.consume_outbound()
        #         await self._send_queue.put(msg)
        # asyncio.create_task(drain_outbound())
        #
        # while self._running:
        #     async with websockets.connect("wss://your-server.com/ws") as ws:
        #         self._ws = ws
        #         recv_task = asyncio.create_task(self._receive_loop(ws))
        #         send_task = asyncio.create_task(self._send_loop(ws))
        #         await asyncio.wait([recv_task, send_task], return_when=asyncio.FIRST_COMPLETED)

        raise NotImplementedError("Custom channel not implemented - edit channels/custom.py")

    async def stop(self) -> None:
        """
        Stop the channel and clean up resources.

        Called when nanobot shuts down. Close connections, cancel tasks, etc.
        """
        self._running = False
        # TODO: Add cleanup code here

    async def send(self, msg: OutboundMessage) -> None:
        """
        Send a message through this channel.

        Called by ChannelManager when there's an outbound message to send.

        Args:
            msg: The OutboundMessage to send.
        """
        # TODO: Implement sending logic here
        # Example:
        # await self._send_queue.put(msg)
        pass
