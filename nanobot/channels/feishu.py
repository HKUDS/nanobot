"""Feishu/Lark channel implementation using lark-oapi SDK with WebSocket long connection."""

import asyncio
import json
import os
import re
import threading
import time
from collections import OrderedDict
from typing import Any

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.channels.feishu_constants import (
    FILE_TYPE_MAP,
    IMAGE_EXTENSIONS,
    AUDIO_EXTENSIONS,
    VIDEO_EXTENSIONS,
)
from nanobot.config.schema import Config, FeishuConfig

try:
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import (
        CreateFileRequest,
        CreateFileRequestBody,
        CreateImageRequest,
        CreateImageRequestBody,
        CreateMessageReactionRequest,
        CreateMessageReactionRequestBody,
        CreateMessageRequest,
        CreateMessageRequestBody,
        Emoji,
        P2ImMessageReceiveV1,
    )
    FEISHU_AVAILABLE = True
except ImportError:
    FEISHU_AVAILABLE = False
    lark = None
    Emoji = None

# Message type display mapping
MSG_TYPE_MAP = {
    "image": "[image]",
    "audio": "[audio]",
    "file": "[file]",
    "sticker": "[sticker]",
}


def _extract_post_text(content_json: dict) -> str:
    """Extract plain text from Feishu post (rich text) message content.
    
    Supports two formats:
    1. Direct format: {"title": "...", "content": [...]}
    2. Localized format: {"zh_cn": {"title": "...", "content": [...]}}
    """
    def extract_from_lang(lang_content: dict) -> str | None:
        if not isinstance(lang_content, dict):
            return None
        title = lang_content.get("title", "")
        content_blocks = lang_content.get("content", [])
        if not isinstance(content_blocks, list):
            return None
        text_parts = []
        if title:
            text_parts.append(title)
        for block in content_blocks:
            if not isinstance(block, list):
                continue
            for element in block:
                if isinstance(element, dict):
                    tag = element.get("tag")
                    if tag == "text":
                        text_parts.append(element.get("text", ""))
                    elif tag == "a":
                        text_parts.append(element.get("text", ""))
                    elif tag == "at":
                        text_parts.append(f"@{element.get('user_name', 'user')}")
        return " ".join(text_parts).strip() if text_parts else None
    
    # Try direct format first
    if "content" in content_json:
        result = extract_from_lang(content_json)
        if result:
            return result
    
    # Try localized format
    for lang_key in ("zh_cn", "en_us", "ja_jp"):
        lang_content = content_json.get(lang_key)
        result = extract_from_lang(lang_content)
        if result:
            return result
    
    return ""


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

    def __init__(self, config: FeishuConfig, bus: MessageBus, full_config: Config | None = None):
        super().__init__(config, bus)
        self.config: FeishuConfig = config
        self._full_config: Config | None = full_config
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
        
        # Start WebSocket client in a separate thread with reconnect loop
        def run_ws():
            while self._running:
                try:
                    self._ws_client.start()
                except Exception as e:
                    logger.warning(f"Feishu WebSocket error: {e}")
                if self._running:
                    time.sleep(5)
        
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
    
    # Regex to match markdown tables (header + separator + data rows)
    _TABLE_RE = re.compile(
        r"((?:^[ \t]*\|.+\|[ \t]*\n)(?:^[ \t]*\|[-:\s|]+\|[ \t]*\n)(?:^[ \t]*\|.+\|[ \t]*\n?)+)",
        re.MULTILINE,
    )

    _HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

    _CODE_BLOCK_RE = re.compile(r"(```[\s\S]*?```)", re.MULTILINE)

    @staticmethod
    def _parse_md_table(table_text: str) -> dict | None:
        """Parse a markdown table into a Feishu table element."""
        lines = [l.strip() for l in table_text.strip().split("\n") if l.strip()]
        if len(lines) < 3:
            return None
        split = lambda l: [c.strip() for c in l.strip("|").split("|")]
        headers = split(lines[0])
        rows = [split(l) for l in lines[2:]]
        columns = [{"tag": "column", "name": f"c{i}", "display_name": h, "width": "auto"}
                   for i, h in enumerate(headers)]
        return {
            "tag": "table",
            "page_size": len(rows) + 1,
            "columns": columns,
            "rows": [{f"c{i}": r[i] if i < len(r) else "" for i in range(len(headers))} for r in rows],
        }

    def _build_card_elements(self, content: str) -> list[dict]:
        """Split content into div/markdown + table elements for Feishu card."""
        elements, last_end = [], 0
        for m in self._TABLE_RE.finditer(content):
            before = content[last_end:m.start()]
            if before.strip():
                elements.extend(self._split_headings(before))
            elements.append(self._parse_md_table(m.group(1)) or {"tag": "markdown", "content": m.group(1)})
            last_end = m.end()
        remaining = content[last_end:]
        if remaining.strip():
            elements.extend(self._split_headings(remaining))
        return elements or [{"tag": "markdown", "content": content}]

    def _split_headings(self, content: str) -> list[dict]:
        """Split content by headings, converting headings to div elements."""
        protected = content
        code_blocks = []
        for m in self._CODE_BLOCK_RE.finditer(content):
            code_blocks.append(m.group(1))
            protected = protected.replace(m.group(1), f"\x00CODE{len(code_blocks)-1}\x00", 1)

        elements = []
        last_end = 0
        for m in self._HEADING_RE.finditer(protected):
            before = protected[last_end:m.start()].strip()
            if before:
                elements.append({"tag": "markdown", "content": before})
            text = m.group(2).strip()
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**{text}**",
                },
            })
            last_end = m.end()
        remaining = protected[last_end:].strip()
        if remaining:
            elements.append({"tag": "markdown", "content": remaining})

        for i, cb in enumerate(code_blocks):
            for el in elements:
                if el.get("tag") == "markdown":
                    el["content"] = el["content"].replace(f"\x00CODE{i}\x00", cb)

        return elements or [{"tag": "markdown", "content": content}]

    def _validate_file_path(self, file_path: str) -> tuple[bool, str]:
        """Validate file path against allowlist.

        Returns:
            (is_valid, error_message)
        """
        from pathlib import Path

        try:
            abs_path = Path(file_path).resolve()
        except Exception as e:
            return False, f"Invalid path: {e}"

        file_name = abs_path.name

        allowlist: list[str] = []
        workspace: Path | None = None

        if self._full_config:
            allowlist = self._full_config.tools.file_upload_allowlist or []
            workspace = self._full_config.workspace_path

        if not allowlist:
            if workspace:
                allowlist = [str(workspace)]
            else:
                allowlist = [str(Path.cwd())]

        for allowed_dir in allowlist:
            try:
                allowed_path = Path(allowed_dir).expanduser().resolve()
                abs_path_str = abs_path.as_posix()
                allowed_path_str = allowed_path.as_posix()
                if allowed_path_str != "/":
                    allowed_path_str = allowed_path_str.rstrip("/")

                # Match exact directory or descendant paths only.
                # Example: "/workspace" matches "/workspace/a.txt" but not "/workspace2/a.txt".
                pattern = (
                    r"^/" if allowed_path_str == "/" else rf"^{re.escape(allowed_path_str)}(?:/|$)"
                )
                if re.match(pattern, abs_path_str):
                    return True, ""
            except Exception:
                continue

        return False, f"Path not in allowlist: {file_name}"

    def _upload_file_sync(self, file_path: str) -> tuple[str | None, str]:
        """Upload a file to Feishu and return (file_key, msg_type)."""
        from pathlib import Path

        file_name = Path(file_path).name if file_path else "unknown"

        is_valid, error_msg = self._validate_file_path(file_path)
        if not is_valid:
            logger.error(f"File access denied: {error_msg}")
            return None, "file"

        try:
            if not os.path.exists(file_path):
                logger.error(f"File not found: {file_name}")
                return None, "file"

            file_size = os.path.getsize(file_path)
            if file_size == 0:
                logger.error(f"Cannot upload empty file: {file_name}")
                return None, "file"

            ext = os.path.splitext(file_path.lower())[1]

            if ext in IMAGE_EXTENSIONS:
                if file_size > 10 * 1024 * 1024:
                    logger.error(f"Image too large: {file_name} ({file_size} bytes, max 10MB)")
                    return None, "image"
                with open(file_path, "rb") as f:
                    request = CreateImageRequest.builder() \
                        .request_body(
                            CreateImageRequestBody.builder()
                            .image_type("message")
                            .image(f)
                            .build()
                        ).build()
                    response = self._client.im.v1.image.create(request)
                    if response.success() and response.data and response.data.image_key:
                        logger.debug(f"Image uploaded: {file_name}")
                        return response.data.image_key, "image"
                    logger.error(f"Failed to upload image {file_name}: code={response.code}, msg={response.msg}")
                    return None, "image"

            if file_size > 30 * 1024 * 1024:
                logger.error(f"File too large: {file_name} ({file_size} bytes, max 30MB)")
                return None, "file"

            file_type = FILE_TYPE_MAP.get(ext, "stream")
            with open(file_path, "rb") as f:
                request = CreateFileRequest.builder() \
                    .request_body(
                        CreateFileRequestBody.builder()
                        .file_type(file_type)
                        .file_name(file_name)
                        .file(f)
                        .build()
                    ).build()
                response = self._client.im.v1.file.create(request)
                if response.success() and response.data and response.data.file_key:
                    logger.debug(f"File uploaded: {file_name}")
                    if ext in VIDEO_EXTENSIONS:
                        return response.data.file_key, "media"
                    if ext in AUDIO_EXTENSIONS:
                        return response.data.file_key, "audio"
                    return response.data.file_key, "file"
                logger.error(f"Failed to upload file {file_name}: code={response.code}, msg={response.msg}")
                return None, "file"

        except Exception as e:
            logger.error(f"Error uploading file {file_name}: {e}")
            return None, "file"

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

            media_sent = 0
            media_failed = 0
            text_sent = False

            for file_path in msg.media or []:
                file_key, msg_type = await asyncio.get_running_loop().run_in_executor(
                    None, self._upload_file_sync, file_path
                )
                if file_key:
                    key_field = "image_key" if msg_type == "image" else "file_key"
                    content = json.dumps({key_field: file_key}, ensure_ascii=False)
                    request = CreateMessageRequest.builder() \
                        .receive_id_type(receive_id_type) \
                        .request_body(
                            CreateMessageRequestBody.builder()
                            .receive_id(msg.chat_id)
                            .msg_type(msg_type)
                            .content(content)
                            .build()
                        ).build()
                    response = self._client.im.v1.message.create(request)
                    if response.success():
                        media_sent += 1
                    else:
                        media_failed += 1
                        logger.error(f"Failed to send file: code={response.code}, msg={response.msg}")
                else:
                    media_failed += 1

            # Send text message
            if msg.content.strip():

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
                if response.success():
                    text_sent = True
                else:
                    logger.error(
                        f"Failed to send text message: code={response.code}, "
                        f"msg={response.msg}, log_id={response.get_log_id()}"
                    )

            total_media = media_sent + media_failed
            if total_media > 0 or text_sent:
                logger.debug(
                    f"Feishu send result: media={media_sent}/{total_media}, text={text_sent}"
                )

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
            
            # Parse message content
            if msg_type == "text":
                try:
                    content = json.loads(message.content).get("text", "")
                except json.JSONDecodeError:
                    content = message.content or ""
            elif msg_type == "post":
                try:
                    content_json = json.loads(message.content)
                    content = _extract_post_text(content_json)
                except (json.JSONDecodeError, TypeError):
                    content = message.content or ""
            else:
                content = MSG_TYPE_MAP.get(msg_type, f"[{msg_type}]")
            
            if not content:
                return
            
            # Forward to message bus
            reply_to = chat_id if chat_type == "group" else sender_id
            await self._handle_message(
                sender_id=sender_id,
                chat_id=reply_to,
                content=content,
                metadata={
                    "message_id": message_id,
                    "chat_type": chat_type,
                    "msg_type": msg_type,
                }
            )
            
        except Exception as e:
            logger.error(f"Error processing Feishu message: {e}")
