"""Stable author-facing API for native nanobot extensions."""

from nanobot.extensions.manifest import (
    EXTENSION_API_VERSION,
    DependencyKind,
    ExtensionDependency,
    ExtensionManifest,
    ExtensionPermission,
)
from nanobot.extensions.runtime import PythonExtensionApi

__all__ = [
    "EXTENSION_API_VERSION",
    "DependencyKind",
    "ExtensionDependency",
    "ExtensionManifest",
    "ExtensionPermission",
    "PythonExtensionApi",
]
