"""QQ channel implementation using botpy SDK."""

import asyncio
import mimetypes
import shutil
import subprocess
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlparse

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

try:
    import pilk

    PILK_AVAILABLE = True
except ImportError:
    PILK_AVAILABLE = False
    pilk = None

if TYPE_CHECKING:
    from botpy.message import C2CMessage, GroupMessage


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

        async def on_direct_message_create(self, message):
            await channel._on_message(message, is_group=False)

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
    _IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
    _AUDIO_EXTS = {
        ".aac", ".amr", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".silk", ".slk", ".wav", ".webm",
    }
    _SILK_HEADER = b"\x02#!SILK_V3"
    _TRANSCRIBE_READY_EXTS = {".m4a", ".mp3", ".wav", ".webm"}

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

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through QQ."""
        if not self._client:
            logger.warning("QQ client not initialized")
            return

        try:
            msg_id = msg.metadata.get("message_id")
            self._msg_seq += 1
            use_markdown = self.config.msg_format == "markdown"
            payload: dict[str, Any] = {
                "msg_type": 2 if use_markdown else 0,
                "msg_id": msg_id,
                "msg_seq": self._msg_seq,
            }
            if use_markdown:
                payload["markdown"] = {"content": msg.content}
            else:
                payload["content"] = msg.content

            chat_type = self._chat_type_cache.get(msg.chat_id, "c2c")
            if chat_type == "group":
                await self._client.api.post_group_message(
                    group_openid=msg.chat_id,
                    **payload,
                )
            else:
                await self._client.api.post_c2c_message(
                    openid=msg.chat_id,
                    **payload,
                )
        except Exception as e:
            logger.error("Error sending QQ message: {}", e)

    @staticmethod
    def _attachment_extension(attachment: Any) -> str:
        filename = (getattr(attachment, "filename", None) or "").strip()
        ext = Path(filename).suffix.lower()
        if ext:
            return ext
        content_type = (getattr(attachment, "content_type", None) or "").split(";", 1)[0].strip().lower()
        return (mimetypes.guess_extension(content_type) or "").lower()

    @classmethod
    def _attachment_kind(cls, attachment: Any) -> str:
        content_type = (getattr(attachment, "content_type", None) or "").split(";", 1)[0].strip().lower()
        ext = cls._attachment_extension(attachment)
        if content_type.startswith("audio/") or ext in cls._AUDIO_EXTS:
            return "audio"
        if content_type.startswith("image/") or ext in cls._IMAGE_EXTS:
            return "image"
        return "file"

    @staticmethod
    def _attachment_url(attachment: Any) -> str:
        url = (getattr(attachment, "url", None) or "").strip()
        if not url:
            return ""
        if url.startswith("//"):
            return f"https:{url}"
        parsed = urlparse(url)
        if parsed.scheme:
            return url
        return f"https://{url.lstrip('/')}"

    async def _download_attachment(self, attachment: Any, message_id: str) -> str | None:
        url = self._attachment_url(attachment)
        if not url:
            return None

        filename = Path((getattr(attachment, "filename", None) or "").strip()).name
        ext = self._attachment_extension(attachment)
        suffix = ext or ".bin"
        stem = filename[: -(len(ext))] if filename and ext and filename.lower().endswith(ext) else filename
        stem = stem or getattr(attachment, "id", None) or "attachment"
        save_path = get_media_dir("qq") / f"{message_id}-{stem}{suffix}"

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            save_path.write_bytes(response.content)
        return str(save_path)

    async def _prepare_audio_for_transcription(self, file_path: str) -> str:
        path = Path(file_path)
        if path.suffix.lower() in self._TRANSCRIBE_READY_EXTS:
            return str(path)

        if self._is_silk_audio(path):
            converted = path.with_suffix(".wav")
            if not PILK_AVAILABLE:
                logger.warning("QQ audio is SILK but pilk is not installed: {}", path.name)
                return str(path)
            try:
                await asyncio.to_thread(pilk.silk_to_wav, str(path), str(converted))
                return str(converted)
            except Exception as e:
                logger.warning("QQ SILK decode failed for {}: {}", path.name, e)
                return str(path)

        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return str(path)

        converted = path.with_suffix(".wav")
        try:
            await asyncio.to_thread(
                subprocess.run,
                [ffmpeg, "-y", "-i", str(path), str(converted)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return str(converted)
        except Exception as e:
            logger.warning("QQ audio conversion failed for {}: {}", path.name, e)
            return str(path)

    @classmethod
    def _is_silk_audio(cls, path: Path) -> bool:
        if path.suffix.lower() in {".silk", ".slk"}:
            return True
        try:
            with path.open("rb") as f:
                return f.read(len(cls._SILK_HEADER)) == cls._SILK_HEADER
        except OSError:
            return False

    async def _on_message(self, data: "C2CMessage | GroupMessage", is_group: bool = False) -> None:
        """Handle incoming message from QQ."""
        try:
            # Dedup by message ID
            if data.id in self._processed_ids:
                return
            self._processed_ids.append(data.id)

            content_parts: list[str] = []
            if (data.content or "").strip():
                content_parts.append(data.content.strip())

            media_paths: list[str] = []
            attachments_meta: list[dict[str, Any]] = []
            for attachment in getattr(data, "attachments", []) or []:
                kind = self._attachment_kind(attachment)
                path: str | None = None
                try:
                    path = await self._download_attachment(attachment, data.id)
                except Exception as e:
                    logger.warning("QQ attachment download failed: {}", e)

                filename = getattr(attachment, "filename", None) or getattr(attachment, "id", None) or "attachment"
                if path:
                    media_paths.append(path)
                    attachments_meta.append(
                        {
                            "type": kind,
                            "path": path,
                            "filename": filename,
                            "content_type": getattr(attachment, "content_type", None),
                            "size_bytes": getattr(attachment, "size", None),
                            "url": self._attachment_url(attachment),
                        }
                    )
                    if kind == "audio":
                        transcription = await self.transcribe_audio(
                            await self._prepare_audio_for_transcription(path)
                        )
                        if transcription:
                            content_parts.append(f"[transcription: {transcription}]")
                        else:
                            content_parts.append(f"[audio: {path}]")
                    else:
                        content_parts.append(f"[{kind}: {path}]")
                else:
                    content_parts.append(f"[{kind}: {filename} - download failed]")

            content = "\n".join(part for part in content_parts if part).strip()
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
                media=media_paths,
                metadata={
                    "message_id": data.id,
                    "attachments": attachments_meta,
                },
            )
        except Exception:
            logger.exception("Error handling QQ message")
