from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from websockets.datastructures import Headers
from websockets.http11 import Request as WsRequest

from nanobot.channels.websocket.runtime import WebSocketConfig
from nanobot.webui.ws_http import GatewayHTTPHandler


def _handler(config: WebSocketConfig) -> GatewayHTTPHandler:
    handler = object.__new__(GatewayHTTPHandler)
    handler.config = config
    return handler


def _request(**headers: str) -> WsRequest:
    return cast(WsRequest, SimpleNamespace(headers=Headers(headers)))


def test_mcp_oauth_callback_uses_configured_public_websocket_origin() -> None:
    handler = _handler(WebSocketConfig(path="/ws", public_ws_url="wss://agent.example/ws"))

    redirect_uri = handler._mcp_oauth_redirect_uri(_request(Host="ignored.example"))

    assert redirect_uri == "https://agent.example/auth/mcp/callback"


def test_mcp_oauth_callback_uses_safe_forwarded_request_origin() -> None:
    handler = _handler(WebSocketConfig(path="/ws", host="127.0.0.1", port=8765))

    redirect_uri = handler._mcp_oauth_redirect_uri(
        _request(Host="nanobot.example:9443", **{"X-Forwarded-Proto": "https"})
    )

    assert redirect_uri == "https://nanobot.example:9443/auth/mcp/callback"
