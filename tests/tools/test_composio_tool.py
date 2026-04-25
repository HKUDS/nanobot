"""Tests for Composio chat-driven auth links."""

from __future__ import annotations

from typing import Any

import pytest

from nanobot.agent.tools.composio import ComposioConnectTool, get_or_create_tool_router_mcp_url
from nanobot.config.schema import ComposioToolConfig


class _Response:
    def __init__(self, status_code: int = 201, data: dict[str, Any] | None = None):
        self.status_code = status_code
        self._data = data or {}
        self.text = str(self._data)

    def json(self):
        return self._data


class _Client:
    posts: list[dict[str, Any]] = []
    gets: list[dict[str, Any]] = []
    list_data: dict[str, Any] = {"items": [{"id": "authcfg_cal"}]}

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url, *, headers=None, json=None):
        self.posts.append({"url": url, "headers": headers, "json": json})
        if url.endswith("/auth_configs"):
            return _Response(data={
                "toolkit": {"slug": json["toolkit"]["slug"]},
                "auth_config": {"id": "authcfg_created"},
            })
        if url.endswith("/tool_router/session"):
            return _Response(data={
                "session_id": "trs_123",
                "mcp": {"type": "http", "url": "https://app.composio.dev/tool_router/v3/trs_123/mcp"},
            })
        return _Response(data={
            "redirect_url": "https://auth.composio.dev/connect?token=lt_123",
            "connected_account_id": "ca_123",
            "expires_at": "2026-04-25T12:00:00Z",
        })

    async def get(self, url, *, headers=None, params=None):
        self.gets.append({"url": url, "headers": headers, "params": params})
        return _Response(data=self.list_data)


@pytest.mark.asyncio
async def test_composio_connect_generates_profile_scoped_link(monkeypatch):
    _Client.posts = []
    _Client.gets = []
    _Client.list_data = {"items": [{"id": "authcfg_cal"}]}
    monkeypatch.setattr("nanobot.agent.tools.composio.httpx.AsyncClient", _Client)
    tool = ComposioConnectTool(ComposioToolConfig(
        enabled=True,
        apiKey="cmp-key",
        userId="ron",
        notifyOnConnect=False,
    ))

    result = await tool.execute(toolkit="google calendar")

    assert "https://auth.composio.dev/connect?token=lt_123" in result
    assert _Client.gets[0]["url"] == "https://backend.composio.dev/api/v3/auth_configs"
    assert _Client.gets[0]["params"]["toolkit_slug"] == "google_calendar"
    link_post = _Client.posts[-1]
    assert link_post["url"] == "https://backend.composio.dev/api/v3/connected_accounts/link"
    assert link_post["headers"]["x-api-key"] == "cmp-key"
    assert link_post["json"] == {
        "auth_config_id": "authcfg_cal",
        "user_id": "ron",
    }


@pytest.mark.asyncio
async def test_composio_connect_creates_missing_managed_auth_config(monkeypatch):
    _Client.posts = []
    _Client.gets = []
    _Client.list_data = {"items": []}
    monkeypatch.setattr("nanobot.agent.tools.composio.httpx.AsyncClient", _Client)
    tool = ComposioConnectTool(ComposioToolConfig(
        enabled=True,
        apiKey="cmp-key",
        userId="ron",
        notifyOnConnect=False,
    ))

    result = await tool.execute(toolkit="notion")

    assert "https://auth.composio.dev/connect?token=lt_123" in result
    create_post = _Client.posts[0]
    assert create_post["url"] == "https://backend.composio.dev/api/v3/auth_configs"
    assert create_post["json"] == {"toolkit": {"slug": "notion"}}
    link_post = _Client.posts[1]
    assert link_post["json"] == {
        "auth_config_id": "authcfg_created",
        "user_id": "ron",
    }


@pytest.mark.asyncio
async def test_composio_connect_uses_tool_router_link(monkeypatch):
    _Client.posts = []
    _Client.gets = []
    monkeypatch.setattr("nanobot.agent.tools.composio.httpx.AsyncClient", _Client)
    tool = ComposioConnectTool(ComposioToolConfig(
        enabled=True,
        apiKey="cmp-key",
        userId="ron",
        toolRouterSessionId="trs_123",
        notifyOnConnect=False,
    ))

    result = await tool.execute(toolkit="github")

    assert "https://auth.composio.dev/connect?token=lt_123" in result
    assert _Client.gets == []
    link_post = _Client.posts[0]
    assert link_post["url"] == "https://backend.composio.dev/api/v3/tool_router/session/trs_123/link"
    assert link_post["headers"]["x-api-key"] == "cmp-key"
    assert link_post["json"] == {"toolkit": "github"}


@pytest.mark.asyncio
async def test_tool_router_mcp_url_is_profile_scoped(monkeypatch, tmp_path):
    _Client.posts = []
    monkeypatch.setattr("nanobot.agent.tools.composio.httpx.AsyncClient", _Client)

    url = await get_or_create_tool_router_mcp_url(
        ComposioToolConfig(
            enabled=True,
            apiKey="cmp-key",
            userId="ron",
            toolkits=["gmail", "google calendar"],
        ),
        workspace=tmp_path,
    )

    assert url == "https://app.composio.dev/tool_router/v3/trs_123/mcp"
    post = _Client.posts[0]
    assert post["url"] == "https://backend.composio.dev/api/v3/tool_router/session"
    assert post["headers"]["x-api-key"] == "cmp-key"
    assert post["json"] == {
        "user_id": "ron",
        "toolkits": {"enabled": ["gmail", "google_calendar"]},
    }
    assert (tmp_path / "composio-tool-router-session.json").exists()

    _Client.posts = []
    cached_url = await get_or_create_tool_router_mcp_url(
        ComposioToolConfig(
            enabled=True,
            apiKey="cmp-key",
            userId="ron",
            toolkits=["gmail", "google calendar"],
        ),
        workspace=tmp_path,
    )
    assert cached_url == url
    assert _Client.posts == []
