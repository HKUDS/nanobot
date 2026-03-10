"""Discord channel implementation using Discord Gateway websocket.

Uses industry-standard packages for reliability patterns:
- tenacity: Retry logic with exponential backoff
- pybreaker: Circuit breaker pattern
"""

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import httpx
import pybreaker
import tenacity
import websockets
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.paths import get_media_dir
from nanobot.config.schema import DiscordConfig
from nanobot.utils.helpers import split_message

DISCORD_API_BASE = "https://discord.com/api/v10"
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024  # 20MB
MAX_MESSAGE_LEN = 2000  # Discord message character limit
MAX_RECONNECT_ATTEMPTS = 5
RECONNECT_BACKOFF_BASE = 5  # seconds
RECONNECT_BACKOFF_MAX = 60  # seconds


# Global circuit breaker for message sending
_message_breaker = pybreaker.CircuitBreaker(
    fail_max=5,
    reset_timeout=60,
    success_threshold=2,
    name='discord_message'
)

# Global circuit breaker for gateway connection
_gateway_breaker = pybreaker.CircuitBreaker(
    fail_max=3,
    reset_timeout=30,
    success_threshold=1,
    name='discord_gateway'
)


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
        self._bot_user_id: str | None = None
        # Error recovery state
        self._reconnect_attempts = 0

    async def start(self) -> None:
        """Start the Discord gateway connection with exponential backoff."""
        if not self.config.token:
            logger.error("Discord bot token not configured")
            return

        self._running = True
        self._http = httpx.AsyncClient(timeout=30.0)

        while self._running:
            try:
                logger.info("Connecting to Discord gateway...")
                async with websockets.connect(
                    self.config.gateway_url,
                    close_timeout=10,
                    ping_timeout=30,
                    ping_interval=45,
                ) as ws:
                    self._ws = ws
                    self._reconnect_attempts = 0
                    self._gateway_circuit.reset()
                    await self._gateway_loop()
            except asyncio.CancelledError:
                break
            except (websockets.ConnectionClosed, websockets.WebSocketException) as e:
                self._gateway_circuit.record_failure()
                logger.warning("Discord gateway connection error: {}", e)
            except Exception as e:
                self._gateway_circuit.record_failure()
                logger.warning("Discord gateway error: {}", e)
            
            if self._running:
                # Exponential backoff with max limit
                if self._reconnect_attempts >= MAX_RECONNECT_ATTEMPTS:
                    logger.error("Max reconnection attempts reached, stopping")
                    break
                
                backoff = min(
                    RECONNECT_BACKOFF_BASE * (2 ** self._reconnect_attempts),
                    RECONNECT_BACKOFF_MAX
                )
                self._reconnect_attempts += 1
                logger.info("Reconnecting to Discord gateway in {}s (attempt {})", 
                          backoff, self._reconnect_attempts)
                await asyncio.sleep(backoff)

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
        """Send a message through Discord REST API with error handling."""
        if not self._http:
            logger.error("Discord HTTP client not initialized")
            return
        
        # Check circuit breaker
        if _message_breaker.current_state == 'open':
            logger.warning("Message sending blocked by circuit breaker")
            return

        url = f"{DISCORD_API_BASE}/channels/{msg.chat_id}/messages"
        headers = {"Authorization": f"Bot {self.config.token}"}

        try:
            sent_media = False
            failed_media: list[str] = []

            # Send file attachments first
            for media_path in msg.media or []:
                if await self._send_file(url, headers, media_path, reply_to=msg.reply_to):
                    sent_media = True
                else:
                    failed_media.append(Path(media_path).name)

            # Send text content
            chunks = split_message(msg.content or "", MAX_MESSAGE_LEN)
            if not chunks and failed_media and not sent_media:
                chunks = split_message(
                    "\n".join(f"[attachment: {name} - send failed]" for name in failed_media),
                    MAX_MESSAGE_LEN,
                )
            if not chunks:
                return

            for i, chunk in enumerate(chunks):
                payload: dict[str, Any] = {"content": chunk}

                # Let the first successful attachment carry the reply if present.
                if i == 0 and msg.reply_to and not sent_media:
                    payload["message_reference"] = {"message_id": msg.reply_to}
                    payload["allowed_mentions"] = {"replied_user": False}

                if not await self._send_payload(url, headers, payload):
                    break  # Abort remaining chunks on failure
                    
        except Exception as e:
            logger.error("Failed to send message: {}", e)
        finally:
            await self._stop_typing(msg.chat_id)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError))
    )
    async def _send_payload(
        self, url: str, headers: dict[str, str], payload: dict[str, Any]
    ) -> bool:
        """Send a single Discord API payload with retry on rate-limit. Returns True on success."""
        try:
            response = await self._http.post(url, headers=headers, json=payload)
            
            # Handle specific HTTP status codes
            if response.status_code == 429:
                # Rate limited - respect Discord's retry_after
                data = response.json()
                retry_after = float(data.get("retry_after", 1.0))
                logger.warning("Discord rate limited, retrying in {}s", retry_after)
                await asyncio.sleep(retry_after)
                raise httpx.TimeoutException("Rate limited")  # Trigger retry
            elif response.status_code == 403:
                logger.error("Discord API 403 Forbidden - bot lacks permissions")
                raise httpx.HTTPStatusError("403 Forbidden", request=response.request, response=response)
            elif response.status_code == 404:
                logger.error("Discord API 404 Not Found - invalid channel or message")
                raise httpx.HTTPStatusError("404 Not Found", request=response.request, response=response)
            elif response.status_code >= 500:
                # Server error - let tenacity retry
                logger.warning("Discord API {} server error, retrying", response.status_code)
                raise httpx.ConnectError(f"Server error {response.status_code}")
            elif response.status_code >= 400:
                # Other client errors
                logger.error("Discord API error {}: {}", response.status_code, response.text)
                raise httpx.HTTPStatusError(f"Client error {response.status_code}", request=response.request, response=response)
                
            response.raise_for_status()
            return True
            
        except (httpx.TimeoutException, httpx.ConnectError):
            # Let tenacity handle retry
            raise
        except httpx.HTTPStatusError:
            # Don't retry HTTP errors
            return False
        except Exception as e:
            logger.error("Unexpected error sending Discord message: {}", e)
            return False

    async def _send_file(
        self,
        url: str,
        headers: dict[str, str],
        file_path: str,
        reply_to: str | None = None,
    ) -> bool:
        """Send a file attachment via Discord REST API using multipart/form-data."""
        path = Path(file_path)
        
        # Validate file exists
        if not path.is_file():
            logger.warning("Discord file not found, skipping: {}", file_path)
            return False

        # Validate file size
        if path.stat().st_size > MAX_ATTACHMENT_BYTES:
            logger.warning("Discord file too large (>20MB), skipping: {}", path.name)
            return False

        payload_json: dict[str, Any] = {}
        if reply_to:
            payload_json["message_reference"] = {"message_id": reply_to}
            payload_json["allowed_mentions"] = {"replied_user": False}

        for attempt in range(3):
            try:
                with open(path, "rb") as f:
                    files = {"files[0]": (path.name, f, "application/octet-stream")}
                    data: dict[str, Any] = {}
                    if payload_json:
                        data["payload_json"] = json.dumps(payload_json)
                    response = await self._http.post(
                        url, headers=headers, files=files, data=data
                    )
                    
                # Handle specific HTTP status codes
                if response.status_code == 429:
                    resp_data = response.json()
                    retry_after = float(resp_data.get("retry_after", 1.0))
                    logger.warning("Discord rate limited, retrying in {}s", retry_after)
                    await asyncio.sleep(retry_after)
                    continue
                elif response.status_code == 403:
                    logger.error("Discord API 403 Forbidden - bot lacks permissions for file upload")
                    self._message_circuit.record_failure()
                    return False
                elif response.status_code == 404:
                    logger.error("Discord API 404 Not Found - invalid channel for file upload")
                    self._message_circuit.record_failure()
                    return False
                elif response.status_code >= 500:
                    logger.warning("Discord API {} server error, retrying", response.status_code)
                    await asyncio.sleep(1)
                    continue
                    
                response.raise_for_status()
                logger.info("Discord file sent: {}", path.name)
                return True
                
            except FileNotFoundError as e:
                logger.error("File not found for upload: {}", path.name)
                return False
            except httpx.TimeoutException as e:
                logger.warning("Discord file upload timeout (attempt {}): {}", attempt + 1, path.name)
                if attempt < 2:
                    await asyncio.sleep(1)
            except httpx.RequestError as e:
                logger.error("Discord file upload request error: {}", e)
                self._message_circuit.record_failure()
                return False
            except Exception as e:
                if attempt == 2:
                    logger.error("Error sending Discord file {}: {}", path.name, e)
                    self._message_circuit.record_failure()
                else:
                    await asyncio.sleep(1)
                    
        self._message_circuit.record_failure()
        return False

    async def _gateway_loop(self) -> None:
        """Main gateway loop: identify, heartbeat, dispatch events with error handling."""
        if not self._ws:
            return

        async for raw in self._ws:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
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
                # Capture bot user ID for mention detection
                user_data = payload.get("user") or {}
                self._bot_user_id = user_data.get("id")
                self._gateway_circuit.record_success()
                logger.info("Discord bot connected as user {}", self._bot_user_id)
            elif op == 0 and event_type == "MESSAGE_CREATE":
                try:
                    await self._handle_message_create(payload)
                except Exception as e:
                    logger.error("Error handling MESSAGE_CREATE: {}", e)
            elif op == 7:
                # RECONNECT: exit loop to reconnect
                logger.info("Discord gateway requested reconnect")
                break
            elif op == 9:
                # INVALID_SESSION: reconnect
                logger.warning("Discord gateway invalid session")
                self._gateway_circuit.record_failure()
                break
            elif op == 6:
                # RESUME: session resumed
                logger.info("Discord gateway session resumed")
                self._gateway_circuit.record_success()

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
        """Start or restart the heartbeat loop with error handling."""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()

        async def heartbeat_loop() -> None:
            while self._running and self._ws:
                payload = {"op": 1, "d": self._seq}
                try:
                    await self._ws.send(json.dumps(payload))
                    self._gateway_circuit.record_success()
                except websockets.ConnectionClosed as e:
                    logger.warning("Discord heartbeat connection closed: {}", e)
                    self._gateway_circuit.record_failure()
                    break
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.warning("Discord heartbeat failed: {}", e)
                    self._gateway_circuit.record_failure()
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
        guild_id = payload.get("guild_id")

        if not sender_id or not channel_id:
            return

        if not self.is_allowed(sender_id):
            return

        # Check group channel policy (DMs always respond if is_allowed passes)
        if guild_id is not None:
            if not self._should_respond_in_group(payload, content):
                return

        content_parts = [content] if content else []
        media_paths: list[str] = []
        media_dir = get_media_dir("discord")

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
            except httpx.TimeoutException as e:
                logger.warning("Timeout downloading Discord attachment {}: {}", filename, e)
                content_parts.append(f"[attachment: {filename} - timeout]")
            except httpx.RequestError as e:
                logger.warning("Failed to download Discord attachment {}: {}", filename, e)
                content_parts.append(f"[attachment: {filename} - download failed]")
            except Exception as e:
                logger.warning("Unexpected error downloading attachment {}: {}", filename, e)
                content_parts.append(f"[attachment: {filename} - error]")

        reply_to = (payload.get("message_reference") or {}).get("message_id")
        # NOTE: Discord does NOT have thread_id field on Message objects
        # Thread context is from channel_id pointing to thread channel
        # Per: https://discord.com/developers/docs/topics/threads

        await self._start_typing(channel_id)

        await self._handle_message(
            sender_id=sender_id,
            chat_id=channel_id,
            content="\n".join(p for p in content_parts if p) or "[empty message]",
            media=media_paths,
            metadata={
                "message_id": str(payload.get("id", "")),
                "guild_id": guild_id,
                "reply_to": reply_to,
                # NOTE: No thread_id - Discord uses channel_id for thread context
            },
        )

    def _should_respond_in_group(self, payload: dict[str, Any], content: str) -> bool:
        """Check if bot should respond in a group channel based on policy."""
        if self.config.group_policy == "open":
            return True

        if self.config.group_policy == "mention":
            # Check if bot was mentioned in the message
            if self._bot_user_id:
                # Check mentions array
                mentions = payload.get("mentions") or []
                for mention in mentions:
                    if str(mention.get("id")) == self._bot_user_id:
                        return True
                # Also check content for mention format <@USER_ID>
                if f"<@{self._bot_user_id}>" in content or f"<@!{self._bot_user_id}>" in content:
                    return True
            logger.debug("Discord message in {} ignored (bot not mentioned)", payload.get("channel_id"))
            return False

        return True

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
