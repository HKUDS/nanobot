"""Terminal capability metadata is authenticated and does not allocate tokens."""

import json
from types import SimpleNamespace

from websockets.datastructures import Headers
from websockets.http11 import Request

from nanobot.channels.websocket.runtime import WebSocketConfig
from nanobot.webui.gateway_tokens import GatewayTokenStore
from nanobot.webui.ws_http import GatewayHTTPHandler


def test_terminal_probe_is_private_stable_and_does_not_issue_credentials():
    handler = object.__new__(GatewayHTTPHandler)
    handler.config = WebSocketConfig(token_issue_secret="fixture-secret")
    handler.tokens = GatewayTokenStore(max_tokens=0)
    connection = SimpleNamespace(remote_address=("127.0.0.1", 10000))
    request = Request("/webui/terminal", Headers({"Host": "127.0.0.1:8765"}))
    assert handler._handle_bootstrap(connection, request, terminal_probe=True).status_code == 401
    request.headers["X-Nanobot-Auth"] = "fixture-secret"
    for _ in range(3):
        response = handler._handle_bootstrap(connection, request, terminal_probe=True)
        assert response.status_code == 200
        assert json.loads(response.body) == {
            "protocolVersion": 1, "gatewayId": handler.tokens.instance_id,
        }
        assert "no-store" in response.headers["Cache-Control"]
    assert not handler.tokens.api_tokens and not handler.tokens.issued_tokens
    assert GatewayTokenStore().instance_id != handler.tokens.instance_id
