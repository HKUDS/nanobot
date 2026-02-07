"""Feishu/Lark channel implementation using lark-oapi SDK with WebSocket long connection."""

import asyncio
import json
import threading
from collections import OrderedDict
from typing import Any

from loguru import logger

from nanobot.channels.base import BaseChannel
from nanobot.config.schema import FeishuConfig

try:
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import (
        CreateMessageRequest,
        CreateMessageRequestBody,
        CreateMessageReactionRequest,
        CreateMessageReactionRequestBody,
        Emoji,
        P2ImMessageReceiveV1,
    )
    FEISHU_AVAILABLE = True
except ImportError:
    FEISHU_AVAILABLE = False
    lark = None
    Emoji = None

MSG_TYPE_MAP = {
    "image": "[image]",
    "audio": "[audio]",
    "file": "[file]",
    "sticker": "[sticker]",
}


class FeishuChannel(BaseChannel):
    """
    Feishu/Lark channel using WebSocket long connection.

    Uses WebSocket to receive events - no public IP or webhook required.
    """

    name = "feishu"

    def __init__(self, config: FeishuConfig, agent_name: str = "agent"):
        super().__init__(config, agent_name)
        self.config: FeishuConfig = config
        self._client: Any = None
        self._ws_client: Any = None
        self._ws_thread: threading.Thread | None = None
        self._processed_message_ids: OrderedDict[str, None] = OrderedDict()
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
        self._loop = asyncio.get_running_loop()

        self._client = lark.Client.builder() \
            .app_id(self.config.app_id) \
            .app_secret(self.config.app_secret) \
            .log_level(lark.LogLevel.INFO) \
            .build()

        event_handler = lark.EventDispatcherHandler.builder(
            self.config.encrypt_key or "",
            self.config.verification_token or "",
        ).register_p2_im_message_receive_v1(
            self._on_message_sync
        ).build()

        self._ws_client = lark.ws.Client(
            self.config.app_id,
            self.config.app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO,
        )

        def run_ws():
            try:
                self._ws_client.start()
            except Exception as e:
                logger.error(f"Feishu WebSocket error: {e}")

        self._ws_thread = threading.Thread(target=run_ws, daemon=True)
        self._ws_thread.start()

        logger.info("Feishu bot started with WebSocket long connection")
        logger.info("No public IP required - using WebSocket to receive events")

        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """Stop the Feishu bot."""
        self._running = False
        if self._ws_client:
            try:
                self._ws_client.stop()
            except Exception as e:
                logger.warning(f"Error stopping WebSocket client: {e}")
        logger.info("Feishu bot stopped")

    def _add_reaction_sync(self, message_id: str, emoji_type: str) -> None:
        """Sync helper for adding reaction (runs in thread pool)."""
        try:
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
                logger.debug(f"Added {emoji_type} reaction to message {message_id}")
        except Exception as e:
            logger.warning(f"Error adding reaction: {e}")

    async def _add_reaction(self, message_id: str, emoji_type: str = "THUMBSUP") -> None:
        """Add a reaction emoji to a message (non-blocking)."""
        if not self._client or not Emoji:
            return
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._add_reaction_sync, message_id, emoji_type)

    async def send_text(self, chat_id: str, content: str) -> None:
        """Send a text message through Feishu."""
        if not self._client:
            logger.warning("Feishu client not initialized")
            return

        try:
            if chat_id.startswith("oc_"):
                receive_id_type = "chat_id"
            else:
                receive_id_type = "open_id"

            msg_content = json.dumps({"text": content})

            request = CreateMessageRequest.builder() \
                .receive_id_type(receive_id_type) \
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(chat_id)
                    .msg_type("text")
                    .content(msg_content)
                    .build()
                ).build()

            response = self._client.im.v1.message.create(request)

            if not response.success():
                logger.error(
                    f"Failed to send Feishu message: code={response.code}, "
                    f"msg={response.msg}, log_id={response.get_log_id()}"
                )
            else:
                logger.debug(f"Feishu message sent to {chat_id}")

        except Exception as e:
            logger.error(f"Error sending Feishu message: {e}")

    def _on_message_sync(self, data: "P2ImMessageReceiveV1") -> None:
        """Sync handler called from WebSocket thread. Schedules async handling."""
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._on_message(data), self._loop)

    async def _on_message(self, data: "P2ImMessageReceiveV1") -> None:
        """Handle incoming message from Feishu."""
        try:
            event = data.event
            message = event.message
            sender = event.sender

            message_id = message.message_id
            if message_id in self._processed_message_ids:
                return
            self._processed_message_ids[message_id] = None

            while len(self._processed_message_ids) > 1000:
                self._processed_message_ids.popitem(last=False)

            sender_type = sender.sender_type
            if sender_type == "bot":
                return

            sender_id = sender.sender_id.open_id if sender.sender_id else "unknown"
            chat_id = message.chat_id
            chat_type = message.chat_type
            msg_type = message.message_type

            await self._add_reaction(message_id, "THUMBSUP")

            if msg_type == "text":
                try:
                    content = json.loads(message.content).get("text", "")
                except json.JSONDecodeError:
                    content = message.content or ""
            else:
                content = MSG_TYPE_MAP.get(msg_type, f"[{msg_type}]")

            if not content:
                return

            reply_to = chat_id if chat_type == "group" else sender_id
            await self._handle_message(
                sender_id=sender_id,
                chat_id=reply_to,
                content=content,
                metadata={
                    "message_id": message_id,
                    "chat_type": chat_type,
                    "msg_type": msg_type,
                },
            )

        except Exception as e:
            logger.error(f"Error processing Feishu message: {e}")
