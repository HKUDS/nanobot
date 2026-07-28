"""Strict schema for native nanobot extension packages."""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EXTENSION_API_VERSION = 1

_IDENTIFIER = re.compile(r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?")
_PERMISSION = re.compile(r"[a-z][a-z0-9]*(?:[._:-][a-z0-9]+)*")


class DependencyKind(str, Enum):
    """Kinds of prerequisites resolved before activation."""

    PYTHON = "python"
    EXECUTABLE = "executable"
    ENVIRONMENT = "environment"


class _ManifestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class ExtensionDependency(_ManifestModel):
    """One activation prerequisite declared by an extension."""

    kind: DependencyKind
    name: str
    specifier: str = ""
    optional: bool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _require_text(value, "extension dependency name")


class ExtensionPermission(_ManifestModel):
    """A privileged host capability requested by an extension."""

    name: str
    reason: str = ""

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if _PERMISSION.fullmatch(value) is None:
            raise ValueError(
                "extension permission must be a lowercase namespaced identifier"
            )
        return value


class ExtensionManifest(_ManifestModel):
    """Identity, prerequisites, and consent declarations for one extension."""

    id: str
    name: str
    version: str
    entry: str = "extension:register"
    description: str = ""
    dependencies: tuple[ExtensionDependency, ...] = ()
    permissions: tuple[ExtensionPermission, ...] = ()
    api_version: Literal[EXTENSION_API_VERSION] = Field(
        default=EXTENSION_API_VERSION,
        alias="apiVersion",
    )
    homepage: str = ""
    license: str = ""

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _require_identifier(value, "extension id")

    @field_validator("name", "version")
    @classmethod
    def validate_required_text(cls, value: str, info) -> str:
        return _require_text(value, f"extension {info.field_name}")

    @field_validator("entry")
    @classmethod
    def validate_entry(cls, value: str) -> str:
        value = _require_text(value, "extension entry")
        module_name = value.partition(":")[0]
        if Path(module_name).is_absolute() or ".." in Path(module_name).parts:
            raise ValueError("extension entry cannot escape the package root")
        return value

    @model_validator(mode="after")
    def reject_duplicates(self) -> Self:
        dependencies = [(item.kind, item.name) for item in self.dependencies]
        if len(set(dependencies)) != len(dependencies):
            raise ValueError("extension manifest contains duplicate dependencies")
        permissions = [item.name for item in self.permissions]
        if len(set(permissions)) != len(permissions):
            raise ValueError("extension manifest contains duplicate permissions")
        return self


def _require_text(value: str, label: str) -> str:
    if not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _require_identifier(value: str, label: str) -> str:
    value = _require_text(value, label)
    if _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(
            f"{label} must use lowercase letters, digits, dots, underscores, or hyphens"
        )
    return value


def validate_extension_id(value: object) -> str:
    """Validate and return one portable extension identifier."""
    if not isinstance(value, str):
        raise ValueError("extension id must be a string")
    return _require_identifier(value, "extension id")
