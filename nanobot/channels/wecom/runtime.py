# pyright: reportMissingTypeStubs=false
"""WeCom (Enterprise WeChat) channel implementation using wecom_aibot_sdk."""

import asyncio
import importlib.util
import os
import re
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from pydantic import Field

from nanobot.bus.events import OutboundMessage
from nanobot.bus.outbound_events import ProgressEvent
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.paths import get_media_dir
from nanobot.config.schema import Base

WECOM_AVAILABLE = importlib.util.find_spec("wecom_aibot_sdk") is not None

# Inbound media safety limit (matching QQ channel defaults)
WECOM_DOWNLOAD_MAX_BYTES = 1024 * 1024 * 200  # 200MB

# Replace unsafe characters with "_", keep Chinese and common safe punctuation.
_SAFE_NAME_RE = re.compile(r"[^\w.\-()\[\]（）【】\u4e00-\u9fff]+", re.UNICODE)


def _sanitize_filename(name: str, fallback: str = "unnamed") -> str:
    """Sanitize filename to avoid traversal and problematic chars."""
    def _clean(value: str) -> str:
        value = (value or "").strip()
        value = Path(value).name
        return _SAFE_NAME_RE.sub("_", value).strip("._ ")

    return _clean(name) or _clean(fallback) or "unnamed"


class WecomConfig(Base):
    """WeCom (Enterprise WeChat) AI Bot channel configuration."""

    enabled: bool = False
    bot_id: str = ""
    secret: str = ""
    allow_from: list[str] = Field(default_factory=list)
    welcome_message: str = ""


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

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = WecomConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: WecomConfig = config
        self._client: Any = None
        self._processed_message_ids: OrderedDict[str, None] = OrderedDict()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._generate_req_id: Callable[[str], str] | None = None
        # Store frame headers for each chat to enable replies
        self._chat_frames: dict[str, Any] = {}

    async def start(self) -> None:
        """Start the WeCom bot with WebSocket long connection."""
        if not WECOM_AVAILABLE:
            self.logger.error("SDK not installed. Run: nanobot plugins enable wecom")
            return

        if not self.config.bot_id or not self.config.secret:
            self.logger.error("bot_id and secret not configured")
            return

        from wecom_aibot_sdk import WSClient, generate_req_id

        self._running = True
        self._loop = asyncio.get_running_loop()
        self._generate_req_id = generate_req_id

        # Create WebSocket client
        ws_client = cast(Any, WSClient)
        self._client = ws_client({
            "bot_id": self.config.bot_id,
            "secret": self.config.secret,
            "reconnect_interval": 1000,
            "max_reconnect_attempts": -1,  # Infinite reconnect
            "heartbeat_interval": 30000,
        })

        # Register event handlers
        self._client.on("connected", self._on_connected)
        self._client.on("authenticated", self._on_authenticated)
        self._client.on("disconnected", self._on_disconnected)
        self._client.on("error", self._on_error)
        self._client.on("message.text", self._on_text_message)
        self._client.on("message.image", self._on_image_message)
        self._client.on("message.voice", self._on_voice_message)
        self._client.on("message.file", self._on_file_message)
        self._client.on("message.mixed", self._on_mixed_message)
        self._client.on("event.enter_chat", self._on_enter_chat)

        self.logger.info("bot starting with WebSocket long connection")
        self.logger.info("No public IP required - using WebSocket to receive events")

        # Connect
        await self._client.connect_async()

        # Keep running until stopped
        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """Stop the WeCom bot."""
        self._running = False
        if self._client:
            await self._client.disconnect()
        self.logger.info("bot stopped")

    async def _on_connected(self, frame: Any) -> None:
        """Handle WebSocket connected event."""
        self.logger.info("WebSocket connected")

    async def _on_authenticated(self, frame: Any) -> None:
        """Handle authentication success event."""
        self.logger.info("authenticated successfully")

    async def _on_disconnected(self, frame: Any) -> None:
        """Handle WebSocket disconnected event."""
        reason = frame.body if hasattr(frame, 'body') else str(frame)
        self.logger.warning("WebSocket disconnected: {}", reason)

    async def _on_error(self, frame: Any) -> None:
        """Handle error event."""
        self.logger.error("error: {}", frame)

    async def _on_text_message(self, frame: Any) -> None:
        """Handle text message."""
        await self._process_message(frame, "text")

    async def _on_image_message(self, frame: Any) -> None:
        """Handle image message."""
        await self._process_message(frame, "image")

    async def _on_voice_message(self, frame: Any) -> None:
        """Handle voice message."""
        await self._process_message(frame, "voice")

    async def _on_file_message(self, frame: Any) -> None:
        """Handle file message."""
        await self._process_message(frame, "file")

    async def _on_mixed_message(self, frame: Any) -> None:
        """Handle mixed content message."""
        await self._process_message(frame, "mixed")

    async def _on_enter_chat(self, frame: Any) -> None:
        """Handle enter_chat event (user opens chat with bot)."""
        try:
            # Extract body from WsFrame dataclass or dict
            if hasattr(frame, "body"):
                body: Any = frame.body or {}
            elif isinstance(frame, dict):
                frame_dict = cast(dict[str, Any], frame)
                body = frame_dict.get("body", frame_dict)
            else:
                body = {}

            body_dict = cast(dict[str, Any], body) if isinstance(body, dict) else {}
            chat_id = cast(str, body_dict.get("chatid", ""))

            if chat_id and not self.is_allowed(chat_id):
                return

            if chat_id and self.config.welcome_message:
                await self._client.reply_welcome(frame, {
                    "msgtype": "text",
                    "text": {"content": self.config.welcome_message},
                })
        except Exception:
            self.logger.exception("Error handling enter_chat")

    async def _process_message(self, frame: Any, msg_type: str) -> None:
        """Process incoming message and forward to bus."""
        try:
            # Extract body from WsFrame dataclass or dict
            if hasattr(frame, "body"):
                body: Any = frame.body or {}
            elif isinstance(frame, dict):
                frame_dict = cast(dict[str, Any], frame)
                body = frame_dict.get("body", frame_dict)
            else:
                body = {}

            # Ensure body is a dict
            if not isinstance(body, dict):
                self.logger.warning("Invalid body type: {}", type(cast(object, body)))
                return
            body = cast(dict[str, Any], body)

            # Extract message info
            msg_id = cast(str, body.get("msgid", ""))
            if not msg_id:
                msg_id = f"{body.get('chatid', '')}_{body.get('sendertime', '')}"

            # Extract sender info from "from" field (SDK format)
            from_info = body.get("from", {})
            sender_id = (
                cast(str, cast(dict[str, Any], from_info).get("userid", "unknown"))
                if isinstance(from_info, dict)
                else "unknown"
            )
            if not self.is_allowed(sender_id):
                return

            # Deduplication check
            if msg_id in self._processed_message_ids:
                return
            self._processed_message_ids[msg_id] = None

            # Trim cache
            while len(self._processed_message_ids) > 1000:
                self._processed_message_ids.popitem(last=False)

            # For single chat, chatid is the sender's userid
            # For group chat, chatid is provided in body
            chat_type = cast(str, body.get("chattype", "single"))
            chat_id = cast(str, body.get("chatid", sender_id))

            content_parts: list[str] = []
            media_paths: list[str] = []

            if msg_type == "text":
                text_info = cast(dict[str, Any], body.get("text", {}))
                text = cast(str, text_info.get("content", ""))
                if text:
                    content_parts.append(text)

            elif msg_type == "image":
                image_info = cast(dict[str, Any], body.get("image", {}))
                file_url = cast(str, image_info.get("url", ""))
                aes_key = cast(str, image_info.get("aeskey", ""))

                if file_url and aes_key:
                    file_path = await self._download_and_save_media(file_url, aes_key, "image")
                    if file_path:
                        filename = os.path.basename(file_path)
                        content_parts.append(f"[image: {filename}]")
                        media_paths.append(file_path)
                    else:
                        content_parts.append("[image: download failed]")
                else:
                    content_parts.append("[image: download failed]")

            elif msg_type == "voice":
                voice_info = cast(dict[str, Any], body.get("voice", {}))
                # Voice message already contains transcribed content from WeCom
                voice_content = cast(str, voice_info.get("content", ""))
                if voice_content:
                    content_parts.append(f"[voice] {voice_content}")
                else:
                    content_parts.append("[voice]")

            elif msg_type == "file":
                file_info = cast(dict[str, Any], body.get("file", {}))
                file_url = cast(str, file_info.get("url", ""))
                aes_key = cast(str, file_info.get("aeskey", ""))
                file_name = cast(str | None, file_info.get("name") or None)

                if file_url and aes_key:
                    file_path = await self._download_and_save_media(file_url, aes_key, "file", file_name)
                    if file_path:
                        display_name = os.path.basename(file_path)
                        content_parts.append(f"[file: {display_name}]")
                        media_paths.append(file_path)
                    else:
                        content_parts.append(f"[file: {file_name or 'unknown'}: download failed]")
                else:
                    content_parts.append(f"[file: {file_name or 'unknown'}: download failed]")

            elif msg_type == "mixed":
                # Mixed content contains multiple message items
                mixed_info = cast(dict[str, Any], body.get("mixed", {}))
                msg_items = cast(list[Any], mixed_info.get("msg_item", []))
                for raw_item in msg_items:
                    item = cast(dict[str, Any], raw_item)
                    item_type = cast(str, item.get("msgtype", ""))
                    if item_type == "text":
                        text_info = cast(dict[str, Any], item.get("text", {}))
                        text = cast(str, text_info.get("content", ""))
                        if text:
                            content_parts.append(text)
                    elif item_type == "image":
                        image_info = cast(dict[str, Any], item.get("image", {}))
                        file_url = cast(str, image_info.get("url", ""))
                        aes_key = cast(str, image_info.get("aeskey", ""))
                        if file_url and aes_key:
                            file_path = await self._download_and_save_media(file_url, aes_key, "image")
                            if file_path:
                                filename = os.path.basename(file_path)
                                content_parts.append(f"[image: {filename}]")
                                media_paths.append(file_path)
                    else:
                        content_parts.append(MSG_TYPE_MAP.get(item_type, f"[{item_type}]"))

            else:
                content_parts.append(MSG_TYPE_MAP.get(msg_type, f"[{msg_type}]"))

            content = "\n".join(content_parts) if content_parts else ""

            if not content:
                return

            # Store frame for this chat to enable replies
            self._chat_frames[chat_id] = frame

            # Forward to message bus
            await self._handle_message(
                sender_id=sender_id,
                chat_id=chat_id,
                content=content,
                media=media_paths or None,
                metadata={
                    "message_id": msg_id,
                    "msg_type": msg_type,
                    "chat_type": chat_type,
                }
            )

        except Exception:
            self.logger.exception("Error processing message")

    async def _download_and_save_media(
        self,
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
            data, fname = await self._client.download_file(file_url, aes_key)

            if not data:
                self.logger.warning("Failed to download media")
                return None

            if len(data) > WECOM_DOWNLOAD_MAX_BYTES:
                self.logger.warning(
                    "inbound media too large: {} bytes (max {})",
                    len(data),
                    WECOM_DOWNLOAD_MAX_BYTES,
                )
                return None

            media_dir = get_media_dir("wecom")
            fallback_name = fname or f"{media_type}_{hash(file_url) % 100000}"
            filename = _sanitize_filename(cast(str, filename or fallback_name), fallback=fallback_name)

            file_path = media_dir / filename
            await asyncio.to_thread(file_path.write_bytes, data)
            self.logger.debug("Downloaded {} to {}", media_type, file_path)
            return str(file_path)

        except Exception:
            self.logger.exception("Error downloading media")
            return None

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through WeCom."""
        if not self._client:
            raise RuntimeError("WeCom client not initialized")

        try:
            content = (msg.content or "").strip()
            is_progress = isinstance(msg.event, ProgressEvent)

            # Get the stored frame for this chat
            frame = self._chat_frames.get(msg.chat_id)

            # Send media files via WebSocket upload
            for file_path in msg.media or []:
                if not os.path.isfile(file_path):
                    self.logger.warning("media file not found: {}", file_path)
                    continue
                try:
                    upload = await self._client.upload_media(file_path)
                except Exception:
                    self.logger.exception("media upload failed for {}", file_path)
                    content += f"\n[file upload failed: {os.path.basename(file_path)}]"
                    continue

                media_type = upload.media_type
                media_body = {
                    "msgtype": media_type,
                    media_type: {"media_id": upload.media_id},
                }
                if frame:
                    await self._client.reply(frame, media_body)
                else:
                    await self._client.send_message(msg.chat_id, media_body)
                self.logger.debug("sent {} → {}", media_type, msg.chat_id)

            if not content:
                return

            if frame:
                # Keep progress and final updates on the SDK's serialized streaming reply path.
                generate_req_id = self._generate_req_id
                if generate_req_id is None:
                    raise RuntimeError("WeCom request-id generator is not initialized")
                stream_id = generate_req_id("stream")
                await self._client.reply_stream(
                    frame,
                    stream_id,
                    content,
                    finish=not is_progress,
                )
                self.logger.debug(
                    "{} sent to {}",
                    "progress" if is_progress else "message",
                    msg.chat_id,
                )
            else:
                # No frame (e.g. cron push): proactive send only supports markdown
                await self._client.send_message(msg.chat_id, {
                    "msgtype": "markdown",
                    "markdown": {"content": content},
                })
                self.logger.info("proactive send to {}", msg.chat_id)

        except Exception:
            self.logger.exception("Error sending message to chat_id={}", msg.chat_id)
            raise
