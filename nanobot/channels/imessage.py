"""iMessage channel using local macOS database or Photon advanced-imessage-http-proxy."""

from __future__ import annotations

import asyncio
import base64
import mimetypes
import platform
import sqlite3
import subprocess
from collections import OrderedDict
from pathlib import Path
from typing import Any, Literal

import httpx
from loguru import logger
from pydantic import Field

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.paths import get_media_dir
from nanobot.config.schema import Base
from nanobot.utils.helpers import split_message

_DEFAULT_DB_PATH = str(Path.home() / "Library" / "Messages" / "chat.db")
_LOCAL_POLL_INTERVAL = 2.0
_REMOTE_POLL_INTERVAL = 2.0

_AUDIO_EXTENSIONS = frozenset({".m4a", ".mp3", ".wav", ".aac", ".ogg", ".caf", ".opus"})
_MAX_MESSAGE_LEN = 20000


def _split_paragraphs(text: str) -> list[str]:
    """Split text on ``\\n\\n`` boundaries, then apply length limits to each chunk."""
    parts: list[str] = []
    for para in text.split("\n\n"):
        stripped = para.strip()
        if stripped:
            parts.extend(split_message(stripped, _MAX_MESSAGE_LEN))
    return parts or [text]


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class IMessageConfig(Base):
    """iMessage channel configuration."""

    enabled: bool = False
    local: bool = True
    server_url: str = ""
    api_key: str = ""
    proxy: str | None = None
    poll_interval: float = _REMOTE_POLL_INTERVAL
    database_path: str = _DEFAULT_DB_PATH
    allow_from: list[str] = Field(default_factory=list)
    group_policy: Literal["open", "ignore"] = "open"
    reply_to_message: bool = False
    react_tapback: str = "love"
    done_tapback: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bearer_token(server_url: str, api_key: str) -> str:
    """Build the Bearer token expected by advanced-imessage-http-proxy.

    If the key already decodes to a ``url|key`` pair it is used as-is.
    """
    try:
        decoded = base64.b64decode(api_key, validate=True).decode()
        if "|" in decoded:
            return api_key
    except Exception as e:
        logger.debug("API key not pre-encoded, will encode: {}", type(e).__name__)
    raw = f"{server_url}|{api_key}"
    return base64.b64encode(raw.encode()).decode()


def _extract_address(chat_id: str) -> str:
    """Convert a chatGuid to the proxy's address format.

    ``iMessage;-;+1234567890`` → ``+1234567890``
    ``iMessage;+;chat123``     → ``group:chat123``
    ``+1234567890``            → ``+1234567890`` (passthrough)
    """
    if ";-;" in chat_id:
        return chat_id.split(";-;", 1)[1]
    if ";+;" in chat_id:
        return "group:" + chat_id.split(";+;", 1)[1]
    return chat_id


# ---------------------------------------------------------------------------
# Channel
# ---------------------------------------------------------------------------


class IMessageChannel(BaseChannel):
    """iMessage channel with local (macOS) and remote (Photon) modes.

    Local mode reads from the native iMessage SQLite database and sends
    via AppleScript — pure Python, no external dependencies.

    Remote mode talks to a Photon ``advanced-imessage-http-proxy`` server.
    See https://github.com/photon-hq/advanced-imessage-http-proxy for the
    full API reference.
    """

    name = "imessage"
    display_name = "iMessage"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return IMessageConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = IMessageConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: IMessageConfig = config
        self._processed_ids: OrderedDict[str, None] = OrderedDict()
        self._http: httpx.AsyncClient | None = None
        self._last_rowid: int = 0

    # ---- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        if self.config.local:
            await self._start_local()
        else:
            await self._start_remote()

    async def stop(self) -> None:
        self._running = False
        if self._http:
            await self._http.aclose()
            self._http = None

    async def send(self, msg: OutboundMessage) -> None:
        if self.config.local:
            await self._send_local(msg)
        else:
            await self._send_remote(msg)

    # ======================================================================
    # LOCAL MODE  (macOS — sqlite3 + AppleScript)
    # ======================================================================

    async def _start_local(self) -> None:
        if platform.system() != "Darwin":
            logger.error("iMessage local mode requires macOS")
            return

        db_path = self.config.database_path
        if not Path(db_path).exists():
            logger.error(
                "iMessage database not found at {}. "
                "Ensure Full Disk Access is granted to your terminal.",
                db_path,
            )
            return

        self._running = True
        self._last_rowid = self._get_max_rowid(db_path)
        logger.info("iMessage local watcher started (polling {})", db_path)

        while self._running:
            try:
                await self._poll_local_db(db_path)
            except Exception as e:
                logger.warning("iMessage local poll error: {}", e)
            await asyncio.sleep(_LOCAL_POLL_INTERVAL)

    def _get_max_rowid(self, db_path: str) -> int:
        try:
            with sqlite3.connect(db_path, uri=True) as conn:
                cur = conn.execute("SELECT MAX(ROWID) FROM message")
                row = cur.fetchone()
                return row[0] or 0
        except Exception:
            return 0

    async def _poll_local_db(self, db_path: str) -> None:
        loop = asyncio.get_running_loop()
        rows = await loop.run_in_executor(None, self._fetch_new_messages, db_path)
        for row in rows:
            await self._handle_local_message(row)
            self._last_rowid = max(self._last_rowid, int(row["ROWID"]))

    def _fetch_new_messages(self, db_path: str) -> list[dict[str, Any]]:
        with sqlite3.connect(db_path, uri=True) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                """
                SELECT
                    m.ROWID,
                    m.guid,
                    m.text,
                    m.is_from_me,
                    m.date AS msg_date,
                    m.service,
                    h.id AS sender,
                    c.chat_identifier,
                    c.style AS chat_style,
                    a.ROWID AS att_rowid,
                    a.filename AS att_filename,
                    a.mime_type AS att_mime,
                    a.transfer_name AS att_transfer_name
                FROM message m
                LEFT JOIN handle h ON m.handle_id = h.ROWID
                LEFT JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
                LEFT JOIN chat c ON cmj.chat_id = c.ROWID
                LEFT JOIN message_attachment_join maj ON m.ROWID = maj.message_id
                LEFT JOIN attachment a ON maj.attachment_id = a.ROWID
                WHERE m.ROWID > ?
                ORDER BY m.ROWID ASC
                """,
                (self._last_rowid,),
            )
            msg_map: dict[int, dict[str, Any]] = {}
            for row in cur:
                d = dict(row)
                rowid = d["ROWID"]
                if rowid not in msg_map:
                    msg_map[rowid] = {**d, "attachments": []}
                if d.get("att_rowid"):
                    raw_path = d.get("att_filename") or ""
                    resolved = (
                        raw_path.replace("~", str(Path.home()), 1)
                        if raw_path.startswith("~")
                        else raw_path
                    )
                    msg_map[rowid]["attachments"].append(
                        {
                            "filename": resolved,
                            "mime_type": d.get("att_mime") or "",
                            "transfer_name": d.get("att_transfer_name") or "",
                        }
                    )
        return list(msg_map.values())

    async def _handle_local_message(self, row: dict[str, Any]) -> None:
        if row.get("is_from_me"):
            return

        message_id = row.get("guid", "")
        if self._is_seen(message_id):
            return

        sender = row.get("sender") or ""
        chat_id = row.get("chat_identifier") or sender
        content = row.get("text") or ""
        is_group = (row.get("chat_style") or 0) == 43

        if is_group and self.config.group_policy == "ignore":
            return

        media_paths: list[str] = []
        for att in row.get("attachments") or []:
            file_path = att.get("filename", "")
            if not file_path or not Path(file_path).exists():
                continue

            mime = att.get("mime_type") or ""
            ext = Path(file_path).suffix.lower()

            if ext in _AUDIO_EXTENSIONS or mime.startswith("audio/"):
                transcription = await self.transcribe_audio(file_path)
                if transcription:
                    voice_tag = f"[Voice Message: {transcription}]"
                    content = f"{content}\n{voice_tag}" if content else voice_tag
                    continue

            media_paths.append(file_path)
            tag = "image" if mime.startswith("image/") else "file"
            media_tag = f"[{tag}: {file_path}]"
            content = f"{content}\n{media_tag}" if content else media_tag

        await self._handle_message(
            sender_id=sender,
            chat_id=chat_id,
            content=content,
            media=media_paths,
            metadata={
                "message_id": message_id,
                "service": row.get("service", "iMessage"),
                "is_group": is_group,
                "source": "local",
            },
        )
        self._mark_seen(message_id)

    async def _send_local(self, msg: OutboundMessage) -> None:
        recipient = msg.chat_id
        if msg.content:
            for chunk in _split_paragraphs(msg.content):
                await self._applescript_send_text(recipient, chunk)

        for media_path in msg.media or []:
            await self._applescript_send_file(recipient, media_path)

    @staticmethod
    def _escape_applescript(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')

    async def _applescript_send_text(self, recipient: str, text: str) -> None:
        escaped_recipient = self._escape_applescript(recipient)
        escaped_text = self._escape_applescript(text)
        script = (
            f'tell application "Messages"\n'
            f"  set targetService to 1st account whose service type = iMessage\n"
            f'  set targetBuddy to participant "{escaped_recipient}" of targetService\n'
            f'  send "{escaped_text}" to targetBuddy\n'
            f"end tell"
        )
        await self._run_osascript(script)

    async def _applescript_send_file(self, recipient: str, file_path: str) -> None:
        escaped_recipient = self._escape_applescript(recipient)
        escaped_path = self._escape_applescript(file_path)
        script = (
            f'tell application "Messages"\n'
            f"  set targetService to 1st account whose service type = iMessage\n"
            f'  set targetBuddy to participant "{escaped_recipient}" of targetService\n'
            f'  send POSIX file "{escaped_path}" to targetBuddy\n'
            f"end tell"
        )
        await self._run_osascript(script)

    async def _run_osascript(self, script: str) -> None:
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    ["osascript", "-e", script],
                    check=True,
                    capture_output=True,
                    timeout=15,
                ),
            )
        except subprocess.CalledProcessError as e:
            logger.error(
                "AppleScript send failed: {}", e.stderr.decode()[:200] if e.stderr else str(e)
            )
            raise
        except subprocess.TimeoutExpired:
            logger.error("AppleScript send timed out")
            raise

    # ======================================================================
    # REMOTE MODE  (advanced-imessage-http-proxy)
    # https://github.com/photon-hq/advanced-imessage-http-proxy
    # ======================================================================

    def _build_http_client(self) -> httpx.AsyncClient:
        token = _make_bearer_token(self.config.server_url, self.config.api_key)
        return httpx.AsyncClient(
            base_url=self.config.server_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            proxy=self.config.proxy or None,
            timeout=30.0,
        )

    async def _start_remote(self) -> None:
        if not self.config.server_url:
            logger.error("iMessage remote mode requires serverUrl")
            return
        if not self.config.api_key:
            logger.error("iMessage remote mode requires apiKey")
            return

        self._running = True
        self._http = self._build_http_client()

        if not await self._api_health():
            logger.error("iMessage server health check failed — will retry in poll loop")

        await self._seed_existing_message_ids()
        poll_interval = max(0.5, self.config.poll_interval)
        logger.info(
            "iMessage remote polling started ({}s interval, proxy={})",
            poll_interval,
            self.config.proxy or "none",
        )

        while self._running:
            try:
                await self._poll_remote()
            except Exception as e:
                logger.warning("iMessage remote poll error: {}", e)
            await asyncio.sleep(poll_interval)

    async def _seed_existing_message_ids(self) -> None:
        """Mark all existing messages as seen so we only process new ones after startup."""
        try:
            resp = await self._api_get_messages(limit=100)
            if resp and isinstance(resp, list):
                for msg in resp:
                    msg_id = msg.get("id") or msg.get("guid", "")
                    if msg_id:
                        self._mark_seen(msg_id)
                logger.info("Seeded {} existing message IDs", len(self._processed_ids))
        except Exception as e:
            logger.debug("Could not seed existing message IDs: {}", e)

    # ---- inbound -----------------------------------------------------------

    async def _poll_remote(self) -> None:
        if not self._http:
            return

        messages = await self._api_get_messages(limit=50)
        if not messages:
            return

        for msg in reversed(messages):
            await self._handle_remote_message(msg)

    async def _handle_remote_message(self, data: dict[str, Any]) -> None:
        sender_raw = data.get("from") or ""
        if sender_raw == "me" or data.get("isFromMe"):
            return

        message_id = data.get("id") or data.get("guid", "")
        if self._is_seen(message_id):
            return

        sender = sender_raw
        if not sender:
            handle = data.get("handle")
            if isinstance(handle, dict):
                sender = handle.get("address", "")

        address = data.get("chat") or sender
        if not address:
            chats = data.get("chats") or []
            chat_guid = chats[0].get("guid", "") if chats else ""
            address = _extract_address(chat_guid) if chat_guid else sender

        content = data.get("text") or ""
        is_group = address.startswith("group:") or (";+;" in address)

        if is_group and self.config.group_policy == "ignore":
            return

        await self._api_react(address, message_id, self.config.react_tapback)
        await self._api_mark_read(address)

        media_paths: list[str] = []
        for att in data.get("attachments") or []:
            att_guid = att.get("guid", "")
            name = att.get("transferName") or att.get("filename") or ""
            if not att_guid or not self._http:
                continue

            local_path = await self._api_download_attachment(att_guid, name)
            if not local_path:
                continue

            mime, _ = mimetypes.guess_type(local_path)
            ext = Path(local_path).suffix.lower()

            if ext in _AUDIO_EXTENSIONS or (mime and mime.startswith("audio/")):
                transcription = await self.transcribe_audio(local_path)
                if transcription:
                    voice_tag = f"[Voice Message: {transcription}]"
                    content = f"{content}\n{voice_tag}" if content else voice_tag
                    continue

            media_paths.append(local_path)
            tag = "image" if mime and mime.startswith("image/") else "file"
            media_tag = f"[{tag}: {local_path}]"
            content = f"{content}\n{media_tag}" if content else media_tag

        await self._handle_message(
            sender_id=sender,
            chat_id=address,
            content=content,
            media=media_paths,
            metadata={
                "message_id": message_id,
                "is_group": is_group,
                "source": "remote",
                "timestamp": data.get("sentAt") or data.get("dateCreated"),
            },
        )
        self._mark_seen(message_id)

    # ---- outbound ----------------------------------------------------------

    async def _send_remote(self, msg: OutboundMessage) -> None:
        if not self._http:
            raise RuntimeError("iMessage remote HTTP client not initialised")

        to = msg.chat_id
        is_progress = (msg.metadata or {}).get("_progress", False)

        if not is_progress:
            await self._api_start_typing(to)

        try:
            if msg.content:
                chunks = _split_paragraphs(msg.content)
                for i, chunk in enumerate(chunks):
                    body: dict[str, Any] = {"to": to, "text": chunk, "service": "iMessage"}
                    if i == 0 and self.config.reply_to_message and msg.reply_to:
                        body["replyTo"] = msg.reply_to
                    if await self._api_send(body) is None:
                        raise RuntimeError(f"iMessage text delivery failed for {to}")

            for media_path in msg.media or []:
                if await self._api_send_file(to, media_path) is None:
                    raise RuntimeError(f"iMessage media delivery failed: {media_path}")
        finally:
            if not is_progress:
                await self._api_stop_typing(to)

        if not is_progress:
            message_id = (msg.metadata or {}).get("message_id")
            if message_id and self.config.react_tapback:
                await self._api_remove_react(to, message_id, self.config.react_tapback)
                if self.config.done_tapback:
                    await self._api_react(to, message_id, self.config.done_tapback)

    # ======================================================================
    # PROXY API METHODS
    # https://github.com/photon-hq/advanced-imessage-http-proxy
    # ======================================================================

    # ---- messaging ---------------------------------------------------------

    async def _api_send(self, body: dict[str, Any]) -> dict[str, Any] | None:
        """``POST /send`` — send text message with optional effect / reply."""
        return await self._post("/send", body)

    async def _api_send_file(
        self, to: str, file_path: str, audio: bool | None = None
    ) -> dict[str, Any] | None:
        """``POST /send/file`` — send attachment (image, file, audio message)."""
        if not self._http:
            return None
        if not Path(file_path).exists():
            logger.warning("iMessage attachment not found: {}", file_path)
            return None
        mime, _ = mimetypes.guess_type(file_path)
        ext = Path(file_path).suffix.lower()
        is_audio = (
            audio
            if audio is not None
            else (ext in _AUDIO_EXTENSIONS or (mime or "").startswith("audio/"))
        )
        data: dict[str, str] = {"to": to}
        if is_audio:
            data["audio"] = "true"
        with open(file_path, "rb") as f:
            resp = await self._http.post(
                "/send/file",
                data=data,
                files={"file": (Path(file_path).name, f, mime or "application/octet-stream")},
            )
        return self._unwrap(resp)

    async def _api_send_sticker(
        self,
        to: str,
        file_path: str,
        reply_to: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        """``POST /send/sticker`` — send standalone or reply sticker."""
        if not self._http:
            return None
        data: dict[str, str] = {"to": to}
        if reply_to:
            data["replyTo"] = reply_to
        for k in ("stickerX", "stickerY", "stickerScale", "stickerRotation", "stickerWidth"):
            if k in kwargs:
                data[k] = str(kwargs[k])
        with open(file_path, "rb") as f:
            resp = await self._http.post(
                "/send/sticker",
                data=data,
                files={"file": (Path(file_path).name, f, "image/png")},
            )
        return self._unwrap(resp)

    async def _api_unsend(self, message_id: str) -> dict[str, Any] | None:
        """``DELETE /messages/:id`` — retract a sent message."""
        return await self._delete(f"/messages/{message_id}")

    # ---- reactions ---------------------------------------------------------

    async def _api_react(self, chat: str, message_id: str, tapback: str) -> None:
        """``POST /messages/:id/react`` — add tapback (best-effort)."""
        if not self._http or not tapback:
            return
        try:
            await self._http.post(
                f"/messages/{message_id}/react",
                json={"chat": chat, "type": tapback},
            )
        except Exception as e:
            logger.debug("iMessage tapback failed: {}", e)

    async def _api_remove_react(self, chat: str, message_id: str, tapback: str) -> None:
        """``DELETE /messages/:id/react`` — remove tapback (best-effort)."""
        if not self._http or not tapback:
            return
        try:
            await self._http.request(
                "DELETE",
                f"/messages/{message_id}/react",
                json={"chat": chat, "type": tapback},
            )
        except Exception as e:
            logger.debug("iMessage remove tapback failed: {}", e)

    # ---- messages ----------------------------------------------------------

    async def _api_get_messages(
        self,
        limit: int = 50,
        chat: str | None = None,
    ) -> list[dict[str, Any]]:
        """``GET /messages`` — query messages."""
        params: dict[str, Any] = {"limit": limit}
        if chat:
            params["chat"] = chat
        data = await self._get("/messages", params=params)
        return data if isinstance(data, list) else []

    async def _api_search_messages(
        self, query: str, chat: str | None = None
    ) -> list[dict[str, Any]]:
        """``GET /messages/search`` — search messages by text."""
        params: dict[str, Any] = {"q": query}
        if chat:
            params["chat"] = chat
        data = await self._get("/messages/search", params=params)
        return data if isinstance(data, list) else []

    async def _api_get_message(self, message_id: str) -> dict[str, Any] | None:
        """``GET /messages/:id`` — get single message details."""
        data = await self._get(f"/messages/{message_id}")
        return data if isinstance(data, dict) else None

    # ---- chats -------------------------------------------------------------

    async def _api_get_chats(self) -> list[dict[str, Any]]:
        """``GET /chats`` — list all conversations."""
        data = await self._get("/chats")
        return data if isinstance(data, list) else []

    async def _api_get_chat(self, address: str) -> dict[str, Any] | None:
        """``GET /chats/:id`` — get chat details."""
        data = await self._get(f"/chats/{address}")
        return data if isinstance(data, dict) else None

    async def _api_get_chat_messages(
        self,
        address: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """``GET /chats/:id/messages`` — get message history for a chat."""
        data = await self._get(f"/chats/{address}/messages", params={"limit": limit})
        return data if isinstance(data, list) else []

    async def _api_get_chat_participants(self, address: str) -> list[dict[str, Any]]:
        """``GET /chats/:id/participants`` — get group participants."""
        data = await self._get(f"/chats/{address}/participants")
        return data if isinstance(data, list) else []

    async def _api_mark_read(self, address: str) -> None:
        """``POST /chats/:id/read`` — clear unread badge."""
        if not self._http:
            return
        try:
            await self._http.post(f"/chats/{address}/read")
        except Exception as e:
            logger.debug("iMessage mark-read failed: {}", e)

    async def _api_start_typing(self, address: str) -> None:
        """``POST /chats/:id/typing`` — show typing indicator."""
        if not self._http:
            return
        try:
            await self._http.post(f"/chats/{address}/typing")
        except Exception as e:
            logger.debug("iMessage typing start failed: {}", e)

    async def _api_stop_typing(self, address: str) -> None:
        """``DELETE /chats/:id/typing`` — stop typing indicator."""
        if not self._http:
            return
        try:
            await self._http.request("DELETE", f"/chats/{address}/typing")
        except Exception as e:
            logger.debug("iMessage typing stop failed: {}", e)

    # ---- groups ------------------------------------------------------------

    async def _api_create_group(
        self, members: list[str], name: str | None = None
    ) -> dict[str, Any] | None:
        """``POST /groups`` — create a group chat."""
        body: dict[str, Any] = {"members": members}
        if name:
            body["name"] = name
        return await self._post("/groups", body)

    async def _api_update_group(self, group_id: str, name: str) -> dict[str, Any] | None:
        """``PATCH /groups/:id`` — rename a group."""
        if not self._http:
            return None
        resp = await self._http.patch(f"/groups/{group_id}", json={"name": name})
        return self._unwrap(resp)

    # ---- polls -------------------------------------------------------------

    async def _api_create_poll(
        self,
        to: str,
        question: str,
        options: list[str],
    ) -> dict[str, Any] | None:
        """``POST /polls`` — create an interactive poll."""
        return await self._post("/polls", {"to": to, "question": question, "options": options})

    async def _api_get_poll(self, poll_id: str) -> dict[str, Any] | None:
        """``GET /polls/:id`` — get poll details."""
        data = await self._get(f"/polls/{poll_id}")
        return data if isinstance(data, dict) else None

    async def _api_vote_poll(
        self, poll_id: str, chat: str, option_id: str
    ) -> dict[str, Any] | None:
        """``POST /polls/:id/vote`` — vote on a poll option."""
        return await self._post(f"/polls/{poll_id}/vote", {"chat": chat, "optionId": option_id})

    async def _api_unvote_poll(
        self, poll_id: str, chat: str, option_id: str
    ) -> dict[str, Any] | None:
        """``POST /polls/:id/unvote`` — remove vote from poll."""
        return await self._post(f"/polls/{poll_id}/unvote", {"chat": chat, "optionId": option_id})

    async def _api_add_poll_option(
        self, poll_id: str, chat: str, text: str
    ) -> dict[str, Any] | None:
        """``POST /polls/:id/options`` — add option to existing poll."""
        return await self._post(f"/polls/{poll_id}/options", {"chat": chat, "text": text})

    # ---- attachments -------------------------------------------------------

    async def _api_download_attachment(self, att_guid: str, filename: str) -> str | None:
        """``GET /attachments/:id`` — download to local media dir."""
        if not self._http:
            return None
        try:
            resp = await self._http.get(f"/attachments/{att_guid}")
            if not resp.is_success:
                return None
            media_dir = get_media_dir("imessage")
            sanitized_guid = att_guid.replace("/", "_").replace("\\", "_").replace("\x00", "")
            safe_name = Path(filename).name.replace("\x00", "") if filename else ""
            if not safe_name:
                safe_name = f"{sanitized_guid}.bin"
            dest = (media_dir / safe_name).resolve()
            if not dest.is_relative_to(media_dir.resolve()):
                dest = (media_dir / f"{sanitized_guid}.bin").resolve()
            dest.write_bytes(resp.content)
            return str(dest)
        except Exception as e:
            logger.warning("Failed to download iMessage attachment {}: {}", att_guid, e)
            return None

    async def _api_attachment_info(self, att_guid: str) -> dict[str, Any] | None:
        """``GET /attachments/:id/info`` — get attachment metadata."""
        data = await self._get(f"/attachments/{att_guid}/info")
        return data if isinstance(data, dict) else None

    # ---- contacts & handles ------------------------------------------------

    async def _api_check_imessage(self, address: str) -> bool:
        """``GET /check/:address`` — check if address uses iMessage."""
        data = await self._get(f"/check/{address}")
        if isinstance(data, dict):
            return bool(data.get("available") or data.get("imessage"))
        return False

    async def _api_get_contacts(self) -> list[dict[str, Any]]:
        """``GET /contacts`` — list device contacts."""
        data = await self._get("/contacts")
        return data if isinstance(data, list) else []

    async def _api_get_handles(self) -> list[dict[str, Any]]:
        """``GET /handles`` — list known handles."""
        data = await self._get("/handles")
        return data if isinstance(data, list) else []

    # ---- server ------------------------------------------------------------

    async def _api_server_info(self) -> dict[str, Any] | None:
        """``GET /server`` — get server info."""
        data = await self._get("/server")
        return data if isinstance(data, dict) else None

    async def _api_health(self) -> bool:
        """``GET /health`` — basic health check."""
        if not self._http:
            return False
        try:
            resp = await self._http.get("/health")
            if resp.is_success:
                logger.info("iMessage server health check passed")
                return True
            logger.warning("iMessage health check HTTP {}", resp.status_code)
        except Exception as e:
            logger.warning("iMessage health check failed: {}", e)
        return False

    # ---- HTTP helpers ------------------------------------------------------

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not self._http:
            return None
        try:
            resp = await self._http.get(path, params=params)
            return self._unwrap(resp)
        except Exception as e:
            logger.warning("iMessage GET {} failed: {}", path, e)
            return None

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any] | None:
        if not self._http:
            return None
        try:
            resp = await self._http.post(path, json=body)
            if not resp.is_success:
                logger.warning(
                    "iMessage POST {} HTTP {}: {}", path, resp.status_code, resp.text[:200]
                )
            return self._unwrap(resp)
        except Exception as e:
            logger.warning("iMessage POST {} failed: {}", path, e)
            raise

    async def _delete(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any] | None:
        if not self._http:
            return None
        try:
            resp = await self._http.request("DELETE", path, json=body)
            return self._unwrap(resp)
        except Exception as e:
            logger.warning("iMessage DELETE {} failed: {}", path, e)
            return None

    @staticmethod
    def _unwrap(resp: httpx.Response) -> Any:
        """Unwrap the proxy's ``{"ok": true, "data": ...}`` envelope."""
        if not resp.is_success:
            return None
        try:
            body = resp.json()
        except Exception:
            logger.debug("iMessage server returned non-JSON response")
            return None
        if isinstance(body, dict) and "data" in body:
            return body["data"]
        return body

    # ---- dedup helper ------------------------------------------------------

    def _is_seen(self, message_id: str) -> bool:
        if not message_id:
            return False
        return message_id in self._processed_ids

    def _mark_seen(self, message_id: str) -> None:
        if not message_id:
            return
        self._processed_ids[message_id] = None
        while len(self._processed_ids) > 1000:
            self._processed_ids.popitem(last=False)
