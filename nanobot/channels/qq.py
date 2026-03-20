"""QQ channel implementation using botpy SDK."""

import asyncio
import base64
import os
from collections import deque
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
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

    async def _upload_file_base64(
        self, file_path: str, chat_id: str, is_group: bool, file_type: int = 4,
    ) -> "dict | None":
        """Upload a local file to QQ using base64 — no public URL required.

        Args:
            file_path: Local path to the file.
            chat_id: Target user/group openid.
            is_group: Whether the target is a group.
            file_type: QQ file_type (1=image, 2=video, 3=audio, 4=file).

        Returns:
            Media info dict from QQ API, or None on failure.
        """
        try:
            with open(file_path, "rb") as f:
                raw = f.read()
            b64 = base64.b64encode(raw).decode()
            payload = {"file_type": file_type, "file_data": b64, "srv_send_msg": False}
            if is_group:
                resp = await self._client.api.post_group_file(
                    group_openid=chat_id, **payload,
                )
            else:
                resp = await self._client.api.post_c2c_file(
                    openid=chat_id, **payload,
                )
            if resp and hasattr(resp, "file_info"):
                return {"file_info": resp.file_info}
            if isinstance(resp, dict):
                return resp
            return None
        except Exception as e:
            logger.error("QQ base64 upload failed for {}: {}", file_path, e)
            return None

    async def _upload_local_file(
        self, file_path: str, chat_id: str, is_group: bool,
    ) -> "dict | None":
        """Detect file type and upload a local file via base64."""
        ext = os.path.splitext(file_path)[1].lower()
        if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"):
            file_type = 1
        elif ext in (".mp4", ".avi", ".mov", ".mkv"):
            file_type = 2
        elif ext in (".mp3", ".m4a", ".wav", ".ogg", ".silk"):
            file_type = 3
        else:
            file_type = 4
        return await self._upload_file_base64(file_path, chat_id, is_group, file_type)

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through QQ."""
        if not self._client:
            logger.warning("QQ client not initialized")
            return

        try:
            msg_id = msg.metadata.get("message_id")
            chat_type = self._chat_type_cache.get(msg.chat_id, "c2c")
            is_group = chat_type == "group"
            content = msg.content or ""

            # Send media files via base64 upload
            for file_path in msg.media or []:
                if not os.path.isfile(file_path):
                    logger.warning("QQ media file not found: {}", file_path)
                    continue
                media_obj = await self._upload_local_file(file_path, msg.chat_id, is_group)
                if media_obj is not None:
                    self._msg_seq += 1
                    media_payload: dict[str, Any] = {
                        "msg_type": 7, "msg_id": msg_id,
                        "msg_seq": self._msg_seq, "media": media_obj,
                    }
                    if is_group:
                        await self._client.api.post_group_message(
                            group_openid=msg.chat_id, **media_payload)
                    else:
                        await self._client.api.post_c2c_message(
                            openid=msg.chat_id, **media_payload)
                else:
                    content += f"\n[file upload failed: {os.path.basename(file_path)}]"

            # Send text content
            if not content.strip():
                return

            self._msg_seq += 1
            use_markdown = self.config.msg_format == "markdown"
            payload: dict[str, Any] = {
                "msg_type": 2 if use_markdown else 0,
                "msg_id": msg_id,
                "msg_seq": self._msg_seq,
            }
            if use_markdown:
                payload["markdown"] = {"content": content}
            else:
                payload["content"] = content

            if is_group:
                await self._client.api.post_group_message(
                    group_openid=msg.chat_id, **payload)
            else:
                await self._client.api.post_c2c_message(
                    openid=msg.chat_id, **payload)
        except Exception as e:
            logger.error("Error sending QQ message: {}", e)

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
