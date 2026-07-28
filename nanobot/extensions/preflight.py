"""Activation preflight for extension runtime prerequisites."""

from __future__ import annotations

import importlib.metadata
import os
import shutil
from dataclasses import replace

from nanobot.extensions.manifest import DependencyKind, ExtensionDependency
from nanobot.extensions.registry import ExtensionCandidate, ExtensionDiagnostic
from nanobot.extensions.versioning import dependency_version_failure


def evaluate_dependencies(
    candidates: tuple[ExtensionCandidate, ...],
) -> tuple[tuple[ExtensionCandidate, ...], tuple[ExtensionDiagnostic, ...]]:
    """Disable candidates with missing required software and explain why."""
    checked: list[ExtensionCandidate] = []
    diagnostics: list[ExtensionDiagnostic] = []
    for candidate in candidates:
        failures = [
            message
            for dependency in candidate.manifest.dependencies
            if not dependency.optional
            if (message := _dependency_failure(dependency))
        ]
        if failures:
            candidate = replace(candidate, enabled=False)
            diagnostics.extend(
                ExtensionDiagnostic(
                    code="dependency_missing",
                    extension_id=candidate.manifest.id,
                    message=message,
                )
                for message in failures
            )
        checked.append(candidate)
    return tuple(checked), tuple(diagnostics)


def _dependency_failure(
    dependency: ExtensionDependency,
) -> str:
    if dependency.kind is DependencyKind.EXECUTABLE:
        if shutil.which(dependency.name) is None:
            return f"Required executable is not installed: {dependency.name}"
        return ""
    if dependency.kind is DependencyKind.ENVIRONMENT:
        if not os.getenv(dependency.name):
            return f"Required environment variable is not set: {dependency.name}"
        return ""
    if dependency.kind is DependencyKind.PYTHON:
        try:
            version = importlib.metadata.version(dependency.name)
        except importlib.metadata.PackageNotFoundError:
            return f"Required Python package is not installed: {dependency.name}"
        return dependency_version_failure(dependency, version, "Python package")
    return f"Unsupported dependency kind: {dependency.kind.value}"
