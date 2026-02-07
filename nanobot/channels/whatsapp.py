"""WhatsApp channel implementation using Node.js bridge."""

import asyncio
import json

from loguru import logger

from nanobot.channels.base import BaseChannel
from nanobot.config.schema import WhatsAppConfig


class WhatsAppChannel(BaseChannel):
    """
    WhatsApp channel that connects to a Node.js bridge.

    The bridge uses @whiskeysockets/baileys to handle the WhatsApp Web protocol.
    Communication between Python and Node.js is via WebSocket.
    """

    name = "whatsapp"

    def __init__(self, config: WhatsAppConfig, agent_name: str = "agent"):
        super().__init__(config, agent_name)
        self.config: WhatsAppConfig = config
        self._ws = None
        self._connected = False

    async def start(self) -> None:
        """Start the WhatsApp channel by connecting to the bridge.

        Connects once. The ChannelManager supervisor handles restarts
        on failure with exponential backoff.
        """
        import websockets

        bridge_url = self.config.bridge_url

        logger.info(f"Connecting to WhatsApp bridge at {bridge_url}...")

        self._running = True

        async with websockets.connect(bridge_url) as ws:
            self._ws = ws
            self._connected = True
            logger.info("Connected to WhatsApp bridge")

            async for message in ws:
                try:
                    await self._handle_bridge_message(message)
                except Exception as e:
                    logger.error(f"Error handling bridge message: {e}")

    async def stop(self) -> None:
        """Stop the WhatsApp channel."""
        self._running = False
        self._connected = False

        if self._ws:
            await self._ws.close()
            self._ws = None

    async def send_text(self, chat_id: str, content: str) -> None:
        """Send a text message through WhatsApp."""
        if not self._ws or not self._connected:
            logger.warning("WhatsApp bridge not connected")
            return

        try:
            payload = {
                "type": "send",
                "to": chat_id,
                "text": content,
            }
            await self._ws.send(json.dumps(payload))
        except Exception as e:
            logger.error(f"Error sending WhatsApp message: {e}")

    async def _handle_bridge_message(self, raw: str) -> None:
        """Handle a message from the bridge."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON from bridge: {raw[:100]}")
            return

        msg_type = data.get("type")

        if msg_type == "message":
            sender = data.get("sender", "")
            content = data.get("content", "")

            chat_id = sender.split("@")[0] if "@" in sender else sender

            if content == "[Voice Message]":
                logger.info(
                    f"Voice message received from {chat_id}, "
                    "but direct download from bridge is not yet supported."
                )
                content = (
                    "[Voice Message: Transcription not available for WhatsApp yet]"
                )

            await self._handle_message(
                sender_id=chat_id,
                chat_id=sender,
                content=content,
                metadata={
                    "message_id": data.get("id"),
                    "timestamp": data.get("timestamp"),
                    "is_group": data.get("isGroup", False),
                },
            )

        elif msg_type == "status":
            status = data.get("status")
            logger.info(f"WhatsApp status: {status}")

            if status == "connected":
                self._connected = True
            elif status == "disconnected":
                self._connected = False

        elif msg_type == "qr":
            logger.info("Scan QR code in the bridge terminal to connect WhatsApp")

        elif msg_type == "error":
            logger.error(f"WhatsApp bridge error: {data.get('error')}")
