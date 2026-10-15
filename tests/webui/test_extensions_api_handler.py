from __future__ import annotations

import json
from pathlib import Path

from nanobot.webui.extensions_api import load_extension
from nanobot.webui.extensions_api_handler import dispatch_extension_api


def _write_extension(root: Path, api_script: str | None = None) -> Path:
    directory = root / "demo"
    directory.mkdir(parents=True)
    manifest = {
        "id": "demo",
        "name": "Demo",
        "description": "demo",
        "entry": "index.html",
        "version": "0.1.0",
    }
    if api_script:
        manifest["api"] = {"script": api_script}
    (directory / "extension.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    (directory / "index.html").write_text("<h1>demo</h1>", encoding="utf-8")
    if api_script:
        (directory / api_script).write_text(
            "def handle(request_path, query, body):\n"
            "    if request_path == '/ping':\n"
            "        return 200, {}, b'pong'\n"
            "    return 404, {'Content-Type': 'application/json'}, b'{\"error\":\"nope\"}'\n",
            encoding="utf-8",
        )
    return directory


def test_extension_api_dispatch_calls_handler(tmp_path) -> None:
    extension = load_extension(_write_extension(tmp_path, "api.py"))
    assert extension is not None
    assert extension.api_script == "api.py"

    status, headers, body = dispatch_extension_api(extension, "/ping", {}, b"")

    assert status == 200
    assert body == b"pong"


def test_extension_api_dispatch_404_without_script(tmp_path) -> None:
    extension = load_extension(_write_extension(tmp_path))
    assert extension is not None
    assert extension.api_script == ""

    status, headers, body = dispatch_extension_api(extension, "/ping", {}, b"")

    assert status == 404
    assert b"no api.script" in body


def test_extension_api_dispatch_handles_json_dict_response(tmp_path) -> None:
    extension = load_extension(_write_extension(tmp_path, "api.py"))
    assert extension is not None

    status, headers, body = dispatch_extension_api(extension, "/nope", {}, b"")

    assert status == 404
    assert headers["Content-Type"].startswith("application/json")
    assert b"nope" in body


def test_extension_api_dispatch_reloads_after_edit(tmp_path) -> None:
    extension = load_extension(_write_extension(tmp_path, "api.py"))
    assert extension is not None
    assert dispatch_extension_api(extension, "/ping", {}, b"")[2] == b"pong"

    # Edit the handler; the next dispatch should pick it up without restart.
    (extension.root / "api.py").write_text(
        "def handle(request_path, query, body):\n"
        "    return 200, {}, b'updated'\n",
        encoding="utf-8",
    )

    status, _, body = dispatch_extension_api(extension, "/ping", {}, b"")
    assert status == 200
    assert body == b"updated"
