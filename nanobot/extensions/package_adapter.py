"""Translate Pi and OpenClaw package metadata into the nanobot manifest."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nanobot.extensions.codec import MANIFEST_FILENAME, load_manifest
from nanobot.extensions.manifest import (
    ContributionKind,
    DependencyKind,
    ExtensionContribution,
    ExtensionDependency,
    ExtensionManifest,
    ExtensionPermission,
    ExtensionRuntime,
)

_ID_CHARS = re.compile(r"[^a-z0-9._-]+")
_OPENCLAW_CONTRACT_KINDS = {
    "tools": ContributionKind.TOOL,
    "realtimeTranscriptionProviders": ContributionKind.TRANSCRIPTION_PROVIDER,
    "imageGenerationProviders": ContributionKind.IMAGE_GENERATION_PROVIDER,
    "webSearchProviders": ContributionKind.WEB_SEARCH_PROVIDER,
}
_TYPESCRIPT_SUFFIXES = (".ts", ".tsx", ".cts", ".mts")
_JITI_DEPENDENCY = ExtensionDependency(
    kind=DependencyKind.NPM,
    name="jiti",
    specifier="^2.4.2",
)
_NODE_RUNTIME_PERMISSION = ExtensionPermission(
    name="runtime.node",
    reason="Run third-party JavaScript or TypeScript in a Node.js process.",
)


@dataclass(frozen=True, slots=True)
class AdaptedPackage:
    """Canonical metadata plus honest compatibility diagnostics."""

    manifest: ExtensionManifest
    diagnostics: tuple[str, ...] = ()
    generated: bool = False


def adapt_package(root: Path) -> AdaptedPackage:
    """Load native metadata or adapt one supported JavaScript package."""
    root = root.resolve()
    canonical = root / MANIFEST_FILENAME
    if canonical.is_file():
        return AdaptedPackage(load_manifest(canonical))

    package = _read_json(root / "package.json", "package.json")
    if isinstance(package.get("pi"), dict):
        return _adapt_pi(package)
    if isinstance(package.get("openclaw"), dict):
        return _adapt_openclaw(root, package)
    raise ValueError(
        f"{root} is not a nanobot, Pi, or OpenClaw extension package"
    )


def _adapt_pi(package: dict[str, Any]) -> AdaptedPackage:
    pi = package["pi"]
    entries = _string_list(pi.get("extensions"), "pi.extensions")
    name = str(package.get("name") or "pi-extension")
    return AdaptedPackage(
        ExtensionManifest(
            id=f"pi.{_identifier(name)}",
            name=str(package.get("displayName") or name),
            version=str(package.get("version") or "0.0.0"),
            runtime=ExtensionRuntime.PI,
            entries=tuple(entries),
            dependencies=(_JITI_DEPENDENCY,) if _has_typescript(entries) else (),
            permissions=(_NODE_RUNTIME_PERMISSION,),
            description=str(package.get("description") or ""),
            homepage=_homepage(package),
            license=str(package.get("license") or ""),
        ),
        generated=True,
    )


def _adapt_openclaw(root: Path, package: dict[str, Any]) -> AdaptedPackage:
    openclaw = package["openclaw"]
    entries = _optional_string_list(
        openclaw.get("runtimeExtensions"),
        "openclaw.runtimeExtensions",
    ) or _string_list(openclaw.get("extensions"), "openclaw.extensions")
    plugin_path = root / "openclaw.plugin.json"
    plugin = _read_json(plugin_path, "openclaw.plugin.json") if plugin_path.is_file() else {}
    plugin_id = str(plugin.get("id") or package.get("name") or "openclaw-plugin")
    contributions = _openclaw_contributions(plugin)
    diagnostics: list[str] = []
    contracts = plugin.get("contracts")
    if isinstance(contracts, dict):
        unsupported = sorted(
            key for key, value in contracts.items()
            if value and key not in _OPENCLAW_CONTRACT_KINDS
        )
        if unsupported:
            diagnostics.append(
                "OpenClaw capabilities retained as metadata but not executable: "
                + ", ".join(unsupported)
            )
    return AdaptedPackage(
        ExtensionManifest(
            id=f"openclaw.{_identifier(plugin_id)}",
            name=str(plugin.get("name") or package.get("name") or plugin_id),
            version=str(package.get("version") or plugin.get("version") or "0.0.0"),
            runtime=ExtensionRuntime.OPENCLAW,
            entries=tuple(entries),
            contributions=contributions,
            dependencies=_openclaw_dependencies(package, openclaw),
            permissions=(_NODE_RUNTIME_PERMISSION,),
            description=str(
                plugin.get("description") or package.get("description") or ""
            ),
            homepage=_homepage(package),
            license=str(package.get("license") or ""),
        ),
        diagnostics=tuple(diagnostics),
        generated=True,
    )


def _openclaw_dependencies(
    package: dict[str, Any],
    openclaw: dict[str, Any],
) -> tuple[ExtensionDependency, ...]:
    build = openclaw.get("build")
    version = build.get("openclawVersion") if isinstance(build, dict) else None
    peers = package.get("peerDependencies")
    peer_version = peers.get("openclaw") if isinstance(peers, dict) else None
    return (
        ExtensionDependency(
            kind=DependencyKind.NPM,
            name="openclaw",
            specifier=str(version or peer_version or "latest"),
        ),
    )


def _openclaw_contributions(
    plugin: dict[str, Any],
) -> tuple[ExtensionContribution, ...]:
    rows: list[ExtensionContribution] = []
    direct = {
        "channels": ContributionKind.CHANNEL,
        "providers": ContributionKind.LLM_PROVIDER,
        "skills": ContributionKind.SKILL,
    }
    for field, kind in direct.items():
        for name in _optional_string_list(plugin.get(field), field):
            rows.append(ExtensionContribution(kind=kind, name=_identifier(name)))
    contracts = plugin.get("contracts")
    if isinstance(contracts, dict):
        for field, kind in _OPENCLAW_CONTRACT_KINDS.items():
            for name in _optional_string_list(contracts.get(field), field):
                rows.append(ExtensionContribution(kind=kind, name=_identifier(name)))
    for alias in plugin.get("commandAliases", []):
        if isinstance(alias, dict) and isinstance(alias.get("name"), str):
            rows.append(
                ExtensionContribution(
                    kind=ContributionKind.COMMAND,
                    name=_identifier(alias["name"]),
                )
            )
    return tuple(dict.fromkeys(rows))


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return value


def _string_list(value: object, label: str) -> list[str]:
    rows = _optional_string_list(value, label)
    if not rows:
        raise ValueError(f"{label} must contain at least one entry")
    return rows


def _optional_string_list(value: object, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise ValueError(f"{label} must be an array of non-empty strings")
    return value


def _identifier(value: str) -> str:
    normalized = value.lower().replace("@", "").replace("/", ".")
    normalized = _ID_CHARS.sub("-", normalized).strip(".-_")
    return normalized or "extension"


def _homepage(package: dict[str, Any]) -> str:
    homepage = package.get("homepage")
    if isinstance(homepage, str):
        return homepage
    repository = package.get("repository")
    if isinstance(repository, str):
        return repository
    if isinstance(repository, dict) and isinstance(repository.get("url"), str):
        return repository["url"]
    return ""


def _has_typescript(entries: list[str]) -> bool:
    return any(entry.lower().endswith(_TYPESCRIPT_SUFFIXES) for entry in entries)
