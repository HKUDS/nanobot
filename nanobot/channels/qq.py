"""QQ channel implementation using botpy SDK."""

import asyncio
from collections import deque
from typing import TYPE_CHECKING

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import QQConfig

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
            super().__init__(intents=intents)

        async def on_ready(self):
            logger.info(f"QQ bot ready: {self.robot.name}")

        async def on_c2c_message_create(self, message: "C2CMessage"):
            await channel._on_message(message)

        async def on_group_at_message_create(self, message: "GroupMessage"):
            await channel._on_group_message(message)

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
        self._bot_task: asyncio.Task | None = None

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

        self._bot_task = asyncio.create_task(self._run_bot())
        logger.info("QQ bot started (C2C + group chat)")

    async def _run_bot(self) -> None:
        """Run the bot connection with auto-reconnect."""
        while self._running:
            try:
                await self._client.start(appid=self.config.app_id, secret=self.config.secret)
            except Exception as e:
                logger.warning(f"QQ bot error: {e}")
            if self._running:
                logger.info("Reconnecting QQ bot in 5 seconds...")
                await asyncio.sleep(5)

    async def stop(self) -> None:
        """Stop the QQ bot."""
        self._running = False
        if self._bot_task:
            self._bot_task.cancel()
            try:
                await self._bot_task
            except asyncio.CancelledError:
                pass
        logger.info("QQ bot stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through QQ."""
        if not self._client:
            logger.warning("QQ client not initialized")
            return
        try:
            metadata = msg.metadata or {}
            if metadata.get("msg_type") == "group":
                await self._client.api.post_group_message(
                    group_openid=metadata["group_openid"],
                    msg_type=0,
                    content=msg.content,
                    msg_id=metadata.get("message_id"),
                )
            else:
                await self._client.api.post_c2c_message(
                    openid=msg.chat_id,
                    msg_type=0,
                    content=msg.content,
                )
        except Exception as e:
            logger.error(f"Error sending QQ message: {e}")

    async def _on_message(self, data: "C2CMessage") -> None:
        """Handle incoming C2C/direct message from QQ."""
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
        except Exception as e:
            logger.error(f"Error handling QQ message: {e}")

    async def _on_group_message(self, data: "GroupMessage") -> None:
        """Handle incoming group @bot message from QQ."""
        try:
            # Dedup by message ID
            if data.id in self._processed_ids:
                return
            self._processed_ids.append(data.id)

            group_openid = data.group_openid
            member_openid = data.author.member_openid

            # Strip the leading @bot mention that botpy delivers as-is
            content = (data.content or "").strip()
            # The @mention typically appears as a leading slash or whitespace-prefixed segment
            # botpy delivers it with a leading space after the mention; strip it
            if content.startswith("/"):
                content = content[1:].strip()
            content = content.strip()
            if not content:
                return

            logger.debug(f"QQ group message from {member_openid} in group {group_openid}")

            await self._handle_message(
                sender_id=member_openid,
                chat_id=group_openid,
                content=content,
                metadata={
                    "msg_type": "group",
                    "group_openid": group_openid,
                    "message_id": data.id,
                },
            )
        except Exception as e:
            logger.error(f"Error handling QQ group message: {e}")
