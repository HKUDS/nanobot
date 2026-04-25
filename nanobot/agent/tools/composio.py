"""Composio user connection tools."""

from __future__ import annotations

import asyncio
import json
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import BooleanSchema, StringSchema, tool_parameters_schema
from nanobot.bus.events import OutboundMessage
from nanobot.config.schema import ComposioToolConfig

_TOOL_ROUTER_SESSION_FILE = "composio-tool-router-session.json"


@tool_parameters(
    tool_parameters_schema(
        toolkit=StringSchema(
            "Toolkit/app slug to connect, such as gmail, googlecalendar, google_calendar, notion, or github. "
            "The tool will find or create a Composio managed auth config when no explicit auth_config_id is provided."
        ),
        auth_config_id=StringSchema(
            "Optional Composio auth config id. Use only when the toolkit is not mapped in config.",
        ),
        callback_url=StringSchema("Optional callback URL after Composio auth completes."),
        alias=StringSchema("Optional human-readable alias for this connected account."),
        wait_for_connection=BooleanSchema(
            description="Whether to watch this connection and text the user when it becomes active.",
            default=True,
        ),
    )
)
class ComposioConnectTool(Tool):
    """Create profile-scoped Composio auth links from chat."""

    def __init__(
        self,
        config: ComposioToolConfig,
        *,
        send_callback: Callable[[OutboundMessage], Awaitable[None]] | None = None,
    ) -> None:
        self.config = config
        self._send_callback = send_callback
        self._default_channel: ContextVar[str] = ContextVar("composio_channel", default="")
        self._default_chat_id: ContextVar[str] = ContextVar("composio_chat_id", default="")

    @property
    def name(self) -> str:
        return "composio_connect"

    @property
    def description(self) -> str:
        configured = ", ".join(sorted(self.config.auth_configs)) or "none configured"
        return (
            "Generate a Composio Connect authentication link for the current user/profile. "
            "Use when the user asks to connect a tool such as Gmail, Google Calendar, Notion, GitHub, Slack, etc. "
            "When a chat channel is active, this tool sends two messages itself: a short setup instruction, then the "
            "raw auth URL as a separate message. After the user authenticates, connected MCP tools become available "
            "for this same profile. If no auth config is mapped, find or create a Composio managed auth "
            f"config for the requested toolkit. Configured toolkit overrides: {configured}."
        )

    def set_context(self, channel: str, chat_id: str, *_args: Any) -> None:
        self._default_channel.set(channel)
        self._default_chat_id.set(chat_id)

    async def execute(
        self,
        toolkit: str = "",
        auth_config_id: str = "",
        callback_url: str = "",
        alias: str = "",
        wait_for_connection: bool = True,
        **_kwargs: Any,
    ) -> str:
        if not self.config.api_key:
            return "Error: Composio is enabled but tools.composio.apiKey is missing."
        if not self.config.user_id:
            return "Error: Composio user_id is missing for this profile."

        toolkit_key = _normalize_toolkit(toolkit)
        auth_id = auth_config_id.strip()
        if toolkit_key and self.config.mode == "toolRouter" and self.config.tool_router_session_id and not auth_id:
            return await self._create_tool_router_link(
                toolkit_key,
                callback_url=callback_url,
                alias=alias,
                wait_for_connection=wait_for_connection,
            )
        if not auth_id and toolkit_key:
            auth_id = self.config.auth_configs.get(toolkit_key, "")
        if not auth_id:
            if not toolkit_key:
                return "Error: toolkit is required when auth_config_id is not provided."
            auth_id = await self._resolve_auth_config_id(toolkit_key)
            if auth_id.startswith("Error:"):
                return auth_id

        payload: dict[str, Any] = {"auth_config_id": auth_id, "user_id": self.config.user_id}
        cb_url = callback_url or self.config.callback_url
        if cb_url:
            payload["callback_url"] = cb_url
        if alias:
            payload["alias"] = alias

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.config.api_base.rstrip('/')}/connected_accounts/link",
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": self.config.api_key,
                },
                json=payload,
            )
            if response.status_code >= 400:
                return (
                    f"Error: Composio auth link failed with HTTP {response.status_code}: "
                    f"{response.text[:500]}"
                )
            data = response.json()

        redirect_url = str(data.get("redirect_url") or "")
        account_id = str(data.get("connected_account_id") or "")
        expires_at = str(data.get("expires_at") or "")
        if not redirect_url:
            return f"Error: Composio did not return a redirect_url. Response: {data}"

        sent = await self._send_auth_link(toolkit_key or auth_id, redirect_url)

        if (
            wait_for_connection
            and self.config.notify_on_connect
            and account_id
            and self._send_callback
            and self._default_channel.get()
            and self._default_chat_id.get()
        ):
            asyncio.create_task(self._watch_connection(account_id, toolkit_key or auth_id))

        expiry = f"\nThis link expires at {expires_at}." if expires_at else ""
        if sent:
            return (
                f"Composio auth link for {toolkit_key or auth_id} was sent to the user as a separate setup message "
                f"and link message.{expiry}"
            )
        return (
            f"Composio auth link for {toolkit_key or auth_id}:\n{redirect_url}"
            f"{expiry}\nAfter the user opens it and finishes auth, the connected tools are available for user_id "
            f"{self.config.user_id}."
        )

    async def _create_tool_router_link(
        self,
        toolkit: str,
        *,
        callback_url: str = "",
        alias: str = "",
        wait_for_connection: bool = True,
    ) -> str:
        payload: dict[str, Any] = {"toolkit": toolkit}
        cb_url = callback_url or self.config.callback_url
        if cb_url:
            payload["callback_url"] = cb_url
        if alias:
            payload["alias"] = alias

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.config.tool_router_api_base.rstrip('/')}/tool_router/session/"
                f"{self.config.tool_router_session_id}/link",
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": self.config.api_key,
                },
                json=payload,
            )
            if response.status_code >= 400:
                return (
                    f"Error: Composio Tool Router auth link failed with HTTP {response.status_code}: "
                    f"{response.text[:500]}"
                )
            data = response.json()

        redirect_url = str(data.get("redirect_url") or "")
        account_id = str(data.get("connected_account_id") or "")
        expires_at = str(data.get("expires_at") or "")
        if not redirect_url:
            return f"Error: Composio Tool Router did not return a redirect_url. Response: {data}"

        sent = await self._send_auth_link(toolkit, redirect_url)

        if (
            wait_for_connection
            and self.config.notify_on_connect
            and account_id
            and self._send_callback
            and self._default_channel.get()
            and self._default_chat_id.get()
        ):
            asyncio.create_task(self._watch_connection(account_id, toolkit))

        expiry = f"\nThis link expires at {expires_at}." if expires_at else ""
        if sent:
            return (
                f"Composio auth link for {toolkit} was sent to the user as a separate setup message "
                f"and link message.{expiry}"
            )
        return (
            f"Composio auth link for {toolkit}:\n{redirect_url}"
            f"{expiry}\nAfter the user opens it and finishes auth, the connected tools are available for user_id "
            f"{self.config.user_id}."
        )

    async def _send_auth_link(self, label: str, redirect_url: str) -> bool:
        if not self._send_callback or not self._default_channel.get() or not self._default_chat_id.get():
            return False
        await self._notify(
            f"I've generated an auth link for {label}. Please click the link below to complete the setup:"
        )
        await self._notify(redirect_url)
        return True

    async def _resolve_auth_config_id(self, toolkit: str) -> str:
        async with httpx.AsyncClient(timeout=30) as client:
            existing = await client.get(
                f"{self.config.api_base.rstrip('/')}/auth_configs",
                headers={"x-api-key": self.config.api_key},
                params={
                    "toolkit_slug": toolkit,
                    "is_composio_managed": "true",
                    "show_disabled": "false",
                    "limit": 10,
                },
            )
            if existing.status_code < 400:
                auth_id = _extract_auth_config_id(existing.json())
                if auth_id:
                    return auth_id

            if not self.config.auto_create_auth_configs:
                available = ", ".join(sorted(self.config.auth_configs)) or "none"
                return (
                    "Error: No Composio auth config id was found, and autoCreateAuthConfigs is disabled. "
                    f"Configured toolkits: {available}."
                )

            created = await client.post(
                f"{self.config.api_base.rstrip('/')}/auth_configs",
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": self.config.api_key,
                },
                json={"toolkit": {"slug": toolkit}},
            )
            if created.status_code >= 400:
                return (
                    f"Error: Composio auth config lookup/create failed for {toolkit}. "
                    f"Lookup HTTP {existing.status_code}; create HTTP {created.status_code}: "
                    f"{created.text[:500]}"
                )
            auth_id = _extract_auth_config_id(created.json())
            if auth_id:
                return auth_id
        return f"Error: Composio did not return an auth config id for {toolkit}."

    async def _watch_connection(self, account_id: str, label: str) -> None:
        deadline = asyncio.get_running_loop().time() + self.config.connection_poll_timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(self.config.connection_poll_seconds)
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    response = await client.get(
                        f"{self.config.api_base.rstrip('/')}/connected_accounts/{account_id}",
                        headers={"x-api-key": self.config.api_key},
                    )
                if response.status_code >= 400:
                    continue
                data = response.json()
            except Exception:
                continue

            status = str(data.get("status") or "").upper()
            if status == "ACTIVE":
                await self._notify(f"Awesome, {label} is connected. I can use those tools now.")
                return

    async def _notify(self, content: str) -> None:
        if not self._send_callback:
            return
        await self._send_callback(OutboundMessage(
            channel=self._default_channel.get(),
            chat_id=self._default_chat_id.get(),
            content=content,
        ))


def _normalize_toolkit(toolkit: str) -> str:
    key = toolkit.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "calendar": "google_calendar",
        "googlecalendar": "google_calendar",
        "gcal": "google_calendar",
        "google_cal": "google_calendar",
        "drive": "google_drive",
        "gdrive": "google_drive",
        "googlemail": "gmail",
        "google_mail": "gmail",
    }
    return aliases.get(key, key)


def _extract_auth_config_id(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    items = data.get("items")
    if isinstance(items, list):
        for item in items:
            auth_id = _extract_auth_config_id(item)
            if auth_id:
                return auth_id
    auth_config = data.get("auth_config")
    if isinstance(auth_config, dict):
        for key in ("id", "nanoid", "nano_id"):
            value = auth_config.get(key)
            if isinstance(value, str) and value:
                return value
    for key in ("id", "nanoid", "nano_id", "auth_config_id"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


async def get_or_create_tool_router_mcp_url(
    config: ComposioToolConfig,
    *,
    workspace: Path,
) -> str:
    """Return a profile-scoped Composio Tool Router MCP URL."""
    data = await get_or_create_tool_router_session(config, workspace=workspace)
    return _extract_tool_router_mcp_url(data)


async def get_or_create_tool_router_session(
    config: ComposioToolConfig,
    *,
    workspace: Path,
) -> dict[str, Any]:
    """Return a persisted profile-scoped Composio Tool Router session."""
    if not config.api_key:
        return {}
    user_id = config.user_id
    if not user_id:
        return {}

    toolkits: dict[str, Any] = {}
    enabled = [_normalize_toolkit(item) for item in config.toolkits if item]
    disabled = [_normalize_toolkit(item) for item in config.disabled_toolkits if item]
    if enabled and disabled:
        raise ValueError("tools.composio.toolkits and disabledToolkits are mutually exclusive")
    if enabled:
        toolkits["enabled"] = enabled
    if disabled:
        toolkits["disabled"] = disabled

    path = workspace / _TOOL_ROUTER_SESSION_FILE
    existing = _read_tool_router_session(path)
    meta = existing.get("_nanobot") if isinstance(existing.get("_nanobot"), dict) else {}
    config_data = existing.get("config") if isinstance(existing.get("config"), dict) else {}
    existing_user_id = existing.get("user_id") or config_data.get("user_id") or meta.get("user_id")
    meta_matches = (
        meta.get("toolkits") == toolkits
        and meta.get("auth_configs", {}) == config.auth_configs
    )
    if existing_user_id == user_id and _extract_tool_router_mcp_url(existing) and meta_matches:
        return existing

    payload: dict[str, Any] = {"user_id": user_id}
    if toolkits:
        payload["toolkits"] = toolkits
    if config.auth_configs:
        payload["auth_configs"] = config.auth_configs

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{config.tool_router_api_base.rstrip('/')}/tool_router/session",
            headers={
                "Content-Type": "application/json",
                "x-api-key": config.api_key,
            },
            json=payload,
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"Composio Tool Router session failed with HTTP {response.status_code}: "
                f"{response.text[:500]}"
            )
        data = response.json()

    data["_nanobot"] = {
        "user_id": user_id,
        "toolkits": toolkits,
        "auth_configs": config.auth_configs,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data


def _read_tool_router_session(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _extract_tool_router_mcp_url(data: dict[str, Any]) -> str:
    nested = data.get("data")
    if isinstance(nested, dict):
        url = _extract_tool_router_mcp_url(nested)
        if url:
            return url
    nested = data.get("session")
    if isinstance(nested, dict):
        url = _extract_tool_router_mcp_url(nested)
        if url:
            return url
    mcp = data.get("mcp")
    if isinstance(mcp, dict):
        url = mcp.get("url")
        if isinstance(url, str) and url:
            return url
    for key in ("url", "mcp_url", "mcpUrl"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def extract_tool_router_mcp_url(data: dict[str, Any]) -> str:
    return _extract_tool_router_mcp_url(data)


def extract_tool_router_session_id(data: dict[str, Any]) -> str:
    nested = data.get("data")
    if isinstance(nested, dict):
        session_id = extract_tool_router_session_id(nested)
        if session_id:
            return session_id
    nested = data.get("session")
    if isinstance(nested, dict):
        session_id = extract_tool_router_session_id(nested)
        if session_id:
            return session_id
    for key in ("session_id", "sessionId", "id"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return ""
