from __future__ import annotations

import asyncio

import pytest

from nanobot.config.network import NetworkConfig
from nanobot.config.schema import MCPServerConfig
from nanobot.runtime_admission import RuntimeAdmission, RuntimeBusyError, RuntimeMaintenanceError
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


class _BlockingConnection:
    def __init__(self) -> None:
        self.close_started = asyncio.Event()
        self.allow_close = asyncio.Event()
        self.closed = False

    async def aclose(self) -> None:
        self.close_started.set()
        await self.allow_close.wait()
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
    manager = McpOAuthManager(RuntimeAdmission())
    connection = _Connection()
    received: dict[str, object] = {}
    reload_calls = 0
    cfg = _config()
    cfg.use_proxy = True
    network_config = NetworkConfig(proxy="http://proxy-a.example:8080")

    monkeypatch.setattr(
        "nanobot.webui.mcp_oauth_api.validate_url_target",
        lambda _url: (True, ""),
    )

    async def connect(servers, _registry, *, oauth_handlers, network):
        assert set(servers) == {"xmind"}
        received["cfg"] = servers["xmind"]
        received["network"] = network
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
        cfg,
        "https://agent.example.com/auth/mcp/callback",
        reload_mcp=reload_mcp,
        network=network_config,
    )

    assert started["status"] == "authorization_required"
    assert started["authorization_url"].startswith("https://accounts.example.com/authorize?")
    cfg.use_proxy = False
    network_config.proxy = "http://proxy-b.example:8080"
    assert received["cfg"] is not cfg
    assert received["cfg"].use_proxy is True
    assert received["network"] is not network_config
    assert received["network"].proxy == "http://proxy-a.example:8080"
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
    await manager.close()
    assert connection.closed is True


@pytest.mark.asyncio
async def test_browser_flow_activates_tools_before_probe_cleanup_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admission = RuntimeAdmission()
    manager = McpOAuthManager(admission)
    connection = _BlockingConnection()
    reload_started = asyncio.Event()

    monkeypatch.setattr(
        "nanobot.webui.mcp_oauth_api.validate_url_target",
        lambda _url: (True, ""),
    )

    async def connect(_servers, _registry, *, oauth_handlers, network):
        handlers = oauth_handlers["linear"]
        await handlers.redirect_handler(
            "https://accounts.example.com/authorize?client_id=test&state=blocked-close"
        )
        await handlers.callback_handler()
        return {"linear": connection}

    async def reload_mcp() -> dict[str, object]:
        reload_started.set()
        return {
            "ok": True,
            "requires_restart": False,
            "connected": ["linear"],
            "failed": [],
        }

    monkeypatch.setattr("nanobot.webui.mcp_oauth_api.connect_mcp_servers", connect)

    started = await manager.start(
        "linear",
        _config(),
        "https://agent.example.com/auth/mcp/callback",
        reload_mcp=reload_mcp,
    )
    manager.submit_callback(state="blocked-close", code="oauth-code", error=None)

    shutdown = None
    try:
        await asyncio.wait_for(reload_started.wait(), timeout=0.5)
        await asyncio.wait_for(connection.close_started.wait(), timeout=0.5)
        result = await manager.status(started["flow_id"])
        assert result["status"] == "connected"
        assert connection.closed is False
        with pytest.raises(RuntimeBusyError), admission.pause_if_idle(lambda: False):
            pytest.fail("MCP transport cleanup is still running")
        shutdown = asyncio.create_task(manager.close())
        await asyncio.wait({shutdown}, timeout=0.01)
        assert not shutdown.done(), "Shutdown must join the in-flight transport cleanup"
    finally:
        connection.allow_close.set()
        if shutdown is not None:
            await shutdown

    for _ in range(10):
        await asyncio.sleep(0)
        if connection.closed:
            break
    assert connection.closed is True
    await manager.close()
    with admission.pause_if_idle(lambda: False):
        pass


@pytest.mark.parametrize("expire", [False, True])
@pytest.mark.asyncio
async def test_browser_flow_remains_busy_through_cancelled_or_expired_cleanup(
    monkeypatch: pytest.MonkeyPatch, expire: bool,
) -> None:
    admission = RuntimeAdmission()
    manager = McpOAuthManager(admission)
    cleanup_started = asyncio.Event()
    allow_cleanup = asyncio.Event()
    monkeypatch.setattr("nanobot.webui.mcp_oauth_api.validate_url_target", lambda _: (True, ""))
    if expire:
        monkeypatch.setattr("nanobot.webui.mcp_oauth_api._FLOW_TTL_S", 0)

    async def connect(_servers, _registry, *, oauth_handlers, network):
        handlers = oauth_handlers["linear"]
        await handlers.redirect_handler("https://accounts.example.com/auth?state=pending")
        try:
            await handlers.callback_handler()
        finally:
            cleanup_started.set()
            await allow_cleanup.wait()
        return {}

    monkeypatch.setattr("nanobot.webui.mcp_oauth_api.connect_mcp_servers", connect)
    started = await manager.start(
        "linear", _config(), "https://agent.example.com/auth/mcp/callback",
        reload_mcp=lambda: asyncio.sleep(0, result={"ok": True}),
    )
    with pytest.raises(RuntimeBusyError), admission.pause_if_idle(lambda: False):
        pytest.fail("The browser response does not finish authorization")
    if expire:
        with pytest.raises(McpOAuthError, match="expired"):
            await manager.status(started["flow_id"])
        await asyncio.wait_for(cleanup_started.wait(), timeout=0.5)

    shutdown = asyncio.create_task(manager.close())
    try:
        await asyncio.wait_for(cleanup_started.wait(), timeout=0.5)
        await asyncio.wait({shutdown}, timeout=0.01)
        assert not shutdown.done()
        with pytest.raises(RuntimeBusyError), admission.pause_if_idle(lambda: False):
            pytest.fail("An expired or cancelled flow still owns its cleanup")
    finally:
        allow_cleanup.set()
        await shutdown

    with admission.pause_if_idle(lambda: False):
        with pytest.raises(RuntimeMaintenanceError):
            await manager.start(
                "linear", _config(), "https://agent.example.com/auth/mcp/callback",
                reload_mcp=lambda: asyncio.sleep(0, result={"ok": True}),
            )


@pytest.mark.asyncio
async def test_remote_http_flow_accepts_a_pasted_loopback_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = McpOAuthManager(RuntimeAdmission())
    connection = _Connection()
    received: dict[str, object] = {}

    monkeypatch.setattr(
        "nanobot.webui.mcp_oauth_api.validate_url_target",
        lambda _url: (True, ""),
    )

    async def connect(_servers, _registry, *, oauth_handlers, network):
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
    await manager.close()
    assert connection.closed is True


@pytest.mark.asyncio
async def test_browser_flow_surfaces_provider_denial_without_callback_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = McpOAuthManager(RuntimeAdmission())
    monkeypatch.setattr(
        "nanobot.webui.mcp_oauth_api.validate_url_target",
        lambda _url: (True, ""),
    )

    async def connect(_servers, _registry, *, oauth_handlers, network):
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
    manager = McpOAuthManager(RuntimeAdmission())
    monkeypatch.setattr(
        "nanobot.webui.mcp_oauth_api.validate_url_target",
        lambda _url: (url_is_safe, "private address"),
    )

    async def connect(_servers, _registry, *, oauth_handlers, network):
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
