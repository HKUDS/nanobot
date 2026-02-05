"""Feishu/Lark channel implementation using official lark-oapi SDK with long connection."""

import asyncio
import json
import threading
from typing import Any

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import FeishuConfig


class FeishuChannel(BaseChannel):
    """
    Feishu/Lark channel using long connection (WebSocket).

    Uses official lark-oapi SDK to receive events through WebSocket,
    eliminating the need for public URL or webhook configuration.
    """

    name = "feishu"

    def __init__(self, config: FeishuConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: FeishuConfig = config
        self._client = None
        self._ws_client = None
        self._event_loop = None
        self._ws_thread = None

    async def start(self) -> None:
        """Start the Feishu channel with long connection."""
        if not self.config.app_id or not self.config.app_secret:
            logger.error("Feishu app_id or app_secret not configured")
            return

        try:
            # Import Feishu SDK
            import lark_oapi as lark
            from lark_oapi.ws import Client as WSClient

            self._running = True
            self._event_loop = asyncio.get_event_loop()

            # Create Feishu client (for sending messages)
            self._client = lark.Client.builder() \
                .app_id(self.config.app_id) \
                .app_secret(self.config.app_secret) \
                .log_level(lark.LogLevel.INFO) \
                .build()

            logger.info(f"Feishu client initialized (app_id: {self.config.app_id})")

            # Create event handler
            event_handler = lark.EventDispatcherHandler.builder(
                self.config.verification_token or "",
                self.config.encrypt_key or ""
            ).register_p2_im_message_receive_v1(
                self._handle_message_event
            ).build()

            # Create WebSocket client
            self._ws_client = WSClient(
                app_id=self.config.app_id,
                app_secret=self.config.app_secret,
                event_handler=event_handler,
                log_level=lark.LogLevel.INFO,
                auto_reconnect=True
            )

            logger.info("Starting Feishu long connection...")

            # Start WebSocket in a separate thread
            # (SDK requires its own event loop, can't run in current loop)
            self._ws_thread = threading.Thread(
                target=self._run_ws_in_thread,
                daemon=True
            )
            self._ws_thread.start()

            logger.info("Feishu WebSocket thread started")

            # Keep the channel alive
            while self._running:
                await asyncio.sleep(1)

        except ImportError as e:
            logger.error(f"Failed to import lark-oapi SDK: {e}")
            logger.info("Install with: pip install lark-oapi")
        except Exception as e:
            logger.error(f"Error starting Feishu channel: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def _run_ws_in_thread(self) -> None:
        """
        Run WebSocket client in a separate thread with its own event loop.

        This is necessary because the lark-oapi SDK's ws.client module
        captures the event loop at import time (module-level code).
        We need to monkey-patch the module's loop variable before calling start().
        """
        # Create a new event loop for this thread
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)

        try:
            # CRITICAL: The SDK's ws.client module captures the event loop
            # at import time in a module-level variable. We must replace it
            # with our new loop before calling start().
            import lark_oapi.ws.client as ws_client_module
            ws_client_module.loop = new_loop

            logger.info("WebSocket thread starting with patched event loop...")
            # SDK's start() method is blocking and handles its own event loop
            self._ws_client.start()
        except Exception as e:
            logger.error(f"WebSocket thread error: {e}")
            import traceback
            logger.error(traceback.format_exc())
        finally:
            # Clean up the event loop when done
            new_loop.close()

    async def stop(self) -> None:
        """Stop the Feishu channel."""
        self._running = False
        logger.info("Feishu channel stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through Feishu."""
        if not self._client:
            logger.warning("Feishu client not initialized")
            return

        try:
            import lark_oapi as lark
            from lark_oapi.api.im.v1 import (
                CreateMessageRequest,
                CreateMessageRequestBody,
            )

            # Build message request
            request = CreateMessageRequest.builder() \
                .receive_id_type("chat_id") \
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(msg.chat_id)
                    .msg_type("text")
                    .content(json.dumps({"text": msg.content}))
                    .build()
                ) \
                .build()

            # Send message
            response = self._client.im.v1.message.create(request)

            # Check response
            if not response.success():
                logger.error(
                    f"Failed to send message: code={response.code}, "
                    f"msg={response.msg}, log_id={response.get_log_id()}"
                )
            else:
                logger.debug(f"Message sent to {msg.chat_id}")

        except Exception as e:
            logger.error(f"Error sending Feishu message: {e}")

    def _handle_message_event(self, data: Any) -> None:
        """
        Handle im.message.receive_v1 event from long connection.

        This is a synchronous callback from the SDK, so we need to
        convert it to async and forward to the message bus.
        """
        try:
            # Extract event data
            event = data.event

            # Get sender info
            sender = event.sender
            sender_id = sender.sender_id.user_id if sender.sender_id else ""

            # Check allowlist
            if not self.is_allowed(sender_id):
                logger.warning(f"Message from unauthorized sender: {sender_id}")
                return

            # Get message info
            message = event.message
            chat_id = message.chat_id
            message_type = message.message_type
            message_id = message.message_id

            # Parse content based on message type
            content = ""
            if message_type == "text":
                content_obj = json.loads(message.content)
                content = content_obj.get("text", "")
            elif message_type == "image":
                content = "[image received]"
                logger.info(f"Image message received: {message_id}")
            elif message_type == "file":
                content = "[file received]"
                logger.info(f"File message received: {message_id}")
            else:
                content = f"[{message_type} message]"
                logger.debug(f"Unhandled message type: {message_type}")

            if not content:
                logger.debug("Empty message content, skipping")
                return

            logger.info(f"Feishu message from {sender_id}: {content[:50]}...")

            # Schedule async message handling
            # Since this callback is sync, we use asyncio.run_coroutine_threadsafe
            if self._event_loop:
                asyncio.run_coroutine_threadsafe(
                    self._handle_message(
                        sender_id=sender_id,
                        chat_id=chat_id,
                        content=content,
                        media=[],
                        metadata={
                            "message_id": message_id,
                            "message_type": message_type,
                            "sender": sender,
                        }
                    ),
                    self._event_loop
                )

        except Exception as e:
            logger.error(f"Error handling Feishu message event: {e}")
            import traceback
            logger.error(traceback.format_exc())
