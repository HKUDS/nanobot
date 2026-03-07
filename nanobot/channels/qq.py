"""QQ channel implementation using botpy SDK."""

import asyncio
import mimetypes
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import QQConfig

try:
    import botpy
    from botpy.message import C2CMessage

    QQ_AVAILABLE = True
except ImportError:
    QQ_AVAILABLE = False
    botpy = None
    C2CMessage = None

if TYPE_CHECKING:
    from botpy.message import C2CMessage

# QQ C2C 富媒体文件类型
# 1: 图片, 2: 语音, 3: 视频, 4: 文件
QQ_FILE_TYPE_IMAGE = 1
QQ_FILE_TYPE_VOICE = 2
QQ_FILE_TYPE_VIDEO = 3
QQ_FILE_TYPE_FILE = 4


def _get_file_type(file_path: str) -> int:
    """根据文件路径判断QQ文件类型."""
    ext = Path(file_path).suffix.lower()
    mime, _ = mimetypes.guess_type(file_path)

    # 图片类型
    if ext in (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp") or (
        mime and mime.startswith("image/")
    ):
        return QQ_FILE_TYPE_IMAGE

    # 语音类型
    if ext in (".mp3", ".wav", ".ogg", ".m4a", ".aac") or (
        mime and mime.startswith("audio/")
    ):
        return QQ_FILE_TYPE_VOICE

    # 视频类型
    if ext in (".mp4", ".avi", ".mov", ".mkv", ".flv") or (
        mime and mime.startswith("video/")
    ):
        return QQ_FILE_TYPE_VIDEO

    # 默认文件类型
    return QQ_FILE_TYPE_FILE


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
            await channel._on_message(message)

        async def on_direct_message_create(self, message):
            await channel._on_message(message)

    return _Bot


class QQChannel(BaseChannel):
    """QQ channel using botpy SDK with WebSocket connection."""

    name = "qq"

    def __init__(self, config: QQConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: QQConfig = config
        self._client: "botpy.Client | None" = None
        self._processed_ids: deque = deque(maxlen=1000)
        self._msg_seq: int = 1  # 消息序列号，避免被 QQ API 去重

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

        logger.info("QQ bot started (C2C private message)")
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

        msg_id = msg.metadata.get("message_id")
        self._msg_seq += 1  # 递增序列号避免去重

        # 发送富媒体文件
        for media_path in (msg.media or []):
            await self._send_media(msg.chat_id, media_path, msg_id)

        # 发送文本内容
        if msg.content and msg.content != "[empty message]":
            try:
                await self._client.api.post_c2c_message(
                    openid=msg.chat_id,
                    msg_type=0,
                    content=msg.content,
                    msg_id=msg_id,
                    msg_seq=self._msg_seq,
                )
            except Exception as e:
                logger.error("Error sending QQ message: {}", e)

    async def _send_media(
        self, chat_id: str, file_path: str, msg_id: str | None = None
    ) -> bool:
        """发送富媒体文件到QQ C2C.

        流程:
        1. 调用 post_c2c_file 上传文件获取 Media 对象
        2. 调用 post_c2c_message 发送富媒体消息 (msg_type=7)
        """
        path = Path(file_path)
        if not path.is_file():
            logger.warning("QQ media file not found: {}", file_path)
            return False

        file_type = _get_file_type(file_path)
        file_url = f"file://{path.absolute()}"

        try:
            self._msg_seq += 1

            # 1. 上传文件获取 Media 对象
            upload_result = await self._client.api.post_c2c_file(
                openid=chat_id,
                file_type=file_type,
                url=file_url,
            )

            if not upload_result:
                logger.error("QQ media upload failed: no response")
                return False

            # 2. 发送富媒体消息
            await self._client.api.post_c2c_message(
                openid=chat_id,
                msg_type=7,  # 7 表示富媒体类型
                msg_id=msg_id,
                msg_seq=self._msg_seq,
                media=upload_result,
            )

            logger.debug("QQ media sent: {}", path.name)
            return True

        except Exception as e:
            logger.error("Error sending QQ media {}: {}", path.name, e)
            return False

    async def _on_message(self, data: "C2CMessage") -> None:
        """Handle incoming message from QQ."""
        try:
            # Dedup by message ID
            if data.id in self._processed_ids:
                return
            self._processed_ids.append(data.id)

            author = data.author
            user_id = str(getattr(author, 'id', None) or getattr(author, 'user_openid', 'unknown'))
            content = (data.content or "").strip()
            if not content:
                return

            await self._handle_message(
                sender_id=user_id,
                chat_id=user_id,
                content=content,
                metadata={"message_id": data.id},
            )
        except Exception:
            logger.exception("Error handling QQ message")

