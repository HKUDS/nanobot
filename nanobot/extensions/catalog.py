"""Discover installed extensions and resolve one activation snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from nanobot.extensions.preflight import evaluate_dependencies
from nanobot.extensions.registry import (
    ExtensionCandidate,
    ExtensionDiagnostic,
    ExtensionRegistry,
    ExtensionSnapshot,
)
from nanobot.extensions.store import ExtensionStore

if TYPE_CHECKING:
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
    user_root: Path | None = None,
) -> ExtensionCatalog:
    """Build the authoritative extension view without executing package code."""
    if not config.extensions.enabled:
        return ExtensionCatalog((), ExtensionSnapshot((), ()), ())

    discovery = ExtensionStore(user_root).discover()
    candidates, dependency_diagnostics = evaluate_dependencies(
        discovery.candidates
    )
    registry = ExtensionRegistry()
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
        discovery.diagnostics
        + dependency_diagnostics
        + tuple(registry_diagnostics)
        + snapshot.diagnostics
    )
    return ExtensionCatalog(candidates, snapshot, diagnostics)
