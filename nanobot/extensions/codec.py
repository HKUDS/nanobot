"""JSON persistence for extension manifests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from nanobot.extensions.manifest import ExtensionManifest

MANIFEST_FILENAME = "nanobot.extension.json"


class ManifestFormatError(ValueError):
    """Raised when a manifest cannot be decoded unambiguously."""


def load_manifest(path: Path) -> ExtensionManifest:
    """Read and validate one canonical JSON manifest."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestFormatError(f"cannot read extension manifest {path}: {exc}") from exc
    return manifest_from_mapping(data)


def dump_manifest(manifest: ExtensionManifest, path: Path) -> None:
    """Write one canonical JSON manifest."""
    path.write_text(
        json.dumps(manifest_to_mapping(manifest), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def manifest_from_mapping(data: object) -> ExtensionManifest:
    """Decode a manifest and reject unknown or invalid fields."""
    try:
        return ExtensionManifest.model_validate(data)
    except ValidationError as exc:
        unknown = sorted(
            ".".join(str(part) for part in error["loc"])
            for error in exc.errors()
            if error["type"] == "extra_forbidden"
        )
        if unknown:
            raise ManifestFormatError(
                f"extension manifest has unknown fields: {', '.join(unknown)}"
            ) from exc
        raise ManifestFormatError(f"invalid extension manifest: {exc}") from exc


def manifest_to_mapping(manifest: ExtensionManifest) -> dict[str, Any]:
    """Return the canonical JSON representation."""
    return manifest.model_dump(mode="json", by_alias=True)
