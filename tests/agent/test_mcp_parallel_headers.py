"""Capture real SDK tool requests on a local HTTP server, including reconnects."""

import asyncio

import httpx
import pytest
from aiohttp import web

from nanobot import __version__
from nanobot.agent.tools import mcp as runtime
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.schema import MCPServerConfig


@pytest.mark.parametrize(
    "url,caller_ua,expected_ua",
    [
        ("https://search.parallel.ai/mcp", None, f"python-httpx/{httpx.__version__} nanobot/{__version__}"),
        ("https://search.parallel.ai/mcp", "custom/1", f"custom/1 nanobot/{__version__}"),
        ("https://search.parallel.ai/mcp", "nanobot/1 custom/1", "nanobot/1 custom/1"),
        ("https://example.com/mcp", "custom/1", "custom/1"),
    ],
)
async def test_parallel_headers_reach_tool_calls_and_reconnect(monkeypatch, url, caller_ua, expected_ua):
    captured = []

    async def handle(request):
        body = await request.json()
        captured.append((body["method"], {key.lower(): value for key, value in request.headers.items()}))
        if "id" not in body:
            return web.Response(status=202)
        method = body["method"]
        if method == "initialize":
            result = {
                "protocolVersion": body["params"]["protocolVersion"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "capture", "version": "1"},
            }
        elif method == "tools/list":
            result = {"tools": [
                {"name": name, "description": name, "inputSchema": {"type": "object"}}
                for name in ("web_search", "web_fetch")
            ]}
        else:
            assert method == "tools/call"
            result = {"content": [{"type": "text", "text": "captured"}]}
        return web.json_response({"jsonrpc": "2.0", "id": body["id"], "result": result})

    app = web.Application()
    app.router.add_post("/mcp", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]

    class LocalCaptureTransport(httpx.AsyncHTTPTransport):
        async def handle_async_request(self, request):
            # Only reroute network delivery. SDK/client headers still go over a
            # real socket and are inspected by the receiving HTTP server.
            request.url = httpx.URL(f"http://127.0.0.1:{port}/mcp")
            return await super().handle_async_request(request)

    monkeypatch.setattr(runtime, "_pinned_transport_kwargs", lambda: {"transport": LocalCaptureTransport(), "trust_env": False})
    monkeypatch.setattr(runtime, "validate_url_target", lambda _: (True, ""))
    monkeypatch.setattr(runtime, "_probe_http_url", lambda _: asyncio.sleep(0, result=True))
    headers = {"Authorization": "Bearer test-only", "X-Caller": "preserved"}
    if caller_ua is not None:
        headers["uSeR-aGeNt"] = caller_ua
    cfg = MCPServerConfig(type="streamableHttp", url=url, headers=headers, enabled_tools=["web_search", "web_fetch"])
    registry = ToolRegistry()
    provider = runtime.MCPProvider({"search": cfg}, registry)
    try:
        await provider.connect()
        stale = registry.get("mcp_search_web_search")
        assert stale is not None
        assert "captured" in await stale.execute()
        replacement = await provider._refresh_terminated_server("search", stale.name, stale)
        assert replacement is not None and replacement is not stale
        assert "captured" in await replacement.execute()
        fetch = registry.get("mcp_search_web_fetch")
        assert fetch is not None
        assert "captured" in await fetch.execute()
    finally:
        await provider.aclose()
        await runner.cleanup()

    assert sum(method == "initialize" for method, _ in captured) == 2
    assert sum(method == "tools/call" for method, _ in captured) == 3
    for _, received in captured:
        assert received["user-agent"] == expected_ua
        assert received["authorization"] == "Bearer test-only"
        assert received["x-caller"] == "preserved"
    assert cfg.headers == headers


@pytest.mark.parametrize("url", ["https://search.parallel.ai.evil/mcp", "https://search.parallel.ai/other", "http://search.parallel.ai/mcp"])
def test_other_endpoints_keep_headers(url):
    headers = {"uSeR-aGeNt": "caller/1", "Authorization": "Bearer test-only"}
    assert runtime._mcp_http_headers(url, headers) == headers
