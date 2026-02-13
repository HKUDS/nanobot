"""Server酱³ Bot channel implementation with webhook and polling support."""

import asyncio
from typing import Any

import aiohttp
from starlette.datastructures import Headers
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import ServerchanConfig


class ServerchanChannel(BaseChannel):
    """
    Server酱³ Bot channel with Polling message reception.
    """

    name = "serverchan"

    def __init__(self, config: ServerchanConfig, bus: Any):
        """
        Initialize the Server酱³ Bot channel.

        Args:
            config: Serverchan channel configuration.
            bus: The message bus for communication.
        """
        super().__init__(config, bus)
        self.config: ServerchanConfig = config
        self.token = config.bot_token
        self.base_url = f"https://bot-go.apijia.cn/bot{self.token}"
        self._polling_task: asyncio.Task | None = None
        self._update_offset: int = 0
        self.id: int = 0
        self.first_name: str = ""
        self.user_name: str = ""

    async def start(self) -> None:
        """Start the channel with polling (webhook is handled by GatewayServer)."""
        if not self.token:
            logger.error("Server酱³ Bot token not configured")
            return

        if not await self._get_me():
            return

        logger.info(f"Server酱³ bot id: {self.id}, name: {self.first_name}")
        self._running = True

        # Always start polling (background task)
        logger.info(
            f"Starting Server酱³ Bot polling (interval: {self.config.polling_interval_ms}ms)..."
        )
        self._polling_task = asyncio.create_task(self._poll_loop())

        # Keep running until stopped
        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """Stop the channel and clean up resources."""
        self._running = False

        # Cancel polling task
        if self._polling_task:
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                pass

        logger.info("Server酱³ Bot channel stopped")

    async def _poll_loop(self) -> None:
        """
        Polling loop for receiving updates.

        Uses long polling with offset tracking to avoid duplicates.
        """
        while self._running:
            try:
                result = await self._get_updates(offset=self._update_offset)
                if result["ok"] and result["result"]:
                    for update in result["result"]:
                        self._update_offset = update["update_id"] + 1
                        await self._process_update(update)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Server酱³ polling error: {e}")
                # Wait before retrying on error
                await asyncio.sleep(5)
                continue

            # Normal interval wait
            try:
                await asyncio.sleep(self.config.polling_interval_ms / 1000)
            except asyncio.CancelledError:
                break

    async def _get_me(self) -> bool:
        async with aiohttp.ClientSession() as session:
            url = f"{self.base_url}/getMe"

            try:
                async with session.get(url) as resp:
                    data = await resp.json()
                    if data["ok"] and data["result"]:
                        result = data["result"]
                        if result["is_bot"]:
                            self.id = result["id"]
                            self.first_name = result["first_name"]
                            self.user_name = result["username"]
                            return True
                    return False
            except Exception as e:
                logger.error(f"getMe failed: {e}")
                return False

    async def _get_updates(self, offset: int = 0, timeout: int = 30) -> dict[str, Any]:
        """
        Get updates from Server酱³ Bot API (long polling).

        Args:
            offset: Update offset to start from.
            timeout: Long polling timeout in seconds.

        Returns:
            Dict with 'ok' boolean and 'updates' list.
        """
        async with aiohttp.ClientSession() as session:
            url = f"{self.base_url}/getUpdates"
            payload = {"offset": offset, "timeout": timeout}

            try:
                async with session.post(
                    url, json=payload
                ) as resp:
                    data = await resp.json()
                    return data
            except Exception as e:
                logger.error(f"getUpdates failed: {e}")
                return {"ok": False, "updates": []}

    async def _process_update(self, update: dict[str, Any]) -> None:
        """
        Process an incoming update from webhook or polling.

        Args:
            update: The update payload from Server酱³ Bot.
        """
        message = update.get("message", {})
        if not message:
            return

        chat = message.get("chat")
        form = message.get("from")

        chat_id = chat.get("id")
        sender_id = form.get("id")
        text = message.get("text", "")

        if not chat_id:
            logger.warning(f"Update missing chat_id: {update}")
            return

        logger.debug(f"Server酱³ message from {self.id}: {text[:50]}...")

        # Forward to message bus
        await self._handle_message(
            sender_id=str(sender_id),
            chat_id=str(chat_id),
            content=text,
            metadata={
                "update_id": update.get("update_id"),
                "message_id": message.get("message_id"),
                "username": self.user_name,
                "first_name": self.first_name,
            },
        )

    async def send(self, msg: OutboundMessage) -> None:
        """
        Send a message through Server酱³ Bot.

        Uses the chat_id from the OutboundMessage (from original received message).

        Args:
            msg: The message to send.
        """
        chat_id = msg.chat_id

        if not chat_id:
            logger.warning("Outbound message missing chat_id, cannot send")
            return

        result = await self._send_message(chat_id, msg.content)

        if not result["ok"]:
            error_msg = result.get("description", "unknown error")
            logger.error(f"Failed to send Server酱³ message: {error_msg}, chat_id: {chat_id}, content: {msg.content}")
        else:
            logger.debug(f"Server酱³ message sent to {chat_id}")

    async def _send_message(
        self, chat_id: str, text: str
    ) -> dict[str, Any]:
        """
        Send a message via Server酱³ Bot API.

        Args:
            chat_id: Target chat ID.
            text: Message text.

        Returns:
            Dict with 'ok' boolean and API response.
        """
        async with aiohttp.ClientSession() as session:
            url = f"{self.base_url}/sendMessage"
            payload = {"chat_id": int(chat_id), "text": text}

            try:
                async with session.post(
                    url, json=payload
                ) as resp:
                    data = await resp.json()
                    return data
            except Exception as e:
                logger.error(f"Server酱³ sendMessage failed: {e}")
                return {"ok": False, "description": str(e)}
