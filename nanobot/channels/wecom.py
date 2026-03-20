"""WeCom (Enterprise WeChat) channel implementation using wecom_aibot_sdk."""

import asyncio
import base64
import hashlib
import importlib.util
import mimetypes
import os
import re
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.paths import get_media_dir
from nanobot.config.schema import Base
from pydantic import Field

WECOM_AVAILABLE = importlib.util.find_spec("wecom_aibot_sdk") is not None

class WecomBotEntry(Base):
    """Single WeCom bot credentials (for multi-bot support)."""

    bot_id: str = ""
    secret: str = ""
    allow_from: list[str] = Field(default_factory=list)
    welcome_message: str = ""


class WecomConfig(Base):
    """WeCom (Enterprise WeChat) AI Bot channel configuration."""

    enabled: bool = False
    bot_id: str = ""
    secret: str = ""
    allow_from: list[str] = Field(default_factory=list)
    welcome_message: str = ""
    # Multiple bots: if non-empty, use this list; otherwise single bot from bot_id/secret above
    bots: list[WecomBotEntry] = Field(default_factory=list)


# Message type display mapping
MSG_TYPE_MAP = {
    "image": "[image]",
    "voice": "[voice]",
    "file": "[file]",
    "mixed": "[mixed content]",
}


class WecomChannel(BaseChannel):
    """
    WeCom (Enterprise WeChat) channel using WebSocket long connection.

    Uses WebSocket to receive events - no public IP or webhook required.

    Requires:
    - Bot ID and Secret from WeCom AI Bot platform
    """

    name = "wecom"
    display_name = "WeCom"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return WecomConfig().model_dump(by_alias=True)

    def _normalize_bot_configs(self) -> list[dict[str, Any]]:
        """Build list of bot configs: from bots[] or single bot_id/secret."""
        if self.config.bots:
            return [
                {
                    "bot_id": b.bot_id,
                    "secret": b.secret,
                    "allow_from": b.allow_from or [],
                    "welcome_message": b.welcome_message or "",
                }
                for b in self.config.bots
                if b.bot_id and b.secret
            ]
        if self.config.bot_id and self.config.secret:
            return [{
                "bot_id": self.config.bot_id,
                "secret": self.config.secret,
                "allow_from": self.config.allow_from or [],
                "welcome_message": self.config.welcome_message or "",
            }]
        return []

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = WecomConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: WecomConfig = config
        # Single-bot: one client; multi-bot: one client per bot
        self._client: Any = None
        self._clients_by_bot_id: dict[str, Any] = {}
        self._processed_message_ids: OrderedDict[str, None] = OrderedDict()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._generate_req_id = None
        # Store (frame, bot_id, chat_type_str) per composite chat_id for replies
        self._chat_frames: dict[str, tuple[Any, str, str]] = {}
        # Per-bot allow_from (bot_id -> list)
        self._allow_from_by_bot_id: dict[str, list[str]] = {}
        # Streaming state per chat_id
        # WeCom streaming uses CUMULATIVE content (each call REPLACES the shown text)
        # and is rate-limited to ~30 msgs/min on the long-connection channel.
        self._active_streams: dict[str, str] = {}         # chat_id -> stream_id
        self._stream_content: dict[str, str] = {}         # chat_id -> accumulated text so far
        self._stream_last_send: dict[str, float] = {}     # chat_id -> timestamp of last send
        self._STREAM_MIN_INTERVAL = 1.5  # seconds between intermediate stream updates
        # Normalized list of bots to start (each: dict with bot_id, secret, allow_from, welcome_message)
        self._bot_configs: list[dict[str, Any]] = self._normalize_bot_configs()

    async def start(self) -> None:
        """Start the WeCom bot(s) with WebSocket long connection."""
        if not WECOM_AVAILABLE:
            logger.error("WeCom SDK not installed. Run: pip install nanobot-ai[wecom]")
            return

        if not self._bot_configs:
            logger.error("WeCom bot_id and secret not configured (or bots list empty)")
            return

        from wecom_aibot_sdk import WSClient, generate_req_id

        self._running = True
        self._loop = asyncio.get_running_loop()
        self._generate_req_id = generate_req_id

        async def run_one_bot(cfg: dict[str, Any]) -> None:
            bot_id = cfg["bot_id"]
            client = WSClient({
                "bot_id": bot_id,
                "secret": cfg["secret"],
                "reconnect_interval": 1000,
                "max_reconnect_attempts": -1,
                "heartbeat_interval": 30000,
            })
            self._clients_by_bot_id[bot_id] = client
            self._allow_from_by_bot_id[bot_id] = cfg.get("allow_from") or []
            if len(self._bot_configs) == 1:
                self._client = client

            def make_handler(msg_type: str):
                async def _handler(frame: Any) -> None:
                    await self._process_message(frame, msg_type, bot_id, client)
                return _handler

            client.on("connected", self._on_connected)
            client.on("authenticated", self._on_authenticated)
            client.on("disconnected", self._on_disconnected)
            client.on("error", self._on_error)
            client.on("message.text", make_handler("text"))
            client.on("message.image", make_handler("image"))
            client.on("message.voice", make_handler("voice"))
            client.on("message.file", make_handler("file"))
            client.on("message.mixed", make_handler("mixed"))
            client.on("event.enter_chat", self._make_enter_chat_handler(bot_id, client, cfg.get("welcome_message") or ""))

            logger.info("WeCom bot starting (bot_id={})", bot_id[:16] + "...")
            await client.connect_async()
            while self._running:
                await asyncio.sleep(1)

        tasks = [asyncio.create_task(run_one_bot(cfg)) for cfg in self._bot_configs]
        logger.info("WeCom: {} bot(s), WebSocket long connection", len(self._bot_configs))
        await asyncio.gather(*tasks, return_exceptions=True)

    def _make_enter_chat_handler(self, bot_id: str, client: Any, welcome_message: str):
        async def _on_enter_chat(frame: Any) -> None:
            try:
                body = frame.body if hasattr(frame, "body") else (frame.get("body", frame) if isinstance(frame, dict) else {})
                chat_id = body.get("chatid", "") if isinstance(body, dict) else ""
                if chat_id and welcome_message:
                    await client.reply_welcome(frame, {"msgtype": "text", "text": {"content": welcome_message}})
            except Exception as e:
                logger.error("Error handling enter_chat: {}", e)
        return _on_enter_chat

    async def stop(self) -> None:
        """Stop the WeCom bot(s)."""
        self._running = False
        for bot_id, client in self._clients_by_bot_id.items():
            try:
                await client.disconnect()
            except Exception as e:
                logger.warning("WeCom disconnect {}: {}", bot_id[:16], e)
        if self._client:
            self._client = None
        self._clients_by_bot_id.clear()
        logger.info("WeCom bot(s) stopped")

    async def _on_connected(self, frame: Any) -> None:
        """Handle WebSocket connected event."""
        logger.info("WeCom WebSocket connected")

    async def _on_authenticated(self, frame: Any) -> None:
        """Handle authentication success event."""
        logger.info("WeCom authenticated successfully")

    async def _on_disconnected(self, frame: Any) -> None:
        """Handle WebSocket disconnected event."""
        reason = frame.body if hasattr(frame, 'body') else str(frame)
        logger.warning("WeCom WebSocket disconnected: {}", reason)

    async def _on_error(self, frame: Any) -> None:
        """Handle error event."""
        logger.error("WeCom error: {}", frame)

    async def _process_message(self, frame: Any, msg_type: str, bot_id: str, client: Any) -> None:
        """Process incoming message and forward to bus."""
        try:
            # Extract body from WsFrame dataclass or dict
            if hasattr(frame, 'body'):
                body = frame.body or {}
            elif isinstance(frame, dict):
                body = frame.get("body", frame)
            else:
                body = {}

            # Ensure body is a dict
            if not isinstance(body, dict):
                logger.warning("Invalid body type: {}", type(body))
                return

            # Extract message info
            msg_id = body.get("msgid", "")
            if not msg_id:
                msg_id = f"{body.get('chatid', '')}_{body.get('sendertime', '')}"

            # Deduplication check
            if msg_id in self._processed_message_ids:
                return
            self._processed_message_ids[msg_id] = None

            # Trim cache
            while len(self._processed_message_ids) > 1000:
                self._processed_message_ids.popitem(last=False)

            # Extract sender info from "from" field (SDK format)
            from_info = body.get("from", {})
            sender_id = from_info.get("userid", "unknown") if isinstance(from_info, dict) else "unknown"

            # For single chat, chatid is the sender's userid; for group, chatid is group id
            chat_type = body.get("chattype", "single")
            chat_id = body.get("chatid", sender_id)
            composite_chat_id = f"{bot_id}:{chat_id}" if len(self._bot_configs) > 1 else chat_id
            logger.info("WeCom recv chat_type={} chat_id={} msg_type={}", chat_type, chat_id[:30] + "..." if len(chat_id) > 30 else chat_id, msg_type)

            # Per-bot allow list
            allow_list = self._allow_from_by_bot_id.get(bot_id) or (
                list(self.config.allow_from) if len(self._bot_configs) <= 1 else []
            )
            if "*" not in allow_list and sender_id not in allow_list:
                logger.warning("WeCom access denied for {} on bot {}", sender_id, bot_id[:16] + "...")
                return

            content_parts = []
            media_paths: list[str] = []

            if msg_type == "text":
                text = body.get("text", {}).get("content", "")
                if text:
                    content_parts.append(text)

            elif msg_type == "image":
                image_info = body.get("image", {})
                file_url = image_info.get("url", "")
                aes_key = image_info.get("aeskey", "")

                if file_url and aes_key:
                    file_path = await self._download_and_save_media(client, file_url, aes_key, "image")
                    if file_path:
                        media_paths.append(file_path)
                        content_parts.append("[image: 用户发送了一张图片]")
                    else:
                        content_parts.append("[image: download failed]")
                else:
                    content_parts.append("[image: download failed]")

            elif msg_type == "voice":
                voice_info = body.get("voice", {})
                # Voice message already contains transcribed content from WeCom
                voice_content = voice_info.get("content", "")
                if voice_content:
                    content_parts.append(f"[voice] {voice_content}")
                else:
                    content_parts.append("[voice]")

            elif msg_type == "file":
                # Any file type (log/yml/txt/json/…): download once, pass path to model; model decides read_file/list_dir/etc.
                file_info = body.get("file", {}) if isinstance(body.get("file"), dict) else {}
                file_url = file_info.get("url", "")
                aes_key = file_info.get("aeskey", "")
                # API may use "name" / "filename" / "filename_extension"; prefer non-empty
                file_name = (
                    file_info.get("name")
                    or file_info.get("filename")
                    or file_info.get("filename_extension")
                    or ""
                ).strip() or None

                if file_url and aes_key:
                    file_path = await self._download_and_save_media(client, file_url, aes_key, "file", file_name)
                    if file_path:
                        display_name = os.path.basename(file_path)
                        content_parts.append(f"[用户发送了文件: {display_name}]\n路径: {file_path}")
                    else:
                        content_parts.append("[file: download failed]")
                else:
                    content_parts.append("[file: download failed]")

            elif msg_type == "mixed":
                # Mixed content (e.g. group image): official API uses mixed.msg_item (WeCom OpenClaw plugin / aibot-node-sdk)
                mixed_raw = body.get("mixed")
                if isinstance(mixed_raw, list):
                    msg_items = mixed_raw
                elif isinstance(mixed_raw, dict):
                    msg_items = (
                        mixed_raw.get("msg_item")
                        or mixed_raw.get("item")
                        or mixed_raw.get("items")
                        or []
                    )
                else:
                    msg_items = []
                for item in msg_items:
                    if not isinstance(item, dict):
                        continue
                    item_type = item.get("type") or item.get("msgtype") or ""
                    if item_type == "text":
                        text = (item.get("text") or {}).get("content", "") if isinstance(item.get("text"), dict) else ""
                        if text:
                            content_parts.append(text)
                    elif item_type == "image":
                        img = item.get("image") if isinstance(item.get("image"), dict) else {}
                        i_url, i_key = img.get("url", ""), img.get("aeskey", "")
                        if i_url and i_key:
                            file_path = await self._download_and_save_media(client, i_url, i_key, "image")
                            if file_path:
                                media_paths.append(file_path)
                                content_parts.append("[image: 用户发送了一张图片]")
                            else:
                                content_parts.append("[image: download failed]")
                        else:
                            content_parts.append("[image: download failed]")
                    elif item_type == "file":
                        # Group chat file: same as top-level file — download and pass path to model
                        file_info = item.get("file") if isinstance(item.get("file"), dict) else {}
                        f_url = file_info.get("url", "")
                        f_key = file_info.get("aeskey", "")
                        f_name = (
                            file_info.get("name")
                            or file_info.get("filename")
                            or file_info.get("filename_extension")
                            or ""
                        ).strip() or None
                        if f_url and f_key:
                            file_path = await self._download_and_save_media(client, f_url, f_key, "file", f_name)
                            if file_path:
                                display_name = os.path.basename(file_path)
                                content_parts.append(f"[用户发送了文件: {display_name}]\n路径: {file_path}")
                            else:
                                content_parts.append("[file: download failed]")
                        else:
                            content_parts.append("[file: download failed]")
                    else:
                        content_parts.append(MSG_TYPE_MAP.get(item_type, f"[{item_type}]"))
                if not content_parts and not media_paths and msg_items:
                    logger.debug("WeCom mixed item keys sample: {}", [list(i.keys()) for i in msg_items[:3]])

            else:
                content_parts.append(MSG_TYPE_MAP.get(msg_type, f"[{msg_type}]"))

            content = "\n".join(content_parts) if content_parts else ""
            if not content and not media_paths:
                logger.warning("WeCom message dropped: no content and no media (chat_type={} msg_type={})", chat_type, msg_type)
                return
            if not content and media_paths:
                content = "[用户发送了图片]"

            # Store (frame, bot_id, chat_type) for this chat to enable replies
            self._chat_frames[composite_chat_id] = (frame, bot_id, chat_type)

            # Session key: one session per (channel, chat) so group and single chat each have their own history
            session_key = f"{self.name}:{composite_chat_id}"

            # Forward to message bus (media paths enable vision for the model)
            await self._handle_message(
                sender_id=sender_id,
                chat_id=composite_chat_id,
                content=content,
                media=media_paths if media_paths else None,
                metadata={
                    "message_id": msg_id,
                    "msg_type": msg_type,
                    "chat_type": chat_type,
                },
                session_key=session_key,
            )

        except Exception as e:
            logger.error("Error processing WeCom message: {}", e)

    async def _download_and_save_media(
        self,
        client: Any,
        file_url: str,
        aes_key: str,
        media_type: str,
        filename: str | None = None,
    ) -> str | None:
        """
        Download and decrypt media from WeCom.

        Returns:
            file_path or None if download failed
        """
        try:
            data, fname = await client.download_file(file_url, aes_key)

            if not data:
                logger.warning("Failed to download media from WeCom")
                return None

            media_dir = get_media_dir("wecom")
            # Use SDK response filename when body did not provide a real name (e.g. "unknown" or empty)
            if not filename or (isinstance(filename, str) and filename.strip() in ("", "unknown")):
                filename = fname or f"{media_type}_{hash(file_url) % 100000}"
            filename = os.path.basename(filename)
            # Avoid overwriting: unique suffix when name is generic or path exists
            file_path = media_dir / filename
            if file_path.exists() or filename in ("unknown", "file"):
                ext = os.path.splitext(filename)[1] or ""
                filename = f"file_{int(time.time() * 1000)}_{hash(file_url) % 100000}{ext}"
                file_path = media_dir / filename
            file_path.write_bytes(data)
            logger.debug("Downloaded {} to {}", media_type, file_path)
            return str(file_path)

        except Exception as e:
            logger.error("Error downloading media: {}", e)
            return None

    async def _upload_media_ws(self, client: Any, file_path: str) -> "tuple[str, str] | tuple[None, None]":
        """Upload a local file to WeCom via WebSocket long connection.

        Uses the 3-step upload protocol:
          aibot_upload_media_init  → upload_id
          aibot_upload_media_chunk × N  (≤512 KB raw per chunk, base64-encoded)
          aibot_upload_media_finish → media_id

        Returns:
            (media_id, media_type) on success, (None, None) on failure.
        """
        from wecom_aibot_sdk.utils import generate_req_id as _gen_req_id

        try:
            fname = os.path.basename(file_path)
            ext = os.path.splitext(fname)[1].lower()

            if ext in (".jpg", ".jpeg", ".png", ".gif"):
                media_type = "image"
            elif ext in (".mp4",):
                media_type = "video"
            elif ext in (".amr",):
                media_type = "voice"
            else:
                media_type = "file"

            data = Path(file_path).read_bytes()
            file_size = len(data)
            md5_hash = hashlib.md5(data).hexdigest()

            CHUNK_SIZE = 512 * 1024  # 512 KB raw (before base64)
            chunks = [data[i:i + CHUNK_SIZE] for i in range(0, file_size, CHUNK_SIZE)]
            n_chunks = len(chunks)

            # 1. Init
            req_id = _gen_req_id("upload_init")
            resp = await client._ws_manager.send_reply(req_id, {
                "type": media_type,
                "filename": fname,
                "total_size": file_size,
                "total_chunks": n_chunks,
                "md5": md5_hash,
            }, "aibot_upload_media_init")
            if resp.errcode != 0:
                logger.warning("WeCom upload init failed ({}): {}", resp.errcode, resp.errmsg)
                return None, None
            upload_id = resp.body.get("upload_id") if resp.body else None
            if not upload_id:
                logger.warning("WeCom upload init: no upload_id in response")
                return None, None

            # 2. Chunks
            for i, chunk in enumerate(chunks):
                req_id = _gen_req_id("upload_chunk")
                resp = await client._ws_manager.send_reply(req_id, {
                    "upload_id": upload_id,
                    "chunk_index": i,
                    "base64_data": base64.b64encode(chunk).decode(),
                }, "aibot_upload_media_chunk")
                if resp.errcode != 0:
                    logger.warning("WeCom upload chunk {} failed ({}): {}", i, resp.errcode, resp.errmsg)
                    return None, None

            # 3. Finish
            req_id = _gen_req_id("upload_finish")
            resp = await client._ws_manager.send_reply(req_id, {
                "upload_id": upload_id,
            }, "aibot_upload_media_finish")
            if resp.errcode != 0:
                logger.warning("WeCom upload finish failed ({}): {}", resp.errcode, resp.errmsg)
                return None, None

            media_id = resp.body.get("media_id") if resp.body else None
            if not media_id:
                logger.warning("WeCom upload finish: no media_id in response body={}", resp.body)
                return None, None

            logger.debug("WeCom uploaded {} ({}) → media_id={}", fname, media_type, media_id[:16] + "...")
            return media_id, media_type

        except Exception as e:
            logger.error("WeCom _upload_media_ws error for {}: {}", file_path, e)
            return None, None

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through WeCom.

        WeCom long-connection protocol:
        - Text/markdown: streamed via reply_stream (cumulative, rate-limited)
        - Media (image/file/video/voice): upload via WS 3-step → send as separate message
          with media_id (aibot_respond_msg or aibot_send_msg)
        - NOTE: msg_item in stream is not supported in long-connection mode (per API docs).
        """
        if not self._clients_by_bot_id:
            logger.warning("WeCom client not initialized")
            return

        try:
            content = (msg.content or "").strip()

            entry = self._chat_frames.get(msg.chat_id)
            frame, bot_id, chat_type_str = (entry if entry else (None, None, "single"))

            # If no frame, pick the first available bot for proactive send
            if bot_id is None:
                bot_id = next(iter(self._clients_by_bot_id), None)
            client = self._clients_by_bot_id.get(bot_id) if bot_id else None
            if not client:
                logger.warning("WeCom client not found for chat {}, cannot send", msg.chat_id)
                return

            _proactive = frame is None
            is_progress = bool(msg.metadata.get("_progress"))

            # ── Media: upload each file and send as dedicated message ──────────
            # Skip media on progress frames (only send with final response)
            if (msg.media or []) and not is_progress:
                raw_chat_id = msg.chat_id.split(":", 1)[-1] if ":" in msg.chat_id else msg.chat_id
                # chat_type for proactive: 1=single, 2=group, 0=auto
                chat_type_int = 2 if chat_type_str == "group" else 1
                for file_path in msg.media:
                    if not os.path.isfile(file_path):
                        logger.warning("WeCom media file not found: {}", file_path)
                        continue
                    media_id, media_type = await self._upload_media_ws(client, file_path)
                    if not media_id:
                        logger.warning("WeCom media upload failed, skipping: {}", file_path)
                        continue
                    media_body: dict[str, Any] = {
                        "msgtype": media_type,
                        media_type: {"media_id": media_id},
                    }
                    from wecom_aibot_sdk.utils import generate_req_id as _gen_req_id
                    if _proactive:
                        media_body["chatid"] = raw_chat_id
                        media_body["chat_type"] = 0  # auto-detect single/group
                        req_id = _gen_req_id("media_send")
                        await client._ws_manager.send_reply(req_id, media_body, "aibot_send_msg")
                    else:
                        req_id = frame.headers["req_id"] if hasattr(frame, "headers") else _gen_req_id("media_reply")
                        await client._ws_manager.send_reply(req_id, media_body, "aibot_respond_msg")
                    logger.debug("WeCom sent media {} ({}) → {}", media_type, os.path.basename(file_path), msg.chat_id)

            # ── Text / markdown ───────────────────────────────────────────────
            if not content:
                return

            if _proactive:
                if not is_progress:
                    raw_chat_id = msg.chat_id.split(":", 1)[-1] if ":" in msg.chat_id else msg.chat_id
                    from wecom_aibot_sdk.utils import generate_req_id as _gen_req_id
                    req_id = _gen_req_id("text_send")
                    await client._ws_manager.send_reply(req_id, {
                        "chatid": raw_chat_id,
                        "chat_type": 0,
                        "msgtype": "markdown",
                        "markdown": {"content": content},
                    }, "aibot_send_msg")
                    logger.debug("WeCom proactive send ({} chars) → {}", len(content), msg.chat_id)

            elif is_progress:
                if msg.chat_id not in self._active_streams:
                    self._active_streams[msg.chat_id] = self._generate_req_id("stream")
                    self._stream_content[msg.chat_id] = ""
                    self._stream_last_send[msg.chat_id] = 0.0

                self._stream_content[msg.chat_id] += content
                accumulated = self._stream_content[msg.chat_id]
                stream_id = self._active_streams[msg.chat_id]

                now = time.time()
                if now - self._stream_last_send[msg.chat_id] >= self._STREAM_MIN_INTERVAL:
                    await client.reply_stream(frame, stream_id, accumulated, finish=False)
                    self._stream_last_send[msg.chat_id] = now
                    logger.debug("WeCom stream update ({} chars) → {}", len(accumulated), msg.chat_id)

            else:
                stream_id = self._active_streams.pop(msg.chat_id, None) or self._generate_req_id("stream")
                self._stream_content.pop(msg.chat_id, None)
                self._stream_last_send.pop(msg.chat_id, None)
                await client.reply_stream(frame, stream_id, content, finish=True)
                logger.debug("WeCom stream finish ({} chars) → {}", len(content), msg.chat_id)

        except Exception as e:
            logger.error("Error sending WeCom message: {}", e)
