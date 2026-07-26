from __future__ import annotations

import json
from types import SimpleNamespace
from urllib.parse import parse_qs, quote, urlsplit

import pytest
from websockets.datastructures import Headers

from nanobot.webui.extensions_routes import WebUIExtensionsRouter
from nanobot.webui.http_utils import http_json_response


class _Service:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def status(self):
        self.calls.append(("status", None))
        return {"extensions": [], "diagnostics": []}

    async def search(self, query, *, ecosystem, limit):
        self.calls.append(("search", (query, ecosystem, limit)))
        return {"packages": []}

    async def install(self, source, *, kind, ref, trusted):
        self.calls.append(("install", (source, kind, ref, trusted)))
        return {"record": {"id": "sample"}}


def _router(
    service: _Service,
    *,
    authorized: bool = True,
    allow_remote: bool = False,
) -> WebUIExtensionsRouter:
    return WebUIExtensionsRouter(
        service=service,
        check_api_token=lambda _request: authorized,
        parse_query=lambda path: parse_qs(urlsplit(path).query),
        json_response=http_json_response,
        error_response=lambda status, message: http_json_response(
            {"error": message},
            status=status,
        ),
        allow_remote_package_install=allow_remote,
        logger=SimpleNamespace(exception=lambda *_args: None),
    )


def _request(
    path: str,
    *,
    method: str = "GET",
    values: dict[str, object] | None = None,
    host: str = "127.0.0.1:8765",
    encode_values: bool = False,
):
    headers = Headers([("Host", host)])
    if values is not None:
        payload = json.dumps(values)
        headers["X-Nanobot-Extension-Values"] = quote(payload) if encode_values else payload
    return SimpleNamespace(path=path, method=method, headers=headers)


_LOCAL = SimpleNamespace(remote_address=("127.0.0.1", 12345))
_REMOTE = SimpleNamespace(remote_address=("192.0.2.1", 12345))


@pytest.mark.asyncio
async def test_extension_status_requires_auth_and_get() -> None:
    service = _Service()

    unauthorized = await _router(service, authorized=False).dispatch(
        _LOCAL,
        _request("/api/extensions"),
        "/api/extensions",
    )
    wrong_method = await _router(service).dispatch(
        _LOCAL,
        _request("/api/extensions", method="POST"),
        "/api/extensions",
    )
    response = await _router(service).dispatch(
        _LOCAL,
        _request("/api/extensions"),
        "/api/extensions",
    )

    assert unauthorized is not None and unauthorized.status_code == 401
    assert wrong_method is not None and wrong_method.status_code == 405
    assert response is not None and response.status_code == 200
    assert service.calls == [("status", None)]


@pytest.mark.asyncio
async def test_extension_market_parses_query() -> None:
    service = _Service()
    response = await _router(service).dispatch(
        _LOCAL,
        _request("/api/extensions/market?q=web&ecosystem=pi&limit=7"),
        "/api/extensions/market",
    )

    assert response is not None and response.status_code == 200
    assert service.calls == [("search", ("web", "pi", 7))]


@pytest.mark.asyncio
async def test_extension_install_is_local_and_untrusted() -> None:
    service = _Service()
    response = await _router(service).dispatch(
        _LOCAL,
        _request(
            "/api/extensions/install",
            method="POST",
            values={"source": "中文扩展", "kind": "npm"},
            encode_values=True,
        ),
        "/api/extensions/install",
    )

    assert response is not None and response.status_code == 200
    assert service.calls == [
        ("install", ("中文扩展", "npm", "", False)),
    ]


@pytest.mark.asyncio
async def test_remote_install_policy_never_exposes_server_local_paths() -> None:
    service = _Service()
    denied = await _router(service).dispatch(
        _REMOTE,
        _request(
            "/api/extensions/install",
            method="POST",
            values={"source": "pi-example", "kind": "npm"},
        ),
        "/api/extensions/install",
    )
    npm_allowed = await _router(service, allow_remote=True).dispatch(
        _REMOTE,
        _request(
            "/api/extensions/install",
            method="POST",
            values={"source": "pi-example", "kind": "npm"},
        ),
        "/api/extensions/install",
    )
    local_denied = await _router(service, allow_remote=True).dispatch(
        _REMOTE,
        _request(
            "/api/extensions/install",
            method="POST",
            values={"source": "/tmp/example", "kind": "local"},
        ),
        "/api/extensions/install",
    )

    assert denied is not None and denied.status_code == 403
    assert npm_allowed is not None and npm_allowed.status_code == 200
    assert local_denied is not None and local_denied.status_code == 403
    assert service.calls == [
        ("install", ("pi-example", "npm", "", False)),
    ]
