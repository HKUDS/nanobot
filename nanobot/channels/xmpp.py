"""XMPP channel — MUC room and direct message support with file transfers."""

import asyncio
import fnmatch
import mimetypes
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

try:
    from slixmpp import ClientXMPP
    from slixmpp.exceptions import XMPPError
except ImportError as e:
    raise ImportError(
        "XMPP dependencies not installed. Run: pip install slixmpp"
    ) from e

from nanobot.bus.events import OutboundMessage
from nanobot.channels.base import BaseChannel
from nanobot.utils.helpers import safe_filename


class XmppClient(ClientXMPP):
    """XMPP client wrapper with MUC and file transfer support."""

    def __init__(
        self,
        jid: str,
        password: str,
        channel: "XmppChannel",
        nickname: str = "nanobot",
        rooms: list[str] | None = None,
    ):
        super().__init__(jid, password)
        self._channel = channel
        self._nickname = nickname
        self._rooms = set(rooms or [])
        self._joined_rooms: set[str] = set()
        self._running = False

        # Register plugins
        self.register_plugin("xep_0030")  # Service Discovery
        self.register_plugin("xep_0045")  # MUC
        self.register_plugin("xep_0085")  # Chat State Notifications (typing)

        # File transfer plugins (if enabled in config)
        self._file_transfer_enabled = getattr(channel.config, "file_transfer_enabled", True)
        if self._file_transfer_enabled:
            self.register_plugin("xep_0065")  # SOCKS5 Bytestreams (direct file transfer)
            self.register_plugin("xep_0363")  # HTTP File Upload (server-mediated)
            # File transfer event handlers
            self.add_event_handler("ibb_stream_start", self._on_file_transfer_start)
            self.add_event_handler("ibb_stream_data", self._on_file_transfer_data)
            self.add_event_handler("ibb_stream_end", self._on_file_transfer_end)
            self.add_event_handler("socks5_stream_start", self._on_socks5_transfer_start)
            self.add_event_handler("socks5_stream_data", self._on_socks5_transfer_data)
            self.add_event_handler("socks5_stream_end", self._on_socks5_transfer_end)

        # Event handlers
        self.add_event_handler("session_start", self._on_session_start)
        self.add_event_handler("message", self._on_message)
        self.add_event_handler("disconnected", self._on_disconnected)

        # File transfer state
        self._incoming_files: dict[str, dict] = {}

    async def _on_session_start(self, event: Any) -> None:
        """Handle session start - send presence and join rooms."""
        logger.info("XMPP session started for {}", self.boundjid)
        self.send_presence()
        logger.debug("Presence sent")
        await self.get_roster()
        logger.debug("Roster retrieved: {} contacts", len(self.client_roster))

        # Join configured MUC rooms
        for room in self._rooms:
            try:
                self.plugin["xep_0045"].join_muc(room, self._nickname)
                self._joined_rooms.add(room)
                logger.info("Joined XMPP room: {}", room)
            except Exception as e:
                logger.warning("Failed to join XMPP room {}: {}", room, e)

    def _on_message(self, msg: Any) -> None:
        """Handle incoming messages."""
        msg_type = msg.get("type", "unknown")
        msg_from = str(msg["from"])
        msg_body = str(msg["body"]) if msg["body"] else ""

        logger.debug("Message received: type={} from={} body={!r}", msg_type, msg_from, msg_body[:50] if msg_body else "")

        # Ignore messages from ourselves to prevent loops
        if str(msg["from"].bare) == self.boundjid.bare:
            logger.debug("Ignoring message from self")
            return

        if not msg_body.strip():
            logger.debug("Ignoring message with empty body")
            return

        if msg_type in ("chat", "normal"):
            # Direct message - use bare JID for typing to handle multi-resource clients
            bare_jid = str(msg["from"].bare)
            logger.info("Direct message from {}: {}", msg_from, msg_body[:100] if msg_body else "")
            asyncio.create_task(self._channel._handle_dm(
                sender_jid=bare_jid,
                body=msg_body,
            ))
        elif msg_type == "groupchat":
            # MUC message
            logger.info("MUC message from {} in {}: {}", msg["from"].resource, msg["from"].bare, msg_body[:100] if msg_body else "")
            asyncio.create_task(self._channel._handle_muc_message(
                room_jid=str(msg["from"].bare),
                sender_nick=str(msg["from"].resource),
                sender_jid=str(msg["from"]),
                body=msg_body,
            ))
        else:
            logger.debug("Ignoring message with type: {}", msg_type)

    def _on_disconnected(self, event: Any) -> None:
        """Handle disconnection."""
        logger.warning("XMPP disconnected, will reconnect...")
        self._joined_rooms.clear()

        # Cancel and clear typing tasks to prevent memory leaks and orphaned tasks
        for task in self._channel._typing_tasks.values():
            task.cancel()
        self._channel._typing_tasks.clear()

    def _media_dir(self) -> Path:
        """Get media directory for file downloads."""
        d = Path.home() / ".nanobot" / "media" / "xmpp"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _is_file_type_allowed(self, mime_type: str) -> bool:
        """Check if MIME type is in allowed file types."""
        allowed_types = getattr(self._channel.config, "allowed_file_types", ["*/*"])
        for pattern in allowed_types:
            if fnmatch.fnmatch(mime_type.lower(), pattern.lower()):
                return True
        return False

    def _check_file_size(self, size_bytes: int) -> bool:
        """Check if file size is within limits."""
        max_size_mb = getattr(self._channel.config, "max_file_size_mb", 50)
        max_bytes = max_size_mb * 1024 * 1024
        return size_bytes <= max_bytes

    def _build_file_path(self, sender: str, filename: str, mime_type: str | None) -> Path:
        """Build safe file path for incoming file."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_sender = safe_filename(sender.replace("@", "_"))

        # Determine extension
        suffix = ""
        if mime_type:
            ext = mimetypes.guess_extension(mime_type, strict=False)
            if ext:
                suffix = ext
        if not suffix and filename:
            suffix = Path(filename).suffix

        # Build safe filename
        safe_name = safe_filename(Path(filename).name) if filename else "unnamed"
        stem = Path(safe_name).stem[:50]
        final_name = f"{timestamp}_{safe_sender}_{stem}{suffix}"
        return self._media_dir() / final_name

    def _on_file_transfer_start(self, event: Any) -> None:
        """Handle IBB (In-Band Bytestreams) file transfer start."""
        sid = getattr(event, "sid", None)
        if not sid:
            return

        sender = str(getattr(event, "from", "unknown"))
        filename = getattr(event, "filename", "unnamed")
        size = getattr(event, "size", 0)
        mime = getattr(event, "mime_type", "application/octet-stream")

        # Check file type and size
        if not self._is_file_type_allowed(mime):
            logger.warning("Rejected file from {}: MIME type {} not allowed", sender, mime)
            return
        if size > 0 and not self._check_file_size(size):
            logger.warning("Rejected file from {}: size {} exceeds limit", sender, size)
            return

        file_path = self._build_file_path(sender, filename, mime)
        self._incoming_files[sid] = {
            "path": file_path,
            "sender": sender,
            "filename": filename,
            "mime": mime,
            "size": size,
            "data": bytearray(),
            "received": 0,
        }
        logger.info("Starting file receive from {}: {} ({} bytes)", sender, filename, size)

    def _on_file_transfer_data(self, event: Any) -> None:
        """Handle IBB file transfer data chunk."""
        sid = getattr(event, "sid", None)
        if sid not in self._incoming_files:
            return

        data = getattr(event, "data", b"")
        self._incoming_files[sid]["data"].extend(data)
        self._incoming_files[sid]["received"] += len(data)

    def _on_file_transfer_end(self, event: Any) -> None:
        """Handle IBB file transfer completion."""
        sid = getattr(event, "sid", None)
        if sid not in self._incoming_files:
            return

        file_info = self._incoming_files.pop(sid)
        try:
            file_path = file_info["path"]
            file_path.write_bytes(file_info["data"])
            logger.info("Received file saved to {} ({} bytes)", file_path, len(file_info["data"]))

            # Forward to channel for processing
            asyncio.create_task(self._channel._handle_file_received(
                sender_jid=file_info["sender"],
                file_path=str(file_path),
                filename=file_info["filename"],
                mime_type=file_info["mime"],
            ))
        except Exception as e:
            logger.error("Failed to save received file: {}", e)

    def _on_socks5_transfer_start(self, event: Any) -> None:
        """Handle SOCKS5 Bytestreams file transfer start."""
        sid = getattr(event, "sid", None)
        if not sid:
            return

        sender = str(getattr(event, "from", "unknown"))
        filename = getattr(event, "filename", "unnamed")
        size = getattr(event, "size", 0)
        mime = getattr(event, "mime_type", "application/octet-stream")

        if not self._is_file_type_allowed(mime):
            logger.warning("Rejected SOCKS5 file from {}: MIME type {} not allowed", sender, mime)
            return
        if size > 0 and not self._check_file_size(size):
            logger.warning("Rejected SOCKS5 file from {}: size {} exceeds limit", sender, size)
            return

        file_path = self._build_file_path(sender, filename, mime)
        self._incoming_files[sid] = {
            "path": file_path,
            "sender": sender,
            "filename": filename,
            "mime": mime,
            "size": size,
            "data": bytearray(),
            "received": 0,
        }
        logger.info("Starting SOCKS5 file receive from {}: {}", sender, filename)

    def _on_socks5_transfer_data(self, event: Any) -> None:
        """Handle SOCKS5 file transfer data chunk."""
        sid = getattr(event, "sid", None)
        if sid not in self._incoming_files:
            return

        data = getattr(event, "data", b"")
        self._incoming_files[sid]["data"].extend(data)
        self._incoming_files[sid]["received"] += len(data)

    def _on_socks5_transfer_end(self, event: Any) -> None:
        """Handle SOCKS5 file transfer completion."""
        sid = getattr(event, "sid", None)
        if sid not in self._incoming_files:
            return

        file_info = self._incoming_files.pop(sid)
        try:
            file_path = file_info["path"]
            file_path.write_bytes(file_info["data"])
            logger.info("Received SOCKS5 file saved to {} ({} bytes)", file_path, len(file_info["data"]))

            asyncio.create_task(self._channel._handle_file_received(
                sender_jid=file_info["sender"],
                file_path=str(file_path),
                filename=file_info["filename"],
                mime_type=file_info["mime"],
            ))
        except Exception as e:
            logger.error("Failed to save SOCKS5 received file: {}", e)

    def send_typing(self, to_jid: str, typing: bool = True) -> None:
        """Send typing notification."""
        state = "composing" if typing else "paused"
        msg = self.make_message(mto=to_jid, mtype="chat")
        msg["chat_state"] = state
        msg.send()

    def shutdown(self) -> None:
        """Clean shutdown."""
        self._running = False
        self.disconnect()


class XmppChannel(BaseChannel):
    """XMPP channel supporting direct messages and MUC rooms."""

    name = "xmpp"

    def __init__(self, config: Any, bus: Any):
        super().__init__(config, bus)
        self.client: XmppClient | None = None
        self._task: asyncio.Task | None = None
        self._typing_tasks: dict[str, asyncio.Task] = {}

    async def start(self) -> None:
        """Start XMPP client and connect to server."""
        self._running = True

        # Build room list from config
        rooms = list(getattr(self.config, "rooms", []) or [])

        self.client = XmppClient(
            jid=self.config.jid,
            password=self.config.password,
            channel=self,
            nickname=getattr(self.config, "nickname", "nanobot"),
            rooms=rooms,
        )

        # Configure TLS
        self.client.use_ssl = getattr(self.config, "use_tls", True)
        if hasattr(self.config, "server") and self.config.server:
            self.client.connect_address = (self.config.server, self.config.port)

        self.client._running = True
        self._task = asyncio.create_task(self._run_client())
        logger.info("XMPP channel started for {}", self.config.jid)

    async def _run_client(self) -> None:
        """Run the XMPP client with reconnection logic."""
        while self._running:
            try:
                await self.client.connect()
                # Keep the task alive until disconnected
                while self.client.is_connected() and self._running:
                    await asyncio.sleep(1)
            except Exception as e:
                logger.warning("XMPP connection error: {}", e)
            if self._running:
                await asyncio.sleep(5)  # Reconnect delay

    async def stop(self) -> None:
        """Stop the XMPP channel."""
        self._running = False

        # Cancel typing tasks
        for task in self._typing_tasks.values():
            task.cancel()
        self._typing_tasks.clear()

        if self.client:
            self.client.shutdown()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def send(self, msg: OutboundMessage) -> None:
        """Send an outbound message with optional file attachments."""
        if not self.client or not self.client.is_connected():
            logger.warning("XMPP not connected, cannot send message")
            return

        # Stop typing indicator if active
        await self._stop_typing(msg.chat_id)

        # Send message text
        content = msg.content or ""
        if content.strip():
            self.client.send_message(msg.chat_id, content, mtype="chat")

        # Send media files if present
        if msg.media and self.client._file_transfer_enabled:
            for media_path in msg.media:
                await self._send_file(media_path, msg.chat_id)

    async def _send_file(self, file_path: str, to_jid: str) -> None:
        """Send a file to a JID using XEP-0363 (HTTP File Upload) or XEP-0065 (SOCKS5)."""
        try:
            path = Path(file_path).expanduser().resolve()
            if not path.is_file():
                logger.error("File not found for XMPP upload: {}", file_path)
                return

            # Check file size
            size = path.stat().st_size
            max_size_mb = getattr(self.config, "max_file_size_mb", 50)
            if size > max_size_mb * 1024 * 1024:
                logger.error("File too large for XMPP transfer: {} ({} > {} MB)",
                            path.name, size / (1024 * 1024), max_size_mb)
                self.client.send_message(to_jid, f"[File too large: {path.name}]", mtype="chat")
                return

            filename = safe_filename(path.name)
            mime = mimetypes.guess_type(filename, strict=False)[0] or "application/octet-stream"

            # Try HTTP File Upload (XEP-0363) first if available
            if self.client.plugin.get("xep_0363"):
                try:
                    upload_result = await self._upload_via_http_upload(path, filename, mime)
                    if upload_result:
                        # Send the URL to the recipient
                        self.client.send_message(
                            to_jid,
                            f"[File: {filename}]\n{upload_result}",
                            mtype="chat"
                        )
                        return
                except Exception as e:
                    logger.debug("HTTP File Upload failed, trying SOCKS5: {}", e)

            # Fallback to SOCKS5 Bytestreams (XEP-0065)
            if self.client.plugin.get("xep_0065"):
                await self._send_via_socks5(path, to_jid, filename, mime)
            else:
                logger.warning("No file transfer method available for {}", filename)
                self.client.send_message(to_jid, f"[Cannot send file: {filename}]", mtype="chat")

        except Exception as e:
            logger.error("Failed to send file via XMPP: {}", e)

    async def _upload_via_http_upload(self, path: Path, filename: str, mime: str) -> str | None:
        """Upload file via XEP-0363 HTTP File Upload and return the URL."""
        plugin = self.client.plugin.get("xep_0363")
        if not plugin:
            return None

        try:
            with path.open("rb") as f:
                # Request upload slot
                result = await plugin.request_upload_slot(
                    filename=filename,
                    size=path.stat().st_size,
                    content_type=mime
                )
                if result and hasattr(result, "url"):
                    upload_url = result.url
                    # Upload the file
                    # Note: slixmpp handles the actual upload
                    return upload_url
        except Exception as e:
            logger.debug("HTTP upload failed: {}", e)
        return None

    async def _send_via_socks5(self, path: Path, to_jid: str, filename: str, mime: str) -> None:
        """Send file via XEP-0065 SOCKS5 Bytestreams."""
        plugin = self.client.plugin.get("xep_0065")
        if not plugin:
            return

        try:
            with path.open("rb") as f:
                data = f.read()

            # Initiate file transfer
            sid = self.client.make_id()
            await plugin.send_file(
                to_jid=to_jid,
                filename=filename,
                size=len(data),
                mime_type=mime,
                sid=sid,
                data=data
            )
            logger.info("Sent file via SOCKS5: {} to {}", filename, to_jid)
        except Exception as e:
            logger.error("SOCKS5 file transfer failed: {}", e)
            self.client.send_message(to_jid, f"[Failed to send file: {filename}]", mtype="chat")

    async def _handle_file_received(
        self, sender_jid: str, file_path: str, filename: str, mime_type: str
    ) -> None:
        """Handle a received file from XMPP."""
        # Determine media type from mime
        media_type = "file"
        if mime_type:
            if mime_type.startswith("image/"):
                media_type = "image"
            elif mime_type.startswith("video/"):
                media_type = "video"
            elif mime_type.startswith("audio/"):
                media_type = "audio"

        content_parts = [f"[{media_type}: {file_path}]"]

        # Handle voice/audio transcription
        if media_type == "audio" or filename.endswith(('.ogg', '.oga')):
            try:
                from nanobot.providers.transcription import GroqTranscriptionProvider
                transcriber = GroqTranscriptionProvider()
                transcription = await transcriber.transcribe(file_path)
                if transcription:
                    logger.info("Transcribed audio from {}: {}...", sender_jid, transcription[:50])
                    content_parts.append(f"[transcription: {transcription}]")
            except Exception as e:
                logger.debug("Audio transcription failed: {}", e)

        content = "\n".join(content_parts)

        # Start typing indicator
        await self._start_typing(sender_jid)

        try:
            await self._handle_message(
                sender_id=sender_jid,
                chat_id=sender_jid,
                content=content,
                media=[file_path],
                metadata={
                    "type": "direct",
                    "jid": sender_jid,
                    "file_transfer": True,
                    "filename": filename,
                    "mime_type": mime_type,
                },
            )
        except Exception:
            await self._stop_typing(sender_jid)
            raise

    async def _handle_dm(self, sender_jid: str, body: str) -> None:
        """Handle direct message."""
        if not body.strip():
            return

        # Start typing indicator
        await self._start_typing(sender_jid)

        try:
            await self._handle_message(
                sender_id=sender_jid,
                chat_id=sender_jid,
                content=body,
                metadata={"type": "direct", "jid": sender_jid},
            )
        except Exception:
            await self._stop_typing(sender_jid)
            raise

    async def _handle_muc_message(
        self, room_jid: str, sender_nick: str, sender_jid: str, body: str
    ) -> None:
        """Handle MUC (groupchat) message."""
        if not body.strip():
            return

        # Skip messages from ourselves
        if sender_nick == getattr(self.config, "nickname", "nanobot"):
            return

        # Check if we should process this message based on group policy
        if not self._should_process_muc_message(room_jid, body):
            return

        # Start typing indicator
        await self._start_typing(room_jid)

        try:
            await self._handle_message(
                sender_id=f"{room_jid}/{sender_nick}",
                chat_id=room_jid,
                content=body,
                metadata={
                    "type": "muc",
                    "room": room_jid,
                    "sender_nick": sender_nick,
                    "sender_jid": sender_jid,
                },
            )
        except Exception:
            await self._stop_typing(room_jid)
            raise

    def _should_process_muc_message(self, room_jid: str, body: str) -> bool:
        """Apply group policy checks for MUC messages."""
        policy = getattr(self.config, "group_policy", "open")

        if policy == "open":
            return True

        if policy == "allowlist":
            allowed = getattr(self.config, "group_allow_from", []) or []
            return room_jid in allowed

        if policy == "mention":
            nickname = getattr(self.config, "nickname", "nanobot")
            # Check if bot nickname is mentioned
            return f"@{nickname}" in body or nickname in body.split()

        return True

    async def _start_typing(self, jid: str) -> None:
        """Start typing indicator with keepalive."""
        # Skip if already typing to this JID to prevent churn
        if jid in self._typing_tasks:
            return

        if self.client and self.client.is_connected():
            try:
                self.client.send_typing(jid, typing=True)
            except Exception:
                pass

        # Start keepalive task
        async def keepalive():
            try:
                while self._running:
                    await asyncio.sleep(25)  # Refresh typing every 25s
                    if self.client and self.client.is_connected():
                        try:
                            self.client.send_typing(jid, typing=True)
                        except Exception:
                            break
            except asyncio.CancelledError:
                pass

        self._typing_tasks[jid] = asyncio.create_task(keepalive())

    async def _stop_typing(self, jid: str) -> None:
        """Stop typing indicator."""
        if jid in self._typing_tasks:
            task = self._typing_tasks.pop(jid)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        if self.client and self.client.is_connected():
            try:
                # Send "paused" to indicate stopped typing
                self.client.send_typing(jid, typing=False)
                # After a brief delay, send "active" to clear the indicator entirely
                await asyncio.sleep(0.5)
                if self.client and self.client.is_connected():
                    msg = self.client.make_message(mto=jid, mtype="chat")
                    msg["chat_state"] = "active"
                    msg.send()
            except Exception:
                pass
