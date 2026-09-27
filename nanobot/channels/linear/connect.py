"""WebUI OAuth connection flow for Linear workspace installations."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, cast

from nanobot.channels.connect import ChannelConnectError, QueryParams, query_first
from nanobot.channels.linear.access import member_allowed
from nanobot.channels.linear.client import LinearApiError, LinearClient
from nanobot.channels.linear.config import LinearConfig
from nanobot.channels.linear.oauth import (
    FLOW_TTL_SECONDS,
    LINEAR_SCOPES,
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
    result: dict[str, Any] | None = None


class LinearConnectStore:
    """Keep short-lived OAuth browser sessions in the gateway process."""

    def __init__(self) -> None:
        self._sessions: dict[str, LinearConnectSession] = {}

    async def handle(self, action: str, query: QueryParams) -> dict[str, Any]:
        await self._cleanup()
        if action == "start":
            operation = (query_first(query, "operation") or "connect").strip().lower()
            if operation == "inspect":
                return self.inspect()
            if operation == "workspace_profile":
                organization_id = (query_first(query, "organization_id") or "").strip()
                if not organization_id:
                    raise ChannelConnectError("missing Linear workspace")
                return await self.workspace_profile(organization_id)
            if operation == "disconnect":
                organization_id = (query_first(query, "organization_id") or "").strip()
                if not organization_id:
                    raise ChannelConnectError("missing Linear workspace")
                return await self.disconnect(organization_id)
            if operation in {"members", "member_access"}:
                organization_id = (query_first(query, "organization_id") or "").strip()
                if not organization_id:
                    raise ChannelConnectError("missing Linear workspace")
                user_id: str | None = None
                allowed: bool | None = None
                if operation == "member_access":
                    user_id = (query_first(query, "user_id") or "").strip()
                    raw_allowed = query_first(query, "allowed")
                    if not user_id or raw_allowed not in {"true", "false"}:
                        raise ChannelConnectError("member access requires a user ID and true/false")
                    allowed = raw_allowed == "true"
                return await self.members(organization_id, user_id=user_id, allowed=allowed)
            if operation != "connect":
                raise ChannelConnectError(f"unsupported Linear connect operation: {operation}")
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
                "installations": _installation_payloads(state, config.client_id),
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
            if session.result is not None:
                return dict(session.result)
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
            session.result = {
                "session_id": session_id,
                "status": "succeeded",
                "message": "Linear is connected.",
                "organization_id": installation.organization_id,
                "organization_name": installation.organization_name,
                "installations": _installation_payloads(session.state, session.config.client_id),
            }
            # A browser may miss the first successful poll while switching tabs.
            # Retain its result until the session expires, but release the callback listener.
            OAUTH_FLOWS.remove(flow)
            await asyncio.to_thread(session.server.close)
            return dict(session.result)

    async def cancel(self, session_id: str) -> dict[str, Any]:
        session = self._sessions.get(session_id)
        if session is not None:
            async with session.completion_lock:
                await self._close_session(session_id)
        return _terminal(session_id, "cancelled", "Linear authorization cancelled.")

    def inspect(self) -> dict[str, Any]:
        config = _load_linear_config()
        state = LinearStateStore()
        installations = (
            _installation_payloads(state, config.client_id) if config.client_id else []
        )
        return {
            "session_id": "",
            "status": "inspected",
            "message": (
                f"{len(installations)} Linear workspace(s) authorized."
                if installations
                else "No Linear workspaces are authorized."
            ),
            "installations": installations,
            "webhook_url": config.webhook_url if config.public_base_url else "",
            "redirect_uri": config.redirect_uri if config.public_base_url else "",
        }

    async def workspace_profile(self, organization_id: str) -> dict[str, Any]:
        config = _load_linear_config()
        state = LinearStateStore()
        installation = state.installation(organization_id)
        if installation is None or installation.oauth_client_id != config.client_id:
            raise ChannelConnectError("Linear workspace is not connected", status=404)
        client = LinearClient(config, state)
        try:
            profile = await client.workspace_profile(organization_id)
        except LinearApiError as exc:
            raise ChannelConnectError("Unable to read Linear workspace profile", status=502) from exc
        finally:
            await client.close()
        return {"session_id": "", "status": "workspace_profile", **profile}

    async def members(
        self, organization_id: str, *, user_id: str | None = None, allowed: bool | None = None,
    ) -> dict[str, Any]:
        config = _load_linear_config()
        state = LinearStateStore()
        installation = state.installation(organization_id)
        if installation is None or installation.oauth_client_id != config.client_id:
            raise ChannelConnectError("Linear workspace is not connected", status=404)
        client = LinearClient(config, state)
        try:
            members = await client.list_members(organization_id, user_id=user_id)
        except LinearApiError as exc:
            raise ChannelConnectError(f"Unable to read Linear members: {exc}", status=502) from exc
        finally:
            await client.close()
        if user_id is not None and allowed is not None:
            if not any(member["id"] == user_id for member in members):
                raise ChannelConnectError("Member is not active in an accessible Linear team", status=404)
            try:
                state.set_member_access(config.client_id, organization_id, user_id, allowed=allowed)
            except ValueError as exc:
                raise ChannelConnectError(str(exc), status=409) from exc
        return {
            "session_id": "",
            "status": "members" if allowed is None else "member_access_saved",
            "organization_id": organization_id,
            "legacy_allow_all": "*" in config.allow_from,
            "members": [
                {**member, "allowed": member_allowed(config, state, organization_id, member["id"])}
                for member in members
            ],
        }

    async def disconnect(self, organization_id: str) -> dict[str, Any]:
        config = _load_linear_config()
        state = LinearStateStore()
        installation = state.installation(organization_id)
        if installation is None or installation.oauth_client_id != config.client_id:
            raise ChannelConnectError("Linear workspace is not connected", status=404)
        client = LinearClient(config, state)
        try:
            await client.revoke_installation(installation)
        except LinearApiError as exc:
            raise ChannelConnectError(
                f"Unable to revoke the Linear workspace authorization: {exc}",
                status=502,
            ) from exc
        finally:
            await client.close()
        removed = state.delete_installation(organization_id, expected=installation)
        if not removed and state.installation(organization_id) is not None:
            raise ChannelConnectError(
                "Linear workspace authorization changed while disconnecting. Refresh and try again.",
                status=409,
            )
        installations = _installation_payloads(state, config.client_id)
        return {
            "session_id": "",
            "status": "disconnected",
            "message": f"Disconnected {installation.organization_name or organization_id}.",
            "organization_id": organization_id,
            "installations": installations,
        }

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


def _installation_payloads(
    state: LinearStateStore,
    oauth_client_id: str | None,
) -> list[dict[str, Any]]:
    now = time.time()
    payloads: list[dict[str, Any]] = []
    for installation in state.list_installations(oauth_client_id):
        missing_scopes = sorted(set(LINEAR_SCOPES) - set(installation.scope))
        payloads.append({
            "organization_id": installation.organization_id,
            "organization_name": installation.organization_name,
            "scopes": list(installation.scope),
            "authorization_status": (
                "missing_scopes"
                if missing_scopes
                else "refresh_required"
                if installation.expires_at <= now + 60
                else "authorized"
            ),
            "missing_scopes": missing_scopes,
        })
    return payloads
