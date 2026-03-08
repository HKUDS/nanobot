"""QQ channel implementation using botpy SDK."""

import asyncio
import base64
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

    QQ_AVAILABLE = True
except ImportError:
    QQ_AVAILABLE = False
    # botpy = None
    # C2CMessage = None
    # GroupMessage = None
    # Media = None

if TYPE_CHECKING:
    from botpy.message import C2CMessage, GroupMessage
    from botpy.types.message import Media
    from botpy import Client
    from botpy.http import Route


# QQ C2C 富媒体文件类型
# 1: 图片, 2: 语音, 3: 视频, 4: 文件
# 2, 3经测试无法发送mp3, mp4等常见格式，暂时只能发送图片和文件
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

    # 默认文件类型
    return QQ_FILE_TYPE_FILE


def _make_bot_class(channel: "QQChannel") -> "type[Client]":
    """Create a botpy Client subclass bound to the given channel."""
    intents = botpy.Intents(public_messages=True, direct_message=True)

    class _Bot(Client):
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


class QQChannel(BaseChannel):
    """QQ channel using botpy SDK with WebSocket connection."""

    name = "qq"

    def __init__(self, config: QQConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: QQConfig = config
        self._client: "Client | None" = None
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

        msg_id = msg.metadata.get("message_id")
        self._msg_seq += 1
        msg_type = self._chat_type_cache.get(msg.chat_id, "c2c")

        # 发送富媒体文件
        is_group = msg_type == "group"
        for media_path in msg.media or []:
            await self._send_media(msg.chat_id, media_path, msg_id, is_group=is_group)

        # 发送文本内容
        if msg.content and msg.content != "[empty message]":
            try:
                if msg_type == "group":
                    await self._client.api.post_group_message(
                        group_openid=msg.chat_id,
                        msg_type=0,
                        content=msg.content,
                        msg_id=msg_id,
                        msg_seq=self._msg_seq,
                    )
                else:
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
        self, chat_id: str, file_path: str, msg_id: str | None = None, is_group: bool = False
    ) -> bool:
        """发送富媒体文件到QQ (C2C或群聊).

        流程:
        1. 上传文件获取 Media 对象
        2. 发送富媒体消息 (msg_type=7)
        """
        path = Path(file_path)
        if not path.is_file():
            logger.warning("QQ media file not found: {}", file_path)
            return False

        base64_encoded_data = base64.b64encode(path.read_bytes()).decode("utf-8")
        file_type = _get_file_type(file_path)
        chat_type = "group" if is_group else "c2c"

        try:
            self._msg_seq += 1

            # 1. 上传文件获取 Media 对象
            upload_result = await self._post_base64file(
                chat_id=chat_id,
                is_group=is_group,
                file_type=file_type,
                file_data=base64_encoded_data,
            )

            if not upload_result:
                logger.error("QQ {} media upload failed: no response", chat_type)
                return False

            # 2. 发送富媒体消息
            if is_group:
                await self._client.api.post_group_message(
                    group_openid=chat_id,
                    msg_type=7,
                    msg_id=msg_id,
                    msg_seq=self._msg_seq,
                    media=upload_result,
                )
            else:
                await self._client.api.post_c2c_message(
                    openid=chat_id,
                    msg_type=7,
                    msg_id=msg_id,
                    msg_seq=self._msg_seq,
                    media=upload_result,
                )

            logger.debug("QQ {} media sent: {}", chat_type, path.name)
            return True

        except Exception as e:
            logger.error("Error sending QQ {} media {}: {}", chat_type, path.name, e)
            return False

    async def _on_message(self, data: "C2CMessage | GroupMessage", is_group: bool = False) -> None:
        """Handle incoming message from QQ."""
        try:
            # Dedup by message ID
            if data.id in self._processed_ids:
                return
            self._processed_ids.append(data.id)

            content = (data.content or "").strip()
            if not content:
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
                metadata={"message_id": data.id},
            )
        except Exception:
            logger.exception("Error handling QQ message")

    # https://github.com/tencent-connect/botpy/issues/198
    # https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/send-receive/rich-media.html
    async def _post_base64file(
        self,
        chat_id: str,
        is_group: bool,
        file_type: int,
        file_data: str,
        srv_send_msg: bool = False,
    ) -> "Media":
        """上传/发送 base64 编码的媒体文件.

        Args:
          chat_id: 用户或群的 openid
          is_group: 是否为群聊
          file_type: 媒体类型：1 图片png/jpg，2 视频mp4，3 语音silk，4 文件（暂不开放）
          file_data: base64 编码的媒体数据
          srv_send_msg: 设置 true 会直接发送消息到目标端，且会占用主动消息频次
        """
        if is_group:
            endpoint = "/v2/groups/{group_openid}/files"
            id_key = "group_openid"
        else:
            endpoint = "/v2/users/{openid}/files"
            id_key = "openid"

        payload = {
            id_key: chat_id,
            "file_type": file_type,
            "file_data": file_data,
            "srv_send_msg": srv_send_msg,
        }
        route = Route("POST", endpoint, **{id_key: chat_id})
        return await self._client.api._http.request(route, json=payload)
