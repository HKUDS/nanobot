"""Deterministic extension selection and contribution ownership."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

from nanobot.extensions.manifest import (
    ContributionKind,
    ExtensionContribution,
    ExtensionManifest,
)


class ExtensionScope(IntEnum):
    """Installation scope. Higher scopes shadow lower copies of the same ID."""

    BUILTIN = 10
    USER = 20
    WORKSPACE = 30


@dataclass(frozen=True, slots=True)
class ExtensionCandidate:
    """One discovered installation of an extension manifest."""

    manifest: ExtensionManifest
    scope: ExtensionScope
    location: Path | None = None
    enabled: bool = True
    trusted: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, ExtensionManifest):
            raise TypeError("extension candidate manifest must be an ExtensionManifest")
        if not isinstance(self.scope, ExtensionScope):
            raise TypeError("extension candidate scope must be an ExtensionScope")
        if self.location is not None and not isinstance(self.location, Path):
            raise TypeError("extension candidate location must be a Path or None")


@dataclass(frozen=True, slots=True)
class ExtensionPolicy:
    """Host allow/deny policy applied after discovery."""

    allow: frozenset[str] = frozenset()
    deny: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not isinstance(self.allow, frozenset) or not isinstance(
            self.deny, frozenset
        ):
            raise TypeError("extension policy allow and deny values must be frozensets")
        overlap = self.allow & self.deny
        if overlap:
            raise ValueError(
                f"extension policy contains IDs in both allow and deny: {sorted(overlap)}"
            )

    def permits(self, candidate: ExtensionCandidate) -> bool:
        extension_id = candidate.manifest.id
        return (
            candidate.enabled
            and (candidate.scope is ExtensionScope.BUILTIN or candidate.trusted)
            and extension_id not in self.deny
            and (not self.allow or extension_id in self.allow)
        )


@dataclass(frozen=True, slots=True)
class ResolvedContribution:
    """An active contribution and the extension that owns it."""

    contribution: ExtensionContribution
    owner: ExtensionCandidate


@dataclass(frozen=True, slots=True)
class ExtensionDiagnostic:
    """A non-fatal discovery or ownership problem."""

    code: str
    extension_id: str
    message: str


@dataclass(frozen=True, slots=True)
class ExtensionSnapshot:
    """Immutable result consumed by runtime adapters and management surfaces."""

    extensions: tuple[ExtensionCandidate, ...]
    contributions: tuple[ResolvedContribution, ...]
    diagnostics: tuple[ExtensionDiagnostic, ...]

    def by_kind(
        self,
        kind: ContributionKind,
    ) -> tuple[ResolvedContribution, ...]:
        return tuple(
            item for item in self.contributions if item.contribution.kind is kind
        )


class ExtensionRegistry:
    """Collect candidates and resolve one safe, deterministic active snapshot."""

    def __init__(self, policy: ExtensionPolicy | None = None) -> None:
        self._policy = policy or ExtensionPolicy()
        self._candidates: dict[
            tuple[str, ExtensionScope],
            ExtensionCandidate,
        ] = {}

    def register(self, candidate: ExtensionCandidate) -> None:
        key = (candidate.manifest.id, candidate.scope)
        existing = self._candidates.get(key)
        if existing is not None:
            raise ValueError(
                f"extension '{candidate.manifest.id}' is already registered in "
                f"{candidate.scope.name.lower()} scope"
            )
        self._candidates[key] = candidate

    def snapshot(self) -> ExtensionSnapshot:
        active = self._select_active_extensions()
        resolved, diagnostics = self._resolve_contributions(active)
        return ExtensionSnapshot(
            extensions=tuple(sorted(active.values(), key=lambda item: item.manifest.id)),
            contributions=tuple(
                sorted(
                    resolved.values(),
                    key=lambda item: (
                        item.contribution.kind.value,
                        item.contribution.name,
                    ),
                )
            ),
            diagnostics=tuple(diagnostics),
        )

    def _select_active_extensions(self) -> dict[str, ExtensionCandidate]:
        active: dict[str, ExtensionCandidate] = {}
        for candidate in sorted(
            self._candidates.values(),
            key=lambda item: (item.scope, item.manifest.id),
        ):
            if self._policy.permits(candidate):
                active[candidate.manifest.id] = candidate
        return active

    def _resolve_contributions(
        self,
        active: dict[str, ExtensionCandidate],
    ) -> tuple[
        dict[tuple[ContributionKind, str], ResolvedContribution],
        list[ExtensionDiagnostic],
    ]:
        resolved: dict[
            tuple[ContributionKind, str],
            ResolvedContribution,
        ] = {}
        diagnostics: list[ExtensionDiagnostic] = []
        for candidate in sorted(
            active.values(),
            key=lambda item: (item.scope, item.manifest.id),
        ):
            for contribution in candidate.manifest.contributions:
                key = (contribution.kind, contribution.name)
                existing = resolved.get(key)
                if existing is None:
                    resolved[key] = ResolvedContribution(contribution, candidate)
                    continue
                existing_id = existing.owner.manifest.id
                if (
                    existing_id in contribution.replaces
                    and candidate.scope >= existing.owner.scope
                ):
                    resolved[key] = ResolvedContribution(contribution, candidate)
                    continue
                diagnostics.append(
                    ExtensionDiagnostic(
                        code="contribution_conflict",
                        extension_id=candidate.manifest.id,
                        message=(
                            f"{contribution.kind.value} '{contribution.name}' is already "
                            f"owned by extension '{existing_id}'; declare an explicit "
                            "replacement from an equal or higher scope to override it"
                        ),
                    )
                )
        return resolved, diagnostics
