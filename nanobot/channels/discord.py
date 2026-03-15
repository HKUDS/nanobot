"""Discord channel implementation using Discord Gateway websocket."""

import asyncio
import base64
import json
import subprocess
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import Field
import websockets
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.paths import get_media_dir
from nanobot.config.schema import Base
from nanobot.utils.helpers import split_message

DISCORD_API_BASE = "https://discord.com/api/v10"
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024  # 20MB
MAX_MESSAGE_LEN = 2000  # Discord message character limit
AUDIO_EXTENSIONS = {".ogg", ".mp3", ".m4a", ".wav", ".aac", ".webm", ".opus"}


def _get_ogg_duration(path: Path) -> float:
    """Get audio duration in seconds using ffprobe."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        return float(result.stdout.strip())
    except Exception:
        return float(path.stat().st_size) / 16000  # rough estimate


def _generate_waveform(path: Path, num_bars: int = 64) -> str:
    """Generate a base64-encoded waveform for Discord voice messages."""
    data = path.read_bytes()
    chunk_size = max(1, len(data) // num_bars)
    amplitudes = []
    for i in range(num_bars):
        chunk = data[i * chunk_size:(i + 1) * chunk_size]
        peak = max(chunk) if chunk else 0
        amplitudes.append(min(255, peak))
    return base64.b64encode(bytes(amplitudes)).decode()


class DiscordConfig(Base):
    """Discord channel configuration."""

    enabled: bool = False
    token: str = ""
    allow_from: list[str] = Field(default_factory=list)
    gateway_url: str = "wss://gateway.discord.gg/?v=10&encoding=json"
    intents: int = 37377
    group_policy: Literal["mention", "open"] = "mention"


class DiscordChannel(BaseChannel):
    """Discord channel using Gateway websocket."""

    name = "discord"
    display_name = "Discord"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return DiscordConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus, *, groq_api_key: str = ""):
        if isinstance(config, dict):
            config = DiscordConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: DiscordConfig = config
        self.groq_api_key = groq_api_key
        self.transcription_api_key = groq_api_key
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._seq: int | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._typing_tasks: dict[str, asyncio.Task] = {}
        self._http: httpx.AsyncClient | None = None
        self._dm_channel_cache: dict[str, str] = {}  # user_id -> dm_channel_id
        self._bot_user_id: str | None = None

    async def start(self) -> None:
        """Start the Discord gateway connection."""
        if not self.config.token:
            logger.error("Discord bot token not configured")
            return

        self._running = True
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=120.0))

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

    async def _resolve_channel_id(self, chat_id: str) -> str:
        """Resolve a chat_id to a channel ID, creating a DM channel if needed."""
        if chat_id in self._dm_channel_cache:
            return self._dm_channel_cache[chat_id]
        # Try to create/get a DM channel with chat_id as a user ID
        headers = {"Authorization": f"Bot {self.config.token}"}
        try:
            resp = await self._http.post(
                f"{DISCORD_API_BASE}/users/@me/channels",
                headers=headers,
                json={"recipient_id": chat_id},
            )
            if resp.status_code == 200:
                dm_id = resp.json().get("id", chat_id)
                self._dm_channel_cache[chat_id] = dm_id
                logger.info("Resolved user {} to DM channel {}", chat_id, dm_id)
                return dm_id
        except Exception as e:
            logger.warning("Failed to create DM channel for {}: {}", chat_id, e)
        return chat_id

    async def _send_with_files(
        self,
        url: str,
        headers: dict[str, str],
        text: str,
        file_paths: list[str],
        reply_to: str | None = None,
    ) -> bool:
        """Upload files as Discord attachments using multipart form-data."""
        from pathlib import Path as _Path

        files_to_upload: list[tuple[str, tuple[str, bytes, str]]] = []
        attachments_meta: list[dict[str, Any]] = []

        for path in file_paths:
            p = _Path(path)
            if not p.exists():
                logger.warning("Attachment not found: {}", path)
                continue
            size = p.stat().st_size
            if size > MAX_ATTACHMENT_BYTES:
                logger.warning("Attachment too large ({}B): {}", size, path)
                continue
            try:
                data = p.read_bytes()
            except Exception as e:
                logger.warning("Cannot read attachment {}: {}", path, e)
                continue
            idx = len(files_to_upload)
            files_to_upload.append(
                (f"files[{idx}]", (p.name, data, "application/octet-stream"))
            )
            attachments_meta.append({"id": idx, "filename": p.name})

        if not files_to_upload:
            # No valid files — fall back to text-only payload
            payload: dict[str, Any] = {"content": text}
            if reply_to:
                payload["message_reference"] = {"message_id": reply_to}
                payload["allowed_mentions"] = {"replied_user": False}
            return await self._send_payload(url, headers, payload)

        payload_json: dict[str, Any] = {"content": text, "attachments": attachments_meta}
        if reply_to:
            payload_json["message_reference"] = {"message_id": reply_to}
            payload_json["allowed_mentions"] = {"replied_user": False}

        for attempt in range(3):
            try:
                response = await self._http.post(
                    url,
                    headers=headers,
                    data={"payload_json": json.dumps(payload_json)},
                    files=files_to_upload,
                )
                if response.status_code == 429:
                    retry_after = float(response.json().get("retry_after", 1.0))
                    logger.warning("Discord rate limited on file upload, retrying in {}s", retry_after)
                    await asyncio.sleep(retry_after)
                    continue
                if response.status_code == 404:
                    logger.warning("Discord channel not found (404) on file upload: {}", url)
                    return False
                response.raise_for_status()
                return True
            except Exception as e:
                if attempt == 2:
                    logger.error("Error uploading Discord attachment: {}", e)
                else:
                    await asyncio.sleep(1)
        return False

    async def _send_voice_message(
        self, url: str, headers: dict[str, str], ogg_path: Path
    ) -> bool:
        """Send OGG as a Discord voice message with waveform."""
        try:
            duration = _get_ogg_duration(ogg_path)
            waveform = _generate_waveform(ogg_path)

            files_data = [
                ("files[0]", (ogg_path.name, ogg_path.read_bytes(), "audio/ogg"))
            ]
            payload = {
                "payload_json": json.dumps({
                    "flags": 8192,  # IS_VOICE_MESSAGE = 1 << 13
                    "attachments": [{
                        "id": 0,
                        "filename": ogg_path.name,
                        "duration_secs": duration,
                        "waveform": waveform,
                    }],
                })
            }

            for attempt in range(3):
                try:
                    resp = await self._http.post(
                        url, headers=headers, files=files_data, data=payload
                    )
                    if resp.status_code == 429:
                        retry_after = float(resp.json().get("retry_after", 1.0))
                        logger.warning("Discord rate limited on voice send, retrying in {}s", retry_after)
                        await asyncio.sleep(retry_after)
                        continue
                    if resp.status_code in (200, 201, 204):
                        return True
                    logger.warning("Discord voice message failed ({}): {}", resp.status_code, resp.text[:200])
                    return False
                except Exception as e:
                    if attempt == 2:
                        logger.error("Error sending Discord voice message: {}", e)
                    else:
                        await asyncio.sleep(1)
        except Exception as e:
            logger.warning("Voice message prep failed, falling back to file: {}", e)
        return False

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through Discord REST API, including file attachments."""
        if not self._http:
            logger.warning("Discord HTTP client not initialized")
            return

        channel_id = msg.chat_id
        headers = {"Authorization": f"Bot {self.config.token}"}
        url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages"
        has_files = bool(msg.media)

        async def _resolve_if_needed(success: bool) -> bool:
            """On failure, try resolving as DM channel and update url/channel_id."""
            nonlocal channel_id, url
            if success:
                return True
            resolved = await self._resolve_channel_id(channel_id)
            if resolved != channel_id:
                channel_id = resolved
                url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages"
            return False

        try:
            chunks = split_message(msg.content or "", MAX_MESSAGE_LEN)
            if not chunks and not has_files:
                return

            if has_files:
                # Separate OGG files for voice message rendering
                ogg_files = [p for p in msg.media if p.lower().endswith(".ogg")]
                other_media = [p for p in msg.media if not p.lower().endswith(".ogg")]

                # Send text chunks before media
                for i, chunk in enumerate(chunks[:-1] if (other_media or not ogg_files) else chunks):
                    payload: dict[str, Any] = {"content": chunk}
                    success = await self._send_payload(url, headers, payload)
                    if not await _resolve_if_needed(success):
                        if not await self._send_payload(url, headers, payload):
                            return

                # Send OGG files as voice messages
                for ogg in ogg_files:
                    success = await self._send_voice_message(url, headers, Path(ogg))
                    if not success:
                        if not await _resolve_if_needed(False):
                            success = await self._send_voice_message(url, headers, Path(ogg))
                        if not success:
                            # Fallback: send as regular file attachment
                            await self._send_with_files(url, headers, "", [ogg])

                # Send remaining non-OGG media with last text chunk
                if other_media:
                    last_text = chunks[-1] if chunks else ""
                    reply_to = msg.reply_to if len(chunks) <= 1 else None
                    success = await self._send_with_files(url, headers, last_text, other_media, reply_to=reply_to)
                    if not await _resolve_if_needed(success):
                        await self._send_with_files(url, headers, last_text, other_media, reply_to=reply_to)
            else:
                # Text-only
                for i, chunk in enumerate(chunks):
                    payload = {"content": chunk}
                    if i == 0 and msg.reply_to:
                        payload["message_reference"] = {"message_id": msg.reply_to}
                        payload["allowed_mentions"] = {"replied_user": False}
                    success = await self._send_payload(url, headers, payload)
                    if not success:
                        if i == 0 and not await _resolve_if_needed(False):
                            if not await self._send_payload(url, headers, payload):
                                break
                        else:
                            break
        finally:
            await self._stop_typing(channel_id)

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
                if response.status_code == 404:
                    # No point retrying — channel not found, caller will try DM resolution
                    logger.warning("Discord channel not found (404): {}", url)
                    return False
                response.raise_for_status()
                return True
            except Exception as e:
                if attempt == 2:
                    logger.error("Error sending Discord message: {}", e)
                else:
                    await asyncio.sleep(1)
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
        if not path.is_file():
            logger.warning("Discord file not found, skipping: {}", file_path)
            return False

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
                if response.status_code == 429:
                    resp_data = response.json()
                    retry_after = float(resp_data.get("retry_after", 1.0))
                    logger.warning("Discord rate limited, retrying in {}s", retry_after)
                    await asyncio.sleep(retry_after)
                    continue
                response.raise_for_status()
                logger.info("Discord file sent: {}", path.name)
                return True
            except Exception as e:
                if attempt == 2:
                    logger.error("Error sending Discord file {}: {}", path.name, e)
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
                # Capture bot user ID for mention detection
                user_data = payload.get("user") or {}
                self._bot_user_id = user_data.get("id")
                logger.info("Discord bot connected as user {}", self._bot_user_id)
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
                async with self._http.stream("GET", url) as resp:
                    resp.raise_for_status()
                    file_path.write_bytes(await resp.aread())
                media_paths.append(str(file_path))

                # Detect audio and transcribe (voice-in)
                ext = Path(filename).suffix.lower()
                api_key = self.groq_api_key or self.transcription_api_key
                if ext in AUDIO_EXTENSIONS and api_key:
                    from nanobot.providers.transcription import GroqTranscriptionProvider
                    transcriber = GroqTranscriptionProvider(api_key=api_key)
                    transcription = await transcriber.transcribe(file_path)
                    if transcription:
                        logger.info("Transcribed Discord audio: {}...", transcription[:50])
                        content_parts.append(f"[transcription: {transcription}]")
                    else:
                        content_parts.append(f"[attachment: {file_path}]")
                else:
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
                "guild_id": guild_id,
                "reply_to": reply_to,
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
