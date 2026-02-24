"""Feishu/Lark channel implementation using lark-oapi SDK with WebSocket long connection."""

import asyncio
import json
import re
import threading
import time
import uuid
from collections import OrderedDict
from typing import Any

from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import FeishuConfig

try:
    import lark_oapi as lark
    from lark_oapi.api.cardkit.v1 import (
        ContentCardElementRequest,
        ContentCardElementRequestBody,
        CreateCardRequest,
        CreateCardRequestBody,
        SettingsCardRequest,
        SettingsCardRequestBody,
    )
    from lark_oapi.api.im.v1 import (
        CreateMessageReactionRequest,
        CreateMessageReactionRequestBody,
        CreateMessageRequest,
        CreateMessageRequestBody,
        Emoji,
        P2ImMessageReceiveV1,
    )

    FEISHU_AVAILABLE = True
    CARDKIT_AVAILABLE = True
except ImportError:
    FEISHU_AVAILABLE = False
    CARDKIT_AVAILABLE = False
    lark = None
    Emoji = None

# Message type display mapping
MSG_TYPE_MAP = {
    "image": "[image]",
    "audio": "[audio]",
    "file": "[file]",
    "sticker": "[sticker]",
}


class FeishuStreamingSession:
    """Manages a streaming card session using CardKit streaming API."""

    ELEMENT_ID = "streaming_content"  # Fixed element ID for streaming updates

    def __init__(self, client: Any, chat_id: str, receive_id_type: str):
        self.client = client
        self.chat_id = chat_id
        self.receive_id_type = receive_id_type
        self.card_id: str | None = None
        self.current_text = ""
        self.closed = False
        self.last_update_time = 0.0
        self.pending_text: str | None = None
        self._sequence = 0
        self._lock = threading.Lock()

    def _build_streaming_card_json(self, initial_text: str = "Thinking...") -> str:
        """Build Card JSON 2.0 with streaming mode enabled."""
        card = {
            "schema": "2.0",
            "header": {"title": {"content": "🤖 AI Assistant", "tag": "plain_text"}},
            "config": {
                "streaming_mode": True,
                "summary": {"content": "[生成中...]"},
                "streaming_config": {
                    "print_frequency_ms": {"default": 50},
                    "print_step": {"default": 2},
                    "print_strategy": "fast",
                },
            },
            "body": {
                "elements": [
                    {
                        "tag": "markdown",
                        "content": initial_text,
                        "element_id": self.ELEMENT_ID,
                    }
                ]
            },
        }
        return json.dumps(card, ensure_ascii=False)

    def start_sync(self) -> bool:
        """Create card entity and send it (sync)."""
        if self.card_id:
            return True

        if not CARDKIT_AVAILABLE:
            logger.warning("CardKit API not available, falling back to simple mode")
            return False

        try:
            # Step 1: Create card entity with streaming mode
            card_json = self._build_streaming_card_json()
            create_request = (
                CreateCardRequest.builder()
                .request_body(
                    CreateCardRequestBody.builder().type("card_json").data(card_json).build()
                )
                .build()
            )

            create_response = self.client.cardkit.v1.card.create(create_request)
            if not create_response.success():
                logger.error(
                    f"Failed to create card entity: code={create_response.code}, "
                    f"msg={create_response.msg}. "
                    "Check if app has 'cardkit:card:write' permission."
                )
                return False

            self.card_id = create_response.data.card_id

            # Step 2: Send card entity as message
            msg_content = json.dumps(
                {"type": "card", "data": {"card_id": self.card_id}}, ensure_ascii=False
            )
            send_request = (
                CreateMessageRequest.builder()
                .receive_id_type(self.receive_id_type)
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(self.chat_id)
                    .msg_type("interactive")
                    .content(msg_content)
                    .build()
                )
                .build()
            )

            send_response = self.client.im.v1.message.create(send_request)
            if not send_response.success():
                logger.error(f"Failed to send card: {send_response.msg}")
                return False
            return True

        except Exception as e:
            logger.error(f"Error starting streaming session: {e}")
            return False

    def update_sync(self, text: str) -> bool:
        """Stream update text content using CardKit API (sync, with throttling)."""
        if self.closed or not self.card_id:
            return False

        with self._lock:
            now = time.time() * 1000
            # Throttle: max 10 requests/sec (100ms interval)
            if now - self.last_update_time < 100:
                self.pending_text = text  # Save for later
                return True  # Skip this update, will catch up

            self.pending_text = text
            self._sequence += 1
            seq = self._sequence
            self.current_text = text
            self.last_update_time = now

        try:
            # Use CardKit streaming content API
            # Each request needs a unique UUID for idempotency
            request = (
                ContentCardElementRequest.builder()
                .card_id(self.card_id)
                .element_id(self.ELEMENT_ID)
                .request_body(
                    ContentCardElementRequestBody.builder()
                    .content(text)
                    .uuid(str(uuid.uuid4()))  # New UUID for each request
                    .sequence(seq)
                    .build()
                )
                .build()
            )

            response = self.client.cardkit.v1.card_element.content(request)
            return response.success()
        except Exception:
            return False

    def close_sync(self, final_text: str | None = None) -> bool:
        """Close streaming mode and finalize card (sync)."""
        if self.closed:
            return True
        self.closed = True

        if not self.card_id:
            return False

        text = final_text or self.pending_text or self.current_text or "Done."

        try:
            # Final content update
            with self._lock:
                self._sequence += 1
                seq = self._sequence

            content_request = (
                ContentCardElementRequest.builder()
                .card_id(self.card_id)
                .element_id(self.ELEMENT_ID)
                .request_body(
                    ContentCardElementRequestBody.builder()
                    .content(text)
                    .uuid(str(uuid.uuid4()))  # New UUID for each request
                    .sequence(seq)
                    .build()
                )
                .build()
            )
            self.client.cardkit.v1.card_element.content(content_request)

            # Close streaming mode
            settings_json = json.dumps({"config": {"streaming_mode": False}}, ensure_ascii=False)
            settings_request = (
                SettingsCardRequest.builder()
                .card_id(self.card_id)
                .request_body(
                    SettingsCardRequestBody.builder()
                    .settings(settings_json)
                    .uuid(str(uuid.uuid4()))  # New UUID for each request
                    .sequence(seq + 1)
                    .build()
                )
                .build()
            )

            return self.client.cardkit.v1.card.settings(settings_request).success()
        except Exception:
            return False


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
        self._processed_message_ids: OrderedDict[str, None] = OrderedDict()  # Ordered dedup cache
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

        # Create Lark client for sending messages
        self._client = (
            lark.Client.builder()
            .app_id(self.config.app_id)
            .app_secret(self.config.app_secret)
            .log_level(lark.LogLevel.INFO)
            .build()
        )

        # Create event handler (only register message receive, ignore other events)
        event_handler = (
            lark.EventDispatcherHandler.builder(
                self.config.encrypt_key or "",
                self.config.verification_token or "",
            )
            .register_p2_im_message_receive_v1(self._on_message_sync)
            .build()
        )

        # Create WebSocket client for long connection
        self._ws_client = lark.ws.Client(
            self.config.app_id,
            self.config.app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO,
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
        if self._ws_client:
            try:
                self._ws_client.stop()
            except Exception as e:
                logger.warning(f"Error stopping WebSocket client: {e}")
        logger.info("Feishu bot stopped")

    async def _add_reaction(self, message_id: str, emoji_type: str = "THUMBSUP") -> None:
        """Add a reaction emoji to a message (non-blocking)."""
        if not self._client or not Emoji:
            return

        def add_sync():
            try:
                request = (
                    CreateMessageReactionRequest.builder()
                    .message_id(message_id)
                    .request_body(
                        CreateMessageReactionRequestBody.builder()
                        .reaction_type(Emoji.builder().emoji_type(emoji_type).build())
                        .build()
                    )
                    .build()
                )
                self._client.im.v1.message_reaction.create(request)
            except Exception:
                pass

        await asyncio.get_running_loop().run_in_executor(None, add_sync)

    # Regex to match markdown tables (header + separator + data rows)
    _TABLE_RE = re.compile(
        r"((?:^[ \t]*\|.+\|[ \t]*\n)(?:^[ \t]*\|[-:\s|]+\|[ \t]*\n)(?:^[ \t]*\|.+\|[ \t]*\n?)+)",
        re.MULTILINE,
    )

    @staticmethod
    def _parse_md_table(table_text: str) -> dict | None:
        """Parse a markdown table into a Feishu table element."""
        lines = [line.strip() for line in table_text.strip().split("\n") if line.strip()]
        if len(lines) < 3:
            return None

        def split_row(row: str) -> list[str]:
            return [c.strip() for c in row.strip("|").split("|")]

        headers = split_row(lines[0])
        rows = [split_row(row) for row in lines[2:]]
        columns = [
            {"tag": "column", "name": f"c{i}", "display_name": h, "width": "auto"}
            for i, h in enumerate(headers)
        ]
        return {
            "tag": "table",
            "page_size": len(rows) + 1,
            "columns": columns,
            "rows": [
                {f"c{i}": r[i] if i < len(r) else "" for i in range(len(headers))} for r in rows
            ],
        }

    def _build_card_elements(self, content: str) -> list[dict]:
        """Split content into markdown + table elements for Feishu card."""
        elements, last_end = [], 0
        for m in self._TABLE_RE.finditer(content):
            before = content[last_end : m.start()].strip()
            if before:
                elements.append({"tag": "markdown", "content": before})
            elements.append(
                self._parse_md_table(m.group(1)) or {"tag": "markdown", "content": m.group(1)}
            )
            last_end = m.end()
        remaining = content[last_end:].strip()
        if remaining:
            elements.append({"tag": "markdown", "content": remaining})
        return elements or [{"tag": "markdown", "content": content}]

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

            # Build card with markdown + table support
            elements = self._build_card_elements(msg.content)
            card = {
                "config": {"wide_screen_mode": True},
                "elements": elements,
            }
            content = json.dumps(card, ensure_ascii=False)

            request = (
                CreateMessageRequest.builder()
                .receive_id_type(receive_id_type)
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(msg.chat_id)
                    .msg_type("interactive")
                    .content(content)
                    .build()
                )
                .build()
            )

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
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._on_message(data), self._loop)

    async def _on_message(self, data: "P2ImMessageReceiveV1") -> None:
        """Handle incoming message from Feishu with streaming support."""
        try:
            event = data.event
            message = event.message
            sender = event.sender

            # Deduplication check
            message_id = message.message_id
            if message_id in self._processed_message_ids:
                return
            self._processed_message_ids[message_id] = None

            # Trim cache: keep most recent 500 when exceeds 1000
            while len(self._processed_message_ids) > 1000:
                self._processed_message_ids.popitem(last=False)

            # Skip bot messages
            sender_type = sender.sender_type
            if sender_type == "bot":
                return

            sender_id = sender.sender_id.open_id if sender.sender_id else "unknown"
            chat_id = message.chat_id
            chat_type = message.chat_type  # "p2p" or "group"
            msg_type = message.message_type

            # Add reaction to indicate "seen"
            await self._add_reaction(message_id, "THUMBSUP")

            # Parse message content
            if msg_type == "text":
                try:
                    content = json.loads(message.content).get("text", "")
                except json.JSONDecodeError:
                    content = message.content or ""
            else:
                content = MSG_TYPE_MAP.get(msg_type, f"[{msg_type}]")

            if not content:
                return

            # Determine reply target
            reply_to = chat_id if chat_type == "group" else sender_id
            receive_id_type = "chat_id" if reply_to.startswith("oc_") else "open_id"

            # Check permission first
            if not self.is_allowed(sender_id):
                logger.warning(
                    f"Access denied for sender {sender_id} on channel {self.name}. "
                    f"Add them to allowFrom list in config to grant access."
                )
                return

            # Try to create streaming session
            stream_id = str(uuid.uuid4())
            streaming_session: FeishuStreamingSession | None = None
            use_streaming = False
            loop = asyncio.get_running_loop()

            if CARDKIT_AVAILABLE:
                streaming_session = FeishuStreamingSession(
                    client=self._client, chat_id=reply_to, receive_id_type=receive_id_type
                )
                use_streaming = await loop.run_in_executor(None, streaming_session.start_sync)
                if not use_streaming:
                    streaming_session = None

            if use_streaming and streaming_session:
                # Accumulated text for updates
                accumulated_text = ""
                accumulated_lock = threading.Lock()

                def stream_callback(chunk: str) -> None:
                    """Callback invoked for each streaming chunk (non-blocking)."""
                    nonlocal accumulated_text
                    with accumulated_lock:
                        accumulated_text += chunk
                        text_snapshot = accumulated_text
                    # Submit update to thread pool (fire-and-forget)
                    try:
                        loop.run_in_executor(None, streaming_session.update_sync, text_snapshot)
                    except RuntimeError:
                        # Loop might be closed
                        pass

                # Register callback with bus
                self.bus.register_stream_callback(stream_id, stream_callback)

            # Create and publish inbound message
            msg = InboundMessage(
                channel=self.name,
                sender_id=str(sender_id),
                chat_id=str(reply_to),
                content=content,
                metadata={
                    "message_id": message_id,
                    "chat_type": chat_type,
                    "msg_type": msg_type,
                },
                stream_id=stream_id if use_streaming else None,
            )

            await self.bus.publish_inbound(msg)

            # Wait for response and close streaming session if active
            if use_streaming and streaming_session:
                await self._wait_and_close_stream(streaming_session)

        except Exception as e:
            logger.error(f"Error processing Feishu message: {e}")

    async def _wait_and_close_stream(self, session: "FeishuStreamingSession") -> None:
        """Wait for response completion and close streaming session."""
        max_wait, check_interval, waited = 300, 0.2, 0.0
        loop = asyncio.get_running_loop()

        while waited < max_wait and not session.closed:
            await asyncio.sleep(check_interval)
            waited += check_interval
            # Close when idle > 1s (response complete)
            if session.current_text and session.last_update_time > 0:
                if (time.time() * 1000 - session.last_update_time) / 1000 > 1.0:
                    await loop.run_in_executor(
                        None, session.close_sync, session.pending_text or session.current_text
                    )
                    return

        if not session.closed:
            await loop.run_in_executor(
                None, session.close_sync, session.current_text or "Response timeout."
            )
