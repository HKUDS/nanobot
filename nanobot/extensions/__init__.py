"""First-class extension metadata and discovery primitives."""

from nanobot.extensions.codec import (
    MANIFEST_FILENAME,
    ManifestFormatError,
    dump_manifest,
    load_manifest,
    manifest_from_mapping,
    manifest_to_mapping,
)
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
from nanobot.extensions.registry import (
    ExtensionCandidate,
    ExtensionDiagnostic,
    ExtensionPolicy,
    ExtensionRegistry,
    ExtensionScope,
    ExtensionSnapshot,
    ResolvedContribution,
)

__all__ = [
    "EXTENSION_API_VERSION",
    "ContributionKind",
    "DependencyKind",
    "ExtensionCandidate",
    "ExtensionContribution",
    "ExtensionDependency",
    "ExtensionDiagnostic",
    "ExtensionManifest",
    "ExtensionPermission",
    "ExtensionPolicy",
    "ExtensionRegistry",
    "ExtensionRuntime",
    "ExtensionScope",
    "ExtensionSnapshot",
    "MANIFEST_FILENAME",
    "ManifestFormatError",
    "ResolvedContribution",
    "dump_manifest",
    "load_manifest",
    "manifest_from_mapping",
    "manifest_to_mapping",
]
