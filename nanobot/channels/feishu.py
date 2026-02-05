"""Feishu (Lark) channel implementation using WebSocket long connection."""

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
    from lark_oapi import ws
    from lark_oapi.api.im.v1 import (
        CreateMessageRequest,
        CreateMessageRequestBody,
        P2ImMessageReceiveV1,
    )
    from lark_oapi.event.dispatcher_handler import EventDispatcherHandler
    LARK_SDK_AVAILABLE = True
except ImportError:
    LARK_SDK_AVAILABLE = False


class FeishuChannel(BaseChannel):
    """
    Feishu channel using WebSocket long connection.
    
    No public IP or webhook required - connects directly to Feishu servers.
    """
    
    name = "feishu"
    
    def __init__(self, config: FeishuConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: FeishuConfig = config
        self._client: Any = None
        self._ws_client: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
    
    async def start(self) -> None:
        """Start the Feishu channel with WebSocket long connection."""
        if not LARK_SDK_AVAILABLE:
            logger.error("lark-oapi not installed. Run: pip install lark-oapi")
            return
        
        if not self.config.app_id or not self.config.app_secret:
            logger.error("Feishu app_id and app_secret not configured")
            return
        
        self._running = True
        self._loop = asyncio.get_event_loop()
        
        # Initialize REST client for sending messages
        self._client = lark.Client.builder() \
            .app_id(self.config.app_id) \
            .app_secret(self.config.app_secret) \
            .build()
        
        # Create event handler
        event_handler = EventDispatcherHandler.builder("", "") \
            .register_p2_im_message_receive_v1(self._on_message_receive) \
            .build()
        
        # Create WebSocket client
        self._ws_client = ws.Client(
            app_id=self.config.app_id,
            app_secret=self.config.app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO,
        )
        
        logger.info("Starting Feishu WebSocket connection...")
        logger.info("No public IP required - using long connection mode")
        
        # Start WebSocket client in a separate thread (it's blocking)
        ws_thread = threading.Thread(target=self._run_ws_client, daemon=True)
        ws_thread.start()
        
        logger.info("Feishu channel started successfully")
        
        # Keep running
        while self._running:
            await asyncio.sleep(1)
    
    def _run_ws_client(self) -> None:
        """Run WebSocket client (blocking, runs in separate thread)."""
        try:
            self._ws_client.start()
        except Exception as e:
            logger.error(f"Feishu WebSocket error: {e}")
    
    async def stop(self) -> None:
        """Stop the Feishu channel."""
        self._running = False
        self._client = None
        self._ws_client = None
        logger.info("Feishu channel stopped")
    
    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through Feishu."""
        if not self._client:
            logger.warning("Feishu client not initialized")
            return
        
        try:
            receive_id_type = self._get_receive_id_type(msg.chat_id)
            
            request = CreateMessageRequest.builder() \
                .receive_id_type(receive_id_type) \
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(msg.chat_id)
                    .msg_type("text")
                    .content(json.dumps({"text": msg.content}))
                    .build()
                ) \
                .build()
            
            response = self._client.im.v1.message.create(request)
            
            if not response.success():
                logger.error(f"Feishu send failed: {response.code} - {response.msg}")
            else:
                logger.debug(f"Feishu message sent to {msg.chat_id}")
                
        except Exception as e:
            logger.error(f"Error sending Feishu message: {e}")
    
    def _get_receive_id_type(self, chat_id: str) -> str:
        """Determine receive_id_type based on chat_id format."""
        if chat_id.startswith("oc_"):
            return "chat_id"
        elif chat_id.startswith("ou_"):
            return "open_id"
        elif chat_id.startswith("on_"):
            return "union_id"
        else:
            return "open_id"
    
    def _on_message_receive(self, data: "P2ImMessageReceiveV1") -> None:
        """Handle incoming message event (called from WebSocket thread)."""
        try:
            event = data.event
            message = event.message
            sender = event.sender
            
            msg_type = message.message_type
            chat_id = message.chat_id
            message_id = message.message_id
            
            # Get sender info
            sender_id = sender.sender_id
            open_id = sender_id.open_id if sender_id else ""
            user_id = sender_id.user_id if sender_id else ""
            
            sender_identifier = open_id or user_id
            
            # Extract content
            content = ""
            try:
                content_json = json.loads(message.content or "{}")
                if msg_type == "text":
                    content = content_json.get("text", "")
                elif msg_type == "image":
                    content = "[image]"
                elif msg_type == "audio":
                    content = "[audio]"
                elif msg_type == "file":
                    content = f"[file: {content_json.get('file_name', 'unknown')}]"
                else:
                    content = f"[{msg_type}]"
            except json.JSONDecodeError:
                content = message.content or ""
            
            if not content:
                return
            
            logger.info(f"Feishu message from {sender_identifier}: {content[:50]}...")
            
            # Schedule async handler in the main event loop
            if self._loop:
                asyncio.run_coroutine_threadsafe(
                    self._handle_message(
                        sender_id=sender_identifier,
                        chat_id=chat_id,
                        content=content,
                        metadata={
                            "message_id": message_id,
                            "open_id": open_id,
                            "user_id": user_id,
                            "msg_type": msg_type,
                            "chat_type": message.chat_type,
                        }
                    ),
                    self._loop
                )
        except Exception as e:
            logger.error(f"Error handling Feishu message: {e}")
