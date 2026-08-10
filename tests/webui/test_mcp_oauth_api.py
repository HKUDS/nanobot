from __future__ import annotations

import asyncio

import pytest

from nanobot.config.schema import MCPServerConfig
from nanobot.webui.mcp_oauth_api import (
    McpOAuthError,
    McpOAuthManager,
    prepare_mcp_oauth_redirect_uri,
    validate_mcp_oauth_redirect_uri,
)


class _Connection:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


def _config() -> MCPServerConfig:
    return MCPServerConfig(
        type="streamableHttp",
        auth="oauth",
        url="https://mcp.example.com/mcp",
    )


@pytest.mark.asyncio
async def test_browser_flow_retries_current_server_and_ignores_unrelated_reload_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = McpOAuthManager()
    connection = _Connection()
    received: dict[str, object] = {}
    reload_calls = 0

    monkeypatch.setattr(
        "nanobot.webui.mcp_oauth_api.validate_url_target",
        lambda _url: (True, ""),
    )

    async def connect(servers, _registry, *, oauth_handlers):
        assert set(servers) == {"xmind"}
        handlers = oauth_handlers["xmind"]
        await handlers.redirect_handler(
            "https://accounts.example.com/authorize?client_id=test&state=state-123"
        )
        received["callback"] = await handlers.callback_handler()
        return {"xmind": connection}

    async def reload_mcp() -> dict[str, object]:
        nonlocal reload_calls
        reload_calls += 1
        if reload_calls == 1:
            return {
                "ok": False,
                "requires_restart": False,
                "failed": ["xmind"],
            }
        return {
            "ok": False,
            "requires_restart": False,
            "connected": ["xmind"],
            "failed": ["notion"],
            "message": "MCP config reloaded, but some servers did not connect: notion",
        }

    monkeypatch.setattr("nanobot.webui.mcp_oauth_api.connect_mcp_servers", connect)

    started = await manager.start(
        "xmind",
        _config(),
        "https://agent.example.com/auth/mcp/callback",
        reload_mcp=reload_mcp,
    )

    assert started["status"] == "authorization_required"
    assert started["authorization_url"].startswith("https://accounts.example.com/authorize?")
    manager.submit_callback(state="state-123", code="oauth-code", error=None)
    with pytest.raises(McpOAuthError, match="expired"):
        manager.submit_callback(state="state-123", code="replayed-code", error=None)

    for _ in range(10):
        await asyncio.sleep(0)
        if reload_calls == 2:
            break
    assert reload_calls == 2

    for _ in range(10):
        first, second = await asyncio.gather(
            manager.status(started["flow_id"]),
            manager.status(started["flow_id"]),
        )
        if first["status"] == "connected":
            break
        await asyncio.sleep(0)

    assert first["status"] == "connected"
    assert second["status"] == "connected"
    assert first["hot_reload"]["failed"] == ["notion"]
    assert received["callback"] == ("oauth-code", "state-123")
    assert reload_calls == 2
    assert connection.closed is True


@pytest.mark.asyncio
async def test_remote_http_flow_accepts_a_pasted_loopback_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = McpOAuthManager()
    connection = _Connection()
    received: dict[str, object] = {}

    monkeypatch.setattr(
        "nanobot.webui.mcp_oauth_api.validate_url_target",
        lambda _url: (True, ""),
    )

    async def connect(_servers, _registry, *, oauth_handlers):
        handlers = oauth_handlers["linear"]
        received["redirect_uri"] = handlers.redirect_uri
        await handlers.redirect_handler(
            "https://accounts.example.com/authorize?client_id=test&state=manual-state"
        )
        received["callback"] = await handlers.callback_handler()
        return {"linear": connection}

    monkeypatch.setattr("nanobot.webui.mcp_oauth_api.connect_mcp_servers", connect)

    started = await manager.start(
        "linear",
        _config(),
        "http://192.0.2.10:8765/auth/mcp/callback",
        reload_mcp=lambda: asyncio.sleep(
            0,
            result={"ok": True, "requires_restart": False},
        ),
    )

    assert started["status"] == "authorization_required"
    assert started["completion_input"] == "callback_url"
    assert received["redirect_uri"] == "http://127.0.0.1:8765/auth/mcp/callback"

    with pytest.raises(McpOAuthError, match="complete callback URL"):
        manager.submit_callback_url(
            flow_id=started["flow_id"],
            callback_url=(
                "http://127.0.0.1:8765/wrong?code=oauth-code&state=manual-state"
            ),
        )
    with pytest.raises(McpOAuthError, match="different or expired"):
        manager.submit_callback_url(
            flow_id=started["flow_id"],
            callback_url=(
                "http://127.0.0.1:8765/auth/mcp/callback"
                "?code=oauth-code&state=other-state"
            ),
        )

    submitted = manager.submit_callback_url(
        flow_id=started["flow_id"],
        callback_url=(
            "http://127.0.0.1:8765/auth/mcp/callback"
            "?code=oauth-code&state=manual-state"
        ),
    )
    assert submitted["status"] == "connecting"

    for _ in range(20):
        await asyncio.sleep(0)
        result = await manager.status(started["flow_id"])
        if result["status"] == "connected":
            break

    assert result["status"] == "connected"
    assert result["completion_input"] == "callback_url"
    assert received["callback"] == ("oauth-code", "manual-state")
    assert connection.closed is True


@pytest.mark.asyncio
async def test_browser_flow_surfaces_provider_denial_without_callback_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = McpOAuthManager()
    monkeypatch.setattr(
        "nanobot.webui.mcp_oauth_api.validate_url_target",
        lambda _url: (True, ""),
    )

    async def connect(_servers, _registry, *, oauth_handlers):
        handlers = oauth_handlers["notion"]
        await handlers.redirect_handler("https://accounts.example.com/auth?state=deny-state")
        await handlers.callback_handler()
        return {}

    monkeypatch.setattr("nanobot.webui.mcp_oauth_api.connect_mcp_servers", connect)
    started = await manager.start(
        "notion",
        _config(),
        "https://agent.example.com/auth/mcp/callback",
        reload_mcp=lambda: asyncio.sleep(0, result={"ok": True}),
    )

    with pytest.raises(McpOAuthError, match="access_denied"):
        manager.submit_callback(state="deny-state", code=None, error="access_denied")
    for _ in range(10):
        await asyncio.sleep(0)
        result = await manager.status(started["flow_id"])
        if result["status"] == "failed":
            break

    assert result["status"] == "failed"
    assert result["error"] == "Authorization was not completed (access_denied)."


@pytest.mark.parametrize(
    ("authorization_url", "url_is_safe", "state"),
    [
        ("https://127.0.0.1/authorize?state=private-state", False, "private-state"),
        ("http://accounts.example.com/authorize?state=http-state", True, "http-state"),
    ],
)
@pytest.mark.asyncio
async def test_browser_flow_blocks_unsafe_authorization_url(
    monkeypatch: pytest.MonkeyPatch,
    authorization_url: str,
    url_is_safe: bool,
    state: str,
) -> None:
    manager = McpOAuthManager()
    monkeypatch.setattr(
        "nanobot.webui.mcp_oauth_api.validate_url_target",
        lambda _url: (url_is_safe, "private address"),
    )

    async def connect(_servers, _registry, *, oauth_handlers):
        await oauth_handlers["linear"].redirect_handler(authorization_url)
        return {}

    monkeypatch.setattr("nanobot.webui.mcp_oauth_api.connect_mcp_servers", connect)

    result = await manager.start(
        "linear",
        _config(),
        "https://agent.example.com/auth/mcp/callback",
        reload_mcp=lambda: asyncio.sleep(0, result={"ok": True}),
    )

    assert result["status"] == "failed"
    assert result["error"] == "The MCP server returned an unsafe authorization URL."
    with pytest.raises(McpOAuthError, match="expired"):
        manager.submit_callback(state=state, code="code", error=None)


def test_redirect_uri_requires_https_except_for_loopback() -> None:
    assert validate_mcp_oauth_redirect_uri(
        "https://agent.example.com/auth/mcp/callback"
    ) == "https://agent.example.com/auth/mcp/callback"
    assert validate_mcp_oauth_redirect_uri(
        "http://127.0.0.1:8765/auth/mcp/callback"
    ) == "http://127.0.0.1:8765/auth/mcp/callback"

    with pytest.raises(McpOAuthError, match="HTTPS or localhost"):
        validate_mcp_oauth_redirect_uri("http://192.0.2.10/auth/mcp/callback")
    with pytest.raises(McpOAuthError, match="Invalid"):
        validate_mcp_oauth_redirect_uri("https://agent.example.com/wrong")


def test_remote_http_redirect_prepares_a_manual_loopback_callback() -> None:
    assert prepare_mcp_oauth_redirect_uri(
        "https://agent.example.com/auth/mcp/callback"
    ) == ("https://agent.example.com/auth/mcp/callback", False)
    assert prepare_mcp_oauth_redirect_uri(
        "http://127.0.0.1:8765/auth/mcp/callback"
    ) == ("http://127.0.0.1:8765/auth/mcp/callback", False)
    assert prepare_mcp_oauth_redirect_uri(
        "http://agent.example.com:9443/auth/mcp/callback"
    ) == ("http://127.0.0.1:9443/auth/mcp/callback", True)
