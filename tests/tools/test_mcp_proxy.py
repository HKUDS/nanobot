"""Shared MCP routing exercised through a real loopback HTTP recording proxy."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlsplit
from urllib.request import getproxies_environment

import aiohttp
import pytest
import pytest_asyncio
from aiohttp import web

from nanobot.agent.tools.mcp import MCPProvider, MCPToolWrapper, connect_mcp_servers
from nanobot.agent.tools.mcp_oauth import MCPOAuthStorage
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.network import NetworkConfig
from nanobot.config.schema import MCPServerConfig
from nanobot.runtime_admission import RuntimeAdmission
from nanobot.security import network as security_network
from nanobot.webui.mcp_oauth_api import McpOAuthManager

_PROXY_ENV_VARS = (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
    "http_proxy", "https_proxy", "all_proxy", "no_proxy",
)


@dataclass
class _RecordingMCPProxy:
    origin: str = ""
    proxy: str = ""
    proxy_requests: list[tuple[str, str]] = field(default_factory=list)
    origin_requests: list[tuple[str, str, str | None]] = field(default_factory=list)
    rpc_methods: list[str] = field(default_factory=list)
    token_grants: list[str] = field(default_factory=list)
    proxy_fails: bool = False
    terminate_next_call: bool = False
    initialized: int = 0

    async def serve_origin(self, request: web.Request) -> web.Response:
        self.origin_requests.append((request.method, request.path, request.headers.get("X-Test-Proxy")))
        if request.path == "/.well-known/oauth-protected-resource":
            return web.json_response({
                "resource": f"{self.origin}/mcp",
                "authorization_servers": [self.origin],
            })
        if request.path == "/.well-known/oauth-authorization-server":
            return web.json_response({
                "issuer": self.origin,
                # Browser navigation is not performed by this fixture or the gateway.
                "authorization_endpoint": "https://8.8.8.8/authorize",
                "token_endpoint": f"{self.origin}/token",
                "registration_endpoint": f"{self.origin}/register",
                "response_types_supported": ["code"],
                "code_challenge_methods_supported": ["S256"],
            })
        if request.path == "/register":
            registration = await request.json()
            return web.json_response({
                "client_id": "local-test-client",
                "redirect_uris": registration["redirect_uris"],
                "token_endpoint_auth_method": "none",
            }, status=201)
        if request.path == "/token":
            token_request = parse_qs(await request.text())
            grant = token_request["grant_type"][0]
            self.token_grants.append(grant)
            if grant == "authorization_code":
                assert token_request["code"] == ["local-test-code"]
                assert len(token_request["code_verifier"][0]) >= 43
            else:
                assert grant == "refresh_token"
                assert token_request["refresh_token"] == ["local-refresh-token"]
            return web.json_response({
                "access_token": "local-access-token", "refresh_token": "local-refresh-token",
                "token_type": "Bearer", "expires_in": 3600,
            })
        if request.path != "/mcp":
            return web.Response(status=404)
        if request.headers.get("Authorization") != "Bearer local-access-token":
            return web.Response(status=401, headers={
                "WWW-Authenticate": (
                    f'Bearer resource_metadata="{self.origin}/.well-known/oauth-protected-resource"'
                ),
            })
        if request.method == "DELETE":
            return web.Response(status=200)
        if request.method != "POST":
            return web.Response(status=405)
        payload = await request.json()
        method = payload["method"]
        self.rpc_methods.append(method)
        if "id" not in payload:
            return web.Response(status=202)
        headers = {}
        if method == "initialize":
            self.initialized += 1
            headers["Mcp-Session-Id"] = f"test-session-{self.initialized}"
            result = {
                "protocolVersion": payload["params"]["protocolVersion"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "local-proxy-test", "version": "1"},
            }
        elif method == "tools/list":
            result = {"tools": [{
                "name": "echo", "description": "Echo over the selected route",
                "inputSchema": {"type": "object", "properties": {}},
            }]}
        elif method == "tools/call":
            if self.terminate_next_call:
                self.terminate_next_call = False
                return web.json_response({
                    "jsonrpc": "2.0", "id": payload["id"],
                    "error": {"code": -32000, "message": "Session terminated"},
                })
            result = {"content": [{"type": "text", "text": "through-shared-proxy"}]}
        else:
            raise AssertionError(f"Unexpected MCP method: {method}")
        return web.json_response({"jsonrpc": "2.0", "id": payload["id"], "result": result}, headers=headers)


@pytest_asyncio.fixture
async def recording_mcp_proxy(tmp_path, monkeypatch: pytest.MonkeyPatch):
    for name in _PROXY_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(security_network, "getproxies", getproxies_environment)
    monkeypatch.setattr("nanobot.agent.tools.mcp_oauth.get_data_dir", lambda: tmp_path)
    previous_whitelist = [str(cidr) for cidr in security_network._allowed_networks]
    security_network.configure_ssrf_whitelist(["127.0.0.1/32"])
    fixture = _RecordingMCPProxy()
    runners: list[web.AppRunner] = []

    async def serve(handler) -> str:
        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", handler)
        runner = web.AppRunner(app)
        runners.append(runner)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{port}"

    try:
        fixture.origin = await serve(fixture.serve_origin)
        async with aiohttp.ClientSession(trust_env=False) as forwarding_client:
            async def forward(request: web.Request) -> web.Response:
                target = request.raw_path
                fixture.proxy_requests.append((request.method, target))
                assert target.startswith(f"{fixture.origin}/"), "test proxy must never forward externally"
                if fixture.proxy_fails:
                    return web.Response(status=502, text="controlled proxy failure")
                headers = {
                    key: value for key, value in request.headers.items()
                    if key.lower() not in {"host", "content-length", "connection", "proxy-connection"}
                }
                headers["X-Test-Proxy"] = "shared"
                async with forwarding_client.request(
                    request.method, target, headers=headers, data=await request.read(),
                    allow_redirects=False,
                ) as response:
                    body = await response.read()
                    response_headers = {
                        key: value for key, value in response.headers.items()
                        if key.lower() not in {"content-length", "transfer-encoding", "connection"}
                    }
                    return web.Response(body=body, status=response.status, headers=response_headers)

            fixture.proxy = await serve(forward)
            yield fixture
    finally:
        for runner in reversed(runners):
            await runner.cleanup()
        security_network.configure_ssrf_whitelist(previous_whitelist)


@pytest.mark.asyncio
async def test_oauth_discovery_tokens_reconnect_and_tool_calls_share_real_proxy(
    recording_mcp_proxy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = recording_mcp_proxy
    # Even an ambient proxy or NO_PROXY=* cannot override an explicitly selected route.
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("NO_PROXY", "*")
    cfg = MCPServerConfig(
        type="streamableHttp", auth="oauth", url=f"{fixture.origin}/mcp",
        use_proxy=True, enabled_tools=["echo"],
    )
    network = NetworkConfig(proxy=fixture.proxy)
    registry = ToolRegistry()
    provider = MCPProvider({"local": cfg}, registry, network=network)
    manager = McpOAuthManager(RuntimeAdmission())

    async def reload_mcp():
        await provider.connect()
        return {"ok": provider.connected_server_names == {"local"}, "connected": ["local"]}

    started = await asyncio.wait_for(manager.start(
        "local", cfg, "http://127.0.0.1:8765/auth/mcp/callback",
        reload_mcp=reload_mcp, network=network,
    ), timeout=10)
    try:
        assert started["status"] == "authorization_required"
        state = parse_qs(urlsplit(started["authorization_url"]).query)["state"][0]
        manager.submit_callback(state=state, code="local-test-code", error=None)
        async with asyncio.timeout(10):
            while (await manager.status(started["flow_id"]))["status"] == "connecting":
                await asyncio.sleep(0.01)
        assert (await manager.status(started["flow_id"]))["status"] == "connected"
        tool = registry.get("mcp_local_echo")
        assert isinstance(tool, MCPToolWrapper)
        assert await tool.execute() == "through-shared-proxy"
        fixture.terminate_next_call = True
        assert await tool.execute() == "through-shared-proxy"
        assert registry.get("mcp_local_echo") is not tool
        assert fixture.initialized == 3  # Browser flow, activation, terminated-session recovery.
        assert fixture.rpc_methods.count("tools/call") == 3
        storage = MCPOAuthStorage("local", cfg.url)
        snapshot = await storage.get_snapshot()
        assert snapshot.tokens is not None
        assert snapshot.tokens.access_token == "local-access-token"
        # A later runtime loads an expired saved token and must refresh over the same route.
        await storage.set_tokens(snapshot.tokens.model_copy(update={"expires_in": -1}))
        await provider.aclose()
        registry = ToolRegistry()
        provider = MCPProvider({"local": cfg}, registry, network=network)
        await provider.connect()
        refreshed_tool = registry.get("mcp_local_echo")
        assert isinstance(refreshed_tool, MCPToolWrapper)
        assert await refreshed_tool.execute() == "through-shared-proxy"
        assert fixture.token_grants == ["authorization_code", "refresh_token"]
        assert ("POST", f"{fixture.origin}/register") in fixture.proxy_requests
        assert ("POST", f"{fixture.origin}/token") in fixture.proxy_requests
        assert ("GET", f"{fixture.origin}/.well-known/oauth-protected-resource") in fixture.proxy_requests
        assert ("GET", f"{fixture.origin}/.well-known/oauth-authorization-server") in fixture.proxy_requests
        assert fixture.origin_requests
        assert all(route == "shared" for _, _, route in fixture.origin_requests)
    finally:
        await manager.cancel(started["flow_id"])
        await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["sse", "streamableHttp"])
async def test_failing_shared_proxy_never_retries_reachable_origin_directly(recording_mcp_proxy, transport) -> None:
    fixture = recording_mcp_proxy
    fixture.proxy_fails = True
    registry = ToolRegistry()
    connections = await asyncio.wait_for(connect_mcp_servers(
        {"local": MCPServerConfig(type=transport, url=f"{fixture.origin}/mcp", use_proxy=True)},
        registry, network=NetworkConfig(proxy=fixture.proxy),
    ), timeout=5)
    assert connections == {}
    assert registry.tool_names == []
    assert fixture.proxy_requests
    assert fixture.origin_requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["sse", "streamableHttp"])
async def test_missing_shared_address_does_not_open_http_connection(recording_mcp_proxy, transport) -> None:
    fixture = recording_mcp_proxy
    registry = ToolRegistry()
    connections = await connect_mcp_servers(
        {"local": MCPServerConfig(type=transport, url=f"{fixture.origin}/mcp", use_proxy=True)},
        registry, network=NetworkConfig(),
    )
    assert connections == {}
    assert registry.tool_names == []
    assert fixture.proxy_requests == []
    assert fixture.origin_requests == []
