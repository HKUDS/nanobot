"""First-class extension metadata and discovery primitives."""

from nanobot.extensions.catalog import ExtensionCatalog, build_extension_catalog
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
from nanobot.extensions.native import discover_native_extensions
from nanobot.extensions.node_host import NodeSidecar
from nanobot.extensions.protocol import (
    NODE_PROTOCOL_VERSION,
    NodeLoadResult,
    NodeProtocolError,
    NodeRegistration,
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
from nanobot.extensions.runtime import (
    ActivatedExtension,
    ActivationResult,
    ExtensionRuntimeManager,
    PythonExtensionApi,
)

__all__ = [
    "EXTENSION_API_VERSION",
    "ContributionKind",
    "DependencyKind",
    "ExtensionCandidate",
    "ExtensionCatalog",
    "ExtensionContribution",
    "ExtensionDependency",
    "ExtensionDiagnostic",
    "ExtensionManifest",
    "ExtensionPermission",
    "ExtensionPolicy",
    "ExtensionRegistry",
    "ExtensionRuntime",
    "ExtensionRuntimeManager",
    "ExtensionScope",
    "ExtensionSnapshot",
    "MANIFEST_FILENAME",
    "ManifestFormatError",
    "NODE_PROTOCOL_VERSION",
    "NodeLoadResult",
    "NodeProtocolError",
    "NodeRegistration",
    "NodeSidecar",
    "ActivatedExtension",
    "ActivationResult",
    "PythonExtensionApi",
    "ResolvedContribution",
    "build_extension_catalog",
    "dump_manifest",
    "discover_native_extensions",
    "load_manifest",
    "manifest_from_mapping",
    "manifest_to_mapping",
]
