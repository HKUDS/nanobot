"""Activation preflight for extension dependencies."""

from __future__ import annotations

import importlib.metadata
import json
import os
import shutil
from dataclasses import replace
from pathlib import Path

from nanobot.extensions.manifest import DependencyKind, ExtensionDependency
from nanobot.extensions.registry import ExtensionCandidate, ExtensionDiagnostic
from nanobot.extensions.versioning import dependency_version_failure


def evaluate_dependencies(
    candidates: tuple[ExtensionCandidate, ...],
) -> tuple[tuple[ExtensionCandidate, ...], tuple[ExtensionDiagnostic, ...]]:
    """Disable candidates with missing hard dependencies and explain why."""
    checked: list[ExtensionCandidate] = []
    diagnostics: list[ExtensionDiagnostic] = []
    for candidate in candidates:
        failures = [
            message
            for dependency in candidate.manifest.dependencies
            if not dependency.optional
            if (
                message := _dependency_failure(
                    dependency,
                    location=candidate.location,
                )
            )
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
    *,
    location: Path | None,
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
    if dependency.kind is DependencyKind.NPM:
        version = _npm_version(location, dependency.name)
        if version is None:
            return f"Required npm package is not installed: {dependency.name}"
        # npm resolved the declared range while installing the package. Re-parsing
        # npm semver here with Python's PEP 440 rules rejects valid ranges such as
        # "latest", "^1.0.0", and "~2.3".
        return ""
    if dependency.kind is DependencyKind.EXTENSION:
        # Extension dependencies are evaluated after policy selection so an
        # installed but inactive package cannot satisfy an activation prerequisite.
        return ""
    return f"Unsupported dependency kind: {dependency.kind.value}"


def _npm_version(location: Path | None, name: str) -> str | None:
    if location is None:
        return None
    package = location / "node_modules" / Path(*name.split("/")) / "package.json"
    try:
        value = json.loads(package.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    version = value.get("version") if isinstance(value, dict) else None
    return version if isinstance(version, str) else None
