"""Feishu/Lark channel implementation using lark-oapi SDK with WebSocket long connection."""

import asyncio
import json
import os
import re
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

from loguru import logger

try:
    import requests as _requests
except ImportError:
    _requests = None  # type: ignore

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import FeishuConfig

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
        DeleteMessageReactionRequest,
        Emoji,
        GetMessageResourceRequest,
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


def _extract_share_card_content(content_json: dict, msg_type: str) -> str:
    """Extract text representation from share cards and interactive messages."""
    parts = []

    if msg_type == "share_chat":
        parts.append(f"[shared chat: {content_json.get('chat_id', '')}]")
    elif msg_type == "share_user":
        parts.append(f"[shared user: {content_json.get('user_id', '')}]")
    elif msg_type == "interactive":
        parts.extend(_extract_interactive_content(content_json))
    elif msg_type == "share_calendar_event":
        parts.append(f"[shared calendar event: {content_json.get('event_key', '')}]")
    elif msg_type == "system":
        parts.append("[system message]")
    elif msg_type == "merge_forward":
        parts.append("[merged forward messages]")

    return "\n".join(parts) if parts else f"[{msg_type}]"


def _extract_interactive_content(content: dict) -> list[str]:
    """Recursively extract text and links from interactive card content."""
    parts = []

    if isinstance(content, str):
        try:
            content = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return [content] if content.strip() else []

    if not isinstance(content, dict):
        return parts

    if "title" in content:
        title = content["title"]
        if isinstance(title, dict):
            title_content = title.get("content", "") or title.get("text", "")
            if title_content:
                parts.append(f"title: {title_content}")
        elif isinstance(title, str):
            parts.append(f"title: {title}")

    for elements in content.get("elements", []) if isinstance(content.get("elements"), list) else []:
        for element in elements:
            parts.extend(_extract_element_content(element))

    card = content.get("card", {})
    if card:
        parts.extend(_extract_interactive_content(card))

    header = content.get("header", {})
    if header:
        header_title = header.get("title", {})
        if isinstance(header_title, dict):
            header_text = header_title.get("content", "") or header_title.get("text", "")
            if header_text:
                parts.append(f"title: {header_text}")

    return parts


def _extract_element_content(element: dict) -> list[str]:
    """Extract content from a single card element."""
    parts = []

    if not isinstance(element, dict):
        return parts

    tag = element.get("tag", "")

    if tag in ("markdown", "lark_md"):
        content = element.get("content", "")
        if content:
            parts.append(content)

    elif tag == "div":
        text = element.get("text", {})
        if isinstance(text, dict):
            text_content = text.get("content", "") or text.get("text", "")
            if text_content:
                parts.append(text_content)
        elif isinstance(text, str):
            parts.append(text)
        for field in element.get("fields", []):
            if isinstance(field, dict):
                field_text = field.get("text", {})
                if isinstance(field_text, dict):
                    c = field_text.get("content", "")
                    if c:
                        parts.append(c)

    elif tag == "a":
        href = element.get("href", "")
        text = element.get("text", "")
        if href:
            parts.append(f"link: {href}")
        if text:
            parts.append(text)

    elif tag == "button":
        text = element.get("text", {})
        if isinstance(text, dict):
            c = text.get("content", "")
            if c:
                parts.append(c)
        url = element.get("url", "") or element.get("multi_url", {}).get("url", "")
        if url:
            parts.append(f"link: {url}")

    elif tag == "img":
        alt = element.get("alt", {})
        parts.append(alt.get("content", "[image]") if isinstance(alt, dict) else "[image]")

    elif tag == "note":
        for ne in element.get("elements", []):
            parts.extend(_extract_element_content(ne))

    elif tag == "column_set":
        for col in element.get("columns", []):
            for ce in col.get("elements", []):
                parts.extend(_extract_element_content(ce))

    elif tag == "plain_text":
        content = element.get("content", "")
        if content:
            parts.append(content)

    else:
        for ne in element.get("elements", []):
            parts.extend(_extract_element_content(ne))

    return parts


def _extract_post_content(content_json: dict) -> tuple[str, list[str]]:
    """Extract text and image keys from Feishu post (rich text) message.

    Handles three payload shapes:
    - Direct:    {"title": "...", "content": [[...]]}
    - Localized: {"zh_cn": {"title": "...", "content": [...]}}
    - Wrapped:   {"post": {"zh_cn": {"title": "...", "content": [...]}}}
    """

    def _parse_block(block: dict) -> tuple[str | None, list[str]]:
        if not isinstance(block, dict) or not isinstance(block.get("content"), list):
            return None, []
        texts, images = [], []
        if title := block.get("title"):
            texts.append(title)
        for row in block["content"]:
            if not isinstance(row, list):
                continue
            for el in row:
                if not isinstance(el, dict):
                    continue
                tag = el.get("tag")
                if tag in ("text", "a"):
                    texts.append(el.get("text", ""))
                elif tag == "at":
                    texts.append(f"@{el.get('user_name', 'user')}")
                elif tag == "img" and (key := el.get("image_key")):
                    images.append(key)
        return (" ".join(texts).strip() or None), images

    # Unwrap optional {"post": ...} envelope
    root = content_json
    if isinstance(root, dict) and isinstance(root.get("post"), dict):
        root = root["post"]
    if not isinstance(root, dict):
        return "", []

    # Direct format
    if "content" in root:
        text, imgs = _parse_block(root)
        if text or imgs:
            return text or "", imgs

    # Localized: prefer known locales, then fall back to any dict child
    for key in ("zh_cn", "en_us", "ja_jp"):
        if key in root:
            text, imgs = _parse_block(root[key])
            if text or imgs:
                return text or "", imgs
    for val in root.values():
        if isinstance(val, dict):
            text, imgs = _parse_block(val)
            if text or imgs:
                return text or "", imgs

    return "", []



def _should_use_card(text: str) -> bool:
    """Detect if text contains markdown that benefits from card rendering."""
    return bool(
        re.search(r"```[\s\S]*?```", text) or
        re.search(r"\|.+\|[\r\n]+\|[-:| ]+\|", text)
    )


def _check_bot_mentioned(mentions: list[dict], bot_open_id: str | None) -> bool:
    """Check if bot is @mentioned in a message."""
    if not bot_open_id:
        return False
    return any(m.get("id", {}).get("open_id") == bot_open_id for m in mentions)


def _strip_bot_mention(text: str, mentions: list[dict]) -> str:
    """Remove @BotName tokens from message text."""
    result = text
    for m in mentions:
        name = m.get("name", "")
        key = m.get("key", "")
        if name:
            result = re.sub(rf"@{re.escape(name)}\s*", "", result)
        if key:
            result = result.replace(key, "")
    return result.strip()


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

    def __init__(self, config: FeishuConfig, bus: MessageBus, agent_pool: Any = None):
        super().__init__(config, bus)
        self.config: FeishuConfig = config
        self.agent_pool = agent_pool
        self._client: Any = None
        self._ws_client: Any = None
        self._ws_thread: threading.Thread | None = None
        self._clients: dict[str, Any] = {}
        self._ws_clients: dict[str, Any] = {}
        self._ws_threads: dict[str, threading.Thread] = {}
        self._app_id_to_account: dict[str, str] = {}
        self._processed_message_ids: OrderedDict[str, None] = OrderedDict()  # Ordered dedup cache
        self._loop: asyncio.AbstractEventLoop | None = None
        self._bot_open_ids: dict[str, str] = {}  # account_id -> bot open_id

    def _get_accounts(self) -> dict[str, dict[str, str]]:
        """Get accounts dict with backward compatibility.

        Returns dict[accountId, {app_id, app_secret}].
        If config.accounts is empty, use legacy appId/appSecret as "default" account.
        """
        if self.config.accounts:
            return {
                account_id: {
                    "app_id": account.app_id,
                    "app_secret": account.app_secret,
                }
                for account_id, account in self.config.accounts.items()
            }
        return {
            "default": {
                "app_id": self.config.app_id,
                "app_secret": self.config.app_secret,
            }
        }

    def _identify_account(self, app_id: str) -> str | None:
        """Map appId to accountId using the internal mapping."""
        return self._app_id_to_account.get(app_id)

    async def start(self) -> None:
        """Start the Feishu bot with WebSocket long connection."""
        if not FEISHU_AVAILABLE:
            logger.error("Feishu SDK not installed. Run: pip install lark-oapi")
            return

        accounts = self._get_accounts()
        if not accounts:
            logger.error("No Feishu accounts configured")
            return

        self._running = True
        self._loop = asyncio.get_running_loop()

        # Create clients and WebSocket connections for each account
        for account_id, account_info in accounts.items():
            app_id = account_info["app_id"]
            app_secret = account_info["app_secret"]

            # Create Lark client for sending messages
            client = lark.Client.builder() \
                .app_id(app_id) \
                .app_secret(app_secret) \
                .log_level(lark.LogLevel.INFO) \
                .build()
            self._clients[account_id] = client

            # Fetch bot open_id for mention detection
            loop = asyncio.get_running_loop()
            open_id = await loop.run_in_executor(None, self._fetch_bot_open_id_sync, client)
            if open_id:
                self._bot_open_ids[account_id] = open_id
                logger.info("Feishu bot open_id for {}: {}", account_id, open_id)

            # Create event handler
            event_handler = lark.EventDispatcherHandler.builder(
                self.config.encrypt_key or "",
                self.config.verification_token or "",
            ).register_p2_im_message_receive_v1(
                lambda data, aid=account_id: self._on_message_sync(data, aid)
            ).build()

            # Create WebSocket client
            ws_client = lark.ws.Client(
                app_id,
                app_secret,
                event_handler=event_handler,
                log_level=lark.LogLevel.INFO
            )
            self._ws_clients[account_id] = ws_client

            # Start WebSocket in thread
            def run_ws(ws_client=ws_client, aid=account_id):
                while self._running:
                    try:
                        ws_client.start()
                    except Exception as e:
                        logger.warning("Feishu WebSocket error ({}): {}", aid, e)
                    if self._running:
                        time.sleep(5)

            ws_thread = threading.Thread(target=run_ws, daemon=True)
            ws_thread.start()
            self._ws_threads[account_id] = ws_thread

            # Build reverse mapping
            self._app_id_to_account[app_id] = account_id

        logger.info("Feishu bot started with {} account(s)", len(accounts))

        # Keep running until stopped
        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """
        Stop the Feishu bot.

        Notice: lark.ws.Client does not expose stop method， simply exiting the program will close the client.

        Reference: https://github.com/larksuite/oapi-sdk-python/blob/v2_main/lark_oapi/ws/client.py#L86
        """
        self._running = False
        logger.info("Feishu bot stopped")

    def _fetch_bot_open_id_sync(self, client: Any) -> str | None:
        """Fetch this bot's own open_id via /open-apis/bot/v3/info."""
        try:
            cfg = client.config
            token_resp = _requests.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": cfg.app_id, "app_secret": cfg.app_secret},
                timeout=10,
            )
            token_data = token_resp.json()
            token = token_data.get("tenant_access_token")
            if not token:
                return None
            bot_resp = _requests.get(
                "https://open.feishu.cn/open-apis/bot/v3/info",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            data = bot_resp.json()
            if data.get("code") == 0:
                return data.get("bot", {}).get("open_id")
            return None
        except Exception as e:
            logger.warning("Failed to fetch bot open_id: {}", e)
            return None

    _sender_name_cache: dict[str, tuple[str, float]] = {}
    _SENDER_NAME_TTL = 600.0  # 10 minutes

    def _fetch_sender_name_sync(self, open_id: str, client: Any) -> str | None:
        """Fetch display name for a user open_id (cached)."""
        import time
        cached = self._sender_name_cache.get(open_id)
        if cached and cached[1] > time.time():
            return cached[0]
        try:
            from lark_oapi.api.contact.v3 import GetUserRequest
            request = GetUserRequest.builder() \
                .user_id(open_id) \
                .user_id_type("open_id") \
                .build()
            res = client.contact.v3.user.get(request)
            if res.success() and res.data and res.data.user:
                name = res.data.user.name or getattr(res.data.user, "nickname", None)
                if name:
                    self._sender_name_cache[open_id] = (name, time.time() + self._SENDER_NAME_TTL)
                    return name
        except Exception as e:
            logger.debug("Failed to fetch sender name for {}: {}", open_id, e)
        return None

    async def _handle_group_message(
        self,
        sender_id: str,
        chat_id: str,
        content: str,
        message_id: str,
        mentions: list[dict],
        account_id: str,
        media: list[str] | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Handle group message with group-level permission and mention gating."""
        # 1. Group allowlist check
        group_allow_from = self.config.group_allow_from
        if group_allow_from and chat_id not in group_allow_from:
            logger.debug("Feishu group {} not in group_allow_from, skipping", chat_id)
            return

        # 2. requireMention check
        if self.config.require_mention:
            bot_open_id = self._bot_open_ids.get(account_id)
            if not _check_bot_mentioned(mentions, bot_open_id):
                logger.debug("Feishu group message in {} not mentioning bot, skipping", chat_id)
                return
            content = _strip_bot_mention(content, mentions)

        # 3. Sender name injection
        client = self._clients.get(account_id)
        if client and sender_id:
            loop = asyncio.get_running_loop()
            name = await loop.run_in_executor(None, self._fetch_sender_name_sync, sender_id, client)
            if name:
                content = f"[{name}]: {content}" if content else f"[{name}]"

        # 4. Forward to bus
        from nanobot.bus.events import InboundMessage
        msg_meta = {**(metadata or {}), "message_id": message_id, "account_id": account_id}
        msg = InboundMessage(
            channel=self.name,
            sender_id=sender_id,
            chat_id=chat_id,
            content=content,
            media=media or [],
            metadata=msg_meta,
        )
        await self.bus.publish_inbound(msg)

    def _add_reaction_sync(self, message_id: str, emoji_type: str, client=None) -> str | None:
        """Sync helper for adding reaction (runs in thread pool). Returns reaction_id."""
        try:
            # Use provided client or fallback to legacy _client
            c = client or self._client
            if not c:
                return None

            request = CreateMessageReactionRequest.builder() \
                .message_id(message_id) \
                .request_body(
                    CreateMessageReactionRequestBody.builder()
                    .reaction_type(Emoji.builder().emoji_type(emoji_type).build())
                    .build()
                ).build()

            response = c.im.v1.message_reaction.create(request)

            if not response.success():
                logger.warning("Failed to add reaction: code={}, msg={}", response.code, response.msg)
                return None
            else:
                reaction_id = response.data.reaction_id if response.data else None
                logger.debug("Added {} reaction to message {}, reaction_id={}", emoji_type, message_id, reaction_id)
                return reaction_id
        except Exception as e:
            logger.warning("Error adding reaction: {}", e)
            return None

    def _delete_reaction_sync(self, message_id: str, reaction_id: str, client=None) -> None:
        """Sync helper for deleting a reaction (runs in thread pool)."""
        try:
            c = client or self._client
            if not c:
                return

            request = DeleteMessageReactionRequest.builder() \
                .message_id(message_id) \
                .reaction_id(reaction_id) \
                .build()

            response = c.im.v1.message_reaction.delete(request)

            if not response.success():
                logger.warning("Failed to delete reaction: code={}, msg={}", response.code, response.msg)
            else:
                logger.debug("Deleted reaction {} from message {}", reaction_id, message_id)
        except Exception as e:
            logger.warning("Error deleting reaction: {}", e)

    async def _add_reaction(self, message_id: str, emoji_type: str = "THUMBSUP", account_id: str = None) -> str | None:
        """
        Add a reaction emoji to a message (non-blocking). Returns reaction_id.

        Common emoji types: THUMBSUP, OK, EYES, DONE, OnIt, HEART
        """
        if not Emoji:
            return None

        # Get client for account
        client = self._clients.get(account_id) if account_id and self._clients else self._client
        if not client:
            return None

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._add_reaction_sync, message_id, emoji_type, client)

    async def _delete_reaction(self, message_id: str, reaction_id: str, account_id: str = None) -> None:
        """Delete a reaction from a message (non-blocking)."""
        if not Emoji:
            return

        client = self._clients.get(account_id) if account_id and self._clients else self._client
        if not client:
            return

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._delete_reaction_sync, message_id, reaction_id, client)

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
        lines = [_line.strip() for _line in table_text.strip().split("\n") if _line.strip()]
        if len(lines) < 3:
            return None
        def split(_line: str) -> list[str]:
            return [c.strip() for c in _line.strip("|").split("|")]
        headers = split(lines[0])
        rows = [split(_line) for _line in lines[2:]]
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

    _IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico", ".tiff", ".tif"}
    _AUDIO_EXTS = {".opus"}
    _FILE_TYPE_MAP = {
        ".opus": "opus", ".mp4": "mp4", ".pdf": "pdf", ".doc": "doc", ".docx": "doc",
        ".xls": "xls", ".xlsx": "xls", ".ppt": "ppt", ".pptx": "ppt",
    }

    def _upload_image_sync(self, file_path: str, client: Any = None) -> str | None:
        """Upload an image to Feishu and return the image_key."""
        if not client:
            client = self._client
        try:
            with open(file_path, "rb") as f:
                request = CreateImageRequest.builder() \
                    .request_body(
                        CreateImageRequestBody.builder()
                        .image_type("message")
                        .image(f)
                        .build()
                    ).build()
                response = client.im.v1.image.create(request)
                if response.success():
                    image_key = response.data.image_key
                    logger.debug("Uploaded image {}: {}", os.path.basename(file_path), image_key)
                    return image_key
                else:
                    logger.error("Failed to upload image: code={}, msg={}", response.code, response.msg)
                    return None
        except Exception as e:
            logger.error("Error uploading image {}: {}", file_path, e)
            return None

    def _upload_file_sync(self, file_path: str, client: Any = None) -> str | None:
        """Upload a file to Feishu and return the file_key."""
        if not client:
            client = self._client
        ext = os.path.splitext(file_path)[1].lower()
        file_type = self._FILE_TYPE_MAP.get(ext, "stream")
        file_name = os.path.basename(file_path)
        try:
            with open(file_path, "rb") as f:
                request = CreateFileRequest.builder() \
                    .request_body(
                        CreateFileRequestBody.builder()
                        .file_type(file_type)
                        .file_name(file_name)
                        .file(f)
                        .build()
                    ).build()
                response = client.im.v1.file.create(request)
                if response.success():
                    file_key = response.data.file_key
                    logger.debug("Uploaded file {}: {}", file_name, file_key)
                    return file_key
                else:
                    logger.error("Failed to upload file: code={}, msg={}", response.code, response.msg)
                    return None
        except Exception as e:
            logger.error("Error uploading file {}: {}", file_path, e)
            return None

    def _download_image_sync(self, message_id: str, image_key: str) -> tuple[bytes | None, str | None]:
        """Download an image from Feishu message by message_id and image_key."""
        try:
            request = GetMessageResourceRequest.builder() \
                .message_id(message_id) \
                .file_key(image_key) \
                .type("image") \
                .build()
            response = self._client.im.v1.message_resource.get(request)
            if response.success():
                file_data = response.file
                # GetMessageResourceRequest returns BytesIO, need to read bytes
                if hasattr(file_data, 'read'):
                    file_data = file_data.read()
                return file_data, response.file_name
            else:
                logger.error("Failed to download image: code={}, msg={}", response.code, response.msg)
                return None, None
        except Exception as e:
            logger.error("Error downloading image {}: {}", image_key, e)
            return None, None

    def _download_file_sync(
        self, message_id: str, file_key: str, resource_type: str = "file"
    ) -> tuple[bytes | None, str | None]:
        """Download a file/audio/media from a Feishu message by message_id and file_key."""
        try:
            request = (
                GetMessageResourceRequest.builder()
                .message_id(message_id)
                .file_key(file_key)
                .type(resource_type)
                .build()
            )
            response = self._client.im.v1.message_resource.get(request)
            if response.success():
                file_data = response.file
                if hasattr(file_data, "read"):
                    file_data = file_data.read()
                return file_data, response.file_name
            else:
                logger.error("Failed to download {}: code={}, msg={}", resource_type, response.code, response.msg)
                return None, None
        except Exception:
            logger.exception("Error downloading {} {}", resource_type, file_key)
            return None, None

    async def _download_and_save_media(
        self,
        msg_type: str,
        content_json: dict,
        message_id: str | None = None
    ) -> tuple[str | None, str]:
        """
        Download media from Feishu and save to local disk.

        Returns:
            (file_path, content_text) - file_path is None if download failed
        """
        loop = asyncio.get_running_loop()
        media_dir = Path.home() / ".nanobot" / "media"
        media_dir.mkdir(parents=True, exist_ok=True)

        data, filename = None, None

        if msg_type == "image":
            image_key = content_json.get("image_key")
            if image_key and message_id:
                data, filename = await loop.run_in_executor(
                    None, self._download_image_sync, message_id, image_key
                )
                if not filename:
                    filename = f"{image_key[:16]}.jpg"

        elif msg_type in ("audio", "file", "media"):
            file_key = content_json.get("file_key")
            if file_key and message_id:
                data, filename = await loop.run_in_executor(
                    None, self._download_file_sync, message_id, file_key, msg_type
                )
                if not filename:
                    ext = {"audio": ".opus", "media": ".mp4"}.get(msg_type, "")
                    filename = f"{file_key[:16]}{ext}"

        if data and filename:
            file_path = media_dir / filename
            file_path.write_bytes(data)
            logger.debug("Downloaded {} to {}", msg_type, file_path)
            return str(file_path), f"[{msg_type}: {filename}]"

        return None, f"[{msg_type}: download failed]"

    def _send_message_sync(self, receive_id_type: str, receive_id: str, msg_type: str, content: str, client: Any = None) -> bool:
        """Send a single message (text/image/file/interactive) synchronously."""
        if not client:
            client = self._client
        try:
            request = CreateMessageRequest.builder() \
                .receive_id_type(receive_id_type) \
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(receive_id)
                    .msg_type(msg_type)
                    .content(content)
                    .build()
                ).build()
            response = client.im.v1.message.create(request)
            if not response.success():
                logger.error(
                    "Failed to send Feishu {} message: code={}, msg={}, log_id={}",
                    msg_type, response.code, response.msg, response.get_log_id()
                )
                return False
            logger.debug("Feishu {} message sent to {}", msg_type, receive_id)
            return True
        except Exception as e:
            logger.error("Error sending Feishu {} message: {}", msg_type, e)
            return False

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through Feishu, including media (images/files) if present."""
        # Skip progress messages for reaction management
        is_progress = msg.metadata.get("_progress") if msg.metadata else False

        # Get client for account (backward compat: use _client if _clients empty)
        account_id = msg.metadata.get("account_id") if msg.metadata else None
        client = self._clients.get(account_id) if account_id and self._clients else (self._clients.get(next(iter(self._clients))) if self._clients else self._client)

        if not client:
            logger.warning("Feishu client not initialized")
            return

        try:
            receive_id_type = "chat_id" if msg.chat_id.startswith("oc_") else "open_id"
            loop = asyncio.get_running_loop()

            for file_path in msg.media:
                if not os.path.isfile(file_path):
                    logger.warning("Media file not found: {}", file_path)
                    continue
                ext = os.path.splitext(file_path)[1].lower()
                if ext in self._IMAGE_EXTS:
                    key = await loop.run_in_executor(None, self._upload_image_sync, file_path, client)
                    if key:
                        await loop.run_in_executor(
                            None, self._send_message_sync,
                            receive_id_type, msg.chat_id, "image", json.dumps({"image_key": key}, ensure_ascii=False), client,
                        )
                else:
                    key = await loop.run_in_executor(None, self._upload_file_sync, file_path, client)
                    if key:
                        media_type = "audio" if ext in self._AUDIO_EXTS else "file"
                        await loop.run_in_executor(
                            None, self._send_message_sync,
                            receive_id_type, msg.chat_id, media_type, json.dumps({"file_key": key}, ensure_ascii=False), client,
                        )

            if msg.content and msg.content.strip():
                render_mode = self.config.render_mode
                use_card = (
                    render_mode == "card" or
                    (render_mode == "auto" and _should_use_card(msg.content))
                )
                if use_card:
                    card = {"config": {"wide_screen_mode": True}, "elements": self._build_card_elements(msg.content)}
                    await loop.run_in_executor(
                        None, self._send_message_sync,
                        receive_id_type, msg.chat_id, "interactive", json.dumps(card, ensure_ascii=False), client,
                    )
                else:
                    await loop.run_in_executor(
                        None, self._send_message_sync,
                        receive_id_type, msg.chat_id, "text", json.dumps({"text": msg.content}, ensure_ascii=False), client,
                    )

            # Delete the "thinking" reaction after final reply (not on progress messages)
            if not is_progress and msg.metadata:
                orig_message_id = msg.metadata.get("message_id")
                reaction_id = msg.metadata.get("reaction_id")
                if orig_message_id and reaction_id:
                    await self._delete_reaction(orig_message_id, reaction_id, account_id)

        except Exception as e:
            logger.error("Error sending Feishu message: {}", e)

    def _on_message_sync(self, data: "P2ImMessageReceiveV1", account_id: str) -> None:
        """
        Sync handler for incoming messages (called from WebSocket thread).
        Schedules async handling in the main event loop.
        """
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._on_message(data, account_id), self._loop)

    async def _on_message(self, data: "P2ImMessageReceiveV1", account_id: str) -> None:
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

            # Trim cache
            while len(self._processed_message_ids) > 1000:
                self._processed_message_ids.popitem(last=False)

            # Skip bot messages
            if sender.sender_type == "bot":
                return

            # Route to agent via AgentPool
            if self.agent_pool:
                agent = self.agent_pool.get_agent("feishu", account_id)
                if not agent:
                    logger.warning("No agent found for feishu account {}", account_id)
                    return

            sender_id = sender.sender_id.open_id if sender.sender_id else "unknown"
            chat_id = message.chat_id
            chat_type = message.chat_type
            msg_type = message.message_type

            # Add reaction and track reaction_id for later removal
            reaction_id = await self._add_reaction(message_id, self.config.react_emoji, account_id)

            # Parse content
            content_parts = []
            media_paths = []

            try:
                content_json = json.loads(message.content) if message.content else {}
            except json.JSONDecodeError:
                content_json = {}

            if msg_type == "text":
                text = content_json.get("text", "")
                if text:
                    content_parts.append(text)

            elif msg_type == "post":
                text, image_keys = _extract_post_content(content_json)
                if text:
                    content_parts.append(text)
                # Download images embedded in post
                for img_key in image_keys:
                    file_path, content_text = await self._download_and_save_media(
                        "image", {"image_key": img_key}, message_id
                    )
                    if file_path:
                        media_paths.append(file_path)
                    content_parts.append(content_text)

            elif msg_type in ("image", "audio", "file", "media"):
                file_path, content_text = await self._download_and_save_media(msg_type, content_json, message_id)
                if file_path:
                    media_paths.append(file_path)
                content_parts.append(content_text)

            elif msg_type in ("share_chat", "share_user", "interactive", "share_calendar_event", "system", "merge_forward"):
                # Handle share cards and interactive messages
                text = _extract_share_card_content(content_json, msg_type)
                if text:
                    content_parts.append(text)

            else:
                content_parts.append(MSG_TYPE_MAP.get(msg_type, f"[{msg_type}]"))

            content = "\n".join(content_parts) if content_parts else ""

            if not content and not media_paths:
                return

            # Forward to message bus
            base_metadata = {
                "message_id": message_id,
                "reaction_id": reaction_id,
                "chat_type": chat_type,
                "msg_type": msg_type,
                "account_id": account_id,
            }
            if chat_type == "group":
                # Extract mentions from event
                mentions_raw: list[dict] = []
                if hasattr(message, "mentions") and message.mentions:
                    mentions_raw = [
                        {
                            "key": m.key,
                            "id": {"open_id": m.id.open_id if m.id else ""},
                            "name": m.name,
                        }
                        for m in message.mentions
                    ]
                await self._handle_group_message(
                    sender_id=sender_id,
                    chat_id=chat_id,
                    content=content,
                    message_id=message_id,
                    mentions=mentions_raw,
                    account_id=account_id,
                    media=media_paths,
                    metadata=base_metadata,
                )
            else:
                await self._handle_message(
                    sender_id=sender_id,
                    chat_id=sender_id,
                    content=content,
                    media=media_paths,
                    metadata=base_metadata,
                )

        except Exception as e:
            logger.error("Error processing Feishu message: {}", e)
