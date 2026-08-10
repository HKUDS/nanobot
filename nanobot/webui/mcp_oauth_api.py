"""Gateway-owned browser authorization flows for remote MCP servers."""

from __future__ import annotations

import asyncio
import re
import secrets
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import SplitResult, parse_qs, urlsplit, urlunsplit

from nanobot.agent.tools.mcp import MCPConnection, connect_mcp_servers
from nanobot.agent.tools.mcp_oauth import MCP_OAUTH_CALLBACK_PATH, MCPOAuthHandlers
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.schema import MCPServerConfig
from nanobot.security.network import validate_url_target
from nanobot.webui.http_utils import is_loopback_host

McpReload = Callable[[], Awaitable[dict[str, Any]]]
_FLOW_TTL_S = 300
_START_WAIT_S = 20
_OAUTH_ERROR_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,80}$")


class McpOAuthError(Exception):
    """Safe WebUI error for an MCP OAuth request."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


class _OAuthCallbackError(RuntimeError):
    pass


@dataclass
class _McpOAuthFlow:
    flow_id: str
    name: str
    cfg: MCPServerConfig
    redirect_uri: str
    manual_callback: bool
    expires_at: float
    authorization_ready: asyncio.Event = field(default_factory=asyncio.Event)
    callback_result: asyncio.Future[tuple[str, str | None]] | None = None
    task: asyncio.Task[bool] | None = None
    authorization_url: str | None = None
    state: str | None = None
    callback_received: bool = False
    error: str | None = None
    reload_result: dict[str, Any] | None = None


def _parse_mcp_oauth_redirect_uri(redirect_uri: str) -> tuple[str, SplitResult, int | None]:
    cleaned = redirect_uri.strip()
    parsed = urlsplit(cleaned)
    try:
        port = parsed.port
    except ValueError as exc:
        raise McpOAuthError("Invalid MCP OAuth callback URL") from exc
    if (
        not parsed.netloc
        or not parsed.hostname
        or parsed.path != MCP_OAUTH_CALLBACK_PATH
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise McpOAuthError("Invalid MCP OAuth callback URL")
    return cleaned, parsed, port


def validate_mcp_oauth_redirect_uri(redirect_uri: str) -> str:
    """Allow HTTPS callbacks, plus loopback HTTP for a local gateway."""
    cleaned, parsed, _port = _parse_mcp_oauth_redirect_uri(redirect_uri)
    if parsed.scheme == "https":
        return cleaned
    if parsed.scheme == "http" and is_loopback_host(parsed.netloc):
        return cleaned
    raise McpOAuthError("MCP OAuth callbacks must use HTTPS or localhost")


def prepare_mcp_oauth_redirect_uri(redirect_uri: str) -> tuple[str, bool]:
    """Use a pasteable loopback callback when a remote WebUI is served over HTTP."""
    cleaned, parsed, port = _parse_mcp_oauth_redirect_uri(redirect_uri)
    if parsed.scheme != "http" or is_loopback_host(parsed.netloc):
        return validate_mcp_oauth_redirect_uri(cleaned), False

    loopback = "127.0.0.1" if port is None else f"127.0.0.1:{port}"
    manual_redirect_uri = urlunsplit(("http", loopback, parsed.path, "", ""))
    return validate_mcp_oauth_redirect_uri(manual_redirect_uri), True


class McpOAuthManager:
    """Own short-lived browser flows while the gateway process is running."""

    def __init__(self) -> None:
        self._flows: dict[str, _McpOAuthFlow] = {}
        self._states: dict[str, str] = {}

    async def start(
        self,
        name: str,
        cfg: MCPServerConfig,
        redirect_uri: str,
        *,
        reload_mcp: McpReload,
        reset_credentials: bool = False,
    ) -> dict[str, Any]:
        self._prune()
        redirect_uri, manual_callback = prepare_mcp_oauth_redirect_uri(redirect_uri)
        await self._cancel_name(name)

        loop = asyncio.get_running_loop()
        now = time.monotonic()
        flow = _McpOAuthFlow(
            flow_id=secrets.token_urlsafe(24),
            name=name,
            cfg=cfg,
            redirect_uri=redirect_uri,
            manual_callback=manual_callback,
            expires_at=now + _FLOW_TTL_S,
            callback_result=loop.create_future(),
        )
        self._flows[flow.flow_id] = flow
        handlers = MCPOAuthHandlers(
            redirect_uri=redirect_uri,
            redirect_handler=lambda url: self._receive_authorization_url(flow, url),
            callback_handler=lambda: self._wait_for_callback(flow),
            reset_credentials=reset_credentials,
        )
        flow.task = asyncio.create_task(
            self._connect_and_reload(flow, handlers, reload_mcp),
            name=f"mcp-oauth:{name}",
        )

        ready_waiter = asyncio.create_task(flow.authorization_ready.wait())
        try:
            await asyncio.wait(
                {ready_waiter, flow.task},
                timeout=_START_WAIT_S,
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            ready_waiter.cancel()
            with suppress(asyncio.CancelledError):
                await ready_waiter
        return self._payload(flow)

    async def status(self, flow_id: str) -> dict[str, Any]:
        self._prune()
        flow = self._flow(flow_id)
        return self._payload(flow)

    def submit_callback(
        self,
        *,
        state: str,
        code: str | None,
        error: str | None,
    ) -> str:
        self._prune()
        flow_id = self._states.pop(state, None)
        if flow_id is None:
            raise McpOAuthError("This MCP authorization request has expired", status=410)
        flow = self._flow(flow_id)
        callback_result = flow.callback_result
        if callback_result is None or callback_result.done():
            raise McpOAuthError("This MCP authorization callback was already used", status=409)

        flow.callback_received = True
        if error:
            safe_error = error if _OAUTH_ERROR_RE.fullmatch(error) else "authorization_failed"
            flow.error = f"Authorization was not completed ({safe_error})."
            callback_result.set_exception(_OAuthCallbackError(flow.error))
            raise McpOAuthError(flow.error)
        elif not code or len(code) > 8192:
            flow.error = "The MCP server did not return an authorization code."
            callback_result.set_exception(_OAuthCallbackError(flow.error))
            raise McpOAuthError(flow.error)
        else:
            callback_result.set_result((code, state))
        return flow.name

    def submit_callback_url(self, *, flow_id: str, callback_url: str) -> dict[str, Any]:
        """Complete a flow from a full browser callback URL pasted into the WebUI."""
        self._prune()
        flow = self._flow(flow_id)
        parsed = urlsplit(callback_url.strip())
        expected = urlsplit(flow.redirect_uri)
        if (
            not parsed.query
            or parsed.fragment
            or parsed.username is not None
            or parsed.password is not None
            or parsed.scheme != expected.scheme
            or parsed.netloc != expected.netloc
            or parsed.path != expected.path
        ):
            raise McpOAuthError(
                "Paste the complete callback URL from the browser address bar."
            )
        try:
            query = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=16)
        except ValueError as exc:
            raise McpOAuthError(
                "Paste the complete callback URL from the browser address bar."
            ) from exc

        states = query.get("state", [])
        state = states[0] if len(states) == 1 else ""
        if not state or state != flow.state:
            raise McpOAuthError(
                "This callback belongs to a different or expired authorization request. "
                "Start again.",
                status=410,
            )

        codes = query.get("code", [])
        errors = query.get("error", [])
        if len(codes) > 1 or len(errors) > 1 or (codes and errors):
            raise McpOAuthError(
                "Paste the complete callback URL from the browser address bar."
            )
        code = codes[0] if len(codes) == 1 else None
        error = errors[0] if len(errors) == 1 else None
        if (not code and not error) or (code is not None and len(code) > 8192):
            raise McpOAuthError(
                "Paste the complete callback URL from the browser address bar."
            )

        self.submit_callback(state=state, code=code, error=error)
        return self._payload(flow)

    async def cancel(self, flow_id: str) -> dict[str, Any]:
        self._prune()
        flow = self._flow(flow_id)
        await self._cancel_flow(flow)
        return self._payload(flow)

    async def _receive_authorization_url(
        self,
        flow: _McpOAuthFlow,
        authorization_url: str,
    ) -> None:
        parsed = urlsplit(authorization_url)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            flow.error = "The MCP server returned an unsafe authorization URL."
            raise McpOAuthError(flow.error)
        ok, _error = validate_url_target(authorization_url)
        if not ok:
            flow.error = "The MCP server returned an unsafe authorization URL."
            raise McpOAuthError(flow.error)
        states = parse_qs(parsed.query).get("state", [])
        state = states[0] if len(states) == 1 else ""
        if not state or len(state) > 512:
            flow.error = "The MCP server returned an invalid authorization URL."
            raise McpOAuthError(flow.error)
        if state in self._states:
            flow.error = "The MCP server reused an OAuth state value."
            raise McpOAuthError(flow.error)
        flow.authorization_url = authorization_url
        flow.state = state
        self._states[state] = flow.flow_id
        flow.authorization_ready.set()

    async def _wait_for_callback(self, flow: _McpOAuthFlow) -> tuple[str, str | None]:
        callback_result = flow.callback_result
        if callback_result is None:
            raise _OAuthCallbackError("MCP OAuth callback is unavailable")
        remaining = max(0.1, flow.expires_at - time.monotonic())
        try:
            return await asyncio.wait_for(asyncio.shield(callback_result), timeout=remaining)
        except asyncio.TimeoutError as exc:
            flow.error = "MCP authorization timed out."
            raise _OAuthCallbackError(flow.error) from exc

    async def _connect(self, flow: _McpOAuthFlow, handlers: MCPOAuthHandlers) -> bool:
        connections: dict[str, MCPConnection] = {}
        try:
            connections = await connect_mcp_servers(
                {flow.name: flow.cfg},
                ToolRegistry(),
                oauth_handlers={flow.name: handlers},
            )
            succeeded = flow.name in connections
            if not succeeded and flow.error is None:
                flow.error = "Could not complete the MCP OAuth connection."
            return succeeded
        except asyncio.CancelledError:
            raise
        except Exception:
            if flow.error is None:
                flow.error = "Could not complete the MCP OAuth connection."
            return False
        finally:
            for connection in connections.values():
                with suppress(Exception):
                    await connection.aclose()

    async def _connect_and_reload(
        self,
        flow: _McpOAuthFlow,
        handlers: MCPOAuthHandlers,
        reload_mcp: McpReload,
    ) -> bool:
        succeeded = await self._connect(flow, handlers)
        if not succeeded:
            return False
        try:
            flow.reload_result = await reload_mcp()
            failed = flow.reload_result.get("failed")
            if (
                not flow.reload_result.get("ok")
                and not flow.reload_result.get("requires_restart")
                and isinstance(failed, list)
                and flow.name in failed
            ):
                flow.reload_result = await reload_mcp()
        except Exception:
            flow.reload_result = {
                "ok": False,
                "message": "Signed in, but nanobot could not activate the MCP tools.",
                "requires_restart": True,
            }
        return True

    def _flow(self, flow_id: str) -> _McpOAuthFlow:
        flow = self._flows.get(flow_id)
        if flow is None:
            raise McpOAuthError("Unknown or expired MCP OAuth flow", status=404)
        return flow

    def _payload(self, flow: _McpOAuthFlow) -> dict[str, Any]:
        task = flow.task
        connected = flow.reload_result.get("connected") if flow.reload_result is not None else None
        if task is not None and task.cancelled():
            status = "cancelled"
        elif task is not None and task.done():
            try:
                succeeded = task.result()
            except Exception:
                succeeded = False
            if not succeeded:
                status = "failed"
            elif flow.reload_result is None:
                status = "authorized"
            elif flow.reload_result.get("ok") or (
                isinstance(connected, list) and flow.name in connected
            ):
                status = "connected"
            else:
                status = "authorized"
        elif flow.callback_received:
            status = "connecting"
        elif flow.authorization_url:
            status = "authorization_required"
        else:
            status = "starting"

        payload: dict[str, Any] = {
            "flow_id": flow.flow_id,
            "name": flow.name,
            "status": status,
            "expires_in": max(0, int(flow.expires_at - time.monotonic())),
        }
        if flow.manual_callback:
            payload["completion_input"] = "callback_url"
        if flow.authorization_url and status == "authorization_required":
            payload["authorization_url"] = flow.authorization_url
        if flow.error:
            payload["error"] = flow.error
        if flow.reload_result is not None:
            payload["hot_reload"] = flow.reload_result
        return payload

    async def _cancel_name(self, name: str) -> None:
        for flow in list(self._flows.values()):
            if flow.name == name and flow.task is not None and not flow.task.done():
                await self._cancel_flow(flow)

    async def _cancel_flow(self, flow: _McpOAuthFlow) -> None:
        if flow.state:
            self._states.pop(flow.state, None)
        task = flow.task
        if task is not None and not task.done():
            task.cancel()
            with suppress(BaseException):
                await task

    def _prune(self) -> None:
        now = time.monotonic()
        for flow_id, flow in list(self._flows.items()):
            if flow.expires_at > now:
                continue
            if flow.state:
                self._states.pop(flow.state, None)
            if flow.task is not None and not flow.task.done():
                flow.task.cancel()
            callback_result = flow.callback_result
            if callback_result is not None and not callback_result.done():
                callback_result.cancel()
            self._flows.pop(flow_id, None)
