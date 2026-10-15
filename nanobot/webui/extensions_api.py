"""WebUI extensions: discover, validate, and serve extension assets.

An extension is a directory containing a ``extension.json`` manifest plus
static files (HTML, JS, CSS, images). Extensions are discovered from a
configurable root directory (``WebUIExtensions``), validated against a
minimal manifest contract, and served by the gateway under two namespaces:

- ``/api/extensions/<id>/...``  JSON API routes (require the WebUI API token)
- ``/extensions/<id>/...``      static assets (require the WebUI API token)

The manifest contract stays intentionally small so extensions can be
distributed as plain folders:

.. code-block:: json

    {
      "id": "glucose-browser",
      "name": "Glucose Research Browser",
      "description": "Browse the glucose research article database.",
      "entry": "index.html",
      "version": "0.1.0"
    }
"""

from __future__ import annotations

import json
import mimetypes
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nanobot.security.workspace_policy import (
    WorkspaceBoundaryError,
    require_path_within,
)

_EXTENSION_MANIFEST = "extension.json"
_EXTENSION_ID = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
_MAX_ENTRY_DEPTH = 8


class WebUIExtensionError(ValueError):
    """User-facing extension validation or serving failure."""

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass(frozen=True)
class WebUIExtension:
    """A validated, discoverable WebUI extension."""

    id: str
    name: str
    description: str
    entry: str
    version: str
    root: Path
    enabled: bool = True
    config: dict[str, Any] = field(default_factory=dict)
    api_script: str = ""

    def asset_path(self, relative: str) -> Path:
        """Resolve *relative* inside this extension's root, guarding traversal."""
        try:
            return require_path_within(self.root / relative, self.root)
        except WorkspaceBoundaryError as exc:
            raise WebUIExtensionError(
                f"extension {self.id}: path escapes extension root",
                status=403,
            ) from exc


def _manifest_payload(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _manifest_string(manifest: dict[str, Any], key: str) -> str:
    value = manifest.get(key)
    if not isinstance(value, str) or not value.strip():
        raise WebUIExtensionError(f"extension.json missing string field {key!r}")
    return value.strip()


def load_extension(root: Path) -> WebUIExtension | None:
    """Validate and load one extension directory, or return ``None`` when it is not one."""
    manifest = _manifest_payload(root / _EXTENSION_MANIFEST)
    if manifest is None:
        return None
    extension_id = _manifest_string(manifest, "id")
    if _EXTENSION_ID.fullmatch(extension_id) is None:
        raise WebUIExtensionError(
            f"invalid extension id {extension_id!r} (must match {_EXTENSION_ID.pattern})"
        )
    entry = _manifest_string(manifest, "entry")
    entry = entry.removeprefix("./")
    if (
        not entry
        or entry.startswith("/")
        or ".." in entry.split("/")
        or len(entry.split("/")) > _MAX_ENTRY_DEPTH
    ):
        raise WebUIExtensionError(f"invalid extension entry {entry!r}")
    if not (root / entry).is_file():
        raise WebUIExtensionError(f"extension entry {entry!r} is missing")
    api = manifest.get("api")
    api_script = ""
    if isinstance(api, dict):
        raw_script = api.get("script")
        if isinstance(raw_script, str) and raw_script.strip():
            api_script = raw_script.strip().removeprefix("./")
            if (
                not api_script
                or api_script.startswith("/")
                or ".." in api_script.split("/")
            ):
                raise WebUIExtensionError(f"invalid extension api.script {api_script!r}")
            if not (root / api_script).is_file():
                raise WebUIExtensionError(
                    f"extension api.script {api_script!r} is missing"
                )
    enabled = manifest.get("enabled", True)
    config = manifest.get("config", {})
    return WebUIExtension(
        id=extension_id,
        name=_manifest_string(manifest, "name"),
        description=_manifest_string(manifest, "description"),
        entry=entry,
        version=_manifest_string(manifest, "version"),
        root=root,
        enabled=bool(enabled) if isinstance(enabled, bool) else True,
        config=config if isinstance(config, dict) else {},
        api_script=api_script,
    )


def discover_extensions(root: Path) -> list[WebUIExtension]:
    """Discover valid extensions from *root*'s immediate subdirectories.

    Invalid manifests are skipped instead of breaking the whole catalog, so
    one broken directory cannot take down the extensions surface.
    """
    if not root.is_dir():
        return []
    extensions: list[WebUIExtension] = []
    for directory in sorted(root.iterdir()):
        if not directory.is_dir():
            continue
        try:
            extension = load_extension(directory)
        except WebUIExtensionError:
            continue
        if extension is not None:
            extensions.append(extension)
    return extensions


def extension_payload(extension: WebUIExtension) -> dict[str, Any]:
    """Return a safe, path-free manifest payload for the WebUI."""
    payload: dict[str, Any] = {
        "id": extension.id,
        "name": extension.name,
        "description": extension.description,
        "entry": extension.entry,
        "version": extension.version,
        "enabled": extension.enabled,
    }
    if extension.config:
        payload["config"] = dict(extension.config)
    return payload


def extensions_payload(root: Path) -> dict[str, Any]:
    """Return the full extension catalog for the WebUI."""
    return {"extensions": [extension_payload(item) for item in discover_extensions(root)]}


def serve_extension_asset(
    extension: WebUIExtension,
    relative: str,
    *,
    default: str = "index.html",
) -> tuple[bytes, str]:
    """Read one extension asset, falling back to *default* for directory roots.

    Returns ``(body, content_type)``. Raises :class:`WebUIExtensionError` when
    neither the requested asset nor the default entry can be served.
    """
    relative = relative.lstrip("/") or default
    candidate = extension.asset_path(relative)
    if not candidate.is_file() and relative != default:
        candidate = extension.asset_path(default)
    if not candidate.is_file():
        raise WebUIExtensionError(
            f"extension {extension.id}: asset {relative!r} not found",
            status=404,
        )
    content_type, _ = mimetypes.guess_type(candidate.name)
    if content_type is None:
        content_type = "application/octet-stream"
    if content_type.startswith("text/") or content_type in {
        "application/javascript",
        "application/json",
    }:
        content_type = f"{content_type}; charset=utf-8"
    try:
        return candidate.read_bytes(), content_type
    except OSError as exc:
        raise WebUIExtensionError(
            f"extension {extension.id}: failed to read {candidate.name}",
            status=500,
        ) from exc
