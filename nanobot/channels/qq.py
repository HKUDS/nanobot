"""QQ channel implementation using botpy SDK."""

import asyncio
from collections import deque
from typing import TYPE_CHECKING

from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage
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


def parse_chat_id(chat_id: str) -> tuple[str, str]:
    """Parse chat_id into (channel, user_id).

    Args:
        chat_id: Format "channel:user_id", e.g. "qq:openid_xxx"

    Returns:
        Tuple of (channel, user_id)
    """
    if ":" not in chat_id:
        raise ValueError(f"Invalid chat_id format: {chat_id}")
    channel, user_id = chat_id.split(":", 1)
    return channel, user_id


class QQChannel(BaseChannel):
    """
    QQ channel using botpy SDK with WebSocket connection.

    Uses botpy SDK to connect to QQ Open Platform (q.qq.com).

    Requires:
    - App ID and Secret from q.qq.com
    - Robot capability enabled
    """

    name = "qq"

    def __init__(self, config: QQConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: QQConfig = config
        self._client: "botpy.Client | None" = None
        self._processed_message_ids: deque = deque(maxlen=1000)
        self._bot_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the QQ bot."""
        if not QQ_AVAILABLE:
            logger.error("QQ SDK 未安装。请运行：pip install qq-botpy")
            return

        if not self.config.app_id or not self.config.secret:
            logger.error("QQ app_id 和 secret 未配置")
            return

        self._running = True

        # Create bot client with C2C intents
        intents = botpy.Intents.all()
        logger.info(f"QQ Intents 配置值: {intents.value}")

        # Create custom bot class with message handlers
        class QQBot(botpy.Client):
            def __init__(self, channel):
                super().__init__(intents=intents)
                self.channel = channel

            async def on_ready(self):
                """Called when bot is ready."""
                logger.info(f"QQ bot ready: {self.robot.name}")

            async def on_c2c_message_create(self, message: "C2CMessage"):
                """Handle C2C (Client to Client) messages - private chat."""
                await self.channel._on_message(message, "c2c")

            async def on_direct_message_create(self, message):
                """Handle direct messages - alternative event name."""
                await self.channel._on_message(message, "direct")

            # TODO: Group message support - implement in future PRD
            # async def on_group_at_message_create(self, message):
            #     """Handle group @ messages."""
            #     pass

        self._client = QQBot(self)

        # Start bot - use create_task to run concurrently
        self._bot_task = asyncio.create_task(
            self._run_bot_with_retry(self.config.app_id, self.config.secret)
        )

        logger.info("QQ bot started with C2C (private message) support")

    async def _run_bot_with_retry(self, app_id: str, secret: str) -> None:
        """Run bot with error handling."""
        try:
            await self._client.start(appid=app_id, secret=secret)
        except Exception as e:
            logger.error(
                f"QQ 鉴权失败，请检查 AppID 和 Secret 是否正确。"
                f"访问 q.qq.com 获取凭证。错误: {e}"
            )
            self._running = False

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
            # Parse chat_id format: qq:{user_id}
            channel, user_id = parse_chat_id(msg.chat_id)

            if channel != "qq":
                logger.warning(f"Invalid channel in chat_id: {msg.chat_id}")
                return

            # Send private message using botpy API
            await self._client.api.post_c2c_message(
                openid=user_id,
                msg_type=0,
                content=msg.content,
            )
            logger.debug(f"QQ message sent to {msg.chat_id}")

        except ValueError as e:
            logger.error(f"Invalid chat_id format: {e}")
        except Exception as e:
            logger.error(f"Error sending QQ message: {e}")

    async def _on_message(self, data: "C2CMessage", msg_type: str) -> None:
        """Handle incoming message from QQ."""
        try:
            # Message deduplication using deque with maxlen
            message_id = data.id
            if message_id in self._processed_message_ids:
                logger.debug(f"Duplicate message {message_id}, skipping")
                return

            self._processed_message_ids.append(message_id)

            # Extract user ID and chat ID from message
            author = data.author
            # Try different possible field names for user ID
            user_id = str(getattr(author, 'id', None) or getattr(author, 'user_openid', 'unknown'))
            user_name = getattr(author, 'username', None) or 'unknown'

            # For C2C messages, chat_id is the user's ID
            chat_id = f"qq:{user_id}"

            # Check allow_from list (if configured)
            if self.config.allow_from and user_id not in self.config.allow_from:
                logger.info(f"User {user_id} not in allow_from list")
                return

            # Get message content
            content = data.content or ""

            if not content:
                logger.debug(f"Empty message from {user_id}, skipping")
                return

            # Publish to message bus
            msg = InboundMessage(
                channel=self.name,
                sender_id=user_id,
                chat_id=chat_id,
                content=content,
                metadata={
                    "message_id": message_id,
                    "user_name": user_name,
                    "msg_type": msg_type,
                },
            )
            await self.bus.publish_inbound(msg)

            logger.info(f"Received QQ message from {user_id} ({msg_type}): {content[:50]}")

        except Exception as e:
            logger.error(f"Error handling QQ message: {e}")
