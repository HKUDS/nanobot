"""QQ channel implementation using botpy SDK."""

import asyncio
import os
import re
import time
from collections import deque
from typing import TYPE_CHECKING, Any, Literal

import httpx
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.paths import get_media_dir
from nanobot.config.schema import Base
from pydantic import Field

try:
    import botpy
    from botpy.message import C2CMessage, GroupMessage

    QQ_AVAILABLE = True
except ImportError:
    QQ_AVAILABLE = False
    botpy = None
    C2CMessage = None
    GroupMessage = None

if TYPE_CHECKING:
    from botpy.message import C2CMessage, GroupMessage

# Matches markdown image syntax: ![alt](url)
_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\((https?://[^\s)]+)\)")
# Matches <qqimg>url_or_path</qqimg> tags (compatible with openclaw qqbot plugin syntax)
_QQIMG_RE = re.compile(r"<qqimg>(.*?)</qqimg>", re.DOTALL)
# Matches <qqfile>path_or_url</qqfile> tags
_QQFILE_RE = re.compile(r"<qqfile>(.*?)</qqfile>", re.DOTALL)


def _make_bot_class(channel: "QQChannel") -> "type[botpy.Client]":
    """Create a botpy Client subclass bound to the given channel."""
    intents = botpy.Intents(public_messages=True, direct_message=True)

    class _Bot(botpy.Client):
        def __init__(self):
            # Disable botpy's file log — nanobot uses loguru; default "botpy.log" fails on read-only fs
            super().__init__(intents=intents, ext_handlers=False)

        async def on_ready(self):
            logger.info("QQ bot ready: {}", self.robot.name)

        async def on_c2c_message_create(self, message: "C2CMessage"):
            await channel._on_message(message, is_group=False)

        async def on_group_at_message_create(self, message: "GroupMessage"):
            await channel._on_message(message, is_group=True)

    return _Bot


class QQConfig(Base):
    """QQ channel configuration using botpy SDK."""

    enabled: bool = False
    app_id: str = ""
    secret: str = ""
    allow_from: list[str] = Field(default_factory=list)
    msg_format: Literal["plain", "markdown"] = "plain"


class QQChannel(BaseChannel):
    """QQ channel using botpy SDK with WebSocket connection."""

    name = "qq"
    display_name = "QQ"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return QQConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = QQConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: QQConfig = config
        self._client: "botpy.Client | None" = None
        self._processed_ids: deque = deque(maxlen=1000)
        self._msg_seq: int = 1  # 消息序列号，避免被 QQ API 去重
        self._chat_type_cache: dict[str, str] = {}

    async def start(self) -> None:
        """Start the QQ bot."""
        if not QQ_AVAILABLE:
            logger.error("QQ SDK not installed. Run: pip install qq-botpy")
            return

        if not self.config.app_id or not self.config.secret:
            logger.error("QQ app_id and secret not configured")
            return

        self._running = True
        BotClass = _make_bot_class(self)
        self._client = BotClass()
        logger.info("QQ bot started (C2C & Group supported)")
        await self._run_bot()

    async def _run_bot(self) -> None:
        """Run the bot connection with auto-reconnect."""
        while self._running:
            try:
                await self._client.start(appid=self.config.app_id, secret=self.config.secret)
            except Exception as e:
                logger.warning("QQ bot error: {}", e)
            if self._running:
                logger.info("Reconnecting QQ bot in 5 seconds...")
                await asyncio.sleep(5)

    async def stop(self) -> None:
        """Stop the QQ bot."""
        self._running = False
        if self._client:
            try:
                await self._client.close()
            except Exception:
                pass
        logger.info("QQ bot stopped")

    async def _download_attachment(self, url: str, filename: str = "", ctype: str = "") -> str | None:
        """Download an attachment from QQ CDN using the bot's access token."""
        try:
            media_dir = get_media_dir("qq")
            # Determine extension
            if filename:
                ext = os.path.splitext(filename)[1] or ".bin"
            elif ctype:
                ext = "." + ctype.split("/")[-1].split(";")[0].strip() if "/" in ctype else ".bin"
            else:
                # Try to guess from URL path
                url_path = url.split("?")[0]
                ext = os.path.splitext(url_path)[1] or ".jpg"

            safe_fname = f"qq_{int(time.time() * 1000)}_{abs(hash(url)) % 100000}{ext}"
            file_path = media_dir / safe_fname

            # Use bot's access_token for CDN auth
            headers = {}
            if self._client and hasattr(self._client, "_http") and hasattr(self._client._http, "token"):
                token = self._client._http.token
                if token:
                    headers["Authorization"] = f"QQBot {token}"

            async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                file_path.write_bytes(resp.content)

            logger.debug("Downloaded QQ attachment ({}) → {}", ctype or ext, file_path)
            return str(file_path)
        except Exception as e:
            logger.warning("Failed to download QQ attachment ({}): {}", url, e)
            return None

    async def _upload_media(self, chat_id: str, url: str, is_group: bool, file_type: int = 1) -> "dict | None":
        """Upload a media URL to QQ and return the Media object for use in messages.

        file_type: 1=image/png/jpg, 2=video/mp4, 3=audio/silk, 4=file
        """
        try:
            if is_group:
                media = await self._client.api.post_group_file(
                    group_openid=chat_id, file_type=file_type, url=url, srv_send_msg=False
                )
            else:
                media = await self._client.api.post_c2c_file(
                    openid=chat_id, file_type=file_type, url=url, srv_send_msg=False
                )
            return media
        except Exception as e:
            logger.warning("QQ media upload failed ({}): {}", url, e)
            return None

    async def _upload_file_base64(self, file_path: str, chat_id: str, is_group: bool, file_type: int = 4) -> "dict | None":
        """Upload a local file to QQ using base64 file_data.

        Bypasses botpy SDK to use file_data directly — no public URL required.
        Supports all file_type values: 1=image, 2=video, 3=audio, 4=file.
        Returns a Media-like dict with file_info on success, or None on failure.
        """
        import base64
        try:
            from botpy.http import Route
        except ImportError:
            return None
        try:
            fname = os.path.basename(file_path)
            with open(file_path, "rb") as f:
                file_data = base64.b64encode(f.read()).decode("ascii")
            body = {
                "file_type": file_type,
                "srv_send_msg": False,
                "file_data": file_data,
                "file_name": fname,
            }
            if is_group:
                route = Route("POST", "/v2/groups/{group_openid}/files", group_openid=chat_id)
            else:
                route = Route("POST", "/v2/users/{openid}/files", openid=chat_id)
            result = await self._client.api._http.request(route, json=body)
            logger.debug("QQ file upload (base64, type={}) success: {} → file_info={}", file_type, fname, str(result)[:80])
            return result
        except Exception as e:
            logger.warning("QQ file upload (base64, type={}) failed for '{}': {}", file_type, os.path.basename(file_path), e)
            return None

    async def _upload_local_file_to_qq(self, file_path: str, chat_id: str, is_group: bool) -> "dict | None":
        """Upload a local file to QQ CDN via base64 direct upload.

        All file types use base64 — no public URL required.
        """
        fname = os.path.basename(file_path)
        ext = os.path.splitext(fname)[1].lower()
        # QQ file_type: 1=image, 2=video, 3=audio, 4=file
        if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"):
            file_type = 1
        elif ext in (".mp4", ".avi", ".mov", ".mkv"):
            file_type = 2
        elif ext in (".mp3", ".m4a", ".wav", ".ogg", ".silk"):
            file_type = 3
        else:
            file_type = 4

        return await self._upload_file_base64(file_path, chat_id, is_group, file_type=file_type)

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through QQ."""
        if not self._client:
            logger.warning("QQ client not initialized")
            return

        # QQ has no streaming/edit API — skip progress messages to avoid duplicates.
        # The final non-progress message carries the complete content.
        if msg.metadata.get("_progress"):
            return

        logger.debug("QQ.send called: chat_id={} content={!r} media={}",
                     msg.chat_id, (msg.content or "")[:60], len(msg.media or []))

        try:
            msg_id = msg.metadata.get("message_id")
            chat_type = self._chat_type_cache.get(msg.chat_id, "c2c")
            is_group = chat_type == "group"
            content = msg.content or ""

            # Send local media files via QQ upload (images/video/audio by URL; files by base64)
            for file_path in (msg.media or []):
                if not os.path.isfile(file_path):
                    logger.warning("QQ media file not found: {}", file_path)
                    continue
                fname = os.path.basename(file_path)
                media_obj = await self._upload_local_file_to_qq(file_path, msg.chat_id, is_group)
                if media_obj is not None:
                    self._msg_seq += 1
                    media_payload: dict[str, Any] = {
                        "msg_type": 7,
                        "msg_id": msg_id,
                        "msg_seq": self._msg_seq,
                        "media": media_obj,
                    }
                    if is_group:
                        await self._client.api.post_group_message(group_openid=msg.chat_id, **media_payload)
                    else:
                        await self._client.api.post_c2c_message(openid=msg.chat_id, **media_payload)
                else:
                    # Upload failed — notify in text
                    content = f"{content}\n📎 {fname} (上传失败)".strip()

            # Extract <qqimg> tags (openclaw-compatible syntax) and convert to upload queue
            qqimg_matches = _QQIMG_RE.findall(content)
            content = _QQIMG_RE.sub("", content)
            for src in qqimg_matches:
                src = src.strip()
                if src.startswith("http://") or src.startswith("https://"):
                    # URL: upload directly
                    media_obj = await self._upload_media(msg.chat_id, src, is_group, file_type=1)
                else:
                    # Local path: upload via base64
                    media_obj = await self._upload_local_file_to_qq(src, msg.chat_id, is_group)
                if media_obj is not None:
                    self._msg_seq += 1
                    img_payload: dict[str, Any] = {
                        "msg_type": 7,
                        "msg_id": msg_id,
                        "msg_seq": self._msg_seq,
                        "media": media_obj,
                    }
                    if is_group:
                        await self._client.api.post_group_message(group_openid=msg.chat_id, **img_payload)
                    else:
                        await self._client.api.post_c2c_message(openid=msg.chat_id, **img_payload)

            # Extract <qqfile> tags — upload as QQ file attachment (base64)
            qqfile_matches = _QQFILE_RE.findall(content)
            content = _QQFILE_RE.sub("", content)
            for src in qqfile_matches:
                src = src.strip()
                fname = os.path.basename(src)
                if src.startswith("http://") or src.startswith("https://"):
                    # Remote URL: try uploading via QQ CDN fetch
                    media_obj = await self._upload_media(msg.chat_id, src, is_group, file_type=4)
                    if media_obj is not None:
                        self._msg_seq += 1
                        file_payload: dict[str, Any] = {
                            "msg_type": 7,
                            "msg_id": msg_id,
                            "msg_seq": self._msg_seq,
                            "media": media_obj,
                        }
                        if is_group:
                            await self._client.api.post_group_message(group_openid=msg.chat_id, **file_payload)
                        else:
                            await self._client.api.post_c2c_message(openid=msg.chat_id, **file_payload)
                    else:
                        content = f"{content}\n📎 {fname}\n{src}".strip()
                elif os.path.isfile(src):
                    # Local file: upload via base64
                    media_obj = await self._upload_file_base64(src, msg.chat_id, is_group)
                    if media_obj is not None:
                        self._msg_seq += 1
                        file_payload = {
                            "msg_type": 7,
                            "msg_id": msg_id,
                            "msg_seq": self._msg_seq,
                            "media": media_obj,
                        }
                        if is_group:
                            await self._client.api.post_group_message(group_openid=msg.chat_id, **file_payload)
                        else:
                            await self._client.api.post_c2c_message(openid=msg.chat_id, **file_payload)
                    else:
                        content = f"{content}\n📎 {fname} (上传失败)".strip()
                else:
                    content = f"{content}\n📎 {fname}".strip()

            # Extract markdown images from content and send them as rich-media messages
            images = _MD_IMAGE_RE.findall(content)
            text_body = _MD_IMAGE_RE.sub("", content).strip()

            use_markdown = self.config.msg_format == "markdown"

            # Send text portion first (if any)
            if text_body:
                self._msg_seq += 1
                payload: dict[str, Any] = {
                    "msg_type": 2 if use_markdown else 0,
                    "msg_id": msg_id,
                    "msg_seq": self._msg_seq,
                }
                if use_markdown:
                    payload["markdown"] = {"content": text_body}
                else:
                    payload["content"] = text_body

                if is_group:
                    await self._client.api.post_group_message(group_openid=msg.chat_id, **payload)
                else:
                    await self._client.api.post_c2c_message(openid=msg.chat_id, **payload)

            # Send each image as a rich-media message (msg_type=7)
            for _alt, img_url in images:
                media = await self._upload_media(msg.chat_id, img_url, is_group)
                if media is None:
                    continue
                self._msg_seq += 1
                img_payload: dict[str, Any] = {
                    "msg_type": 7,
                    "msg_id": msg_id,
                    "msg_seq": self._msg_seq,
                    "media": media,
                }
                if is_group:
                    await self._client.api.post_group_message(group_openid=msg.chat_id, **img_payload)
                else:
                    await self._client.api.post_c2c_message(openid=msg.chat_id, **img_payload)

            # Fallback: if content had no text and no images, send raw
            if not text_body and not images:
                self._msg_seq += 1
                payload = {
                    "msg_type": 2 if use_markdown else 0,
                    "msg_id": msg_id,
                    "msg_seq": self._msg_seq,
                }
                if use_markdown:
                    payload["markdown"] = {"content": content}
                else:
                    payload["content"] = content
                if is_group:
                    await self._client.api.post_group_message(group_openid=msg.chat_id, **payload)
                else:
                    await self._client.api.post_c2c_message(openid=msg.chat_id, **payload)

        except Exception as e:
            logger.error("Error sending QQ message: {}", e)

    async def _on_message(self, data: "C2CMessage | GroupMessage", is_group: bool = False) -> None:
        """Handle incoming message from QQ."""
        try:
            # Dedup by (message_id, author_id) — prevents double-fire from
            # overlapping botpy event callbacks for the same message
            dedup_key = f"{data.id}:{getattr(data.author, 'member_openid', None) or getattr(data.author, 'user_openid', None) or getattr(data.author, 'id', '')}"
            if dedup_key in self._processed_ids:
                logger.debug("QQ duplicate message skipped: {}", data.id)
                return
            self._processed_ids.append(dedup_key)

            content = (data.content or "").strip()
            media_paths: list[str] = []

            # Process attachments: download images/files to local storage
            attachments = getattr(data, "attachments", None) or []
            logger.debug("QQ message id={} content={!r} attachments={}", data.id, content[:80], len(attachments))
            for att in attachments:
                url = getattr(att, "url", None)
                ctype = getattr(att, "content_type", "") or ""
                fname = getattr(att, "filename", "") or ""
                logger.debug("QQ attachment: url={} content_type={} filename={}", url, ctype, fname)
                if not url:
                    continue
                is_image = (
                    ctype.startswith("image/")
                    or any(url.lower().split("?")[0].endswith(ext)
                           for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp"))
                    or "multimedia" in url  # QQ CDN pattern
                )
                local_path = await self._download_attachment(url, fname, ctype)
                if local_path:
                    if is_image:
                        media_paths.append(local_path)
                    else:
                        # Non-image file: save path and tell LLM about it
                        label = fname or os.path.basename(url.split("?")[0])
                        content = f"{content}\n[已下载文件: {label} → {local_path}]".strip()
                else:
                    label = fname or url
                    content = f"{content}\n[附件: {label}]({url}) (下载失败，可通过URL访问)".strip()

            # QQ also delivers images as markdown image links embedded in content text.
            # Extract, download, and remove them so the VL model receives actual image data.
            inline_images = _MD_IMAGE_RE.findall(content)
            if inline_images:
                for _alt, img_url in inline_images:
                    if "multimedia" in img_url or any(
                        img_url.lower().split("?")[0].endswith(ext)
                        for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp")
                    ):
                        logger.debug("QQ inline image found: {}", img_url[:80])
                        local_path = await self._download_attachment(img_url)
                        if local_path:
                            media_paths.append(local_path)
                            logger.debug("QQ inline image downloaded → {}", local_path)
                        else:
                            logger.warning("QQ inline image download failed: {}", img_url[:80])
                # Strip all inline image markdown from content to avoid sending raw URLs to LLM
                content = _MD_IMAGE_RE.sub("", content).strip()

            if not content and not media_paths:
                return

            if is_group:
                chat_id = data.group_openid
                user_id = data.author.member_openid
                self._chat_type_cache[chat_id] = "group"
            else:
                chat_id = str(getattr(data.author, 'id', None) or getattr(data.author, 'user_openid', 'unknown'))
                user_id = chat_id
                self._chat_type_cache[chat_id] = "c2c"

            await self._handle_message(
                sender_id=user_id,
                chat_id=chat_id,
                content=content,
                media=media_paths if media_paths else None,
                metadata={"message_id": data.id},
            )
        except Exception:
            logger.exception("Error handling QQ message")
