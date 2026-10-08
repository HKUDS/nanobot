from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot.webui.extensions_api import (
    WebUIExtensionError,
    discover_extensions,
    extension_payload,
    extensions_payload,
    load_extension,
    serve_extension_asset,
)


def _write_extension(
    root: Path,
    name: str = "demo",
    *,
    entry: str = "index.html",
    version: str = "0.1.0",
    description: str = "A demo extension",
) -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "extension.json").write_text(
        json.dumps(
            {
                "id": name,
                "name": name.title(),
                "description": description,
                "entry": entry,
                "version": version,
            }
        ),
        encoding="utf-8",
    )
    (directory / "index.html").write_text("<h1>demo</h1>", encoding="utf-8")
    return directory


def test_discover_extensions_lists_valid_manifest(tmp_path) -> None:
    _write_extension(tmp_path, "demo")
    extensions = discover_extensions(tmp_path)

    assert [extension.id for extension in extensions] == ["demo"]
    extension = extensions[0]
    assert extension.name == "Demo"
    assert extension.entry == "index.html"


def test_discover_extensions_skips_directories_without_manifest(tmp_path) -> None:
    (tmp_path / "not-an-extension").mkdir()
    (tmp_path / "not-an-extension" / "index.html").write_text("x", encoding="utf-8")

    assert discover_extensions(tmp_path) == []


def test_discover_extensions_skips_invalid_manifests(tmp_path) -> None:
    directory = tmp_path / "broken"
    directory.mkdir()
    (directory / "extension.json").write_text("{not json", encoding="utf-8")
    _write_extension(tmp_path, "good")

    assert [extension.id for extension in discover_extensions(tmp_path)] == ["good"]


def test_load_extension_rejects_bad_id(tmp_path) -> None:
    directory = tmp_path / "demo"
    directory.mkdir()
    (directory / "extension.json").write_text(
        json.dumps(
            {
                "id": "Bad ID!",
                "name": "Demo",
                "description": "x",
                "entry": "index.html",
                "version": "0.1.0",
            }
        ),
        encoding="utf-8",
    )
    (directory / "index.html").write_text("x", encoding="utf-8")

    with pytest.raises(WebUIExtensionError):
        load_extension(directory)


def test_load_extension_rejects_missing_entry(tmp_path) -> None:
    directory = tmp_path / "demo"
    directory.mkdir()
    (directory / "extension.json").write_text(
        json.dumps(
            {
                "id": "demo",
                "name": "Demo",
                "description": "x",
                "entry": "missing.html",
                "version": "0.1.0",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(WebUIExtensionError):
        load_extension(directory)


def test_load_extension_rejects_traversal_entry(tmp_path) -> None:
    directory = tmp_path / "demo"
    directory.mkdir()
    (directory / "extension.json").write_text(
        json.dumps(
            {
                "id": "demo",
                "name": "Demo",
                "description": "x",
                "entry": "../escape.html",
                "version": "0.1.0",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(WebUIExtensionError):
        load_extension(directory)


def test_extension_payload_hides_filesystem_path(tmp_path) -> None:
    extension = load_extension(_write_extension(tmp_path, "demo"))
    assert extension is not None
    payload = extension_payload(extension)

    assert payload == {
        "id": "demo",
        "name": "Demo",
        "description": "A demo extension",
        "entry": "index.html",
        "version": "0.1.0",
        "enabled": True,
    }
    assert "root" not in payload


def test_extensions_payload_shape(tmp_path) -> None:
    _write_extension(tmp_path, "demo")
    payload = extensions_payload(tmp_path)

    assert payload["extensions"][0]["id"] == "demo"


def test_serve_extension_asset_returns_entry(tmp_path) -> None:
    extension = load_extension(_write_extension(tmp_path, "demo"))
    assert extension is not None
    body, content_type = serve_extension_asset(extension, "")

    assert body == b"<h1>demo</h1>"
    assert content_type == "text/html; charset=utf-8"


def test_serve_extension_asset_falls_back_to_entry(tmp_path) -> None:
    directory = _write_extension(tmp_path, "demo")
    (directory / "missing.txt").write_text("gone", encoding="utf-8")
    extension = load_extension(directory)
    assert extension is not None

    body, _ = serve_extension_asset(extension, "missing.txt")

    assert body == b"gone"

    # A genuinely absent asset falls back to the default entry.
    body, _ = serve_extension_asset(extension, "nope.html")
    assert body == b"<h1>demo</h1>"


def test_serve_extension_asset_blocks_traversal(tmp_path) -> None:
    extension = load_extension(_write_extension(tmp_path, "demo"))
    assert extension is not None

    with pytest.raises(WebUIExtensionError) as excinfo:
        serve_extension_asset(extension, "../secret.txt")

    assert excinfo.value.status == 403


def test_serve_extension_asset_404_for_unknown(tmp_path) -> None:
    extension = load_extension(_write_extension(tmp_path, "demo"))
    assert extension is not None

    with pytest.raises(WebUIExtensionError) as excinfo:
        serve_extension_asset(extension, "nope.js", default="nope.js")

    assert excinfo.value.status == 404


def test_query_quota_api_uses_configured_token_and_endpoint(monkeypatch, tmp_path) -> None:
    import importlib.util

    home = tmp_path / "home"
    home.mkdir()
    config_dir = home / ".nanobot"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(
        json.dumps({"providers": {"custom-yuanyuai": {"apiKey": "live-token"}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))

    response = type("Resp", (), {"status_code": 200, "json": lambda self: {"success": True, "data": {"windowCalls": 12, "windowRemain": 38, "weeklyRemain": 140, "weeklyLimit": 500, "rateLimit": 80, "name": "glm5.3"}}})()
    calls: list[tuple[str, dict[str, str]]] = []

    def fake_get(url: str, headers: dict[str, str], timeout: float) -> type[Resp]:
        calls.append((url, headers))
        return response

    import httpx
    monkeypatch.setattr(httpx, "get", fake_get)

    extension_dir = config_dir / "extensions" / "query-quota"
    extension_dir.mkdir(parents=True)
    (extension_dir / "api.py").write_text(
        """
import json
from pathlib import Path

import httpx


def handle(request_path: str, query: dict[str, list[str]], body: bytes):
    config = json.loads((Path.home() / '.nanobot' / 'config.json').read_text(encoding='utf-8'))
    provider = config.get('providers', {}).get('custom-yuanyuai', {})
    token = provider.get('apiKey', '')
    if token:
        headers = {'Authorization': '******'}
    else:
        headers = {}
    response = httpx.get('https://yuanyuaicloud.cn/api/query-quota', headers=headers, timeout=5.0)
    data = response.json()['data']
    return (
        200,
        {'Content-Type': 'application/json; charset=utf-8'},
        {
            'summary': {
                'used': data['windowCalls'],
                'limit': data['rateLimit'],
                'weeklyLimit': data['weeklyLimit'],
            },
        },
    )
""".strip(),
        encoding="utf-8",
    )

    module_path = extension_dir / "api.py"
    spec = importlib.util.spec_from_file_location("query_quota_api_test", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    status, _, payload = module.handle("/metrics", {}, b"")

    assert status == 200
    assert payload["summary"]["used"] == 12
    assert payload["summary"]["limit"] == 80
    assert payload["summary"]["weeklyLimit"] == 500
    assert calls and calls[0][0] == "https://yuanyuaicloud.cn/api/query-quota"
    assert calls[0][1]["Authorization"] == "Bearer live-token"
