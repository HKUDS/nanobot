"""WeChat-owned interactive connection flow."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from nanobot.channels.connect import ChannelConnectError, QueryParams, query_first
from nanobot.config.loader import load_config

if TYPE_CHECKING:
    from nanobot.channels.weixin.runtime import WeixinChannel


@dataclass(slots=True)
class WeixinConnectSession:
    id: str
    qrcode_id: str
    qr_url: str
    channel: WeixinChannel
    current_poll_base_url: str
    refresh_count: int
    force: bool
    created_wall: float
    deadline: float
    last_error: str | None = None


class WeixinConnectStore:
    """In-memory WeChat QR login sessions for the WebUI."""

    def __init__(self) -> None:
        self._sessions: dict[str, WeixinConnectSession] = {}

    async def handle(self, action: str, query: QueryParams) -> dict[str, Any]:
        """Handle one generic settings connection action."""
        if action == "start":
            force = (query_first(query, "force") or "").strip().lower() in {
                "1",
                "true",
                "yes",
            }
            return await self.start(force=force)

        session_id = (query_first(query, "session_id") or "").strip()
        if not session_id:
            raise ChannelConnectError("missing WeChat connect session")
        if action == "poll":
            return await self.poll(
                session_id,
                verify_code=(query_first(query, "verify_code") or "").strip(),
            )
        if action == "cancel":
            return await self.cancel(session_id)
        raise ChannelConnectError(f"unsupported WeChat connect action: {action}", status=404)

    async def start(self, *, force: bool = False) -> dict[str, Any]:
        await self._cleanup()

        channel = self._build_channel()
        if force:
            # Preserve the working account until a replacement scan succeeds.
            channel.connect_reset_pending_credentials()
        elif channel.connect_load_state():
            return {
                "session_id": "",
                "status": "succeeded",
                "message": "WeChat is already connected.",
                "interval_ms": 2000,
            }

        channel.connect_open_client()
        try:
            qrcode_id, qr_url = await channel.connect_fetch_qr_code(force=force)
        except Exception as exc:
            await self._close_channel(channel)
            raise ChannelConnectError(
                f"Unable to start WeChat QR login: {exc}",
                status=502,
            ) from exc

        session_id = secrets.token_urlsafe(18)
        now_wall = time.time()
        self._sessions[session_id] = WeixinConnectSession(
            id=session_id,
            qrcode_id=qrcode_id,
            qr_url=qr_url,
            channel=channel,
            current_poll_base_url=channel.connect_base_url,
            refresh_count=0,
            force=force,
            created_wall=now_wall,
            deadline=time.monotonic() + 600,
        )
        return self._start_payload(self._sessions[session_id])

    async def poll(self, session_id: str, *, verify_code: str = "") -> dict[str, Any]:
        await self._cleanup()
        session = self._sessions.get(session_id)
        if session is None:
            return {
                "session_id": session_id,
                "status": "expired",
                "message": "This WeChat login has expired. Start again.",
            }

        try:
            status_data = await session.channel.connect_poll_qr_code(
                base_url=session.current_poll_base_url,
                qrcode_id=session.qrcode_id,
                verify_code=verify_code,
            )
        except Exception as exc:
            if session.channel.connect_poll_error_is_retryable(exc):
                session.last_error = str(exc)
                return self._pending_payload(session)
            self._sessions.pop(session_id, None)
            await self._close_channel(session.channel)
            return {
                "session_id": session_id,
                "status": "failed",
                "message": f"WeChat QR login failed: {exc}",
            }

        status_payload = status_data
        status = status_payload.get("status", "")
        from nanobot.channels.weixin.runtime import MAX_QR_REFRESH_COUNT

        if status == "confirmed":
            if self._sessions.get(session_id) is not session:
                return {
                    "session_id": session_id,
                    "status": "cancelled",
                    "message": "WeChat login cancelled.",
                }
            token = str(status_payload.get("bot_token", "") or "")
            if not token:
                self._sessions.pop(session_id, None)
                await self._close_channel(session.channel)
                return {
                    "session_id": session_id,
                    "status": "failed",
                    "message": "WeChat confirmed the scan but returned no token.",
                }
            base_url = str(status_payload.get("baseurl", "") or "")
            session.channel.connect_commit_account(token=token, base_url=base_url)
            self._sessions.pop(session_id, None)
            await self._close_channel(session.channel)
            return {
                "session_id": session_id,
                "status": "succeeded",
                "message": "WeChat is connected.",
                "account": str(status_payload.get("ilink_user_id", "") or ""),
            }

        if status == "scaned_but_redirect":
            redirect_host = str(status_payload.get("redirect_host", "") or "").strip()
            if redirect_host:
                session.current_poll_base_url = (
                    redirect_host
                    if redirect_host.startswith(("http://", "https://"))
                    else f"https://{redirect_host}"
                )
            return self._pending_payload(session)

        if status == "need_verifycode":
            return self._pending_payload(
                session,
                challenge="verify_code",
                message=(
                    "That verification code did not match. Enter the new number shown in WeChat."
                    if verify_code
                    else "Enter the number shown in WeChat to continue."
                ),
                verification_failed=bool(verify_code),
            )

        if status == "verify_code_blocked":
            session.refresh_count += 1
            if session.refresh_count > MAX_QR_REFRESH_COUNT:
                self._sessions.pop(session_id, None)
                await self._close_channel(session.channel)
                return {
                    "session_id": session_id,
                    "status": "failed",
                    "message": "Too many incorrect verification attempts. Try again later.",
                }
            try:
                session.qrcode_id, session.qr_url = (
                    await session.channel.connect_fetch_qr_code(force=session.force)
                )
            except Exception as exc:
                self._sessions.pop(session_id, None)
                await self._close_channel(session.channel)
                return {
                    "session_id": session_id,
                    "status": "failed",
                    "message": f"Could not refresh WeChat QR code: {exc}",
                }
            session.current_poll_base_url = session.channel.connect_base_url
            return self._pending_payload(
                session,
                message="Verification was blocked. Scan the refreshed QR code to try again.",
            )

        if status == "binded_redirect":
            if session.force:
                self._sessions.pop(session_id, None)
                await self._close_channel(session.channel)
                return {
                    "session_id": session_id,
                    "status": "failed",
                    "message": (
                        "Unable to complete a new WeChat login. "
                        "Start again and scan with the account you want to connect."
                    ),
                }
            if not session.channel.connect_load_state():
                self._sessions.pop(session_id, None)
                await self._close_channel(session.channel)
                return {
                    "session_id": session_id,
                    "status": "failed",
                    "message": (
                        "WeChat reports an existing binding, but no local credentials were found."
                    ),
                }
            self._sessions.pop(session_id, None)
            await self._close_channel(session.channel)
            return {
                "session_id": session_id,
                "status": "succeeded",
                "message": "WeChat is already connected to this nanobot instance.",
            }

        if status == "expired":
            session.refresh_count += 1
            if session.refresh_count > MAX_QR_REFRESH_COUNT:
                self._sessions.pop(session_id, None)
                await self._close_channel(session.channel)
                return {
                    "session_id": session_id,
                    "status": "expired",
                    "message": "This WeChat QR code expired. Start again.",
                }
            try:
                session.qrcode_id, session.qr_url = (
                    await session.channel.connect_fetch_qr_code(force=session.force)
                )
            except Exception as exc:
                self._sessions.pop(session_id, None)
                await self._close_channel(session.channel)
                return {
                    "session_id": session_id,
                    "status": "failed",
                    "message": f"Could not refresh WeChat QR code: {exc}",
                }
            session.current_poll_base_url = session.channel.connect_base_url
            return self._pending_payload(session)

        return self._pending_payload(session)

    async def cancel(self, session_id: str) -> dict[str, Any]:
        session = self._sessions.pop(session_id, None)
        if session is not None:
            await self._close_channel(session.channel)
        return {
            "session_id": session_id,
            "status": "cancelled",
            "message": "WeChat login cancelled.",
        }

    async def _cleanup(self) -> None:
        now = time.monotonic()
        expired = [
            session_id
            for session_id, session in self._sessions.items()
            if now >= session.deadline
        ]
        for session_id in expired:
            session = self._sessions.pop(session_id, None)
            if session is not None:
                await self._close_channel(session.channel)

    @staticmethod
    def _build_channel() -> WeixinChannel:
        from nanobot.bus.queue import MessageBus
        from nanobot.channels.weixin.runtime import WeixinChannel

        section = getattr(load_config().channels, "weixin", None)
        if section is not None and hasattr(section, "model_dump"):
            config = section.model_dump(mode="json", by_alias=True)
        elif isinstance(section, dict):
            config = dict(cast(dict[str, Any], section))
        else:
            config = {}
        return WeixinChannel(config, MessageBus())

    @staticmethod
    async def _close_channel(channel: WeixinChannel) -> None:
        await channel.connect_close_client()

    @staticmethod
    def _start_payload(session: WeixinConnectSession) -> dict[str, Any]:
        return {
            "session_id": session.id,
            "status": "pending",
            "qr_url": session.qr_url,
            "interval_ms": 2000,
            "expires_at_ms": int((session.created_wall + 600) * 1000),
            "message": "Scan with WeChat to connect.",
        }

    @staticmethod
    def _pending_payload(
        session: WeixinConnectSession,
        *,
        challenge: str = "",
        message: str = "Waiting for WeChat scan.",
        verification_failed: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "session_id": session.id,
            "status": "pending",
            "qr_url": session.qr_url,
            "interval_ms": 2000,
            "expires_at_ms": int((session.created_wall + 600) * 1000),
            "message": message,
        }
        if challenge:
            payload["challenge"] = challenge
            payload["verification_failed"] = verification_failed
        return payload


__all__ = ["WeixinConnectStore"]
