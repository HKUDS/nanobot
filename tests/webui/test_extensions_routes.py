from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

from websockets.datastructures import Headers
from websockets.http11 import Request as WsRequest

from nanobot.webui.extensions_services import WebUIExtensions
from nanobot.webui.ws_http import GatewayHTTPHandler


def _write_extension(root: Path, name: str = "demo") -> None:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "extension.json").write_text(
        json.dumps(
            {
                "id": name,
                "name": name.title(),
                "description": "demo",
                "entry": "index.html",
                "version": "0.1.0",
            }
        ),
        encoding="utf-8",
    )
    (directory / "index.html").write_text("<h1>demo</h1>", encoding="utf-8")
    (directory / "app.js").write_text("console.log('demo');", encoding="utf-8")


def _handler(root: Path, *, authorized: bool = True) -> GatewayHTTPHandler:
    handler = object.__new__(GatewayHTTPHandler)
    handler.extensions = WebUIExtensions(root)
    handler._log = MagicMock()
    handler.check_api_token = MagicMock(return_value=authorized)
    return handler


def _request(path: str) -> WsRequest:
    return cast(WsRequest, SimpleNamespace(path=path, headers=Headers()))


def test_extensions_list_requires_token(tmp_path) -> None:
    _write_extension(tmp_path)
    handler = _handler(tmp_path, authorized=False)

    response = handler._handle_extensions_list(_request("/api/extensions"))

    assert response.status_code == 401


def test_extensions_list_returns_catalog(tmp_path) -> None:
    _write_extension(tmp_path)
    handler = _handler(tmp_path)

    response = handler._handle_extensions_list(_request("/api/extensions"))

    assert response.status_code == 200
    payload = json.loads(response.body)
    assert payload["extensions"][0]["id"] == "demo"


def test_extension_api_returns_manifest(tmp_path) -> None:
    _write_extension(tmp_path)
    handler = _handler(tmp_path)

    response = handler._handle_extension_api(_request("/api/extensions/demo"), "demo", "")

    assert response.status_code == 200
    payload = json.loads(response.body)
    assert payload["id"] == "demo"
    assert "root" not in payload


def test_extension_api_unknown_extension_404(tmp_path) -> None:
    handler = _handler(tmp_path)

    response = handler._handle_extension_api(
        _request("/api/extensions/nope"), "nope", ""
    )

    assert response.status_code == 404


def test_extension_asset_serves_file(tmp_path) -> None:
    _write_extension(tmp_path)
    handler = _handler(tmp_path)

    response = handler._handle_extension_asset(
        _request("/extensions/demo/app.js"), "demo", "app.js"
    )

    assert response.status_code == 200
    assert response.body == b"console.log('demo');"
    assert response.headers["Content-Type"].startswith("application/javascript")


def test_extension_asset_serves_default_entry(tmp_path) -> None:
    _write_extension(tmp_path)
    handler = _handler(tmp_path)

    response = handler._handle_extension_asset(
        _request("/extensions/demo/"), "demo", ""
    )

    assert response.status_code == 200
    assert response.body == b"<h1>demo</h1>"
    assert response.headers["Content-Type"].startswith("text/html")


def test_extension_asset_unknown_extension_404(tmp_path) -> None:
    handler = _handler(tmp_path)

    response = handler._handle_extension_asset(
        _request("/extensions/nope/"), "nope", ""
    )

    assert response.status_code == 404


def test_extension_asset_serves_without_token(tmp_path) -> None:
    """Assets are public read-only files (SPA-like); data stays token-gated."""
    _write_extension(tmp_path)
    handler = _handler(tmp_path, authorized=False)

    response = handler._handle_extension_asset(
        _request("/extensions/demo/app.js"), "demo", "app.js"
    )

    assert response.status_code == 200
    assert response.body == b"console.log('demo');"


def test_dispatch_routes_extension_assets(tmp_path) -> None:
    _write_extension(tmp_path)
    handler = _handler(tmp_path)

    response = asyncio.run(handler._dispatch_extension_routes(
        _request("/extensions/demo/app.js"), "/extensions/demo/app.js"
    ))

    assert response is not None
    assert response.status_code == 200
    assert response.body == b"console.log('demo');"
