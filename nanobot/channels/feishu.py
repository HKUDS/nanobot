"""Feishu/Lark channel implementation using lark-oapi SDK with WebSocket long connection."""

import asyncio
import json
import re
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

import httpx
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

    async def _download_media(self, message_id: str, file_key: str, media_type: str) -> str | None:
        """
        Download media file from Feishu and save to local disk.

        Args:
            message_id: Message ID
            file_key: File key (image_key or file_key)
            media_type: Media type (image/audio/file)

        Returns:
            Local file path, or None if download failed
        """
        try:
            # Get file extension
            ext = self._get_extension(media_type)

            # Create media directory
            from nanobot.utils.helpers import get_data_path
            media_dir = get_data_path() / "media"
            media_dir.mkdir(parents=True, exist_ok=True)

            # Generate file path
            file_path = media_dir / f"{file_key[:16]}{ext}"

            # Fetch file content from Feishu API
            file_content = await self._fetch_file_content(message_id, file_key, media_type)

            if not file_content:
                logger.warning(f"Failed to fetch {media_type} content: {file_key}")
                return None

            # Save to file
            file_path.write_bytes(file_content)

            logger.info(f"Downloaded {media_type} to {file_path}")
            return str(file_path)

        except Exception as e:
            logger.error(f"Failed to download {media_type}: {e}")
            return None

    async def _fetch_file_content(self, message_id: str, file_key: str, media_type: str) -> bytes | None:
        """
        Fetch file content from Feishu API.

        Uses message resource API to get file content directly.

        Returns:
            File content as bytes, or None if failed
        """
        try:
            # Get tenant access token via HTTP API
            token_url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
            token_payload = {
                "app_id": self.config.app_id,
                "app_secret": self.config.app_secret
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                token_response = await client.post(token_url, json=token_payload)

                if token_response.status_code != 200:
                    logger.error(f"Failed to get access token: status {token_response.status_code}")
                    return None

                token_data = token_response.json()
                if token_data.get("code") != 0:
                    logger.error(f"Failed to get access token: {token_data.get('msg')}")
                    return None

                access_token = token_data.get("tenant_access_token")
                logger.debug(f"Got access token: {access_token[:20]}...")

                # Use message resource API to get file content
                # Reference: https://open.feishu.cn/document/server-docs/im-v1/message-resource/get
                api_url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/resources/{file_key}"

                # Make request to get file
                response = await client.get(
                    api_url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                    },
                    params={"type": media_type}
                )

                logger.debug(f"Fetch file response: status={response.status_code}")
                logger.debug(f"Response headers: {dict(response.headers)}")
                logger.debug(f"Response content-type: {response.headers.get('Content-Type', 'unknown')}")

                if response.status_code != 200:
                    logger.warning(f"HTTP error: status={response.status_code}, response={response.text[:500]}")
                    return None

                # Check if response is JSON (might contain download_url or file data)
                content_type = response.headers.get("Content-Type", "")

                if "application/json" in content_type:
                    try:
                        data = response.json()
                        logger.debug(f"JSON response: {json.dumps(data, ensure_ascii=False)}")

                        if data.get("code") == 0:
                            # Check if response contains download_url
                            download_url = data.get("data", {}).get("file", {}).get("download_url")
                            if download_url:
                                # Download from the URL
                                logger.info(f"Got download URL, fetching from: {download_url}")
                                file_resp = await client.get(download_url)
                                file_resp.raise_for_status()
                                return file_resp.content

                            # Check if response contains file content (base64 or other format)
                            file_data = data.get("data", {}).get("file", {}).get("content")
                            if file_data:
                                import base64
                                return base64.b64decode(file_data)

                            logger.error(f"JSON response doesn't contain file content or download_url")
                        else:
                            logger.error(f"API error: code={data.get('code')}, msg={data.get('msg')}")
                        return None
                    except Exception as json_err:
                        logger.error(f"Failed to parse JSON response: {json_err}")
                        logger.error(f"Response was: {response.text[:1000]}")
                        return None

                # Response is binary file content directly
                logger.info(f"Got binary file content, size: {len(response.content)} bytes")
                return response.content

        except Exception as e:
            logger.error(f"Error fetching file content: {e}")
            return None

    def _get_extension(self, media_type: str) -> str:
        """Get file extension based on media type."""
        ext_map = {
            "image": ".jpg",
            "audio": ".m4a",
            "file": "",
            "video": ".mp4",
        }
        return ext_map.get(media_type, "")
    
    # Regex to match markdown tables (header + separator + data rows)
    _TABLE_RE = re.compile(
        r"((?:^[ \t]*\|.+\|[ \t]*\n)(?:^[ \t]*\|[-:\s|]+\|[ \t]*\n)(?:^[ \t]*\|.+\|[ \t]*\n?)+)",
        re.MULTILINE,
    )

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
            content_parts = []
            media_paths = []

            if msg_type == "text":
                try:
                    content = json.loads(message.content).get("text", "")
                except json.JSONDecodeError:
                    content = message.content or ""
                content_parts.append(content)

            elif msg_type in ("image", "audio", "file", "video"):
                # Download media file
                try:
                    content_json = json.loads(message.content)
                    logger.debug(f"Media content: {content_json}")

                    # Get file key (different keys for different types)
                    file_key = None
                    if msg_type == "image":
                        file_key = content_json.get("image_key")
                    else:
                        file_key = content_json.get("file_key")

                    logger.info(f"Processing {msg_type}: file_key={file_key}, message_id={message_id}")

                    if file_key:
                        # Download the file
                        local_path = await self._download_media(
                            message_id=message_id,
                            file_key=file_key,
                            media_type=msg_type
                        )

                        if local_path:
                            media_paths.append(local_path)
                            content_parts.append(f"[{msg_type}: {local_path}]")
                            logger.info(f"Successfully downloaded {msg_type} to {local_path}")
                        else:
                            content_parts.append(f"[{msg_type}: download failed]")
                            logger.warning(f"Failed to download {msg_type}")
                    else:
                        content_parts.append(f"[{msg_type}: no file_key]")
                        logger.warning(f"No file_key found for {msg_type}")

                except json.JSONDecodeError:
                    content_parts.append(f"[{msg_type}: JSON decode error]")
                    logger.error(f"JSON decode error for {msg_type}")
                except Exception as e:
                    logger.error(f"Error processing media: {e}")
                    content_parts.append(f"[{msg_type}: processing error]")
            else:
                # Other message types
                content_parts.append(MSG_TYPE_MAP.get(msg_type, f"[{msg_type}]"))

            # Build final content
            content = "\n".join(content_parts) if content_parts else ""

            if not content:
                return

            # Forward to message bus
            reply_to = chat_id if chat_type == "group" else sender_id
            await self._handle_message(
                sender_id=sender_id,
                chat_id=reply_to,
                content=content,
                media=media_paths,
                metadata={
                    "message_id": message_id,
                    "chat_type": chat_type,
                    "msg_type": msg_type,
                }
            )
            
        except Exception as e:
            logger.error(f"Error processing Feishu message: {e}")
