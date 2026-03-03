"""Discord channel implementation using Discord Gateway websocket.

Supports streaming output via message editing.
"""

import asyncio
import json
import time
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
MAX_MESSAGE_LEN = 2000  # Discord message character limit
STREAM_UPDATE_INTERVAL = 0.3  # 300ms between stream updates to avoid rate limits


def _split_message(content: str, max_len: int = MAX_MESSAGE_LEN) -> list[str]:
    """Split content into chunks within max_len, preferring line breaks."""
    if not content:
        return []
    if len(content) <= max_len:
        return [content]
    chunks: list[str] = []
    while content:
        if len(content) <= max_len:
            chunks.append(content)
            break
        cut = content[:max_len]
        pos = cut.rfind('\n')
        if pos <= 0:
            pos = cut.rfind(' ')
        if pos <= 0:
            pos = max_len
        chunks.append(content[:pos])
        content = content[pos:].lstrip()
    return chunks


class DiscordChannel(BaseChannel):
    """Discord channel using Gateway websocket.

    Supports streaming output via message editing:
    - First chunk: send new message, store message_id
    - Subsequent chunks: edit the message
    - Final message: edit with complete content
    """

    name = "discord"

    def __init__(self, config: DiscordConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: DiscordConfig = config
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._seq: int | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._typing_tasks: dict[str, asyncio.Task] = {}
        self._http: httpx.AsyncClient | None = None
        # Streaming state
        self._streaming_message_ids: dict[str, str] = {}  # channel_id -> message_id
        self._streaming_contents: dict[str, str] = {}  # channel_id -> accumulated content
        self._last_stream_time: dict[str, float] = {}  # channel_id -> last update timestamp
        self._stream_locks: dict[str, asyncio.Lock] = {}  # channel_id -> lock for stream operations

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
                logger.warning("Discord gateway error: {}", e)
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
        """Send a message through Discord REST API.

        Supports streaming via _progress metadata:
        - _progress=True: streaming chunk, will edit existing message or create new one
        - _progress=False/absent: final message, will edit or send normally
        """
        if not self._http:
            logger.warning("Discord HTTP client not initialized")
            return

        is_progress = msg.metadata.get("_progress", False)

        # Handle streaming messages
        if is_progress:
            await self._send_streaming(msg)
            return

        # Final message - check if we need to finalize a streaming message
        channel_id = msg.chat_id
        streaming_msg_id = self._streaming_message_ids.get(channel_id)

        if streaming_msg_id:
            # We had a streaming message, finalize it
            await self._finalize_streaming(msg)
            return

        # Normal message send (no streaming involved)
        await self._stop_typing(channel_id)
        await self._send_normal(msg)

    async def _send_streaming(self, msg: OutboundMessage) -> None:
        """Send or update a streaming message.

        Uses message editing to create a "typing" effect.
        Rate limited to avoid Discord API limits.
        Falls back to typing indicator if stream_messages is disabled.
        """
        channel_id = msg.chat_id

        # Check if streaming is enabled
        if not self.config.stream_messages:
            # Fall back to typing indicator only
            await self._start_typing(channel_id)
            return

        # Get or create lock for this channel
        if channel_id not in self._stream_locks:
            self._stream_locks[channel_id] = asyncio.Lock()

        async with self._stream_locks[channel_id]:
            # Skip empty content
            if not msg.content or not msg.content.strip():
                return

            # Accumulate content (msg.content is already accumulated from LLM streaming)
            accumulated = msg.content
            self._streaming_contents[channel_id] = accumulated

            # Rate limiting check
            now = time.time()
            last_time = self._last_stream_time.get(channel_id, 0)
            if now - last_time < STREAM_UPDATE_INTERVAL:
                # Too soon, skip this update (content is already accumulated)
                return

            streaming_msg_id = self._streaming_message_ids.get(channel_id)

            if streaming_msg_id:
                # Edit existing message
                await self._edit_message(channel_id, streaming_msg_id, accumulated)
            else:
                # Send new message
                message_id = await self._send_new_message(channel_id, accumulated)
                if message_id:
                    self._streaming_message_ids[channel_id] = message_id

            self._last_stream_time[channel_id] = now

    async def _finalize_streaming(self, msg: OutboundMessage) -> None:
        """Finalize streaming by editing the message with final content."""
        channel_id = msg.chat_id
        streaming_msg_id = self._streaming_message_ids.get(channel_id)

        if not streaming_msg_id:
            # No streaming message to finalize, send normally
            await self._send_normal(msg)
            return

        # Stop typing indicator
        await self._stop_typing(channel_id)

        # Edit the streaming message with final content
        if msg.content and msg.content.strip():
            await self._edit_message(channel_id, streaming_msg_id, msg.content)

        # Clear streaming state
        self._streaming_message_ids.pop(channel_id, None)
        self._streaming_contents.pop(channel_id, None)
        self._last_stream_time.pop(channel_id, None)

        logger.debug("[DISCORD] Finalized streaming message for channel {}", channel_id)

    async def _send_new_message(self, channel_id: str, content: str) -> str | None:
        """Send a new message and return its ID."""
        if not self._http:
            return None

        url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages"
        headers = {"Authorization": f"Bot {self.config.token}"}

        # Truncate to Discord limit
        truncated = content[:MAX_MESSAGE_LEN] if len(content) > MAX_MESSAGE_LEN else content

        payload = {"content": truncated}

        try:
            response = await self._http.post(url, headers=headers, json=payload)
            if response.status_code == 429:
                data = response.json()
                retry_after = float(data.get("retry_after", 1.0))
                logger.warning("Discord rate limited, retrying in {}s", retry_after)
                await asyncio.sleep(retry_after)
                # Retry once
                response = await self._http.post(url, headers=headers, json=payload)

            response.raise_for_status()
            data = response.json()
            message_id = data.get("id")
            logger.debug("[DISCORD] Sent new streaming message: {}", message_id)
            return message_id
        except Exception as e:
            logger.error("[DISCORD] Failed to send streaming message: {}", e)
            return None

    async def _edit_message(self, channel_id: str, message_id: str, content: str) -> bool:
        """Edit an existing message. Returns True on success."""
        if not self._http:
            return False

        url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}"
        headers = {"Authorization": f"Bot {self.config.token}"}

        # Truncate to Discord limit
        truncated = content[:MAX_MESSAGE_LEN] if len(content) > MAX_MESSAGE_LEN else content

        payload = {"content": truncated}

        try:
            response = await self._http.patch(url, headers=headers, json=payload)
            if response.status_code == 429:
                data = response.json()
                retry_after = float(data.get("retry_after", 1.0))
                logger.warning("Discord rate limited on edit, retrying in {}s", retry_after)
                await asyncio.sleep(retry_after)
                response = await self._http.patch(url, headers=headers, json=payload)

            response.raise_for_status()
            logger.debug("[DISCORD] Edited streaming message: {}", message_id)
            return True
        except Exception as e:
            logger.warning("[DISCORD] Failed to edit streaming message: {}", e)
            return False

    async def _send_normal(self, msg: OutboundMessage) -> None:
        """Send a normal (non-streaming) message."""
        url = f"{DISCORD_API_BASE}/channels/{msg.chat_id}/messages"
        headers = {"Authorization": f"Bot {self.config.token}"}

        try:
            chunks = _split_message(msg.content or "")
            if not chunks:
                return

            for i, chunk in enumerate(chunks):
                payload: dict[str, Any] = {"content": chunk}

                # Only set reply reference on the first chunk
                if i == 0 and msg.reply_to:
                    payload["message_reference"] = {"message_id": msg.reply_to}
                    payload["allowed_mentions"] = {"replied_user": False}

                if not await self._send_payload(url, headers, payload):
                    break  # Abort remaining chunks on failure
        finally:
            await self._stop_typing(msg.chat_id)

    async def _send_payload(
        self, url: str, headers: dict[str, str], payload: dict[str, Any]
    ) -> bool:
        """Send a single Discord API payload with retry on rate-limit. Returns True on success."""
        for attempt in range(3):
            try:
                response = await self._http.post(url, headers=headers, json=payload)
                if response.status_code == 429:
                    data = response.json()
                    retry_after = float(data.get("retry_after", 1.0))
                    logger.warning("Discord rate limited, retrying in {}s", retry_after)
                    await asyncio.sleep(retry_after)
                    continue
                response.raise_for_status()
                return True
            except Exception as e:
                if attempt == 2:
                    logger.error("Error sending Discord message: {}", e)
                else:
                    await asyncio.sleep(1)
        return False

    async def _gateway_loop(self) -> None:
        """Main gateway loop: identify, heartbeat, dispatch events."""
        if not self._ws:
            return

        async for raw in self._ws:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Invalid JSON from Discord gateway: {}", raw[:100])
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
                    logger.warning("Discord heartbeat failed: {}", e)
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

        # Clear streaming state for this channel when receiving new message
        # This prevents editing old messages from previous conversations
        self._streaming_message_ids.pop(channel_id, None)
        self._streaming_contents.pop(channel_id, None)
        self._last_stream_time.pop(channel_id, None)

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
                logger.warning("Failed to download Discord attachment: {}", e)
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
                except asyncio.CancelledError:
                    return
                except Exception as e:
                    logger.debug("Discord typing indicator failed for {}: {}", channel_id, e)
                    return
                await asyncio.sleep(8)

        self._typing_tasks[channel_id] = asyncio.create_task(typing_loop())

    async def _stop_typing(self, channel_id: str) -> None:
        """Stop typing indicator for a channel."""
        task = self._typing_tasks.pop(channel_id, None)
        if task:
            task.cancel()
