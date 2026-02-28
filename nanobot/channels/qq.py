"""QQ channel implementation using botpy SDK."""

import asyncio
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import QQConfig

MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024  # 20MB

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


def _make_bot_class(channel: "QQChannel") -> "type[botpy.Client]":
    """Create a botpy Client subclass bound to the given channel."""
    intents = botpy.Intents(public_messages=True, direct_message=True)

    class _Bot(botpy.Client):
        def __init__(self):
            super().__init__(intents=intents)

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
        self._http: httpx.AsyncClient | None = None
        self._processed_ids: deque = deque(maxlen=1000)

    async def start(self) -> None:
        """Start the QQ bot."""
        if not QQ_AVAILABLE:
            logger.error("QQ SDK not installed. Run: pip install qq-botpy")
            return

        if not self.config.app_id or not self.config.secret:
            logger.error("QQ app_id and secret not configured")
            return

        self._running = True
        self._http = httpx.AsyncClient(timeout=30.0)
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
        if self._http:
            try:
                await self._http.aclose()
            except Exception:
                pass
            self._http = None
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
            await self._client.api.post_c2c_message(
                openid=msg.chat_id,
                msg_type=0,
                content=msg.content,
            )
        except Exception as e:
            logger.error("Error sending QQ message: {}", e)

    def _attachment_info(self, att: Any) -> dict[str, Any]:
        """Get url, filename, size from an attachment (dict or object)."""
        if isinstance(att, dict):
            return {
                "url": att.get("url"),
                "filename": att.get("filename") or "attachment",
                "size": att.get("size") or 0,
                "content_type": att.get("content_type") or "",
            }
        return {
            "url": getattr(att, "url", None),
            "filename": getattr(att, "filename", None) or "attachment",
            "size": getattr(att, "size", None) or 0,
            "content_type": getattr(att, "content_type", None) or "",
        }

    async def _on_message(self, data: "C2CMessage") -> None:
        """Handle incoming message from QQ (text and/or attachments)."""
        try:
            # Dedup by message ID
            if data.id in self._processed_ids:
                return
            self._processed_ids.append(data.id)

            author = data.author
            user_id = str(getattr(author, "id", None) or getattr(author, "user_openid", "unknown"))
            content = (data.content or "").strip()
            attachments = getattr(data, "attachments", None) or []

            if not content and not attachments:
                return

            content_parts = [content] if content else []
            media_paths: list[str] = []
            media_dir = Path.home() / ".nanobot" / "media"

            for idx, att in enumerate(attachments):
                info = self._attachment_info(att)
                url = info["url"]
                filename = info["filename"]
                size = info["size"]
                if not url or not self._http:
                    continue
                if size and size > MAX_ATTACHMENT_BYTES:
                    content_parts.append(f"[attachment: {filename} - too large]")
                    continue
                try:
                    media_dir.mkdir(parents=True, exist_ok=True)
                    safe_name = filename.replace("/", "_").replace("\\", "_") or "attachment"
                    file_path = media_dir / f"qq_{data.id}_{idx}_{safe_name}"
                    resp = await self._http.get(url)
                    resp.raise_for_status()
                    file_path.write_bytes(resp.content)
                    media_paths.append(str(file_path))
                    content_parts.append(f"[attachment: {file_path}]")
                except Exception as e:
                    logger.warning("Failed to download QQ attachment {}: {}", filename, e)
                    content_parts.append(f"[attachment: {filename} - download failed]")

            await self._handle_message(
                sender_id=user_id,
                chat_id=user_id,
                content="\n".join(p for p in content_parts if p) or "[empty message]",
                media=media_paths if media_paths else None,
                metadata={"message_id": data.id},
            )
        except Exception:
            logger.exception("Error handling QQ message")
