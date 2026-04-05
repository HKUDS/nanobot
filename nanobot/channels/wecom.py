"""WeCom (Enterprise WeChat) channel implementation using wecom_aibot_sdk."""

import asyncio
import base64
import hashlib
import importlib.util
import json
import os
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

class WecomConfig(Base):
    """WeCom (Enterprise WeChat) AI Bot channel configuration."""

    enabled: bool = False
    bot_id: str = ""
    secret: str = ""
    allow_from: list[str] = Field(default_factory=list)
    welcome_message: str = ""
    streaming: bool = True  # Stream final results; if False, send as normal message


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
        self._generate_req_id = None
        # Store frame headers for each chat to enable replies
        self._chat_frames: dict[str, Any] = {}
        # Store stream IDs for each chat to enable progress updates
        self._stream_ids: dict[str, str] = {}
        # Store result stream state for streaming results
        self._result_stream_bufs: dict[str, str] = {}  # chat_id -> accumulated text
        self._result_stream_ids: dict[str, str] = {}  # chat_id -> stream_id

    async def start(self) -> None:
        """Start the WeCom bot with WebSocket long connection."""
        if not WECOM_AVAILABLE:
            logger.error("WeCom SDK not installed. Run: pip install nanobot-ai[wecom]")
            return

        if not self.config.bot_id or not self.config.secret:
            logger.error("WeCom bot_id and secret not configured")
            return

        from wecom_aibot_sdk import WSClient, generate_req_id

        self._running = True
        self._loop = asyncio.get_running_loop()
        self._generate_req_id = generate_req_id

        # Create WebSocket client
        self._client = WSClient({
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

        logger.info("WeCom bot starting with WebSocket long connection")
        logger.info("No public IP required - using WebSocket to receive events")

        # Connect
        await self._client.connect()

        # Keep running until stopped
        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """Stop the WeCom bot."""
        self._running = False
        if self._client:
            await self._client.disconnect()
        logger.info("WeCom bot stopped")

    async def _on_connected(self, frame: Any = None) -> None:
        """Handle WebSocket connected event."""
        logger.info("WeCom WebSocket connected")

    async def _on_authenticated(self, frame: Any = None) -> None:
        """Handle authentication success event."""
        logger.info("WeCom authenticated successfully")

    async def _on_disconnected(self, frame: Any) -> None:
        """Handle WebSocket disconnected event."""
        reason = frame.body if hasattr(frame, 'body') else str(frame)
        logger.warning("WeCom WebSocket disconnected: {}", reason)

    async def _on_error(self, frame: Any) -> None:
        """Handle error event."""
        logger.error("WeCom error: {}", frame)

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
            if hasattr(frame, 'body'):
                body = frame.body or {}
            elif isinstance(frame, dict):
                body = frame.get("body", frame)
            else:
                body = {}

            chat_id = body.get("chatid", "") if isinstance(body, dict) else ""

            if chat_id and self.config.welcome_message:
                await self._client.reply_welcome(frame, {
                    "msgtype": "text",
                    "text": {"content": self.config.welcome_message},
                })
        except Exception as e:
            logger.error("Error handling enter_chat: {}", e)

    async def _process_message(self, frame: Any, msg_type: str) -> None:
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

            # For single chat, chatid is the sender's userid
            # For group chat, chatid is provided in body
            chat_type = body.get("chattype", "single")
            chat_id = body.get("chatid", sender_id)

            content_parts = []

            if msg_type == "text":
                text = body.get("text", {}).get("content", "")
                if text:
                    content_parts.append(text)

            elif msg_type == "image":
                image_info = body.get("image", {})
                file_url = image_info.get("url", "")
                aes_key = image_info.get("aeskey", "")

                if file_url and aes_key:
                    file_path = await self._download_and_save_media(file_url, aes_key, "image")
                    if file_path:
                        filename = os.path.basename(file_path)
                        content_parts.append(f"[image: {filename}]\n[Image: source: {file_path}]")
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
                file_info = body.get("file", {})
                file_url = file_info.get("url", "")
                aes_key = file_info.get("aeskey", "")
                file_name = file_info.get("name", "unknown")

                if file_url and aes_key:
                    file_path = await self._download_and_save_media(file_url, aes_key, "file", file_name)
                    if file_path:
                        content_parts.append(f"[file: {file_name}]\n[File: source: {file_path}]")
                    else:
                        content_parts.append(f"[file: {file_name}: download failed]")
                else:
                    content_parts.append(f"[file: {file_name}: download failed]")

            elif msg_type == "mixed":
                # Mixed content contains multiple message items
                msg_items = body.get("mixed", {}).get("item", [])
                for item in msg_items:
                    item_type = item.get("type", "")
                    if item_type == "text":
                        text = item.get("text", {}).get("content", "")
                        if text:
                            content_parts.append(text)
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
            # Note: media paths are included in content for broader model compatibility
            await self._handle_message(
                sender_id=sender_id,
                chat_id=chat_id,
                content=content,
                media=None,
                metadata={
                    "message_id": msg_id,
                    "msg_type": msg_type,
                    "chat_type": chat_type,
                }
            )

        except Exception as e:
            logger.error("Error processing WeCom message: {}", e)

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
                logger.warning("Failed to download media from WeCom")
                return None

            media_dir = get_media_dir("wecom")
            if not filename:
                filename = fname or f"{media_type}_{hash(file_url) % 100000}"
            filename = os.path.basename(filename)

            file_path = media_dir / filename
            file_path.write_bytes(data)
            logger.debug("Downloaded {} to {}", media_type, file_path)
            return str(file_path)

        except Exception as e:
            logger.error("Error downloading media: {}", e)
            return None

    # ========== Image processing helper methods ==========

    @staticmethod
    def _is_image_url(path: str) -> bool:
        """Check if path is an HTTP/HTTPS URL."""
        return path.startswith(("http://", "https://"))

    @staticmethod
    def _get_image_extension(path: str) -> str:
        """Get image file extension from path."""
        ext = Path(path).suffix.lower()
        # Normalize common extensions
        if ext in (".jpg", ".jpeg"):
            return ".jpg"
        elif ext == ".png":
            return ".png"
        elif ext == ".gif":
            return ".gif"
        return ext

    @staticmethod
    def _validate_image_size(size: int) -> bool:
        """Validate image size (≤10MB for WeCom)."""
        MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB
        return size <= MAX_IMAGE_SIZE

    @staticmethod
    def _get_media_type(file_path: str) -> str:
        """
        Determine WeCom media type based on file extension.

        Returns:
            One of: "image", "video", "voice", "file"
        """
        ext = Path(file_path).suffix.lower()

        # Image formats
        if ext in (".jpg", ".jpeg", ".png", ".gif"):
            return "image"
        # Video formats
        if ext in (".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv"):
            return "video"
        # Voice/Audio formats
        if ext in (".mp3", ".wav", ".amr", ".m4a", ".aac", ".ogg"):
            return "voice"
        # Everything else as file
        return "file"

    def _read_and_encode_image(self, file_path: str) -> tuple[str, str] | None:
        """
        Read local image file and encode as Base64 with MD5 checksum.

        Returns:
            (base64_encoded_data, md5_hash) or None if failed
        """
        try:
            p = Path(file_path)
            if not p.is_file():
                logger.warning("Image file not found: {}", file_path)
                return None

            # Validate file extension
            ext = self._get_image_extension(file_path)
            if ext not in (".jpg", ".jpeg", ".png", ".gif"):
                logger.warning("Unsupported image format {}: {} (only JPG/PNG/GIF supported)", ext, file_path)
                return None

            # Read raw image data
            raw_data = p.read_bytes()
            logger.debug("Read image file: {}, size: {} bytes", file_path, len(raw_data))

            # Validate size
            if not self._validate_image_size(len(raw_data)):
                logger.warning("Image file too large (>10MB): {}", file_path)
                return None

            # Calculate MD5 of original content
            md5_hash = hashlib.md5(raw_data).hexdigest()

            # Encode as Base64
            base64_data = base64.b64encode(raw_data).decode("utf-8")
            logger.debug("Image encoded: Base64 length: {}, MD5: {}", len(base64_data), md5_hash)

            return base64_data, md5_hash

        except Exception as e:
            logger.error("Error reading image {}: {} | Error: {}", file_path, e, e)
            return None

    async def _upload_media(self, file_data: bytes, media_type: str, filename: str) -> str | None:
        """
        Upload media data to WeCom via SDK and return media_id.

        Args:
            file_data: Raw file bytes.
            media_type: One of "image", "video", "voice", "file".
            filename: Filename for the upload.

        Returns:
            media_id or None if upload failed.
        """
        try:
            result = await self._client.upload_media(
                file_data, type=media_type, filename=filename
            )
            media_id = result.get("media_id")
            if media_id:
                logger.info("Uploaded {} {} , media_id: {}", media_type, filename, media_id)
            else:
                logger.error("Upload returned no media_id: {}", result)
            return media_id
        except Exception as e:
            logger.error("Error uploading {} {}: {}", media_type, filename, e)
            return None

    async def _upload_local_media(self, file_path: str) -> str | None:
        """Read local media file and upload via SDK."""
        try:
            p = Path(file_path)
            if not p.is_file():
                logger.warning("Media file not found: {}", file_path)
                return None

            raw_data = p.read_bytes()
            # Use 50MB as max for general files (SDK supports up to ~50MB)
            MAX_FILE_SIZE = 50 * 1024 * 1024
            if len(raw_data) > MAX_FILE_SIZE:
                logger.warning("File too large (>50MB): {}", file_path)
                return None

            media_type = self._get_media_type(file_path)
            return await self._upload_media(raw_data, media_type, p.name)
        except Exception as e:
            logger.error("Error reading local media {}: {}", file_path, e)
            return None

    async def _download_and_upload_media(self, url: str) -> str | None:
        """Download media from URL and upload via SDK."""
        try:
            import httpx

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                raw_data = resp.content

            # Extract filename from URL, fallback to file.bin
            filename = Path(url).name or "file.bin"
            # Strip query parameters from filename
            if "?" in filename:
                filename = filename.split("?")[0]
            # Ensure filename has an extension
            if "." not in filename:
                filename = "file.bin"

            MAX_FILE_SIZE = 50 * 1024 * 1024
            if len(raw_data) > MAX_FILE_SIZE:
                logger.warning("Downloaded file too large (>50MB): {}", url)
                return None

            media_type = self._get_media_type(filename)
            return await self._upload_media(raw_data, media_type, filename)
        except Exception as e:
            logger.error("Error downloading media {}: {}", url, e)
            return None

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through WeCom."""
        if not self._client:
            logger.warning("WeCom client not initialized")
            return

        # Get the stored frame for this chat
        frame = self._chat_frames.get(msg.chat_id)
        if not frame:
            logger.warning("No frame found for chat {}, cannot reply", msg.chat_id)
            return

        # Check if this is a progress message
        is_progress = bool((msg.metadata or {}).get("_progress", False))

        try:
            content = msg.content.strip()

            if is_progress:
                # === Progress message flow ===
                # Check if this is the first progress message for this chat
                stream_id = self._stream_ids.get(msg.chat_id)
                is_first_progress = stream_id is None

                if is_first_progress:
                    # First progress: create new stream and send "正在处理..."
                    stream_id = self._generate_req_id("stream")
                    self._stream_ids[msg.chat_id] = stream_id
                    await self._client.reply_stream(
                        frame,
                        stream_id,
                        "正在处理...",
                        finish=False,
                    )
                    logger.info("WeCom progress stream started for {}", msg.chat_id)

                # Send progress content update
                if content:
                    await self._client.reply_stream(
                        frame,
                        stream_id,
                        content,
                        finish=False,
                    )
                    logger.info("WeCom progress update sent to {}", msg.chat_id)

            else:
                # === Final message flow ===
                # Check if there's an active progress stream
                progress_stream_id = self._stream_ids.pop(msg.chat_id, None)
                if progress_stream_id:
                    # End progress stream with "处理完成"
                    await self._client.reply_stream(
                        frame,
                        progress_stream_id,
                        "处理完成",
                        finish=True,
                    )
                    logger.info("WeCom progress stream ended for {}", msg.chat_id)

                # Send final result
                if content:
                    if self.config.streaming:
                        # Stream the result
                        stream_id = self._generate_req_id("stream")
                        await self._client.reply_stream(
                            frame,
                            stream_id,
                            content,
                            finish=True,
                        )
                        logger.info("WeCom streaming result sent to {}", msg.chat_id)
                    else:
                        # Send as normal message
                        await self._client.reply(frame, content)
                        logger.info("WeCom normal result sent to {}", msg.chat_id)

                # Send media files if any
                if msg.media:
                    await self._send_media_files(frame, msg.media, msg.chat_id)

        except Exception as e:
            logger.error("Error sending WeCom message: {}", e)
            raise

    async def _send_media_files(self, frame: Any, media_paths: list[str], chat_id: str) -> None:
        """Send media files through WeCom."""
        logger.info("Processing {} media file(s)", len(media_paths))
        for media_path in media_paths:
            try:
                if self._is_image_url(media_path):
                    # URL: download then upload via SDK
                    media_id = await self._download_and_upload_media(media_path)
                else:
                    # Local file: read and upload via SDK
                    media_id = await self._upload_local_media(media_path)

                if media_id:
                    # Get correct media type based on extension
                    media_type = self._get_media_type(media_path)
                    await self._client.reply_media(frame, media_type, media_id)
                    logger.info("WeCom {} sent to {}", media_type, chat_id)
                else:
                    logger.warning("Failed to prepare media: {}", media_path)
            except Exception as e:
                logger.error("Error processing media {}: {}", media_path, e)

    async def send_delta(self, chat_id: str, delta: str, finish: bool = False) -> None:
        """
        Send streaming delta text to a chat.

        This is used for streaming results when streaming is enabled.

        Args:
            chat_id: The chat ID to send to
            delta: The text delta to send
            finish: Whether this is the final chunk
        """
        if not self._client:
            logger.warning("WeCom client not initialized")
            return

        frame = self._chat_frames.get(chat_id)
        if not frame:
            logger.warning("No frame found for chat {}, cannot send delta", chat_id)
            return

        # Get or create stream ID for this chat
        stream_id = self._result_stream_ids.get(chat_id)
        if not stream_id:
            stream_id = self._generate_req_id("stream")
            self._result_stream_ids[chat_id] = stream_id
            self._result_stream_bufs[chat_id] = ""

        # Accumulate text
        accumulated_text = self._result_stream_bufs[chat_id] + delta
        self._result_stream_bufs[chat_id] = accumulated_text

        # Send the accumulated text
        await self._client.reply_stream(
            frame,
            stream_id,
            accumulated_text,
            finish=finish,
        )

        # Clean up if finished
        if finish:
            self._result_stream_ids.pop(chat_id, None)
            self._result_stream_bufs.pop(chat_id, None)
            logger.info("WeCom streaming delta ended for {}", chat_id)
