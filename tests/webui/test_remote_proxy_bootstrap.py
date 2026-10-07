"""An optional host capability survives the authenticated bootstrap proxy."""

import json
from unittest.mock import MagicMock

import httpx
import pytest
from aiohttp.test_utils import make_mocked_request

from nanobot.webui.remote_proxy import RemoteProxy
from nanobot.webui.remote_ssh import Tunnel


@pytest.mark.asyncio
@pytest.mark.parametrize("capabilities", [
    ["webui.core.v1"],
    ["webui.core.v1", "webui.subagents.v1"],
    ["webui.core.v1", "webui.subagents.v1", "webui.subagents.events.v1"],
    ["webui.core.v1", "webui.subagents.v1", "webui.subagents.events.v1", "webui.subagents.history.v1"],
])
async def test_proxy_preserves_independently_declared_host_capabilities(monkeypatch, capabilities):
    tunnel = MagicMock(spec=Tunnel)
    tunnel.active = True
    tunnel.port = 18791
    proxy = RemoteProxy(tunnel, "private-upstream-secret", "gateway-test", "")
    declaration = {
        "version": "custom-host", "min_protocol": 1, "max_protocol": 1,
        "capabilities": capabilities,
    }

    def upstream(request):
        assert request.url.path == "/webui/bootstrap"
        assert request.headers["X-Nanobot-Auth"] == "private-upstream-secret"
        return httpx.Response(200, json={
            "terminal": {"protocolVersion": 1, "gatewayId": "gateway-test", "webui": declaration},
            "token": "upstream-ws-token", "api_token": "upstream-api-token",
            "expires_in": 300, "ws_path": "/custom/ws",
        })

    client_type = httpx.AsyncClient
    monkeypatch.setattr("nanobot.webui.remote_proxy.httpx.AsyncClient", lambda **kwargs: (
        client_type(transport=httpx.MockTransport(upstream), **kwargs)
    ))
    request = make_mocked_request("GET", "/webui/bootstrap", headers={
        "Host": "127.0.0.1:0", "X-Nanobot-Auth": proxy.secret,
    })
    try:
        response = await proxy._handle(request)
        assert response.status == 200
        payload = json.loads(response.text)
        assert payload["terminal"]["webui"] == declaration
        assert payload["host_compatibility"]["status"] == "compatible"
        assert payload["token"] != "upstream-ws-token"
        assert payload["api_token"] != "upstream-api-token"
        assert "private-upstream-secret" not in response.text
    finally:
        await proxy.close()
