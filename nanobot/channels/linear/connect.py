"""WebUI OAuth connection flow for Linear workspace installations."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, cast

from nanobot.channels.connect import ChannelConnectError, QueryParams, query_first
from nanobot.channels.linear.client import LinearApiError, LinearClient
from nanobot.channels.linear.config import LinearConfig
from nanobot.channels.linear.oauth import (
    FLOW_TTL_SECONDS,
    OAUTH_FLOWS,
    LinearOAuthFlow,
    authorization_url,
)
from nanobot.channels.linear.server import LinearServerLease, acquire_http_server
from nanobot.channels.linear.state import LinearStateStore
from nanobot.config.loader import load_config


@dataclass(slots=True)
class LinearConnectSession:
    flow: LinearOAuthFlow
    config: LinearConfig
    state: LinearStateStore
    server: LinearServerLease
    completion_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)


class LinearConnectStore:
    """Keep short-lived OAuth browser sessions in the gateway process."""

    def __init__(self) -> None:
        self._sessions: dict[str, LinearConnectSession] = {}

    async def handle(self, action: str, query: QueryParams) -> dict[str, Any]:
        await self._cleanup()
        if action == "start":
            return await self.start(force=_query_bool(query, "force"))
        session_id = (query_first(query, "session_id") or "").strip()
        if not session_id:
            raise ChannelConnectError("missing Linear connect session")
        if action == "poll":
            return await self.poll(session_id)
        if action == "cancel":
            return await self.cancel(session_id)
        raise ChannelConnectError(f"unsupported Linear connect action: {action}", status=404)

    async def start(self, *, force: bool = False) -> dict[str, Any]:
        config = _load_linear_config()
        try:
            config.validate_runtime()
        except ValueError as exc:
            raise ChannelConnectError(str(exc)) from exc
        state = LinearStateStore()
        if state.has_installations(config.client_id) and not force:
            return {
                "session_id": "",
                "status": "succeeded",
                "message": "Linear is already connected. Use reconnect to add or replace a workspace.",
            }
        flow = OAUTH_FLOWS.create()
        try:
            lease = await asyncio.to_thread(acquire_http_server, config, state)
        except (OSError, RuntimeError) as exc:
            OAUTH_FLOWS.remove(flow)
            raise ChannelConnectError(
                f"Unable to start the Linear callback listener on {config.host}:{config.port}: {exc}",
                status=502,
            ) from exc
        self._sessions[flow.session_id] = LinearConnectSession(
            flow=flow,
            config=config,
            state=state,
            server=lease,
        )
        return {
            "session_id": flow.session_id,
            "status": "pending",
            "authorization_url": authorization_url(config, flow),
            "qr_url": authorization_url(config, flow),
            "redirect_uri": config.redirect_uri,
            "webhook_url": config.webhook_url,
            "interval_ms": 1500,
            "expires_at_ms": int((flow.created_at + FLOW_TTL_SECONDS) * 1000),
            "message": "Authorize the nanobot app in Linear.",
        }

    async def poll(self, session_id: str) -> dict[str, Any]:
        session = self._sessions.get(session_id)
        if session is None:
            return _terminal(session_id, "expired", "This Linear authorization has expired.")
        async with session.completion_lock:
            if self._sessions.get(session_id) is not session:
                return _terminal(session_id, "cancelled", "Linear authorization cancelled.")
            flow = session.flow
            if time.monotonic() >= flow.deadline:
                await self._close_session(session_id)
                return _terminal(session_id, "expired", "This Linear authorization has expired.")
            if flow.error:
                message = "Linear authorization was cancelled."
                await self._close_session(session_id)
                return _terminal(session_id, "failed", message)
            if not flow.code:
                return {
                    "session_id": session_id,
                    "status": "pending",
                    "interval_ms": 1500,
                    "expires_at_ms": int((flow.created_at + FLOW_TTL_SECONDS) * 1000),
                    "message": "Waiting for Linear authorization.",
                }

            client = LinearClient(session.config, session.state)
            try:
                installation = await client.exchange_code(flow.code, flow.verifier)
            except LinearApiError as exc:
                await self._close_session(session_id)
                return _terminal(
                    session_id,
                    "failed",
                    f"Linear authorization could not be completed: {exc}",
                )
            finally:
                await client.close()
            await self._close_session(session_id)
            return {
                "session_id": session_id,
                "status": "succeeded",
                "message": "Linear is connected.",
                "organization_id": installation.organization_id,
                "organization_name": installation.organization_name,
            }

    async def cancel(self, session_id: str) -> dict[str, Any]:
        session = self._sessions.get(session_id)
        if session is not None:
            async with session.completion_lock:
                await self._close_session(session_id)
        return _terminal(session_id, "cancelled", "Linear authorization cancelled.")

    async def _cleanup(self) -> None:
        expired = [
            session_id
            for session_id, session in self._sessions.items()
            if time.monotonic() >= session.flow.deadline
        ]
        for session_id in expired:
            await self.cancel(session_id)

    async def _close_session(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return
        OAUTH_FLOWS.remove(session.flow)
        await asyncio.to_thread(session.server.close)


def _load_linear_config() -> LinearConfig:
    config = load_config()
    extras: dict[str, Any] = config.channels.model_extra or {}
    raw: object = extras.get("linear", {})
    if not isinstance(raw, dict):
        raw = {}
    return LinearConfig.model_validate(cast(dict[str, Any], raw))


def _query_bool(query: QueryParams, key: str) -> bool:
    return (query_first(query, key) or "").strip().lower() in {"1", "true", "yes"}


def _terminal(session_id: str, status: str, message: str) -> dict[str, Any]:
    return {"session_id": session_id, "status": status, "message": message}
