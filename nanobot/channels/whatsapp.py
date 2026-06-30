"""WhatsApp channel implementation using neonize."""

from __future__ import annotations

import asyncio
import mimetypes
import re
import secrets
import time
from collections import OrderedDict
from contextlib import suppress
from pathlib import Path
from typing import Any, Literal, NamedTuple

from pydantic import Field

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.paths import get_media_dir, get_runtime_subdir
from nanobot.config.schema import Base


class WhatsAppConfig(Base):
    """WhatsApp channel configuration."""

    enabled: bool = False
    allow_from: list[str] = Field(default_factory=list)
    group_policy: Literal["open", "mention"] = "open"
    database_path: str = ""
    lid_mappings: dict[str, str] = Field(default_factory=dict)


class _NeonizeAPI(NamedTuple):
    NewAClient: Any
    ConnectedEv: Any
    DisconnectedEv: Any
    MessageEv: Any
    PairStatusEv: Any
    build_jid: Any


class _MediaInfo(NamedTuple):
    kind: str
    message: Any
    mimetype: str
    filename: str
    is_voice: bool = False


_NEONIZE_API: _NeonizeAPI | None = None
_JID_RE = re.compile(r"^(?P<user>[^@]+)@(?P<server>[^@]+)$")
_LEGACY_BRIDGE_CONFIG_FIELDS = ("bridgeUrl", "bridgeToken", "bridge_url", "bridge_token")


def _default_database_path() -> Path:
    return get_runtime_subdir("whatsapp-auth") / "neonize.db"


def _legacy_bridge_config_fields(config: dict[str, Any]) -> list[str]:
    return [field for field in _LEGACY_BRIDGE_CONFIG_FIELDS if field in config]


def _load_neonize() -> _NeonizeAPI:
    global _NEONIZE_API
    if _NEONIZE_API is not None:
        return _NEONIZE_API

    try:
        from neonize.aioze.client import NewAClient
        from neonize.aioze.events import ConnectedEv, DisconnectedEv, MessageEv, PairStatusEv
        from neonize.utils.jid import build_jid
    except ImportError as exc:
        raise RuntimeError(
            'WhatsApp dependencies not installed. Run: pip install "nanobot-ai[whatsapp]"'
        ) from exc

    _NEONIZE_API = _NeonizeAPI(
        NewAClient=NewAClient,
        ConnectedEv=ConnectedEv,
        DisconnectedEv=DisconnectedEv,
        MessageEv=MessageEv,
        PairStatusEv=PairStatusEv,
        build_jid=build_jid,
    )
    return _NEONIZE_API


def _has_field(message: Any, name: str) -> bool:
    if message is None:
        return False

    has_field = getattr(message, "HasField", None)
    if callable(has_field):
        try:
            return bool(has_field(name))
        except ValueError:
            pass

    list_fields = getattr(message, "ListFields", None)
    if callable(list_fields):
        try:
            return any(getattr(field, "name", "") == name for field, _ in list_fields())
        except Exception:
            pass

    value = getattr(message, name, None)
    return value is not None and value != "" and value != b""


def _message_field(message: Any, *names: str) -> Any:
    for name in names:
        if _has_field(message, name):
            return getattr(message, name)
    return None


def _safe_attr(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    return getattr(obj, name, default)


def _jid_to_string(jid: Any) -> str:
    if jid is None:
        return ""
    if isinstance(jid, str):
        return jid.strip()
    if bool(_safe_attr(jid, "IsEmpty", False)):
        return ""

    user = str(_safe_attr(jid, "User", "") or "").strip()
    server = str(_safe_attr(jid, "Server", "") or "").strip()
    if user and server:
        return f"{user}@{server}"
    return server or user


def _normalize_jid(raw: Any) -> str:
    jid = _jid_to_string(raw).strip()
    if not jid:
        return ""
    if jid.endswith("@lid.whatsapp.net"):
        return jid[: -len(".whatsapp.net")]
    return jid


def _bare_jid(raw: Any) -> str:
    jid = _normalize_jid(raw)
    if "@" not in jid:
        return jid
    return jid.split("@", 1)[0].split(":", 1)[0]


def _classify_sender_ids(jids: list[Any]) -> tuple[str, str]:
    phone_id = ""
    lid_id = ""

    for raw in jids:
        jid = _normalize_jid(raw)
        if not jid:
            continue
        match = _JID_RE.match(jid)
        if match:
            user = match.group("user").split(":", 1)[0]
            server = match.group("server")
            if server in {"s.whatsapp.net", "c.us"}:
                phone_id = phone_id or user
            elif server in {"lid", "lid.whatsapp.net"}:
                lid_id = lid_id or user
            continue

        if not phone_id:
            phone_id = jid

    return phone_id, lid_id


def _context_infos(message: Any) -> list[Any]:
    infos: list[Any] = []
    for container in (
        message,
        _message_field(message, "extendedTextMessage"),
        _message_field(message, "imageMessage"),
        _message_field(message, "videoMessage"),
        _message_field(message, "audioMessage"),
        _message_field(message, "documentMessage"),
        _message_field(message, "stickerMessage"),
    ):
        context = _message_field(container, "contextInfo")
        if context is not None:
            infos.append(context)
    return infos


def _message_text(message: Any) -> str:
    conversation = str(_safe_attr(message, "conversation", "") or "").strip()
    if conversation:
        return conversation

    extended = _message_field(message, "extendedTextMessage")
    text = str(_safe_attr(extended, "text", "") or "").strip()
    if text:
        return text

    for field_name in ("imageMessage", "videoMessage", "documentMessage", "stickerMessage"):
        media_message = _message_field(message, field_name)
        caption = str(_safe_attr(media_message, "caption", "") or "").strip()
        if caption:
            return caption

    return ""


def _media_message(message: Any) -> _MediaInfo | None:
    image = _message_field(message, "imageMessage")
    if image is not None:
        return _MediaInfo(
            kind="image",
            message=image,
            mimetype=str(_safe_attr(image, "mimetype", "") or "image/jpeg"),
            filename=str(_safe_attr(image, "fileName", "") or ""),
        )

    video = _message_field(message, "videoMessage")
    if video is not None:
        return _MediaInfo(
            kind="video",
            message=video,
            mimetype=str(_safe_attr(video, "mimetype", "") or "video/mp4"),
            filename=str(_safe_attr(video, "fileName", "") or ""),
        )

    audio = _message_field(message, "audioMessage")
    if audio is not None:
        return _MediaInfo(
            kind="audio",
            message=audio,
            mimetype=str(_safe_attr(audio, "mimetype", "") or "audio/ogg"),
            filename=str(_safe_attr(audio, "fileName", "") or ""),
            is_voice=bool(_safe_attr(audio, "PTT", False) or _safe_attr(audio, "ptt", False)),
        )

    document = _message_field(message, "documentMessage")
    if document is not None:
        return _MediaInfo(
            kind="file",
            message=document,
            mimetype=str(_safe_attr(document, "mimetype", "") or "application/octet-stream"),
            filename=str(
                _safe_attr(document, "fileName", "")
                or _safe_attr(document, "title", "")
                or ""
            ),
        )

    sticker = _message_field(message, "stickerMessage")
    if sticker is not None:
        return _MediaInfo(
            kind="sticker",
            message=sticker,
            mimetype=str(_safe_attr(sticker, "mimetype", "") or "image/webp"),
            filename=str(_safe_attr(sticker, "fileName", "") or ""),
        )

    return None


class WhatsAppChannel(BaseChannel):
    """WhatsApp channel using neonize's async WhatsApp client."""

    name = "whatsapp"
    display_name = "WhatsApp"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return WhatsAppConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        legacy_bridge_fields = _legacy_bridge_config_fields(config) if isinstance(config, dict) else []
        if isinstance(config, dict):
            config = WhatsAppConfig.model_validate(config)
        super().__init__(config, bus)
        if legacy_bridge_fields:
            self.logger.warning(
                "Ignoring deprecated WhatsApp bridge config fields: {}. "
                "Run 'nanobot channels login whatsapp' to create a neonize session.",
                ", ".join(legacy_bridge_fields),
            )
        self._client: Any | None = None
        self._connected = False
        self._processed_message_ids: OrderedDict[str, None] = OrderedDict()
        self._lid_to_phone = self._load_lid_mappings()
        self._self_jids: set[str] = set()
        self._started_at = 0.0

    def _database_path(self) -> Path:
        configured = self.config.database_path.strip()
        return Path(configured).expanduser() if configured else _default_database_path()

    def _load_lid_mappings(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for lid, phone in self.config.lid_mappings.items():
            phone_text = str(phone).strip()
            if phone_text:
                mapping[str(lid).strip()] = phone_text
        return mapping

    def _new_client(self) -> Any:
        api = _load_neonize()
        db_path = self._database_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return api.NewAClient(str(db_path))

    async def login(self, force: bool = False) -> bool:
        db_path = self._database_path()
        if force:
            self._reset_database(db_path)

        client = self._new_client()
        login_result = asyncio.get_running_loop().create_future()
        self._register_handlers(client, login_result=login_result, handle_messages=False)

        try:
            self.logger.info("Starting WhatsApp login with neonize...")
            connect_task = await client.connect()
            self._fail_login_on_connect_task_done(connect_task, login_result)
            await login_result
            self.logger.info("WhatsApp login complete")
            return True
        except Exception as exc:
            self.logger.error("WhatsApp login failed: {}", exc)
            return False
        finally:
            with suppress(Exception):
                await client.stop()

    async def start(self) -> None:
        self._running = True
        self._started_at = time.time()
        client = self._new_client()
        self._client = client
        self._register_handlers(client, handle_messages=True)

        try:
            self.logger.info("Connecting WhatsApp channel with neonize...")
            await client.connect()
            await client.idle()
        except asyncio.CancelledError:
            raise
        finally:
            self._running = False
            self._connected = False
            if self._client is client:
                self._client = None
            with suppress(Exception):
                await client.stop()

    async def stop(self) -> None:
        self._running = False
        self._connected = False
        client = self._client
        self._client = None
        if client is not None:
            await client.stop()

    @staticmethod
    def _fail_login_on_connect_task_done(
        connect_task: asyncio.Task[Any] | None,
        login_result: asyncio.Future[None],
    ) -> None:
        if connect_task is None:
            return

        def _on_done(task: asyncio.Task[Any]) -> None:
            try:
                exc = task.exception()
            except asyncio.CancelledError:
                return
            if login_result.done():
                return
            if exc is not None:
                login_result.set_exception(exc)
            else:
                login_result.set_exception(
                    RuntimeError("WhatsApp connection ended before login completed")
                )

        connect_task.add_done_callback(_on_done)

    async def send(self, msg: OutboundMessage) -> None:
        client = self._client
        if client is None or not self._connected:
            raise RuntimeError("WhatsApp channel is not connected")

        to = self._build_jid(msg.chat_id)
        if msg.content:
            await client.send_message(to, msg.content)

        for media_path in msg.media or []:
            await self._send_media(client, to, media_path)

    def _build_jid(self, raw: str) -> Any:
        api = _load_neonize()
        target = raw.strip()
        match = _JID_RE.match(_normalize_jid(target))
        if not match:
            return api.build_jid(target)

        user = match.group("user").split(":", 1)[0]
        server = match.group("server")
        return api.build_jid(user, server)

    async def _send_media(self, client: Any, to: Any, media_path: str) -> None:
        path = str(Path(media_path).expanduser())
        mime, _ = mimetypes.guess_type(path)
        mimetype = mime or "application/octet-stream"
        if mimetype.startswith("image/"):
            await client.send_image(to, path)
        elif mimetype.startswith("video/"):
            await client.send_video(to, path)
        elif mimetype.startswith("audio/"):
            await client.send_audio(to, path)
        else:
            await client.send_document(
                to,
                path,
                filename=Path(path).name,
                mimetype=mimetype,
            )

    def _register_handlers(
        self,
        client: Any,
        *,
        login_result: asyncio.Future[None] | None = None,
        handle_messages: bool,
    ) -> None:
        api = _load_neonize()

        @client.qr
        async def _on_qr(_: Any, qr_data: bytes) -> None:
            import segno

            self.logger.info("Scan the WhatsApp QR code with Linked Devices")
            segno.make_qr(qr_data).terminal(compact=True)

        @client.event(api.ConnectedEv)
        async def _on_connected(current_client: Any, _: Any) -> None:
            self._connected = True
            try:
                await self._remember_self_jids(current_client)
            except Exception as exc:
                if login_result is not None and not login_result.done():
                    login_result.set_exception(exc)
                raise
            if login_result is not None and not login_result.done():
                login_result.set_result(None)
            self.logger.info("WhatsApp connected")

        @client.event(api.DisconnectedEv)
        async def _on_disconnected(_: Any, event: Any) -> None:
            self._connected = False
            if login_result is not None and not login_result.done():
                login_result.set_exception(
                    RuntimeError(f"WhatsApp disconnected before login completed: {event}")
                )
            self.logger.warning("WhatsApp disconnected: {}", event)

        @client.event(api.PairStatusEv)
        async def _on_pair_status(_: Any, event: Any) -> None:
            error = str(_safe_attr(event, "Error", "") or "")
            if error:
                exc = RuntimeError(f"WhatsApp pair status error: {error}")
                if login_result is not None and not login_result.done():
                    login_result.set_exception(exc)
                raise exc
            self.logger.info("WhatsApp pair status: {}", event)

        if not handle_messages:
            return

        @client.event(api.MessageEv)
        async def _on_message(current_client: Any, event: Any) -> None:
            try:
                await self._handle_neonize_message(current_client, event)
            except Exception:
                self.logger.exception("Error handling WhatsApp message")
                raise

    async def _remember_self_jids(self, client: Any) -> None:
        device = _safe_attr(client, "me")
        if device is None:
            device = await client.get_me()

        for attr in ("JID", "LID"):
            jid = _normalize_jid(_safe_attr(device, attr))
            if jid:
                self._self_jids.add(jid)
                self._self_jids.add(_bare_jid(jid))

    async def _send_read_receipt(
        self, client: Any, info: Any, source: Any, message_id: str
    ) -> None:
        """Send a read receipt (blue double-check) for an incoming message.

        Best-effort: any failure is logged at debug level and swallowed so it
        never blocks message processing.
        """
        if not message_id:
            return
        try:
            from neonize.utils.enum import ReceiptType

            chat = _safe_attr(source, "Chat")
            sender = _safe_attr(source, "Sender")
            if chat is None or sender is None:
                return
            await client.mark_read(
                message_id,
                chat=chat,
                sender=sender,
                receipt=ReceiptType.READ,
            )
        except Exception as exc:  # noqa: BLE001 - read receipt is best-effort
            self.logger.debug("Failed to send WhatsApp read receipt: {}", exc)

    async def _handle_neonize_message(self, client: Any, event: Any) -> None:
        info = _safe_attr(event, "Info")
        message = _safe_attr(event, "Message")
        source = _safe_attr(info, "MessageSource")
        if info is None or message is None or source is None:
            raise ValueError("WhatsApp MessageEv is missing Info, Message, or MessageSource")

        if bool(_safe_attr(source, "IsFromMe", False)):
            return

        chat_jid = _normalize_jid(_safe_attr(source, "Chat"))
        if not chat_jid:
            raise ValueError("WhatsApp message has no chat JID")
        if chat_jid == "status@broadcast":
            return

        timestamp = float(_safe_attr(info, "Timestamp", 0) or 0)
        if self._started_at and timestamp and timestamp < self._started_at:
            return

        is_group = bool(_safe_attr(source, "IsGroup", False))
        if is_group and self.config.group_policy == "mention":
            if not self._is_addressed_to_bot(message):
                return

        message_id = str(_safe_attr(info, "ID", "") or "")
        if message_id:
            if message_id in self._processed_message_ids:
                return
            self._processed_message_ids[message_id] = None
            while len(self._processed_message_ids) > 1000:
                self._processed_message_ids.popitem(last=False)

        # Mark the incoming message as read (blue double-check). Best-effort.
        await self._send_read_receipt(client, info, source, message_id)

        participant_jid = _normalize_jid(_safe_attr(source, "Sender"))
        sender_alt_jid = _normalize_jid(_safe_attr(source, "SenderAlt"))
        sender_candidates = [sender_alt_jid, participant_jid]
        if not is_group:
            sender_candidates.append(chat_jid)

        phone_id, lid_id = _classify_sender_ids(sender_candidates)
        if phone_id and lid_id:
            self._lid_to_phone[lid_id] = phone_id

        sender_id = phone_id or self._lid_to_phone.get(lid_id, "") or lid_id
        if not sender_id:
            raise ValueError("WhatsApp message has no resolvable sender ID")
        metadata = {
            "message_id": message_id or None,
            "timestamp": int(timestamp) if timestamp else None,
            "is_group": is_group,
            "is_forwarded": self._is_forwarded(message),
            "participant": participant_jid or None,
            "sender_alt": sender_alt_jid or None,
            "lid": lid_id or None,
            "phone": phone_id or None,
            "is_reply_to_bot": self._is_reply_to_bot(message),
        }
        if not self.is_allowed(sender_id):
            self.logger.info(
                "Passing unauthorized WhatsApp sender {} to pairing flow "
                "(phone={}, lid={}, chat={})",
                sender_id,
                phone_id or "",
                lid_id or "",
                chat_jid,
            )
            await self._handle_message(
                sender_id=sender_id,
                chat_id=chat_jid,
                content=_message_text(message),
                media=[],
                metadata=metadata,
                is_dm=not is_group,
            )
            return

        text = _message_text(message)
        media_paths: list[str] = []
        media = _media_message(message)
        if media is not None:
            path = await self._download_media(client, event, media)
            if media.kind == "audio" and media.is_voice:
                transcription = await self.transcribe_audio(path)
                if transcription:
                    text = transcription
                else:
                    media_paths.append(path)
                    text = self._append_media_tag(text, "audio", path)
            else:
                media_paths.append(path)
                text = self._append_media_tag(text, media.kind, path)

        if not text and not media_paths:
            return

        await self._handle_message(
            sender_id=sender_id,
            chat_id=chat_jid,
            content=text,
            media=media_paths,
            metadata=metadata,
            is_dm=not is_group,
        )

    def _is_addressed_to_bot(self, message: Any) -> bool:
        return self._was_mentioned(message) or self._is_reply_to_bot(message)

    def _was_mentioned(self, message: Any) -> bool:
        if not self._self_jids:
            return False
        for context in _context_infos(message):
            mentioned = (
                _safe_attr(context, "mentionedJID")
                or _safe_attr(context, "mentionedJid")
                or _safe_attr(context, "mentioned_jid")
                or []
            )
            for jid in mentioned:
                normalized = _normalize_jid(jid)
                if normalized in self._self_jids or _bare_jid(normalized) in self._self_jids:
                    return True
        return False

    def _is_reply_to_bot(self, message: Any) -> bool:
        if not self._self_jids:
            return False
        for context in _context_infos(message):
            participant = _normalize_jid(
                _safe_attr(context, "participant")
                or _safe_attr(context, "Participant")
                or ""
            )
            if participant in self._self_jids or _bare_jid(participant) in self._self_jids:
                return True
        return False

    @staticmethod
    def _is_forwarded(message: Any) -> bool:
        for context in _context_infos(message):
            if bool(_safe_attr(context, "isForwarded", False)):
                return True
            if int(_safe_attr(context, "forwardingScore", 0) or 0) > 0:
                return True
        return False

    async def _download_media(self, client: Any, event: Any, media: _MediaInfo) -> str:
        info = _safe_attr(event, "Info")
        message_id = str(_safe_attr(info, "ID", "") or "")
        path = self._media_path(message_id, media)
        await client.download_any(_safe_attr(event, "Message"), str(path))
        return str(path)

    def _media_path(self, message_id: str, media: _MediaInfo) -> Path:
        media_dir = get_media_dir("whatsapp")
        safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", message_id or str(int(time.time())))
        filename = Path(media.filename).name if media.filename else ""
        suffix = Path(filename).suffix if filename else ""
        if not suffix:
            suffix = mimetypes.guess_extension(media.mimetype) or {
                "image": ".jpg",
                "video": ".mp4",
                "audio": ".ogg",
                "sticker": ".webp",
            }.get(media.kind, ".bin")
        return media_dir / f"wa_{safe_id}_{secrets.token_hex(4)}{suffix}"

    @staticmethod
    def _append_media_tag(text: str, kind: str, path: str) -> str:
        label = kind if kind in {"image", "video", "audio", "sticker"} else "file"
        tag = f"[{label}: {path}]"
        return f"{text}\n{tag}" if text else tag

    @staticmethod
    def _reset_database(path: Path) -> None:
        for candidate in (
            path,
            path.with_suffix(path.suffix + "-shm"),
            path.with_suffix(path.suffix + "-wal"),
        ):
            if candidate.exists():
                candidate.unlink()
