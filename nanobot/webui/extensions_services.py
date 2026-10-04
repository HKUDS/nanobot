"""Gateway-owned state for the WebUI extensions surface."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from nanobot.config.paths import get_data_dir
from nanobot.webui.extensions_api import (
    WebUIExtension,
    WebUIExtensionError,
    discover_extensions,
    extensions_payload,
    load_extension,
)


def _default_extensions_root() -> Path:
    """Return the instance-level WebUI extensions directory."""
    return get_data_dir() / "extensions"


class WebUIExtensions:
    """Discover and serve WebUI extensions from a configurable root.

    The root defaults to ``<data-dir>/extensions`` and is created lazily so
    the surface exists (and stays empty) even when the user never installs an
    extension. The gateway builds one instance per gateway process.
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else _default_extensions_root()

    def _directory(self, extension_id: str) -> Path | None:
        if not self.root.is_dir():
            return None
        directory = (self.root / extension_id).resolve()
        if directory.parent != self.root.resolve():
            return None
        if not directory.is_dir():
            return None
        return directory

    def _manifest(self, extension_id: str) -> dict[str, Any] | None:
        directory = self._directory(extension_id)
        if directory is None:
            return None
        manifest_path = directory / "extension.json"
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return raw if isinstance(raw, dict) else None

    def _write_manifest(self, extension_id: str, manifest: dict[str, Any]) -> None:
        directory = self._directory(extension_id)
        if directory is None:
            raise WebUIExtensionError(f"extension {extension_id!r} not found")
        target = directory / "extension.json"
        payload = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
        temp = target.with_suffix(".json.tmp")
        temp.write_text(payload + "\n", encoding="utf-8")
        os.replace(temp, target)

    def discover(self) -> list[WebUIExtension]:
        return discover_extensions(self.root)

    def get(self, extension_id: str) -> WebUIExtension | None:
        directory = self._directory(extension_id)
        if directory is None:
            return None
        try:
            return load_extension(directory)
        except WebUIExtensionError:
            return None

    def set_enabled(self, extension_id: str, enabled: bool) -> bool:
        extension = self.get(extension_id)
        if extension is None:
            return False
        manifest = self._manifest(extension_id)
        if manifest is None:
            return False
        manifest["enabled"] = bool(enabled)
        self._write_manifest(extension_id, manifest)
        return True

    def set_config(self, extension_id: str, config: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(config, dict):
            raise WebUIExtensionError("extension config must be an object", status=400)
        extension = self.get(extension_id)
        if extension is None:
            raise WebUIExtensionError(f"extension {extension_id!r} not found", status=404)
        manifest = self._manifest(extension_id)
        if manifest is None:
            raise WebUIExtensionError(f"extension {extension_id!r} manifest is invalid", status=400)
        manifest["config"] = config
        self._write_manifest(extension_id, manifest)
        return dict(config)

    def remove(self, extension_id: str) -> bool:
        directory = self._directory(extension_id)
        if directory is None:
            return False
        try:
            shutil.rmtree(directory)
        except OSError:
            return False
        return True

    def payload(self) -> dict[str, object]:
        """Return the extension catalog for the WebUI."""
        return extensions_payload(self.root)
