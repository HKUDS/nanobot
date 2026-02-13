"""Discord channel implementation using Discord Gateway websocket."""

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import websockets
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import DiscordConfig


DISCORD_API_BASE = "https://discord.com/api/v10"
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024  # 20MB
MAX_MESSAGE_LENGTH = 2000  # Discord message limit


class DiscordChannel(BaseChannel):
    """Discord channel using Gateway websocket."""

    name = "discord"

    def __init__(self, config: DiscordConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: DiscordConfig = config
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._seq: int | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._typing_tasks: dict[str, asyncio.Task] = {}
        self._http: httpx.AsyncClient | None = None

    async def start(self) -> None:
        """Start the Discord gateway connection."""
        if not self.config.token:
            logger.error("Discord bot token not configured")
            return

        self._running = True
        self._http = httpx.AsyncClient(timeout=30.0)

        while self._running:
            try:
                logger.info("Connecting to Discord gateway...")
                async with websockets.connect(self.config.gateway_url) as ws:
                    self._ws = ws
                    await self._gateway_loop()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Discord gateway error: {e}")
                if self._running:
                    logger.info("Reconnecting to Discord gateway in 5 seconds...")
                    await asyncio.sleep(5)

    async def stop(self) -> None:
        """Stop the Discord channel."""
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
        for task in self._typing_tasks.values():
            task.cancel()
        self._typing_tasks.clear()
        if self._ws:
            await self._ws.close()
            self._ws = None
        if self._http:
            await self._http.aclose()
            self._http = None

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through Discord REST API, splitting if too long."""
        if not self._http:
            logger.warning("Discord HTTP client not initialized")
            return
        # Split message if too long
        message_parts = self._split_message(msg.content)

        headers = {"Authorization": f"Bot {self.config.token}"}

        for i, part in enumerate(message_parts):
            url = f"{DISCORD_API_BASE}/channels/{msg.chat_id}/messages"
            payload: dict[str, Any] = {"content": part}

            # Only add reply_to to the first message
            if i == 0 and msg.reply_to:
                payload["message_reference"] = {"message_id": msg.reply_to}
                payload["allowed_mentions"] = {"replied_user": False}

            try:
                for attempt in range(3):
                    try:
                        #logger.info(f"Discord header {headers} : payload {payload}")
                        response = await self._http.post(url, headers=headers, json=payload)
                        if response.status_code == 429:
                            data = response.json()
                            retry_after = float(data.get("retry_after", 1.0))
                            logger.warning(f"Discord rate limited, retrying in {retry_after}s")
                            await asyncio.sleep(retry_after)
                            continue
                        response.raise_for_status()
                        break
                    except Exception as e:
                        if attempt == 2:
                            logger.error(f"Error sending Discord message part {i+1}/{len(message_parts)}: {e}")
                        else:
                            await asyncio.sleep(1)
                # Small delay between messages to avoid rate limits
                if i < len(message_parts) - 1:
                    await asyncio.sleep(0.5)
            finally:
                if i == len(message_parts) - 1:  # Last message
                    await self._stop_typing(msg.chat_id)

    def _split_message(self, content: str) -> list[str]:
        """Split a message into chunks that fit within Discord's limits.
        
        Tries to split at newlines or other natural boundaries first.
        """
        if len(content) <= MAX_MESSAGE_LENGTH:
            return [content]

        chunks = []
        remaining = content

        while remaining:
            if len(remaining) <= MAX_MESSAGE_LENGTH:
                chunks.append(remaining)
                break

            # Try to find a good split point
            split_index = MAX_MESSAGE_LENGTH

            # First try to split at a double newline
            double_newline = remaining.rfind('\n\n', 0, MAX_MESSAGE_LENGTH)
            if double_newline > MAX_MESSAGE_LENGTH * 0.5:  # Only use if we get a decent chunk
                split_index = double_newline + 2  # Include both newlines
            # Then try a single newline
            elif double_newline == -1:
                newline = remaining.rfind('\n', 0, MAX_MESSAGE_LENGTH)
                if newline > MAX_MESSAGE_LENGTH * 0.5:
                    split_index = newline + 1
            # Then try a period followed by space
            elif double_newline == -1 and newline == -1:
                period = remaining.rfind('. ', 0, MAX_MESSAGE_LENGTH)
                if period > MAX_MESSAGE_LENGTH * 0.5:
                    split_index = period + 2
            # Then try any whitespace
            elif double_newline == -1 and newline == -1 and period == -1:
                whitespace = remaining.rfind(' ', 0, MAX_MESSAGE_LENGTH)
                if whitespace > MAX_MESSAGE_LENGTH * 0.5:
                    split_index = whitespace + 1
            # Last resort: hard split
            elif split_index == MAX_MESSAGE_LENGTH:
                split_index = MAX_MESSAGE_LENGTH - 3  # Leave room for "..."
                remaining = remaining[:split_index] + "..."

            chunk = remaining[:split_index]
            chunks.append(chunk)
            remaining = remaining[split_index:].lstrip()

            # Add continuation indicator if needed
            if remaining:
                chunks[-1] += " (continued...)"

        return chunks

    async def _gateway_loop(self) -> None:
        """Main gateway loop: identify, heartbeat, dispatch events."""
        if not self._ws:
            return

        async for raw in self._ws:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON from Discord gateway: {raw[:100]}")
                continue

            op = data.get("op")
            event_type = data.get("t")
            seq = data.get("s")
            payload = data.get("d")

            if seq is not None:
                self._seq = seq

            if op == 10:
                # HELLO: start heartbeat and identify
                interval_ms = payload.get("heartbeat_interval", 45000)
                await self._start_heartbeat(interval_ms / 1000)
                await self._identify()
            elif op == 0 and event_type == "READY":
                logger.info("Discord gateway READY")
            elif op == 0 and event_type == "MESSAGE_CREATE":
                await self._handle_message_create(payload)
            elif op == 7:
                # RECONNECT: exit loop to reconnect
                logger.info("Discord gateway requested reconnect")
                break
            elif op == 9:
                # INVALID_SESSION: reconnect
                logger.warning("Discord gateway invalid session")
                break

    async def _identify(self) -> None:
        """Send IDENTIFY payload."""
        if not self._ws:
            return

        identify = {
            "op": 2,
            "d": {
                "token": self.config.token,
                "intents": self.config.intents,
                "properties": {
                    "os": "nanobot",
                    "browser": "nanobot",
                    "device": "nanobot",
                },
            },
        }
        await self._ws.send(json.dumps(identify))

    async def _start_heartbeat(self, interval_s: float) -> None:
        """Start or restart the heartbeat loop."""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()

        async def heartbeat_loop() -> None:
            while self._running and self._ws:
                payload = {"op": 1, "d": self._seq}
                try:
                    await self._ws.send(json.dumps(payload))
                except Exception as e:
                    logger.warning(f"Discord heartbeat failed: {e}")
                    break
                await asyncio.sleep(interval_s)

        self._heartbeat_task = asyncio.create_task(heartbeat_loop())

    async def _handle_message_create(self, payload: dict[str, Any]) -> None:
        """Handle incoming Discord messages."""
        author = payload.get("author") or {}
        if author.get("bot"):
            return

        sender_id = str(author.get("id", ""))
        channel_id = str(payload.get("channel_id", ""))
        content = payload.get("content") or ""

        if not sender_id or not channel_id:
            return

        if not self.is_allowed(sender_id):
            return

        content_parts = [content] if content else []
        media_paths: list[str] = []
        media_dir = Path.home() / ".nanobot" / "media"

        for attachment in payload.get("attachments") or []:
            url = attachment.get("url")
            filename = attachment.get("filename") or "attachment"
            size = attachment.get("size") or 0
            if not url or not self._http:
                continue
            if size and size > MAX_ATTACHMENT_BYTES:
                content_parts.append(f"[attachment: {filename} - too large]")
                continue
            try:
                media_dir.mkdir(parents=True, exist_ok=True)
                file_path = media_dir / f"{attachment.get('id', 'file')}_{filename.replace('/', '_')}"
                resp = await self._http.get(url)
                resp.raise_for_status()
                file_path.write_bytes(resp.content)
                media_paths.append(str(file_path))
                content_parts.append(f"[attachment: {file_path}]")
            except Exception as e:
                logger.warning(f"Failed to download Discord attachment: {e}")
                content_parts.append(f"[attachment: {filename} - download failed]")

        reply_to = (payload.get("referenced_message") or {}).get("id")

        await self._start_typing(channel_id)

        await self._handle_message(
            sender_id=sender_id,
            chat_id=channel_id,
            content="\n".join(p for p in content_parts if p) or "[empty message]",
            media=media_paths,
            metadata={
                "message_id": str(payload.get("id", "")),
                "guild_id": payload.get("guild_id"),
                "reply_to": reply_to,
            },
        )

    async def _start_typing(self, channel_id: str) -> None:
        """Start periodic typing indicator for a channel."""
        await self._stop_typing(channel_id)

        async def typing_loop() -> None:
            url = f"{DISCORD_API_BASE}/channels/{channel_id}/typing"
            headers = {"Authorization": f"Bot {self.config.token}"}
            while self._running:
                try:
                    await self._http.post(url, headers=headers)
                except Exception:
                    pass
                await asyncio.sleep(8)

        self._typing_tasks[channel_id] = asyncio.create_task(typing_loop())

    async def _stop_typing(self, channel_id: str) -> None:
        """Stop typing indicator for a channel."""
        task = self._typing_tasks.pop(channel_id, None)
        if task:
            task.cancel()
