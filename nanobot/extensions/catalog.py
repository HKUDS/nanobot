"""Assemble native and installed extensions into one inspectable catalog."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from nanobot.extensions.discovery import (
    ExtensionDiscoveryResult,
    discover_manifest_root,
)
from nanobot.extensions.native import discover_native_extensions
from nanobot.extensions.registry import (
    ExtensionCandidate,
    ExtensionDiagnostic,
    ExtensionPolicy,
    ExtensionRegistry,
    ExtensionScope,
    ExtensionSnapshot,
)

if TYPE_CHECKING:
    from nanobot.agent.skills import SkillsLoader
    from nanobot.agent.tools.registry import ToolRegistry
    from nanobot.command.router import CommandRouter
    from nanobot.config.schema import Config


@dataclass(frozen=True, slots=True)
class ExtensionCatalog:
    """Discovered candidates plus the active, policy-resolved snapshot."""

    candidates: tuple[ExtensionCandidate, ...]
    snapshot: ExtensionSnapshot
    diagnostics: tuple[ExtensionDiagnostic, ...]


def build_extension_catalog(
    config: Config,
    *,
    skills: SkillsLoader | None = None,
    tools: ToolRegistry | None = None,
    commands: CommandRouter | None = None,
    user_root: Path | None = None,
) -> ExtensionCatalog:
    """Build the authoritative extension view without executing plugin code."""
    native = discover_native_extensions(
        config,
        skills=skills,
        tools=tools,
        commands=commands,
    )
    discoveries = [native]
    if config.extensions.enabled:
        discoveries.extend(
            _external_discoveries(
                config,
                user_root=user_root or Path.home() / ".nanobot" / "extensions",
            )
        )

    candidates = tuple(
        _apply_entry_config(config, candidate)
        for result in discoveries
        for candidate in result.candidates
    )
    discovery_diagnostics = tuple(
        diagnostic
        for result in discoveries
        for diagnostic in result.diagnostics
    )
    registry = ExtensionRegistry(
        ExtensionPolicy(
            allow=frozenset(config.extensions.allow),
            deny=frozenset(config.extensions.deny),
        )
    )
    registry_diagnostics: list[ExtensionDiagnostic] = []
    for candidate in candidates:
        try:
            registry.register(candidate)
        except ValueError as exc:
            registry_diagnostics.append(
                ExtensionDiagnostic(
                    code="duplicate_installation",
                    extension_id=candidate.manifest.id,
                    message=str(exc),
                )
            )
    snapshot = registry.snapshot()
    diagnostics = (
        discovery_diagnostics
        + tuple(registry_diagnostics)
        + snapshot.diagnostics
    )
    return ExtensionCatalog(candidates, snapshot, diagnostics)


def _external_discoveries(
    config: Config,
    *,
    user_root: Path,
) -> Iterable[ExtensionDiscoveryResult]:
    yield discover_manifest_root(
        user_root,
        scope=ExtensionScope.USER,
    )
    for raw_path in config.extensions.paths:
        yield discover_manifest_root(
            Path(raw_path).expanduser(),
            scope=ExtensionScope.USER,
        )

    workspace_root = config.workspace_path / ".nanobot" / "extensions"
    workspace_trust = config.extensions.workspace_trust
    if workspace_trust != "deny":
        yield discover_manifest_root(
            workspace_root,
            scope=ExtensionScope.WORKSPACE,
            trusted=workspace_trust == "allow",
        )


def _apply_entry_config(
    config: Config,
    candidate: ExtensionCandidate,
) -> ExtensionCandidate:
    entry = config.extensions.entries.get(candidate.manifest.id)
    if entry is None or candidate.scope is ExtensionScope.BUILTIN:
        return candidate
    return replace(
        candidate,
        enabled=entry.enabled,
        trusted=candidate.trusted or entry.trusted,
    )
