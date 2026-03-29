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
            self._stop_typing(chat_id)

        if self._ws:
            await self._ws.close()
            self._ws = None

    def _start_typing(self, chat_id: str) -> None:
        self._stop_typing(chat_id)
        self._typing_tasks[chat_id] = asyncio.create_task(self._typing_loop(chat_id))

    def _stop_typing(self, chat_id: str) -> None:
        task = self._typing_tasks.pop(chat_id, None)
        if task and not task.done():
            task.cancel()
        # Send explicit "stopped composing" so WhatsApp clears the indicator
        if self._ws and self._connected:
            try:
                asyncio.ensure_future(
                    self._ws.send(json.dumps({"type": "typing", "to": chat_id, "composing": False}))
                )
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

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through WhatsApp."""
        if not self._ws or not self._connected:
            logger.warning("WhatsApp bridge not connected")
            return

        chat_id = msg.chat_id
        self._stop_typing(chat_id)

        if msg.content and not msg.media:
            try:
                payload = {"type": "send", "to": chat_id, "text": msg.content}
                await self._ws.send(json.dumps(payload, ensure_ascii=False))
            except Exception as e:
                logger.error("Error sending WhatsApp message: {}", e)
                raise

        for i, media_path in enumerate(msg.media or []):
            try:
                mime, _ = mimetypes.guess_type(media_path)
                payload = {
                    "type": "send_media",
                    "to": chat_id,
                    "filePath": media_path,
                    "mimetype": mime or "application/octet-stream",
                    "fileName": media_path.rsplit("/", 1)[-1],
                }
                if i == 0 and msg.content:
                    payload["caption"] = msg.content
                await self._ws.send(json.dumps(payload, ensure_ascii=False))
            except Exception as e:
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
            # Deprecated by whatsapp: old phone number style typically: <phone>@s.whatspp.net
            pn = data.get("pn", "")
            # New LID sytle typically:
            sender = data.get("sender", "")
            content = data.get("content", "")
            message_id = data.get("id", "")

            if message_id:
                if message_id in self._processed_message_ids:
                    return
                self._processed_message_ids[message_id] = None
                while len(self._processed_message_ids) > 1000:
                    self._processed_message_ids.popitem(last=False)

            # Extract just the phone number or lid as chat_id
            is_group = data.get("isGroup", False)
            was_mentioned = data.get("wasMentioned", False)

            if is_group and getattr(self.config, "group_policy", "open") == "mention":
                if not was_mentioned:
                    return

            user_id = pn if pn else sender
            sender_id = user_id.split("@")[0] if "@" in user_id else user_id
            logger.info("Sender {}", sender)

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

            self._start_typing(sender)

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

        elif msg_type == "error":
            logger.error("WhatsApp bridge error: {}", data.get('error'))

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
