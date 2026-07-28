"""Deterministic extension activation planning."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from nanobot.extensions.manifest import ExtensionManifest


@dataclass(frozen=True, slots=True)
class ExtensionCandidate:
    """One discovered extension package and its activation state."""

    manifest: ExtensionManifest
    location: Path | None = None
    enabled: bool = True
    trusted: bool = False
    integrity_valid: bool = True
    granted_permissions: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class ExtensionDiagnostic:
    """A non-fatal discovery or activation problem."""

    code: str
    extension_id: str
    message: str
    severity: str = "warning"


@dataclass(frozen=True, slots=True)
class ExtensionSnapshot:
    """Immutable activation plan consumed by the runtime."""

    extensions: tuple[ExtensionCandidate, ...]
    diagnostics: tuple[ExtensionDiagnostic, ...]


class ExtensionRegistry:
    """Select trusted candidates and report missing permission grants."""

    def __init__(self) -> None:
        self._candidates: dict[str, ExtensionCandidate] = {}

    def register(self, candidate: ExtensionCandidate) -> None:
        extension_id = candidate.manifest.id
        if extension_id in self._candidates:
            raise ValueError(f"extension '{extension_id}' is already installed")
        self._candidates[extension_id] = candidate

    def snapshot(self) -> ExtensionSnapshot:
        active: list[ExtensionCandidate] = []
        diagnostics: list[ExtensionDiagnostic] = []
        for candidate in sorted(
            self._candidates.values(),
            key=lambda item: item.manifest.id,
        ):
            requested = {
                permission.name for permission in candidate.manifest.permissions
            }
            missing = sorted(requested - candidate.granted_permissions)
            if (
                candidate.enabled
                and candidate.integrity_valid
                and candidate.trusted
                and not missing
            ):
                active.append(candidate)
            elif candidate.enabled and candidate.trusted and missing:
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
        return ExtensionSnapshot(tuple(active), tuple(diagnostics))
