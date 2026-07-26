"""Deterministic extension selection and contribution ownership."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

from nanobot.extensions.manifest import (
    ContributionKind,
    DependencyKind,
    ExtensionContribution,
    ExtensionManifest,
)
from nanobot.extensions.versioning import dependency_version_failure


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
    integrity_valid: bool = True
    granted_permissions: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, ExtensionManifest):
            raise TypeError("extension candidate manifest must be an ExtensionManifest")
        if not isinstance(self.scope, ExtensionScope):
            raise TypeError("extension candidate scope must be an ExtensionScope")
        if self.location is not None and not isinstance(self.location, Path):
            raise TypeError("extension candidate location must be a Path or None")
        if not isinstance(self.integrity_valid, bool):
            raise TypeError("extension integrity state must be a boolean")
        if not isinstance(self.granted_permissions, frozenset):
            raise TypeError("extension granted permissions must be a frozenset")


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
        requested = {
            permission.name for permission in candidate.manifest.permissions
        }
        return (
            candidate.enabled
            and candidate.integrity_valid
            and (
                candidate.scope is ExtensionScope.BUILTIN
                or (
                    candidate.trusted
                    and requested <= candidate.granted_permissions
                )
            )
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
    severity: str = "warning"


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
        active, selection_diagnostics = self._select_active_extensions()
        active, dependency_diagnostics = self._resolve_extension_dependencies(active)
        resolved, resolution_diagnostics = self._resolve_contributions(active)
        return ExtensionSnapshot(
            extensions=self._activation_order(active),
            contributions=tuple(
                sorted(
                    resolved.values(),
                    key=lambda item: (
                        item.contribution.kind.value,
                        item.contribution.name,
                    ),
                )
            ),
            diagnostics=tuple(
                selection_diagnostics
                + dependency_diagnostics
                + resolution_diagnostics
            ),
        )

    def _select_active_extensions(
        self,
    ) -> tuple[dict[str, ExtensionCandidate], list[ExtensionDiagnostic]]:
        active: dict[str, ExtensionCandidate] = {}
        diagnostics: list[ExtensionDiagnostic] = []
        for candidate in sorted(
            self._candidates.values(),
            key=lambda item: (item.scope, item.manifest.id),
        ):
            if self._policy.permits(candidate):
                active[candidate.manifest.id] = candidate
                continue
            if (
                candidate.enabled
                and candidate.trusted
                and candidate.scope is not ExtensionScope.BUILTIN
            ):
                requested = {
                    permission.name
                    for permission in candidate.manifest.permissions
                }
                missing = sorted(requested - candidate.granted_permissions)
                if missing:
                    diagnostics.append(
                        ExtensionDiagnostic(
                            code="permission_required",
                            extension_id=candidate.manifest.id,
                            message=(
                                "Grant required extension permissions: "
                                + ", ".join(missing)
                            ),
                        )
                    )
        return active, diagnostics

    def _resolve_extension_dependencies(
        self,
        active: dict[str, ExtensionCandidate],
    ) -> tuple[dict[str, ExtensionCandidate], list[ExtensionDiagnostic]]:
        active = dict(active)
        diagnostics: list[ExtensionDiagnostic] = []
        while active:
            failed: dict[str, list[str]] = {}
            for extension_id, candidate in active.items():
                for dependency in candidate.manifest.dependencies:
                    if (
                        dependency.optional
                        or dependency.kind is not DependencyKind.EXTENSION
                    ):
                        continue
                    required = active.get(dependency.name)
                    if required is None:
                        failed.setdefault(extension_id, []).append(
                            f"Required extension is not active: {dependency.name}"
                        )
                        continue
                    if message := dependency_version_failure(
                        dependency,
                        required.manifest.version,
                        "extension",
                    ):
                        failed.setdefault(extension_id, []).append(message)
            if failed:
                for extension_id, messages in sorted(failed.items()):
                    active.pop(extension_id, None)
                    diagnostics.extend(
                        ExtensionDiagnostic(
                            code="dependency_missing",
                            extension_id=extension_id,
                            message=message,
                        )
                        for message in messages
                    )
                continue

            cycle = self._dependency_cycle(active)
            if not cycle:
                break
            for extension_id in sorted(cycle):
                active.pop(extension_id, None)
                diagnostics.append(
                    ExtensionDiagnostic(
                        code="dependency_cycle",
                        extension_id=extension_id,
                        message=(
                            "Extension dependency cycle contains: "
                            + ", ".join(sorted(cycle))
                        ),
                    )
                )
        return active, diagnostics

    @staticmethod
    def _dependency_cycle(
        active: dict[str, ExtensionCandidate],
    ) -> set[str]:
        state: dict[str, int] = {}
        stack: list[str] = []
        cycle: set[str] = set()

        def visit(extension_id: str) -> None:
            state[extension_id] = 1
            stack.append(extension_id)
            dependencies = (
                dependency.name
                for dependency in active[extension_id].manifest.dependencies
                if not dependency.optional
                and dependency.kind is DependencyKind.EXTENSION
                and dependency.name in active
            )
            for dependency_id in sorted(dependencies):
                if state.get(dependency_id, 0) == 0:
                    visit(dependency_id)
                elif state.get(dependency_id) == 1:
                    cycle.update(stack[stack.index(dependency_id) :])
            stack.pop()
            state[extension_id] = 2

        for extension_id in sorted(active):
            if state.get(extension_id, 0) == 0:
                visit(extension_id)
        return cycle

    @staticmethod
    def _activation_order(
        active: dict[str, ExtensionCandidate],
    ) -> tuple[ExtensionCandidate, ...]:
        ordered: list[ExtensionCandidate] = []
        visited: set[str] = set()

        def visit(extension_id: str) -> None:
            if extension_id in visited:
                return
            visited.add(extension_id)
            dependencies = (
                dependency.name
                for dependency in active[extension_id].manifest.dependencies
                if dependency.kind is DependencyKind.EXTENSION
                and dependency.name in active
            )
            for dependency_id in sorted(dependencies):
                visit(dependency_id)
            ordered.append(active[extension_id])

        for extension_id in sorted(active):
            visit(extension_id)
        return tuple(ordered)

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
                diagnostics.append(
                    ExtensionDiagnostic(
                        code="contribution_conflict",
                        extension_id=candidate.manifest.id,
                        message=(
                            f"{contribution.kind.value} '{contribution.name}' is already "
                            f"owned by extension '{existing_id}'; disable one owner "
                            "before activating the other"
                        ),
                    )
                )
        return resolved, diagnostics
