"""QQ-owned interactive QR connection flow.

Scans the official QQ Bot QR binding page (``q.qq.com``) and writes the
resulting AppID/secret straight to config, so the settings form never needs
them typed by hand. The portal encrypts the secret with a key generated here,
so credentials never travel in plaintext.
"""

from __future__ import annotations

import asyncio
import base64
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, cast
from urllib.parse import quote

import httpx
from filelock import FileLock

from nanobot.channels.connect import ChannelConnectError, QueryParams, query_first

PORTAL_BASE = "https://q.qq.com"
CONNECT_URL = "https://q.qq.com/qqbot/openclaw/connect.html?task_id={task_id}&_wv=2"
POLL_INTERVAL_MS = 2000
SESSION_TTL_SECONDS = 600
_REQUEST_TIMEOUT = 10.0
# q.qq.com serves a JS anti-bot challenge without a browser-like request.
_HEADERS = {"Accept": "application/json", "User-Agent": "Mozilla/5.0 (QQBot/1.0)"}


@dataclass(slots=True)
class QQConnectSession:
    id: str
    task_id: str
    key: str
    created_wall: float
    deadline: float
    credentials: tuple[str, str] | None = field(default=None, repr=False)


def _decrypt_secret(encrypted: str, key: str) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    raw = base64.b64decode(encrypted)
    return AESGCM(base64.b64decode(key)).decrypt(raw[:12], raw[12:], None).decode()


async def create_bind_task() -> tuple[str, str]:
    """Return ``(task_id, base64 AES key)`` for one QR binding."""
    key = base64.b64encode(secrets.token_bytes(32)).decode()
    data = await _portal_post("/lite/create_bind_task", {"key": key})
    task_id = str(data.get("task_id") or "")
    if not task_id:
        raise RuntimeError("QQ did not return a QR task id")
    return task_id, key


async def poll_bind_task(task_id: str) -> dict[str, Any]:
    return await _portal_post("/lite/poll_bind_result", {"task_id": task_id})


async def _portal_post(path: str, body: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
        response = await client.post(f"{PORTAL_BASE}{path}", json=body, headers=_HEADERS)
        response.raise_for_status()
        payload = cast(dict[str, Any], response.json())
    if payload.get("retcode") != 0:
        raise RuntimeError(payload.get("msg") or f"QQ portal error for {path}")
    data = payload.get("data")
    return cast(dict[str, Any], data) if isinstance(data, dict) else {}


def save_credentials(app_id: str, secret: str) -> None:
    """Merge credentials under the same file lock as settings mutations."""
    from nanobot.config.loader import get_config_path, load_config, save_config

    path = get_config_path().expanduser().resolve(strict=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(path.with_suffix(f"{path.suffix}.lock"))):
        config = load_config(path)
        raw = getattr(config.channels, "qq", None)
        values: dict[str, Any] = dict(cast(dict[str, Any], raw)) if isinstance(raw, dict) else {}
        values.update(appId=app_id, secret=secret)
        setattr(config.channels, "qq", values)
        save_config(config, path)


class QQConnectStore:
    """In-memory QQ QR binding sessions for the WebUI and CLI login."""

    def __init__(self) -> None:
        self._sessions: dict[str, QQConnectSession] = {}
        self._commits: dict[str, asyncio.Task[None]] = {}
        self._closed = False

    @property
    def has_pending_work(self) -> bool:
        now = time.monotonic()
        return bool(self._commits) or any(session.deadline > now for session in self._sessions.values())

    async def close(self) -> None:
        self._closed = True
        self._sessions.clear()
        if self._commits:
            await asyncio.shield(asyncio.gather(*self._commits.values(), return_exceptions=True))

    async def handle(self, action: str, query: QueryParams) -> dict[str, Any]:
        if action == "start":
            return await self.start()
        session_id = (query_first(query, "session_id") or "").strip()
        if not session_id:
            raise ChannelConnectError("missing QQ connect session")
        if action == "poll":
            return await self.poll(session_id)
        if action == "cancel":
            return await self.cancel(session_id)
        raise ChannelConnectError(f"unsupported QQ connect action: {action}", status=404)

    async def start(self) -> dict[str, Any]:
        self._cleanup()
        try:
            task_id, key = await create_bind_task()
        except Exception as exc:
            raise ChannelConnectError(f"Unable to start QQ QR login: {exc}", status=502) from exc
        session = self._new_session(task_id, key)
        return _pending(session, "Scan with mobile QQ to connect.")

    async def poll(self, session_id: str) -> dict[str, Any]:
        self._cleanup()
        session = self._sessions.get(session_id)
        if session is None:
            return _payload(session_id, "expired", "This QQ login has expired. Start again.")

        try:
            result = await poll_bind_task(session.task_id)
        except Exception:
            # A transient portal error is not proof the scan failed; keep waiting.
            return _pending(session, "Waiting for QQ scan...", retrying=True)

        self._cleanup()
        if self._sessions.get(session_id) is not session:
            return _payload(session_id, "expired", "This QQ login has expired. Start again.")

        status = result.get("status")
        if status == 3:
            self._sessions.pop(session_id, None)
            return _payload(session_id, "expired", "This QQ QR code expired. Start again.")
        if status != 2:
            return _pending(session, "Waiting for QQ scan...")

        app_id = str(result.get("bot_appid") or "")
        encrypted = str(result.get("bot_encrypt_secret") or "")
        self._sessions.pop(session_id, None)
        try:
            secret = _decrypt_secret(encrypted, session.key)
        except Exception as exc:
            return _payload(session_id, "failed", f"QQ secret could not be decrypted: {exc}")
        if not app_id or not secret:
            return _payload(session_id, "failed", "QQ confirmed the scan but returned no credentials.")

        # Cancelling the awaiting request cannot stop a file-writing thread.
        # Retain ownership until the writer finishes, including during shutdown.
        commit = asyncio.create_task(asyncio.to_thread(save_credentials, app_id, secret))
        self._commits[session_id] = commit
        commit.add_done_callback(lambda task: self._commits.pop(session_id, None))
        commit.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
        await asyncio.shield(commit)
        session.credentials = (app_id, secret)
        return _payload(session_id, "succeeded", "QQ is connected.")

    async def cancel(self, session_id: str) -> dict[str, Any]:
        self._sessions.pop(session_id, None)
        if commit := self._commits.get(session_id):
            await asyncio.shield(asyncio.gather(commit, return_exceptions=True))
        return _payload(session_id, "cancelled", "QQ login cancelled.")

    async def login(self) -> tuple[str, str] | None:
        """Print the QR and return committed credentials to the CLI config owner."""
        try:
            task_id, key = await create_bind_task()
        except Exception as exc:
            raise ChannelConnectError(f"Unable to start QQ QR login: {exc}", status=502) from exc
        session = self._new_session(task_id, key)
        try:
            _print_qr(CONNECT_URL.format(task_id=quote(task_id)))
            while True:
                payload = await self.poll(session.id)
                if payload["status"] != "pending":
                    return session.credentials if payload["status"] == "succeeded" else None
                await asyncio.sleep(POLL_INTERVAL_MS / 1000)
        finally:
            self._sessions.pop(session.id, None)

    def _new_session(self, task_id: str, key: str) -> QQConnectSession:
        if self._closed:
            raise ChannelConnectError("QQ connection store is closed", status=409)
        session = QQConnectSession(
            id=secrets.token_urlsafe(18),
            task_id=task_id,
            key=key,
            created_wall=time.time(),
            deadline=time.monotonic() + SESSION_TTL_SECONDS,
        )
        self._sessions[session.id] = session
        return session

    def _cleanup(self) -> None:
        now = time.monotonic()
        for session_id in [sid for sid, s in self._sessions.items() if now >= s.deadline]:
            self._sessions.pop(session_id, None)


def _print_qr(url: str) -> None:
    import qrcode

    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.make(fit=True)
    qr.print_ascii(invert=True)


def _payload(session_id: str, status: str, message: str) -> dict[str, Any]:
    return {"session_id": session_id, "status": status, "message": message, "retrying": False}


def _pending(session: QQConnectSession, message: str, *, retrying: bool = False) -> dict[str, Any]:
    return {
        "session_id": session.id,
        "status": "pending",
        "qr_url": CONNECT_URL.format(task_id=quote(session.task_id)),
        "interval_ms": POLL_INTERVAL_MS,
        "expires_at_ms": int((session.created_wall + SESSION_TTL_SECONDS) * 1000),
        "message": message,
        "retrying": retrying,
    }


__all__ = [
    "QQConnectStore",
    "create_bind_task",
    "poll_bind_task",
    "save_credentials",
]
