"""Side-effect-free discovery of extension manifests on disk."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from nanobot.extensions.codec import MANIFEST_FILENAME, load_manifest
from nanobot.extensions.registry import (
    ExtensionCandidate,
    ExtensionDiagnostic,
    ExtensionScope,
)


@dataclass(frozen=True, slots=True)
class ExtensionDiscoveryResult:
    candidates: tuple[ExtensionCandidate, ...] = ()
    diagnostics: tuple[ExtensionDiagnostic, ...] = ()


def discover_manifest_root(
    root: Path,
    *,
    scope: ExtensionScope,
    trusted: bool = False,
    enabled_ids: frozenset[str] = frozenset(),
) -> ExtensionDiscoveryResult:
    """Discover direct children containing ``nanobot.extension.json``."""
    if not root.exists():
        return ExtensionDiscoveryResult()
    if not root.is_dir():
        return ExtensionDiscoveryResult(
            diagnostics=(
                ExtensionDiagnostic(
                    code="invalid_extension_root",
                    extension_id="",
                    message=f"extension root is not a directory: {root}",
                ),
            )
        )

    manifests = []
    direct_manifest = root / MANIFEST_FILENAME
    if direct_manifest.is_file():
        manifests.append(direct_manifest)
    manifests.extend(
        sorted(
            path / MANIFEST_FILENAME
            for path in root.iterdir()
            if not path.name.startswith(".")
            and path.is_dir()
            and (path / MANIFEST_FILENAME).is_file()
        )
    )

    candidates: list[ExtensionCandidate] = []
    diagnostics: list[ExtensionDiagnostic] = []
    for path in manifests:
        try:
            manifest = load_manifest(path)
            candidates.append(
                ExtensionCandidate(
                    manifest=manifest,
                    scope=scope,
                    location=path.parent.resolve(),
                    enabled=not enabled_ids or manifest.id in enabled_ids,
                    trusted=trusted,
                )
            )
        except Exception as exc:
            diagnostics.append(
                ExtensionDiagnostic(
                    code="invalid_manifest",
                    extension_id=path.parent.name,
                    message=str(exc),
                )
            )
    return ExtensionDiscoveryResult(tuple(candidates), tuple(diagnostics))
