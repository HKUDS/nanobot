"""Activation preflight for extension dependencies."""

from __future__ import annotations

import importlib.metadata
import json
import os
import shutil
from dataclasses import replace
from pathlib import Path

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from nanobot.extensions.manifest import DependencyKind, ExtensionDependency
from nanobot.extensions.registry import ExtensionCandidate, ExtensionDiagnostic


def evaluate_dependencies(
    candidates: tuple[ExtensionCandidate, ...],
) -> tuple[tuple[ExtensionCandidate, ...], tuple[ExtensionDiagnostic, ...]]:
    """Disable candidates with missing hard dependencies and explain why."""
    available = {
        candidate.manifest.id: candidate.manifest.version
        for candidate in candidates
    }
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
                    extensions=available,
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
    extensions: dict[str, str],
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
        return _version_failure(dependency, version, "Python package")
    if dependency.kind is DependencyKind.NPM:
        version = _npm_version(location, dependency.name)
        if version is None:
            return f"Required npm package is not installed: {dependency.name}"
        return _version_failure(dependency, version, "npm package")
    if dependency.kind is DependencyKind.EXTENSION:
        version = extensions.get(dependency.name)
        if version is None:
            return f"Required extension is not installed: {dependency.name}"
        return _version_failure(dependency, version, "extension")
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


def _version_failure(
    dependency: ExtensionDependency,
    version: str,
    label: str,
) -> str:
    if not dependency.specifier:
        return ""
    try:
        matches = Version(version) in SpecifierSet(dependency.specifier)
    except (InvalidSpecifier, InvalidVersion):
        return (
            f"{label} {dependency.name} has an unsupported version constraint: "
            f"{dependency.specifier}"
        )
    if matches:
        return ""
    return (
        f"{label} {dependency.name} {version} does not satisfy "
        f"{dependency.specifier}"
    )
