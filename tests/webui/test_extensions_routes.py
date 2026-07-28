from __future__ import annotations

import json
from types import SimpleNamespace
from urllib.parse import quote

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

    async def install(self, source, *, kind, ref, trusted):
        self.calls.append(("install", (source, kind, ref, trusted)))
        return {"record": {"id": "sample"}}

    async def set_trusted(self, extension_id, trusted):
        self.calls.append(("trust", (extension_id, trusted)))
        return {"record": {"id": extension_id}}

    async def set_permissions(self, extension_id, permissions):
        self.calls.append(("permissions", (extension_id, permissions)))
        return {"record": {"id": extension_id}}


def _router(
    service: _Service,
    *,
    authorized: bool = True,
    allow_remote: bool = False,
) -> WebUIExtensionsRouter:
    return WebUIExtensionsRouter(
        service=service,
        check_api_token=lambda _request: authorized,
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
):
    headers = Headers([("Host", host)])
    if values is not None:
        headers["X-Nanobot-Extension-Values"] = quote(json.dumps(values))
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
async def test_local_install_is_untrusted() -> None:
    service = _Service()
    response = await _router(service).dispatch(
        _LOCAL,
        _request(
            "/api/extensions/install",
            method="POST",
            values={"source": "https://example.com/acme.git", "kind": "git"},
        ),
        "/api/extensions/install",
    )

    assert response is not None and response.status_code == 200
    assert service.calls == [
        ("install", ("https://example.com/acme.git", "git", "", False)),
    ]


@pytest.mark.asyncio
async def test_remote_policy_allows_git_but_never_local_paths() -> None:
    service = _Service()
    denied = await _router(service).dispatch(
        _REMOTE,
        _request(
            "/api/extensions/install",
            method="POST",
            values={"source": "https://example.com/acme.git", "kind": "git"},
        ),
        "/api/extensions/install",
    )
    allowed = await _router(service, allow_remote=True).dispatch(
        _REMOTE,
        _request(
            "/api/extensions/install",
            method="POST",
            values={"source": "https://example.com/acme.git", "kind": "git"},
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
    assert allowed is not None and allowed.status_code == 200
    assert local_denied is not None and local_denied.status_code == 403
    assert service.calls == [
        ("install", ("https://example.com/acme.git", "git", "", False)),
    ]


@pytest.mark.asyncio
async def test_remote_clients_cannot_change_trust() -> None:
    service = _Service()
    response = await _router(service, allow_remote=True).dispatch(
        _REMOTE,
        _request(
            "/api/extensions/trust",
            method="POST",
            values={"id": "sample"},
        ),
        "/api/extensions/trust",
    )

    assert response is not None and response.status_code == 403
    assert service.calls == []


@pytest.mark.asyncio
async def test_permissions_require_an_array_of_strings() -> None:
    response = await _router(_Service()).dispatch(
        _LOCAL,
        _request(
            "/api/extensions/permissions",
            method="POST",
            values={"id": "sample", "permissions": "network"},
        ),
        "/api/extensions/permissions",
    )

    assert response is not None and response.status_code == 400
