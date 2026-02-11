"""Feishu/Lark channel implementation using lark-oapi SDK with WebSocket long connection."""

import asyncio
import json
import re
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import FeishuConfig

try:
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import (
        CreateMessageReactionRequest,
        CreateMessageReactionRequestBody,
        CreateMessageRequest,
        CreateMessageRequestBody,
        Emoji,
        GetMessageResourceRequest,
        P2ImMessageReceiveV1,
    )
    FEISHU_AVAILABLE = True
except ImportError:
    FEISHU_AVAILABLE = False
    lark = None
    Emoji = None
    GetMessageResourceRequest = None

# Message type display mapping
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
        """
        Add a reaction emoji to a message (non-blocking).

        Common emoji types: THUMBSUP, OK, EYES, DONE, OnIt, HEART
        """
        if not self._client or not Emoji:
            return

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._add_reaction_sync, message_id, emoji_type)

    def _download_resource_sync(
        self, message_id: str, file_key: str, resource_type: str, file_name: str | None = None
    ) -> str | None:
        """
        Download resource from Feishu message using message_resource API.

        This API can download any resource (image/file/audio) from a message,
        regardless of who sent it.

        Args:
            message_id: The message ID containing the resource
            file_key: The file_key or image_key of the resource
            resource_type: "image" or "file"
            file_name: Optional filename hint for extension
        """
        if not self._client or not GetMessageResourceRequest:
            return None

        try:
            request = (
                GetMessageResourceRequest.builder()
                .message_id(message_id)
                .file_key(file_key)
                .type(resource_type)
                .build()
            )
            response = self._client.im.v1.message_resource.get(request)

            if response.code != 0:
                logger.warning(
                    f"Failed to download {resource_type}: code={response.code}, msg={response.msg}"
                )
                return None

            # Save to ~/.nanobot/media/
            media_dir = Path.home() / ".nanobot" / "media"
            media_dir.mkdir(parents=True, exist_ok=True)

            # Determine extension
            ext = ""
            if file_name:
                ext = Path(file_name).suffix
            elif response.file_name:
                ext = Path(response.file_name).suffix
            elif resource_type == "image":
                ext = ".png"  # Default for images

            file_path = media_dir / f"{file_key[:24]}{ext}"
            file_path.write_bytes(response.file.read())

            logger.debug(f"Downloaded Feishu {resource_type} to {file_path}")
            return str(file_path)

        except Exception as e:
            logger.error(f"Error downloading Feishu {resource_type}: {e}")
            return None

    async def _download_resource(
        self, message_id: str, file_key: str, resource_type: str, file_name: str | None = None
    ) -> str | None:
        """Download resource from Feishu message (async wrapper)."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._download_resource_sync, message_id, file_key, resource_type, file_name
        )

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
        def split_row(row):
            return [c.strip() for c in row.strip("|").split("|")]
        headers = split_row(lines[0])
        rows = [split_row(row) for row in lines[2:]]
        columns = [{"tag": "column", "name": f"c{i}", "display_name": h, "width": "auto"}
                   for i, h in enumerate(headers)]
        return {
            "tag": "table",
            "page_size": len(rows) + 1,
            "columns": columns,
            "rows": [{f"c{i}": r[i] if i < len(r) else "" for i in range(len(headers))} for r in rows],
        }

    def _build_card_elements(self, content: str) -> list[dict]:
        """Split content into markdown + table elements for Feishu card."""
        elements, last_end = [], 0
        for m in self._TABLE_RE.finditer(content):
            before = content[last_end:m.start()].strip()
            if before:
                elements.append({"tag": "markdown", "content": before})
            elements.append(self._parse_md_table(m.group(1)) or {"tag": "markdown", "content": m.group(1)})
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

            request = CreateMessageRequest.builder() \
                .receive_id_type(receive_id_type) \
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(msg.chat_id)
                    .msg_type("interactive")
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
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._on_message(data), self._loop)

    async def _on_message(self, data: "P2ImMessageReceiveV1") -> None:
        """Handle incoming message from Feishu."""
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

            # Parse message content and handle media
            content_parts: list[str] = []
            media_paths: list[str] = []

            try:
                msg_content = json.loads(message.content) if message.content else {}
            except json.JSONDecodeError:
                msg_content = {}

            if msg_type == "text":
                content_parts.append(msg_content.get("text", message.content or ""))

            elif msg_type == "image":
                # Download image and add to media
                image_key = msg_content.get("image_key", "")
                if image_key:
                    file_path = await self._download_resource(message_id, image_key, "image")
                    if file_path:
                        media_paths.append(file_path)
                        content_parts.append(f"[image: {file_path}]")
                    else:
                        content_parts.append("[image: download failed]")
                else:
                    content_parts.append("[image]")

            elif msg_type == "file":
                # Download file
                file_key = msg_content.get("file_key", "")
                file_name = msg_content.get("file_name", "")
                if file_key:
                    file_path = await self._download_resource(message_id, file_key, "file", file_name)
                    if file_path:
                        content_parts.append(f"[file: {file_path}]")
                    else:
                        content_parts.append(f"[file: {file_name or 'download failed'}]")
                else:
                    content_parts.append("[file]")

            elif msg_type == "audio":
                # Audio messages have file_key
                file_key = msg_content.get("file_key", "")
                if file_key:
                    file_path = await self._download_resource(message_id, file_key, "file", "audio.opus")
                    if file_path:
                        content_parts.append(f"[audio: {file_path}]")
                    else:
                        content_parts.append("[audio: download failed]")
                else:
                    content_parts.append("[audio]")

            elif msg_type == "sticker":
                content_parts.append("[sticker]")

            elif msg_type == "post":
                # Rich text post - extract text content
                title = msg_content.get("title", "")
                if title:
                    content_parts.append(f"[post: {title}]")
                # Extract text from post content
                post_content = msg_content.get("content", [])
                for paragraph in post_content:
                    for elem in paragraph:
                        if elem.get("tag") == "text":
                            content_parts.append(elem.get("text", ""))
                        elif elem.get("tag") == "img":
                            # Handle images in post
                            image_key = elem.get("image_key", "")
                            if image_key:
                                file_path = await self._download_resource(
                                    message_id, image_key, "image"
                                )
                                if file_path:
                                    media_paths.append(file_path)

            else:
                content_parts.append(f"[{msg_type}]")

            content = "\n".join(content_parts).strip()
            if not content:
                return

            # Forward to message bus
            reply_to = chat_id if chat_type == "group" else sender_id
            await self._handle_message(
                sender_id=sender_id,
                chat_id=reply_to,
                content=content,
                media=media_paths if media_paths else None,
                metadata={
                    "message_id": message_id,
                    "chat_type": chat_type,
                    "msg_type": msg_type,
                }
            )

        except Exception as e:
            logger.error(f"Error processing Feishu message: {e}")
