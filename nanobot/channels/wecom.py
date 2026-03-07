"""WeChat Work (企业微信) channel via SillyMD bridge.

Receives encrypted WeChat messages through SillyMD WebSocket, decrypts them,
and forwards to the nanobot agent via MessageBus.  Agent responses are sent
back to WeChat through SillyMD HTTP API.

Ported from sillymd-openclaw-wechat-plugin, with OpenClaw logic replaced by
nanobot's MessageBus architecture.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import xml.etree.ElementTree as ET
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import WeComConfig

try:
    from nanobot.channels.wecom_crypto import WeChatCrypto

    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

try:
    from nanobot.channels.wecom_connector import SillyMDConnector

    CONNECTOR_AVAILABLE = True
except ImportError:
    CONNECTOR_AVAILABLE = False


class WeComChannel(BaseChannel):
    """WeChat Work channel using SillyMD as the message bridge.

    Architecture::

        WeChat ←→ SillyMD Server ←(WebSocket/HTTP)→ WeComChannel ←(MessageBus)→ nanobot agent
    """

    name = "wecom"

    def __init__(self, config: WeComConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: WeComConfig = config
        self._connector: SillyMDConnector | None = None
        self._crypto: WeChatCrypto | None = None
        self._ws_task: asyncio.Task | None = None
        self._corp_id: str = ""

        # Dedup caches
        self._processed_encrypted: OrderedDict[str, None] = OrderedDict()
        self._processed_msg_ids: OrderedDict[str, None] = OrderedDict()
        self._MAX_DEDUP = 500

        # Media storage
        self._media_dir = Path.home() / ".nanobot" / "media"

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the WeChat Work channel."""
        if not CRYPTO_AVAILABLE:
            logger.error("WeChat crypto not available. Install pycryptodome: pip install pycryptodome")
            return
        if not CONNECTOR_AVAILABLE:
            logger.error("WeChat connector not available. Install websockets and aiohttp")
            return
        if not self.config.api_key:
            logger.error("WeChat Work api_key not configured")
            return
        if not self.config.owner_id:
            logger.error("WeChat Work owner_id not configured")
            return

        self._running = True
        self._media_dir.mkdir(parents=True, exist_ok=True)

        # Create connector
        self._connector = SillyMDConnector(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
        )

        # Fetch tenant info and WeChat config
        logger.info("Fetching SillyMD tenant info...")
        tenant = await self._connector.fetch_tenant_info()
        if not tenant or not tenant.get("id"):
            logger.error("Failed to fetch tenant info — check api_key")
            return

        wechat = tenant.get("wechat", {})
        if not wechat.get("token") or not wechat.get("encoding_aes_key"):
            logger.error("SillyMD tenant has no WeChat config. Configure it on the SillyMD dashboard.")
            return

        self._corp_id = wechat.get("corp_id", "")
        self._connector.corp_id = self._corp_id

        # Initialise crypto
        self._crypto = WeChatCrypto(
            token=wechat["token"],
            encoding_aes_key=wechat["encoding_aes_key"],
            corp_id=self._corp_id,
        )

        # Register WS handler and run
        self._connector.add_handler(self._on_ws_message)

        logger.info("WeChat Work channel started (via SillyMD bridge)")
        logger.info("  Tenant: {} ({})", tenant.get("name"), tenant.get("id"))
        logger.info("  Owner:  {}", self.config.owner_id)

        await self._connector.run_forever()

    async def stop(self) -> None:
        """Stop the WeChat Work channel."""
        self._running = False
        if self._connector:
            await self._connector.close()
        logger.info("WeChat Work channel stopped")

    # ── Inbound (WebSocket → MessageBus) ─────────────────────────────────

    async def _on_ws_message(self, message: dict) -> None:
        """Handle a raw message from SillyMD WebSocket."""
        msg_data = message.get("data", message)
        msg_type = msg_data.get("type", "unknown")

        # Skip non-encrypted messages
        if msg_type in ("ping", "connected", "wechat_reply"):
            return
        if msg_type != "wechat_encrypted":
            return

        # Dedup by encrypted content hash
        encrypted = msg_data.get("encrypted", "")
        if encrypted:
            h = hashlib.md5(encrypted[:100].encode()).hexdigest()[:16]
            if h in self._processed_encrypted:
                return
            self._processed_encrypted[h] = None
            self._trim_dedup(self._processed_encrypted)

        # Decrypt
        try:
            xml = self._crypto.decrypt_msg(
                msg_data.get("msg_signature", ""),
                msg_data.get("timestamp", ""),
                msg_data.get("nonce", ""),
                encrypted,
            )
        except Exception as e:
            logger.error("WeChat message decrypt failed: {}", e)
            return

        # Dedup by MsgId
        msg_id = self._extract_xml_field(xml, "MsgId")
        if msg_id:
            if msg_id in self._processed_msg_ids:
                return
            self._processed_msg_ids[msg_id] = None
            self._trim_dedup(self._processed_msg_ids)

        # Parse message
        payload, sender = self._parse_message(xml)
        if not payload or not sender:
            return

        inner_type = payload.get("type", "text")

        if inner_type == "text":
            content = payload.get("content", "")
            if not content:
                return
            await self._handle_message(
                sender_id=sender,
                chat_id=sender,
                content=content,
                metadata={"platform": "wecom", "owner_id": self.config.owner_id},
            )

        elif inner_type == "voice":
            # If WeChat already transcribed, use that
            recognition = payload.get("recognition")
            if recognition:
                await self._handle_message(
                    sender_id=sender,
                    chat_id=sender,
                    content=f"[语音消息] {recognition}",
                    metadata={"platform": "wecom", "owner_id": self.config.owner_id},
                )
            else:
                # Download and save for potential processing
                media_id = payload.get("media_id")
                file_path = await self._download_and_save(media_id, "voice", payload.get("format", "amr"))
                desc = f"[语音消息] 文件: {file_path}" if file_path else "[语音消息] 下载失败"
                media = [file_path] if file_path else []
                await self._handle_message(
                    sender_id=sender,
                    chat_id=sender,
                    content=desc,
                    media=media,
                    metadata={"platform": "wecom", "owner_id": self.config.owner_id},
                )

        elif inner_type == "image":
            media_id = payload.get("media_id")
            file_path = await self._download_and_save(media_id, "image", "jpg")
            desc = f"[图片]" if file_path else "[图片] 下载失败"
            media = [file_path] if file_path else []
            await self._handle_message(
                sender_id=sender,
                chat_id=sender,
                content=desc,
                media=media,
                metadata={"platform": "wecom", "owner_id": self.config.owner_id},
            )

        elif inner_type == "video":
            media_id = payload.get("media_id")
            file_path = await self._download_and_save(media_id, "video", "mp4")
            desc = f"[视频]" if file_path else "[视频] 下载失败"
            media = [file_path] if file_path else []
            await self._handle_message(
                sender_id=sender,
                chat_id=sender,
                content=desc,
                media=media,
                metadata={"platform": "wecom", "owner_id": self.config.owner_id},
            )

        elif inner_type == "file":
            file_name = payload.get("file_name", "unknown")
            await self._handle_message(
                sender_id=sender,
                chat_id=sender,
                content=f"[文件] {file_name}",
                metadata={"platform": "wecom", "owner_id": self.config.owner_id},
            )

        else:
            logger.warning("Unsupported WeChat message type: {}", inner_type)

    # ── Outbound (MessageBus → WeChat) ───────────────────────────────────

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message back to WeChat via SillyMD."""
        if not self._connector:
            logger.warning("WeChat connector not initialized")
            return

        target = msg.chat_id
        owner = self.config.owner_id

        # If sender is not the owner, CC the owner
        if target != owner and owner:
            target = f"{target}|{owner}"

        # Send text
        if msg.content and msg.content.strip():
            await self._connector.send_text(msg.content.strip(), touser=target)

        # Send media files
        for file_path in msg.media or []:
            if not os.path.isfile(file_path):
                logger.warning("Media file not found: {}", file_path)
                continue
            ext = os.path.splitext(file_path)[1].lower()
            media_type = "image" if ext in {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"} else "file"
            await self._connector.send_media(
                media_type=media_type,
                file_path=file_path,
                touser=target,
            )

    # ── XML parsing ──────────────────────────────────────────────────────

    @staticmethod
    def _extract_xml_field(xml: str, tag: str) -> str | None:
        """Extract a field from WeChat XML message."""
        try:
            root = ET.fromstring(xml)
            elem = root.find(tag)
            if elem is not None:
                return elem.text
            # Fallback: search ignoring namespace
            for child in root.iter():
                if child.tag == tag or child.tag.endswith("}" + tag):
                    return child.text
        except Exception:
            pass
        return None

    def _parse_message(self, xml: str) -> tuple[dict | None, str | None]:
        """Parse a decrypted WeChat XML message into (payload, sender)."""
        try:
            root = ET.fromstring(xml)

            def find(tag: str) -> ET.Element | None:
                elem = root.find(tag)
                if elem is not None:
                    return elem
                for child in root.iter():
                    if child.tag == tag or child.tag.endswith("}" + tag):
                        return child
                return None

            msg_type_el = find("MsgType")
            from_el = find("FromUserName")
            msg_type = msg_type_el.text if msg_type_el is not None else "text"
            sender = from_el.text if from_el is not None else None

            if msg_type == "text":
                content_el = find("Content")
                return {"type": "text", "content": content_el.text if content_el is not None else ""}, sender

            if msg_type == "image":
                pic_url_el = find("PicUrl")
                media_id_el = find("MediaId")
                return {
                    "type": "image",
                    "pic_url": pic_url_el.text if pic_url_el is not None else None,
                    "media_id": media_id_el.text if media_id_el is not None else None,
                }, sender

            if msg_type in ("video", "shortvideo"):
                media_id_el = find("MediaId")
                return {
                    "type": "video",
                    "media_id": media_id_el.text if media_id_el is not None else None,
                }, sender

            if msg_type == "voice":
                media_id_el = find("MediaId")
                format_el = find("Format")
                recognition_el = find("Recognition")
                return {
                    "type": "voice",
                    "media_id": media_id_el.text if media_id_el is not None else None,
                    "format": format_el.text if format_el is not None else "amr",
                    "recognition": recognition_el.text if recognition_el is not None else None,
                }, sender

            if msg_type == "file":
                file_name_el = find("FileName")
                file_ext_el = find("FileExtension")
                file_size_el = find("FileSize")
                return {
                    "type": "file",
                    "file_name": file_name_el.text if file_name_el is not None else "unknown",
                    "file_ext": file_ext_el.text if file_ext_el is not None else "",
                    "file_size": int(file_size_el.text) if file_size_el is not None and file_size_el.text and file_size_el.text.isdigit() else 0,
                }, sender

            # Unknown type — return text fallback
            content_el = find("Content")
            return {"type": "text", "content": content_el.text if content_el is not None else f"[{msg_type}]"}, sender

        except Exception as e:
            logger.error("XML parse failed: {}", e)
            return None, None

    # ── Media helpers ────────────────────────────────────────────────────

    async def _download_and_save(self, media_id: str | None, media_type: str, ext: str) -> str | None:
        """Download media from WeChat via SillyMD and save locally."""
        if not media_id or not self._connector:
            return None
        try:
            data = await self._connector.download_media(media_id)
            if not data:
                return None
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"wecom_{media_type}_{media_id[:12]}_{ts}.{ext}"
            path = self._media_dir / filename
            path.write_bytes(data)
            logger.debug("Saved {} to {}", media_type, path)
            return str(path)
        except Exception as e:
            logger.error("Download/save media failed: {}", e)
            return None

    # ── Dedup helpers ────────────────────────────────────────────────────

    def _trim_dedup(self, cache: OrderedDict) -> None:
        while len(cache) > self._MAX_DEDUP:
            cache.popitem(last=False)
