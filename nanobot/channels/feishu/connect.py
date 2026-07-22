"""Short-lived WebUI channel connection sessions."""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any

import httpx

from nanobot.channels.connect import ChannelConnectError, QueryParams, query_first
from nanobot.channels.feishu import runtime as feishu
from nanobot.channels.feishu.instances import DEFAULT_INSTANCE_ID, validate_instance_id


@dataclass(slots=True)
class FeishuConnectSession:
    id: str
    instance_id: str
    instance_name: str
    device_code: str
    qr_url: str
    domain: str
    interval: int
    expire_in: int
    created_wall: float
    deadline: float
    last_error: str | None = None


class FeishuConnectStore:
    """In-memory Feishu/Lark QR connection state.

    Sessions intentionally live only in the gateway process and expire quickly.
    The app secret is never returned to the browser; it is saved directly to
    config when Feishu/Lark completes authorization.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, FeishuConnectSession] = {}

    async def handle(self, action: str, query: QueryParams) -> dict[str, Any]:
        """Handle one generic settings connection action."""
        if action == "start":
            return await asyncio.to_thread(
                self.start,
                domain=(query_first(query, "domain") or "feishu").strip(),
                instance_id=(query_first(query, "instance_id") or "default").strip(),
                mode=(query_first(query, "mode") or "replace").strip(),
            )

        session_id = (query_first(query, "session_id") or "").strip()
        if not session_id:
            raise ChannelConnectError("missing Feishu connect session")
        if action == "poll":
            return await asyncio.to_thread(self.poll, session_id)
        if action == "cancel":
            return self.cancel(session_id)
        raise ChannelConnectError(f"unsupported Feishu connect action: {action}", status=404)

    def start(
        self,
        *,
        domain: str = "feishu",
        instance_id: str = DEFAULT_INSTANCE_ID,
        mode: str = "replace",
    ) -> dict[str, Any]:
        domain = _normalize_domain(domain)
        instance_id = _resolve_instance_id(instance_id, mode)
        self._cleanup()
        try:
            feishu._init_registration(domain)
            begin = feishu._begin_registration(domain)
        except (RuntimeError, OSError, json.JSONDecodeError, httpx.HTTPError) as exc:
            raise ChannelConnectError(
                f"Unable to start Feishu/Lark connection: {exc}",
                status=502,
            ) from exc

        session_id = secrets.token_urlsafe(18)
        now_wall = time.time()
        now = time.monotonic()
        expire_in = int(begin["expire_in"])
        interval = max(2, int(begin["interval"]))
        session = FeishuConnectSession(
            id=session_id,
            instance_id=instance_id,
            instance_name=_default_instance_name(instance_id),
            device_code=str(begin["device_code"]),
            qr_url=str(begin["qr_url"]),
            domain=domain,
            interval=interval,
            expire_in=expire_in,
            created_wall=now_wall,
            deadline=now + expire_in,
        )
        self._sessions[session_id] = session
        return _start_payload(session)

    def poll(self, session_id: str) -> dict[str, Any]:
        self._cleanup()
        session = self._sessions.get(session_id)
        if session is None:
            return {
                "session_id": session_id,
                "status": "expired",
                "message": "This Feishu connection has expired. Start again.",
            }

        if time.monotonic() >= session.deadline:
            self._sessions.pop(session_id, None)
            return {
                "session_id": session_id,
                "status": "expired",
                "message": "This Feishu connection has expired. Start again.",
            }

        try:
            result = feishu.poll_registration_once(
                device_code=session.device_code,
                domain=session.domain,
            )
        except (RuntimeError, OSError, json.JSONDecodeError, httpx.HTTPError) as exc:
            session.last_error = str(exc)
            return _pending_payload(session)

        session.domain = str(result.get("domain") or session.domain)
        status = result.get("status")
        if status == "succeeded":
            session.instance_id = feishu.save_registration_result(
                result,
                instance_id=session.instance_id,
                name=session.instance_name,
            )
            self._sessions.pop(session_id, None)
            return {
                "session_id": session_id,
                "instance_id": session.instance_id,
                "status": "succeeded",
                "message": "Feishu is connected.",
                "domain": session.domain,
                "app_id": result.get("app_id"),
            }

        if status == "failed":
            self._sessions.pop(session_id, None)
            return {
                "session_id": session_id,
                "instance_id": session.instance_id,
                "status": "failed",
                "message": "Authorization was cancelled or expired.",
                "domain": session.domain,
            }

        return _pending_payload(session)

    def cancel(self, session_id: str) -> dict[str, Any]:
        session = self._sessions.pop(session_id, None)
        return {
            "session_id": session_id,
            "instance_id": session.instance_id if session else DEFAULT_INSTANCE_ID,
            "status": "cancelled",
            "message": "Feishu connection cancelled.",
        }

    def _cleanup(self) -> None:
        now = time.monotonic()
        expired = [session_id for session_id, session in self._sessions.items() if now >= session.deadline]
        for session_id in expired:
            self._sessions.pop(session_id, None)


def _normalize_domain(domain: str) -> str:
    normalized = domain.strip().lower()
    return normalized if normalized in {"feishu", "lark"} else "feishu"


def _resolve_instance_id(instance_id: str, mode: str) -> str:
    if mode == "create":
        return f"assistant-{secrets.token_hex(3)}"
    try:
        return validate_instance_id(instance_id or DEFAULT_INSTANCE_ID)
    except ValueError as exc:
        raise ChannelConnectError(str(exc), status=400) from exc


def _default_instance_name(instance_id: str) -> str:
    return "nanobot" if instance_id == DEFAULT_INSTANCE_ID else f"nanobot {instance_id}"


def _start_payload(session: FeishuConnectSession) -> dict[str, Any]:
    return {
        "session_id": session.id,
        "instance_id": session.instance_id,
        "status": "pending",
        "qr_url": session.qr_url,
        "domain": session.domain,
        "interval_ms": session.interval * 1000,
        "expires_at_ms": int((session.created_wall + session.expire_in) * 1000),
        "message": "Scan with Feishu or Lark to connect.",
    }


def _pending_payload(session: FeishuConnectSession) -> dict[str, Any]:
    return {
        "session_id": session.id,
        "instance_id": session.instance_id,
        "status": "pending",
        "domain": session.domain,
        "interval_ms": session.interval * 1000,
        "expires_at_ms": int((session.created_wall + session.expire_in) * 1000),
        "message": "Waiting for authorization.",
    }
