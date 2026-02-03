"""WhatsApp channel implementation using Node.js bridge."""

import asyncio
import json
from typing import Any

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import WhatsAppConfig


class WhatsAppChannel(BaseChannel):
    """
    WhatsApp channel that connects to a Node.js bridge.
    
    The bridge uses @whiskeysockets/baileys to handle the WhatsApp Web protocol.
    Communication between Python and Node.js is via WebSocket.
    """
    
    name = "whatsapp"
    
    def __init__(self, config: WhatsAppConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: WhatsAppConfig = config
        self._ws = None
        self._connected = False
    
    async def start(self) -> None:
        """Start the WhatsApp channel by connecting to the bridge."""
        import websockets
        
        bridge_url = self.config.bridge_url
        
        logger.info(f"Connecting to WhatsApp bridge at {bridge_url}...")
        
        self._running = True
        
        while self._running:
            try:
                async with websockets.connect(bridge_url) as ws:
                    self._ws = ws
                    self._connected = True
                    logger.info("Connected to WhatsApp bridge")
                    
                    # Listen for messages
                    async for message in ws:
                        try:
                            await self._handle_bridge_message(message)
                        except Exception as e:
                            logger.error(f"Error handling bridge message: {e}")
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._connected = False
                self._ws = None
                logger.warning(f"WhatsApp bridge connection error: {e}")
                
                if self._running:
                    logger.info("Reconnecting in 5 seconds...")
                    await asyncio.sleep(5)
    
    async def stop(self) -> None:
        """Stop the WhatsApp channel."""
        self._running = False
        self._connected = False
        
        if self._ws:
            await self._ws.close()
            self._ws = None
    
    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through WhatsApp."""
        if not self._ws or not self._connected:
            logger.warning("WhatsApp bridge not connected")
            return
        
        try:
            payload = {
                "type": "send",
                "to": msg.chat_id,
                "text": msg.content
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
            # Incoming message from WhatsApp
            sender = data.get("sender", "")
            content = data.get("content", "")

            # sender is typically: <phone>@s.whatsapp.net
            # Extract just the phone number as chat_id
            chat_id = sender.split("@")[0] if "@" in sender else sender

            # Apply prefix rules - filter and strip prefix if needed
            filtered_content = self._apply_prefix_rules(chat_id, content)
            if filtered_content is None:
                logger.debug(f"Ignoring message from {chat_id} - missing required prefix")
                return
            content = filtered_content

            # Handle voice transcription if it's a voice message
            if content == "[Voice Message]":
                logger.info(f"Voice message received from {chat_id}, but direct download from bridge is not yet supported.")
                content = "[Voice Message: Transcription not available for WhatsApp yet]"

            await self._handle_message(
                sender_id=chat_id,
                chat_id=sender,  # Use full JID for replies
                content=content,
                metadata={
                    "message_id": data.get("id"),
                    "timestamp": data.get("timestamp"),
                    "is_group": data.get("isGroup", False)
                }
            )
        
        elif msg_type == "status":
            # Connection status update
            status = data.get("status")
            logger.info(f"WhatsApp status: {status}")
            
            if status == "connected":
                self._connected = True
            elif status == "disconnected":
                self._connected = False
        
        elif msg_type == "qr":
            # QR code for authentication
            logger.info("Scan QR code in the bridge terminal to connect WhatsApp")
        
        elif msg_type == "error":
            logger.error(f"WhatsApp bridge error: {data.get('error')}")

    def _apply_prefix_rules(self, phone: str, content: str) -> str | None:
        """
        Apply prefix rules to filter/strip messages.

        Returns:
            - The (possibly stripped) content if message should be processed
            - None if message should be ignored
        """
        # Check if any prefix rule matches this phone number
        for rule in self.config.prefix_rules:
            if rule.phone in phone:
                # This phone has a prefix rule
                content_lower = content.lower().strip()
                prefix_lower = rule.prefix.lower()

                # Check if message starts with the required prefix
                if content_lower.startswith(prefix_lower + " "):
                    # Has prefix with space - strip it
                    if rule.strip:
                        stripped = content[len(rule.prefix):].strip()
                        logger.info(f"Triggered by '{rule.prefix}' prefix from {phone}")
                        return stripped
                    return content
                elif content_lower == prefix_lower:
                    # Just the prefix alone - treat as greeting
                    logger.info(f"Triggered by '{rule.prefix}' alone from {phone}")
                    return "oi"
                else:
                    # Missing required prefix - ignore
                    return None

        # No prefix rule for this phone - allow all messages
        return content
