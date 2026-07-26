"""Strict JSON codec for portable extension manifests."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from nanobot.extensions.manifest import (
    EXTENSION_API_VERSION,
    ContributionKind,
    DependencyKind,
    ExtensionContribution,
    ExtensionDependency,
    ExtensionManifest,
    ExtensionPermission,
    ExtensionRuntime,
)

MANIFEST_FILENAME = "nanobot.extension.json"

_MANIFEST_KEYS = frozenset(
    {
        "id",
        "name",
        "version",
        "runtime",
        "entry",
        "entries",
        "contributions",
        "description",
        "dependencies",
        "permissions",
        "apiVersion",
        "homepage",
        "license",
    }
)
_CONTRIBUTION_KEYS = frozenset(
    {"kind", "name", "target", "description", "replaces"}
)
_DEPENDENCY_KEYS = frozenset({"kind", "name", "specifier", "optional"})
_PERMISSION_KEYS = frozenset({"name", "reason"})


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
    payload = json.dumps(
        manifest_to_mapping(manifest),
        ensure_ascii=False,
        indent=2,
    )
    path.write_text(payload + "\n", encoding="utf-8")


def manifest_from_mapping(data: object) -> ExtensionManifest:
    """Decode a mapping while rejecting misspelled or ambiguous fields."""
    mapping = _mapping(data, "extension manifest")
    _reject_unknown(mapping, _MANIFEST_KEYS, "extension manifest")
    try:
        contributions = tuple(
            _contribution_from_mapping(item)
            for item in _sequence(mapping.get("contributions", ()), "contributions")
        )
        dependencies = tuple(
            _dependency_from_mapping(item)
            for item in _sequence(mapping.get("dependencies", ()), "dependencies")
        )
        permissions = tuple(
            _permission_from_mapping(item)
            for item in _sequence(mapping.get("permissions", ()), "permissions")
        )
        return ExtensionManifest(
            id=mapping["id"],
            name=mapping["name"],
            version=mapping["version"],
            runtime=ExtensionRuntime(mapping["runtime"]),
            entry=mapping.get("entry", ""),
            entries=tuple(_sequence(mapping.get("entries", ()), "entries")),
            contributions=contributions,
            description=mapping.get("description", ""),
            dependencies=dependencies,
            permissions=permissions,
            api_version=mapping.get("apiVersion", EXTENSION_API_VERSION),
            homepage=mapping.get("homepage", ""),
            license=mapping.get("license", ""),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ManifestFormatError(f"invalid extension manifest: {exc}") from exc


def manifest_to_mapping(manifest: ExtensionManifest) -> dict[str, Any]:
    """Return the stable wire representation used by sidecars and catalogs."""
    return {
        "id": manifest.id,
        "name": manifest.name,
        "version": manifest.version,
        "apiVersion": manifest.api_version,
        "runtime": manifest.runtime.value,
        "entry": manifest.entry,
        "entries": list(manifest.entries),
        "description": manifest.description,
        "homepage": manifest.homepage,
        "license": manifest.license,
        "contributions": [
            {
                "kind": item.kind.value,
                "name": item.name,
                "target": item.target,
                "description": item.description,
                "replaces": list(item.replaces),
            }
            for item in manifest.contributions
        ],
        "dependencies": [
            {
                "kind": item.kind.value,
                "name": item.name,
                "specifier": item.specifier,
                "optional": item.optional,
            }
            for item in manifest.dependencies
        ],
        "permissions": [
            {"name": item.name, "reason": item.reason}
            for item in manifest.permissions
        ],
    }


def _contribution_from_mapping(data: object) -> ExtensionContribution:
    mapping = _mapping(data, "extension contribution")
    _reject_unknown(mapping, _CONTRIBUTION_KEYS, "extension contribution")
    try:
        return ExtensionContribution(
            kind=ContributionKind(mapping["kind"]),
            name=mapping["name"],
            target=mapping.get("target", ""),
            description=mapping.get("description", ""),
            replaces=tuple(
                _sequence(mapping.get("replaces", ()), "contribution replaces")
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ManifestFormatError(f"invalid extension contribution: {exc}") from exc


def _dependency_from_mapping(data: object) -> ExtensionDependency:
    mapping = _mapping(data, "extension dependency")
    _reject_unknown(mapping, _DEPENDENCY_KEYS, "extension dependency")
    try:
        return ExtensionDependency(
            kind=DependencyKind(mapping["kind"]),
            name=mapping["name"],
            specifier=mapping.get("specifier", ""),
            optional=mapping.get("optional", False),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ManifestFormatError(f"invalid extension dependency: {exc}") from exc


def _permission_from_mapping(data: object) -> ExtensionPermission:
    mapping = _mapping(data, "extension permission")
    _reject_unknown(mapping, _PERMISSION_KEYS, "extension permission")
    try:
        return ExtensionPermission(
            name=mapping["name"],
            reason=mapping.get("reason", ""),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ManifestFormatError(f"invalid extension permission: {exc}") from exc


def _mapping(data: object, label: str) -> Mapping[str, Any]:
    if not isinstance(data, Mapping) or not all(
        isinstance(key, str) for key in data
    ):
        raise ManifestFormatError(f"{label} must be a JSON object")
    return data


def _sequence(data: object, label: str) -> list[Any] | tuple[Any, ...]:
    if not isinstance(data, (list, tuple)):
        raise ManifestFormatError(f"{label} must be a JSON array")
    return data


def _reject_unknown(
    mapping: Mapping[str, Any],
    allowed: frozenset[str],
    label: str,
) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise ManifestFormatError(f"{label} has unknown fields: {', '.join(unknown)}")
