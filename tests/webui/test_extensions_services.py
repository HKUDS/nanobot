from __future__ import annotations

import json
from pathlib import Path

from nanobot.webui.extensions_services import WebUIExtensions


def _write_extension(root: Path, name: str) -> None:
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


def test_discover_empty_root(tmp_path) -> None:
    registry = WebUIExtensions(tmp_path)
    assert registry.discover() == []
    assert registry.payload() == {"extensions": []}


def test_discover_and_get(tmp_path) -> None:
    _write_extension(tmp_path, "demo")
    registry = WebUIExtensions(tmp_path)

    assert [extension.id for extension in registry.discover()] == ["demo"]
    assert registry.get("demo") is not None
    assert registry.get("missing") is None


def test_get_rejects_traversal(tmp_path) -> None:
    _write_extension(tmp_path, "demo")
    registry = WebUIExtensions(tmp_path)

    assert registry.get("../demo") is None
    assert registry.get("demo/../../secret") is None


def test_get_ignores_non_manifest_dirs(tmp_path) -> None:
    (tmp_path / "plain").mkdir()
    registry = WebUIExtensions(tmp_path)

    assert registry.get("plain") is None


def test_manage_extension_lifecycle(tmp_path) -> None:
    _write_extension(tmp_path, "demo")
    registry = WebUIExtensions(tmp_path)

    extension = registry.get("demo")
    assert extension is not None
    assert extension.enabled is True

    assert registry.set_enabled("demo", False) is True
    manifest = json.loads((tmp_path / "demo" / "extension.json").read_text(encoding="utf-8"))
    assert manifest["enabled"] is False
    assert registry.get("demo") is not None
    assert registry.get("demo").enabled is False

    assert registry.set_config("demo", {"theme": "dark", "items": ["one"]}) == {
        "theme": "dark",
        "items": ["one"],
    }
    manifest = json.loads((tmp_path / "demo" / "extension.json").read_text(encoding="utf-8"))
    assert manifest["config"] == {"theme": "dark", "items": ["one"]}

    assert registry.remove("demo") is True
    assert registry.get("demo") is None
