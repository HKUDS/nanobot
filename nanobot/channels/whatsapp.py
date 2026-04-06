"""WhatsApp channel implementation using Node.js bridge."""

import asyncio
import base64
import json
import mimetypes
import os
import shutil
import subprocess
from collections import OrderedDict
from pathlib import Path
from typing import Any, Literal

from loguru import logger
from pydantic import Field

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import Base
from nanobot.providers.transcription import TranscriptionProvider


class WhatsAppConfig(Base):
    """WhatsApp channel configuration."""

    enabled: bool = False
    bridge_url: str = "ws://localhost:3001"
    bridge_token: str = ""
    allow_from: list[str] = Field(default_factory=list)
    group_policy: Literal["open", "mention"] = "open"
    identity_resolution: bool = False  # Enable LID→name resolution via sender_map/lid_map


class WhatsAppChannel(BaseChannel):
    """
    WhatsApp channel that connects to a Node.js bridge.

    The bridge uses @whiskeysockets/baileys to handle the WhatsApp Web protocol.
    Communication between Python and Node.js is via WebSocket.
    """

    name = "whatsapp"
    display_name = "WhatsApp"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return WhatsAppConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = WhatsAppConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: WhatsAppConfig = config
        self._ws = None
        self._connected = False
        self._processed_message_ids: OrderedDict[str, None] = OrderedDict()
        self._typing_tasks: dict[str, asyncio.Task] = {}
        self._pending_acks: dict[str, asyncio.Future[None]] = {}
        self._msg_id_counter = 0
        # LID identity resolution state
        self._lid_map: dict[str, dict] = {}  # in-memory cache of lid_map.json
        self._lid_map_lock = asyncio.Lock()
        self._lid_map_loaded = False
        self._sender_map: dict[str, str] = {}  # in-memory cache of sender_map.json
        self._greeted_sessions: OrderedDict[str, None] = OrderedDict()  # tracks first-message injection

    async def login(self, force: bool = False) -> bool:
        """
        Set up and run the WhatsApp bridge for QR code login.

        This spawns the Node.js bridge process which handles the WhatsApp
        authentication flow. The process blocks until the user scans the QR code
        or interrupts with Ctrl+C.
        """
        from nanobot.config.paths import get_runtime_subdir

        try:
            bridge_dir = _ensure_bridge_setup()
        except RuntimeError as e:
            logger.error("{}", e)
            return False

        env = {**os.environ}
        if self.config.bridge_token:
            env["BRIDGE_TOKEN"] = self.config.bridge_token
        env["AUTH_DIR"] = str(get_runtime_subdir("whatsapp-auth"))

        logger.info("Starting WhatsApp bridge for QR login...")
        try:
            subprocess.run(
                [shutil.which("npm"), "start"], cwd=bridge_dir, check=True, env=env
            )
        except subprocess.CalledProcessError:
            return False

        return True

    async def start(self) -> None:
        """Start the WhatsApp channel by connecting to the bridge."""
        import websockets

        # Load identity maps eagerly if identity resolution is enabled
        if self.config.identity_resolution:
            await self._ensure_maps_loaded()

        bridge_url = self.config.bridge_url

        logger.info("Connecting to WhatsApp bridge at {}...", bridge_url)

        self._running = True

        while self._running:
            try:
                async with websockets.connect(bridge_url) as ws:
                    self._ws = ws
                    # Send auth token if configured
                    if self.config.bridge_token:
                        await ws.send(
                            json.dumps({"type": "auth", "token": self.config.bridge_token})
                        )
                    self._connected = True
                    logger.info("Connected to WhatsApp bridge")

                    # Listen for messages
                    async for message in ws:
                        try:
                            await self._handle_bridge_message(message)
                        except Exception as e:
                            logger.error("Error handling bridge message: {}", e)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._connected = False
                self._ws = None
                logger.warning("WhatsApp bridge connection error: {}", e)

                if self._running:
                    logger.info("Reconnecting in 5 seconds...")
                    await asyncio.sleep(5)

    async def stop(self) -> None:
        """Stop the WhatsApp channel."""
        self._running = False
        self._connected = False

        for chat_id in list(self._typing_tasks):
            await self._stop_typing(chat_id)

        if self._ws:
            await self._ws.close()
            self._ws = None

    async def _start_typing(self, chat_id: str) -> None:
        await self._stop_typing(chat_id)
        self._typing_tasks[chat_id] = asyncio.create_task(self._typing_loop(chat_id))

    async def _stop_typing(self, chat_id: str) -> None:
        task = self._typing_tasks.pop(chat_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        # Send explicit paused so WhatsApp clears the indicator
        if self._ws and self._connected:
            try:
                await self._ws.send(json.dumps({"type": "typing", "to": chat_id, "composing": False}))
            except Exception:
                pass

    async def _typing_loop(self, chat_id: str) -> None:
        """Send 'composing' presence every 10 seconds until cancelled."""
        try:
            while self._ws and self._connected:
                await self._ws.send(json.dumps({"type": "typing", "to": chat_id, "composing": True}))
                await asyncio.sleep(10)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug("WhatsApp typing indicator stopped for {}: {}", chat_id, e)

    def _next_msg_id(self) -> str:
        self._msg_id_counter += 1
        return f"msg_{self._msg_id_counter}"

    async def _send_and_await_ack(self, payload: dict, timeout: float = 30.0) -> None:
        """Send a payload to the bridge and await acknowledgment."""
        msg_id = self._next_msg_id()
        payload["msg_id"] = msg_id

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[None] = loop.create_future()
        self._pending_acks[msg_id] = fut

        try:
            await self._ws.send(json.dumps(payload, ensure_ascii=False))
            await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("WhatsApp bridge ack timeout for {}", msg_id)
            # Don't raise — treat timeout as soft failure (bridge may have sent it)
        finally:
            self._pending_acks.pop(msg_id, None)

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through WhatsApp."""
        if not self._ws or not self._connected:
            raise ConnectionError("WhatsApp bridge not connected")

        chat_id = msg.chat_id
        await self._stop_typing(chat_id)

        if msg.content and not msg.media:
            try:
                payload = {"type": "send", "to": chat_id, "text": msg.content}
                await self._send_and_await_ack(payload)
            except Exception as e:
                logger.error("Error sending WhatsApp message: {}", e)
                raise

        already_sent = set(msg.metadata.get("_sent_media", []))
        sent_media: list[str] = list(already_sent)
        for i, media_path in enumerate(msg.media or []):
            if media_path in already_sent:
                continue
            try:
                mime, _ = mimetypes.guess_type(media_path)
                payload = {
                    "type": "send_media",
                    "to": chat_id,
                    "filePath": media_path,
                    "mimetype": mime or "application/octet-stream",
                    "fileName": media_path.rsplit("/", 1)[-1],
                }
                if i == 0 and msg.content and not already_sent:
                    payload["caption"] = msg.content
                await self._send_and_await_ack(payload)
                sent_media.append(media_path)
            except Exception as e:
                # Record which media succeeded so retries can skip them
                msg.metadata["_sent_media"] = sent_media
                logger.error("Error sending WhatsApp media {}: {}", media_path, e)
                raise

    async def _handle_bridge_message(self, raw: str) -> None:
        """Handle a message from the bridge."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON from bridge: {}", raw[:100])
            return

        msg_type = data.get("type")

        if msg_type == "message":
            # Incoming message from WhatsApp
            pn = data.get("pn", "")
            sender = data.get("sender", "")
            content = data.get("content", "")
            message_id = data.get("id", "")

            if message_id:
                if message_id in self._processed_message_ids:
                    return
                self._processed_message_ids[message_id] = None
                while len(self._processed_message_ids) > 1000:
                    self._processed_message_ids.popitem(last=False)

            is_group = data.get("isGroup", False)
            was_mentioned = data.get("wasMentioned", False)

            if is_group and getattr(self.config, "group_policy", "open") == "mention":
                if not was_mentioned:
                    return

            # When identity_resolution is enabled, always use LID (sender) as
            # canonical identifier. Otherwise, prefer pn for backward compat
            # with existing allow_from lists that use phone numbers.
            if self.config.identity_resolution:
                sender_id = sender.split("@")[0] if "@" in sender else sender
            else:
                user_id = pn if pn else sender
                sender_id = user_id.split("@")[0] if "@" in user_id else user_id
            logger.info("Sender {} (pn={})", sender, pn or "none")

            # Load identity maps on first message (if enabled)
            if self.config.identity_resolution:
                await self._ensure_maps_loaded()
                # Learn LID↔phone from inbound messages (handles case where
                # user messages bot before bot has ever messaged them)
                if pn and sender and pn != sender:
                    await self._save_lid_mapping(pn, sender)

            # Handle voice/audio message transcription
            audio_data = data.get("audio")
            if audio_data:
                content = await self._transcribe_audio(audio_data, sender_id)

            # Extract media paths (images/documents/videos downloaded by the bridge)
            media_paths = data.get("media") or []

            # Build content tags matching Telegram's pattern: [image: /path] or [file: /path]
            if media_paths:
                for p in media_paths:
                    mime, _ = mimetypes.guess_type(p)
                    media_type = "image" if mime and mime.startswith("image/") else "file"
                    media_tag = f"[{media_type}: {p}]"
                    content = f"{content}\n{media_tag}" if content else media_tag

            if self.is_allowed(sender_id):
                await self._start_typing(sender)

            # Resolve sender name and inject on first message in session.
            # Skip for: media-only (empty content), slash commands (starts with /)
            if self.config.identity_resolution and content and not content.startswith("/"):
                session_key = f"whatsapp:{sender}"
                sender_name = self._resolve_sender_name(sender_id, session_key)
                if sender_name:
                    content = f"[Sender: {sender_name}]\n{content}"

            await self._handle_message(
                sender_id=sender_id,
                chat_id=sender,  # Use full LID for replies
                content=content,
                media=media_paths,
                metadata={
                    "message_id": message_id,
                    "timestamp": data.get("timestamp"),
                    "is_group": data.get("isGroup", False),
                },
            )

        elif msg_type == "status":
            # Connection status update
            status = data.get("status")
            logger.info("WhatsApp status: {}", status)

            if status == "connected":
                self._connected = True
            elif status == "disconnected":
                self._connected = False

        elif msg_type == "qr":
            # QR code for authentication
            logger.info("Scan QR code in the bridge terminal to connect WhatsApp")

        elif msg_type == "sent":
            msg_id = data.get("msg_id")
            lid = data.get("lid", "")
            to = data.get("to", "")
            if self.config.identity_resolution and lid and to and lid != to:
                await self._save_lid_mapping(to, lid)
            if msg_id and msg_id in self._pending_acks:
                self._pending_acks[msg_id].set_result(None)

        elif msg_type == "error":
            error_text = data.get("error", "Unknown bridge error")
            logger.error("WhatsApp bridge error: {}", error_text)
            msg_id = data.get("msg_id")
            if msg_id and msg_id in self._pending_acks:
                self._pending_acks[msg_id].set_exception(
                    RuntimeError(f"WhatsApp bridge error: {error_text}")
                )

    def is_allowed(self, sender_id: str) -> bool:
        """Check if sender_id is permitted, including dynamic LID resolution.

        Extends base is_allowed to also check the in-memory lid_map: if this
        sender_id is a LID that maps to an authorized phone, allow it.
        Evaluates allow_from on every call so config changes take effect.
        """
        if super().is_allowed(sender_id):
            return True
        info = self._lid_map.get(sender_id)
        if isinstance(info, dict):
            phone = info.get("phone", "")
            if phone and super().is_allowed(phone):
                return True
        return False

    def _resolve_sender_name(self, sender_id: str, session_key: str) -> str | None:
        """Resolve sender_id to a guest name using sender_map + lid_map.

        Only returns a name on the first message in a session to avoid the LLM
        parroting the name in every response. Bounded to 500 sessions max.
        Only marks session as greeted if a name is actually resolved.
        """
        if session_key in self._greeted_sessions:
            return None  # Already injected for this session

        name: str | None = None

        # Check sender_map (build-time: phone/LID → name)
        if sender_id in self._sender_map:
            name = self._sender_map[sender_id]

        # Check lid_map (runtime: LID → {phone, name?})
        if not name:
            info = self._lid_map.get(sender_id)
            if isinstance(info, dict):
                name = info.get("name") or None
                if not name:
                    phone = info.get("phone", "")
                    if phone and phone in self._sender_map:
                        name = self._sender_map[phone]

        # Only mark as greeted if we actually resolved a name
        if name:
            self._greeted_sessions[session_key] = None
            while len(self._greeted_sessions) > 500:
                self._greeted_sessions.popitem(last=False)

        return name

    async def _ensure_maps_loaded(self) -> None:
        """Load sender_map.json and lid_map.json into memory on first use."""
        if not self._lid_map_loaded:
            async with self._lid_map_lock:
                if not self._lid_map_loaded:
                    lid_map, sender_map = await asyncio.to_thread(self._read_maps_from_disk)
                    # Merge disk data with in-memory entries (preserve both sides)
                    for k, v in lid_map.items():
                        if k not in self._lid_map:
                            self._lid_map[k] = v
                        elif isinstance(v, dict) and isinstance(self._lid_map[k], dict):
                            # Deep merge: disk fields fill in gaps in memory
                            for field, val in v.items():
                                self._lid_map[k].setdefault(field, val)
                    self._sender_map = sender_map
                    self._lid_map_loaded = True

    def _read_maps_from_disk(self) -> tuple[dict, dict[str, str]]:
        """Synchronous disk reads, called via asyncio.to_thread.

        Returns (lid_map, sender_map) — does NOT mutate instance state
        to avoid thread-safety issues.
        """
        from nanobot.config.paths import get_data_dir

        lid_map: dict = {}
        sender_map: dict[str, str] = {}

        # lid_map.json
        lid_map_path = get_data_dir() / "lid_map.json"
        if lid_map_path.exists():
            try:
                raw = json.loads(lid_map_path.read_text(encoding="utf-8"))
                lid_map = {k: v for k, v in raw.items() if isinstance(v, dict)} if isinstance(raw, dict) else {}
                logger.debug("Loaded lid_map with {} entries", len(lid_map))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load lid_map.json: {}", e)

        # sender_map.json — check workspace paths
        for candidate in self._sender_map_paths():
            if candidate.exists():
                try:
                    data = json.loads(candidate.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        sender_map = {k: v for k, v in data.items() if isinstance(v, str)}
                        logger.debug("Loaded sender_map with {} entries from {}", len(sender_map), candidate)
                        break
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("Failed to load sender_map from {}: {}", candidate, e)

        return lid_map, sender_map

    @staticmethod
    def _sender_map_paths() -> list[Path]:
        """Return candidate sender_map.json paths."""
        from nanobot.config.paths import get_data_dir
        return [get_data_dir() / "sender_map.json"]

    async def _save_lid_mapping(self, phone_jid: str, lid: str) -> None:
        """Persist a phone→LID mapping learned from an outbound send ack.

        Updates in-memory cache immediately and persists to disk asynchronously
        under a lock to prevent concurrent write corruption.
        """
        lid_prefix = lid.split("@")[0] if "@" in lid else lid
        phone_digits = phone_jid.split("@")[0] if "@" in phone_jid else phone_jid

        existing = self._lid_map.get(lid_prefix)
        if isinstance(existing, dict) and existing.get("phone") == phone_digits:
            return  # Already mapped

        # Update in-memory cache — merge to preserve existing fields (e.g. name)
        if not isinstance(existing, dict):
            self._lid_map[lid_prefix] = {"phone": phone_digits}
        else:
            existing["phone"] = phone_digits

        # Snapshot under lock, write outside lock (atomic write is safe without lock)
        async with self._lid_map_lock:
            snapshot = dict(self._lid_map)
        await asyncio.to_thread(self._write_lid_map, snapshot)
        logger.info("LID mapping saved: {} → {}", lid_prefix, phone_digits)

    @staticmethod
    def _write_lid_map(data: dict) -> None:
        """Synchronous atomic disk write, called via asyncio.to_thread under lock."""
        import tempfile
        from nanobot.config.paths import get_data_dir
        map_path = get_data_dir() / "lid_map.json"
        map_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd, tmp_path = tempfile.mkstemp(dir=map_path.parent, suffix=".tmp")
            os.close(fd)  # Close fd immediately; reopen with standard open
            try:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                Path(tmp_path).replace(map_path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except OSError as e:
            logger.warning("Failed to save LID mapping: {}", e)

    async def _transcribe_audio(self, audio_data: dict, sender_id: str) -> str:
        """Transcribe a voice/audio message using base channel transcription.

        Audio bytes from the bridge are base64-encoded, decoded to a temp file,
        then transcribed via self.transcribe_audio() (Groq via BaseChannel).
        """
        import tempfile

        try:
            audio_bytes = base64.b64decode(audio_data.get("data", ""))
        except Exception as e:
            logger.error("Failed to decode audio bytes from bridge for {}: {}", sender_id, e)
            return "[Voice message - transcription failed]"

        if not audio_bytes:
            return "[Voice message - transcription failed]"

        mimetype = audio_data.get("mimetype", "audio/ogg; codecs=opus")
        ext = ".ogg" if "ogg" in mimetype else ".mp3"

        logger.info(
            "Transcribing voice message from {} ({} bytes, mimetype={})",
            sender_id, len(audio_bytes), mimetype,
        )

        try:
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name
            transcript = await self.transcribe_audio(tmp_path)
        except Exception as e:
            logger.error("Voice transcription failed for {}: {}", sender_id, e)
            return "[Voice message - transcription failed]"
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        if transcript:
            logger.info("Transcribed voice message from {}: {}...", sender_id, transcript[:80])
        else:
            logger.warning("Empty transcript for voice message from {}", sender_id)
            transcript = "[Voice message - transcription failed]"

        return transcript
