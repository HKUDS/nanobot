"""Feishu/Lark channel implementation using lark-oapi SDK with WebSocket long connection."""

import asyncio
import json
import threading
from typing import Any

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import FeishuConfig

try:
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import (
        CreateMessageRequest,
        CreateMessageRequestBody,
        CreateMessageReactionRequest,
        CreateMessageReactionRequestBody,
        P2ImMessageReceiveV1,
    )
    FEISHU_AVAILABLE = True
except ImportError:
    FEISHU_AVAILABLE = False
    lark = None


class FeishuChannel(BaseChannel):
    """
    Feishu/Lark channel using WebSocket long connection.
    
    Uses WebSocket to receive events - no public IP or webhook required.
    
    Requires:
    - App ID and App Secret from Feishu Open Platform
    - Bot capability enabled
    - Event subscription enabled (im.message.receive_v1)
    """
    
    name = "feishu"
    
    def __init__(self, config: FeishuConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: FeishuConfig = config
        self._client: Any = None
        self._ws_client: Any = None
        self._ws_thread: threading.Thread | None = None
        self._processed_message_ids: set[str] = set()  # Dedup message IDs
        self._loop: asyncio.AbstractEventLoop | None = None
    
    async def start(self) -> None:
        """Start the Feishu bot with WebSocket long connection."""
        if not FEISHU_AVAILABLE:
            logger.error("Feishu SDK not installed. Run: pip install lark-oapi")
            return
        
        if not self.config.app_id or not self.config.app_secret:
            logger.error("Feishu app_id and app_secret not configured")
            return
        
        self._running = True
        self._loop = asyncio.get_event_loop()
        
        # Create Lark client for sending messages
        self._client = lark.Client.builder() \
            .app_id(self.config.app_id) \
            .app_secret(self.config.app_secret) \
            .log_level(lark.LogLevel.INFO) \
            .build()
        
        # Create event handler (only register message receive, ignore other events)
        event_handler = lark.EventDispatcherHandler.builder(
            self.config.encrypt_key or "",
            self.config.verification_token or "",
        ).register_p2_im_message_receive_v1(
            self._on_message_sync
        ).build()
        
        # Create WebSocket client for long connection
        self._ws_client = lark.ws.Client(
            self.config.app_id,
            self.config.app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO
        )
        
        # Start WebSocket client in a separate thread
        def run_ws():
            try:
                self._ws_client.start()
            except Exception as e:
                logger.error(f"Feishu WebSocket error: {e}")
        
        self._ws_thread = threading.Thread(target=run_ws, daemon=True)
        self._ws_thread.start()
        
        logger.info("Feishu bot started with WebSocket long connection")
        logger.info("No public IP required - using WebSocket to receive events")
        
        # Keep running until stopped
        while self._running:
            await asyncio.sleep(1)
    
    async def stop(self) -> None:
        """Stop the Feishu bot."""
        self._running = False
        logger.info("Feishu bot stopped")
    
    def _add_reaction(self, message_id: str, emoji_type: str = "SMILE") -> None:
        """
        Add a reaction emoji to a message.
        
        Common emoji types: THUMBSUP, OK, EYES, DONE, OnIt, HEART
        """
        if not self._client:
            logger.warning("Cannot add reaction: client not initialized")
            return
        
        try:
            from lark_oapi.api.im.v1 import Emoji
            
            request = CreateMessageReactionRequest.builder() \
                .message_id(message_id) \
                .request_body(
                    CreateMessageReactionRequestBody.builder()
                    .reaction_type(Emoji.builder().emoji_type(emoji_type).build())
                    .build()
                ).build()
            
            response = self._client.im.v1.message_reaction.create(request)
            
            if not response.success():
                logger.warning(f"Failed to add reaction: code={response.code}, msg={response.msg}")
            else:
                logger.info(f"Added {emoji_type} reaction to message {message_id}")
        except Exception as e:
            logger.warning(f"Error adding reaction: {e}")
    
    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through Feishu."""
        if not self._client:
            logger.warning("Feishu client not initialized")
            return
        
        try:
            # Determine receive_id_type based on chat_id format
            # open_id starts with "ou_", chat_id starts with "oc_"
            if msg.chat_id.startswith("oc_"):
                receive_id_type = "chat_id"
            else:
                receive_id_type = "open_id"
            
            # Build text message content
            content = json.dumps({"text": msg.content})
            
            request = CreateMessageRequest.builder() \
                .receive_id_type(receive_id_type) \
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(msg.chat_id)
                    .msg_type("text")
                    .content(content)
                    .build()
                ).build()
            
            response = self._client.im.v1.message.create(request)
            
            if not response.success():
                logger.error(
                    f"Failed to send Feishu message: code={response.code}, "
                    f"msg={response.msg}, log_id={response.get_log_id()}"
                )
            else:
                logger.debug(f"Feishu message sent to {msg.chat_id}")
                
        except Exception as e:
            logger.error(f"Error sending Feishu message: {e}")
    
    def _on_message_sync(self, data: "P2ImMessageReceiveV1") -> None:
        """
        Sync handler for incoming messages (called from WebSocket thread).
        Schedules async handling in the main event loop.
        """
        try:
            if self._loop and self._loop.is_running():
                # Schedule the async handler in the main event loop
                asyncio.run_coroutine_threadsafe(
                    self._on_message(data),
                    self._loop
                )
            else:
                # Fallback: run in new event loop
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(self._on_message(data))
                finally:
                    loop.close()
        except Exception as e:
            logger.error(f"Error handling Feishu message: {e}")
    
    async def _on_message(self, data: "P2ImMessageReceiveV1") -> None:
        """Handle incoming message from Feishu."""
        try:
            event = data.event
            message = event.message
            sender = event.sender
            
            # Get message ID for deduplication
            message_id = message.message_id
            if message_id in self._processed_message_ids:
                logger.debug(f"Skipping duplicate message: {message_id}")
                return
            self._processed_message_ids.add(message_id)
            
            # Limit dedup cache size
            if len(self._processed_message_ids) > 1000:
                self._processed_message_ids = set(list(self._processed_message_ids)[-500:])
            
            # Extract sender info
            sender_id = sender.sender_id.open_id if sender.sender_id else "unknown"
            sender_type = sender.sender_type  # "user" or "bot"
            
            # Skip bot messages
            if sender_type == "bot":
                return
            
            # Add reaction to user's message to indicate "seen" (👍 THUMBSUP)
            self._add_reaction(message_id, "THUMBSUP")
            
            # Get chat_id for replies
            chat_id = message.chat_id
            chat_type = message.chat_type  # "p2p" or "group"
            
            # Parse message content
            content = ""
            msg_type = message.message_type
            
            if msg_type == "text":
                # Text message: {"text": "hello"}
                try:
                    content_obj = json.loads(message.content)
                    content = content_obj.get("text", "")
                except json.JSONDecodeError:
                    content = message.content or ""
            elif msg_type == "image":
                content = "[image]"
            elif msg_type == "audio":
                content = "[audio]"
            elif msg_type == "file":
                content = "[file]"
            elif msg_type == "sticker":
                content = "[sticker]"
            else:
                content = f"[{msg_type}]"
            
            if not content:
                return
            
            logger.debug(f"Feishu message from {sender_id} in {chat_id}: {content[:50]}...")
            
            # Forward to message bus
            # Use chat_id for group chats, sender's open_id for p2p
            reply_to = chat_id if chat_type == "group" else sender_id
            
            await self._handle_message(
                sender_id=sender_id,
                chat_id=reply_to,
                content=content,
                metadata={
                    "message_id": message_id,
                    "chat_type": chat_type,
                    "msg_type": msg_type,
                    "sender_type": sender_type,
                }
            )
            
        except Exception as e:
            logger.error(f"Error processing Feishu message: {e}")
