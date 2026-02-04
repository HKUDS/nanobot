"""WhatsApp channel implementation using Node.js bridge."""

import asyncio
import base64
import json
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import WhatsAppConfig


class WhatsAppChannel(BaseChannel):
    """
    WhatsApp channel that connects to a Node.js bridge.

    The bridge uses @whiskeysockets/baileys to handle the WhatsApp Web protocol.
    Communication between Python and Node.js is via WebSocket.
    """

    name = "whatsapp"

    def __init__(self, config: WhatsAppConfig, bus: MessageBus, groq_api_key: str = ""):
        super().__init__(config, bus)
        self.config: WhatsAppConfig = config
        self.groq_api_key = groq_api_key
        self._ws = None
        self._connected = False
        self._media_dir = Path.home() / ".nanobot" / "media"
        self._media_dir.mkdir(parents=True, exist_ok=True)
    
    async def start(self) -> None:
        """Start the WhatsApp channel by connecting to the bridge."""
        import websockets
        
        bridge_url = self.config.bridge_url
        
        logger.info(f"Connecting to WhatsApp bridge at {bridge_url}...")
        
        self._running = True
        
        while self._running:
            try:
                async with websockets.connect(bridge_url) as ws:
                    self._ws = ws
                    self._connected = True
                    logger.info("Connected to WhatsApp bridge")
                    
                    # Listen for messages
                    async for message in ws:
                        try:
                            await self._handle_bridge_message(message)
                        except Exception as e:
                            logger.error(f"Error handling bridge message: {e}")
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._connected = False
                self._ws = None
                logger.warning(f"WhatsApp bridge connection error: {e}")
                
                if self._running:
                    logger.info("Reconnecting in 5 seconds...")
                    await asyncio.sleep(5)
    
    async def stop(self) -> None:
        """Stop the WhatsApp channel."""
        self._running = False
        self._connected = False
        
        if self._ws:
            await self._ws.close()
            self._ws = None
    
    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through WhatsApp."""
        if not self._ws or not self._connected:
            logger.warning("WhatsApp bridge not connected")
            return

        try:
            # Check if we have media to send
            if msg.media:
                for media_path in msg.media:
                    await self._send_media(msg.chat_id, media_path, msg.content)
                # If we sent media with caption, don't send text separately
                if not msg.media or not msg.content:
                    return

            # Send text message
            if msg.content:
                payload = {
                    "type": "send",
                    "to": msg.chat_id,
                    "text": msg.content
                }
                await self._ws.send(json.dumps(payload))
        except Exception as e:
            logger.error(f"Error sending WhatsApp message: {e}")

    async def _send_media(self, to: str, media_path: str, caption: str = "") -> None:
        """Send media file through WhatsApp."""
        path = Path(media_path)
        if not path.exists():
            logger.error(f"Media file not found: {media_path}")
            return

        # Determine media type from extension
        ext = path.suffix.lower()
        media_type_map = {
            ".jpg": ("image", "image/jpeg"),
            ".jpeg": ("image", "image/jpeg"),
            ".png": ("image", "image/png"),
            ".gif": ("image", "image/gif"),
            ".webp": ("image", "image/webp"),
            ".mp3": ("audio", "audio/mpeg"),
            ".ogg": ("audio", "audio/ogg; codecs=opus"),
            ".opus": ("audio", "audio/ogg; codecs=opus"),
            ".m4a": ("audio", "audio/mp4"),
            ".wav": ("audio", "audio/wav"),
            ".mp4": ("video", "video/mp4"),
            ".pdf": ("document", "application/pdf"),
        }

        if ext not in media_type_map:
            logger.warning(f"Unknown media type for extension: {ext}")
            return

        media_type, mimetype = media_type_map[ext]

        with open(path, "rb") as f:
            media_data = base64.b64encode(f.read()).decode()

        payload = {
            "type": "send_media",
            "to": to,
            "mediaData": media_data,
            "mimetype": mimetype,
            "mediaType": media_type,
            "caption": caption if media_type != "audio" else None,
            "filename": path.name if media_type == "document" else None,
            "ptt": media_type == "audio",  # Voice note for audio
        }

        await self._ws.send(json.dumps(payload))
        logger.info(f"Sent {media_type} to {to}")
    
    async def _handle_bridge_message(self, raw: str) -> None:
        """Handle a message from the bridge."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON from bridge: {raw[:100]}")
            return
        
        msg_type = data.get("type")
        
        if msg_type == "message":
            # Incoming message from WhatsApp
            sender = data.get("sender", "")
            content = data.get("content", "")
            media_info = data.get("media")

            # sender is typically: <phone>@s.whatsapp.net
            # Extract just the phone number as chat_id
            chat_id = sender.split("@")[0] if "@" in sender else sender

            # Apply prefix rules - filter and strip prefix if needed
            filtered_content = self._apply_prefix_rules(chat_id, content)
            if filtered_content is None:
                logger.debug(f"Ignoring message from {chat_id} - missing required prefix")
                return
            content = filtered_content

            # Process media if present
            media_paths = []
            if media_info:
                media_path, media_content = await self._process_media(media_info, chat_id)
                if media_path:
                    media_paths.append(media_path)
                if media_content:
                    # Replace placeholder content with processed content
                    if content.startswith("[Voice Message]"):
                        content = media_content
                    elif content.startswith("[Image]"):
                        content = media_content
                    else:
                        content = f"{media_content}\n{content}" if content else media_content

            await self._handle_message(
                sender_id=chat_id,
                chat_id=sender,  # Use full JID for replies
                content=content,
                media=media_paths,
                metadata={
                    "message_id": data.get("id"),
                    "timestamp": data.get("timestamp"),
                    "is_group": data.get("isGroup", False)
                }
            )

        elif msg_type == "status":
            # Connection status update
            status = data.get("status")
            logger.info(f"WhatsApp status: {status}")

            if status == "connected":
                self._connected = True
            elif status == "disconnected":
                self._connected = False

        elif msg_type == "qr":
            # QR code for authentication
            logger.info("Scan QR code in the bridge terminal to connect WhatsApp")

        elif msg_type == "error":
            logger.error(f"WhatsApp bridge error: {data.get('error')}")

    async def _process_media(self, media_info: dict, chat_id: str) -> tuple[str | None, str | None]:
        """
        Process incoming media from WhatsApp.

        Returns:
            Tuple of (file_path, content_string)
        """
        media_type = media_info.get("type")
        mimetype = media_info.get("mimetype", "")
        media_data = media_info.get("data", "")

        if not media_data:
            return None, None

        # Determine file extension
        ext_map = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/gif": ".gif",
            "image/webp": ".webp",
            "audio/ogg": ".ogg",
            "audio/ogg; codecs=opus": ".ogg",
            "audio/mpeg": ".mp3",
            "audio/mp4": ".m4a",
            "video/mp4": ".mp4",
        }
        ext = ext_map.get(mimetype.split(";")[0], f".{media_type}" if media_type else ".bin")

        # Save media file
        import time
        filename = f"{chat_id}_{int(time.time())}{ext}"
        file_path = self._media_dir / filename

        try:
            with open(file_path, "wb") as f:
                f.write(base64.b64decode(media_data))
            logger.info(f"Saved {media_type} to {file_path}")
        except Exception as e:
            logger.error(f"Failed to save media: {e}")
            return None, None

        # Process based on type
        content = None

        if media_type == "audio":
            # Transcribe audio using Groq Whisper
            content = await self._transcribe_audio(file_path)
        elif media_type == "image":
            # For images, return path for multimodal processing
            content = f"[image: {file_path}]"

        return str(file_path), content

    async def _transcribe_audio(self, file_path: Path) -> str:
        """Transcribe audio file using Groq Whisper."""
        try:
            from nanobot.providers.transcription import GroqTranscriptionProvider

            transcriber = GroqTranscriptionProvider(api_key=self.groq_api_key)
            transcription = await transcriber.transcribe(file_path)

            if transcription:
                logger.info(f"Transcribed audio: {transcription[:50]}...")
                return f"[transcription: {transcription}]"
            else:
                return f"[audio: {file_path}]"
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            return f"[audio: {file_path}]"

    def _apply_prefix_rules(self, phone: str, content: str) -> str | None:
        """
        Apply prefix rules to filter/strip messages.

        Returns:
            - The (possibly stripped) content if message should be processed
            - None if message should be ignored
        """
        # Check if any prefix rule matches this phone number
        for rule in self.config.prefix_rules:
            if rule.phone in phone:
                # This phone has a prefix rule
                content_lower = content.lower().strip()
                prefix_lower = rule.prefix.lower()

                # Check if message starts with the required prefix
                if content_lower.startswith(prefix_lower + " "):
                    # Has prefix with space - strip it
                    if rule.strip:
                        stripped = content[len(rule.prefix):].strip()
                        logger.info(f"Triggered by '{rule.prefix}' prefix from {phone}")
                        return stripped
                    return content
                elif content_lower == prefix_lower:
                    # Just the prefix alone - treat as greeting
                    logger.info(f"Triggered by '{rule.prefix}' alone from {phone}")
                    return "oi"
                else:
                    # Missing required prefix - ignore
                    return None

        # No prefix rule for this phone - allow all messages
        return content
