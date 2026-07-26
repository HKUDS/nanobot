"""Dependency-free metadata shared by every nanobot extension format."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

EXTENSION_API_VERSION = 1

_IDENTIFIER = re.compile(r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?")
_PERMISSION = re.compile(r"[a-z][a-z0-9]*(?:[._:-][a-z0-9]+)*")


class ExtensionRuntime(str, Enum):
    """Runtime used to activate an extension package."""

    PYTHON = "python"
    PI = "pi"
    OPENCLAW = "openclaw"
    DECLARATIVE = "declarative"


class ContributionKind(str, Enum):
    """Native capability slots an extension may contribute to."""

    TOOL = "tool"
    SKILL = "skill"
    CHANNEL = "channel"
    LLM_PROVIDER = "llm_provider"
    TRANSCRIPTION_PROVIDER = "transcription_provider"
    IMAGE_GENERATION_PROVIDER = "image_generation_provider"
    WEB_SEARCH_PROVIDER = "web_search_provider"
    MCP_SERVER = "mcp_server"
    HOOK = "hook"
    COMMAND = "command"
    WEBUI = "webui"


class DependencyKind(str, Enum):
    """Kinds of prerequisites resolved before activation."""

    PYTHON = "python"
    NPM = "npm"
    EXECUTABLE = "executable"
    ENVIRONMENT = "environment"
    EXTENSION = "extension"


@dataclass(frozen=True, slots=True)
class ExtensionDependency:
    """One activation prerequisite declared by an extension."""

    kind: DependencyKind
    name: str
    specifier: str = ""
    optional: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.kind, DependencyKind):
            raise TypeError("extension dependency kind must be a DependencyKind")
        _require_text(self.name, "extension dependency name")
        if self.kind is DependencyKind.EXTENSION:
            _require_identifier(self.name, "extension dependency name")
        if not isinstance(self.specifier, str):
            raise TypeError("extension dependency specifier must be a string")


@dataclass(frozen=True, slots=True)
class ExtensionPermission:
    """A privileged host capability requested by an extension."""

    name: str
    reason: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or _PERMISSION.fullmatch(self.name) is None:
            raise ValueError(
                "extension permission must be a lowercase namespaced identifier"
            )
        if not isinstance(self.reason, str):
            raise TypeError("extension permission reason must be a string")


@dataclass(frozen=True, slots=True)
class ExtensionContribution:
    """A contribution projected into one existing nanobot registry."""

    kind: ContributionKind
    name: str
    target: str = ""
    description: str = ""
    replaces: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ContributionKind):
            raise TypeError("extension contribution kind must be a ContributionKind")
        _require_identifier(self.name, "extension contribution name")
        if not isinstance(self.target, str):
            raise TypeError("extension contribution target must be a string")
        if not isinstance(self.description, str):
            raise TypeError("extension contribution description must be a string")
        if not isinstance(self.replaces, tuple):
            raise TypeError("extension contribution replaces must be a tuple")
        for extension_id in self.replaces:
            _require_identifier(extension_id, "replaced extension id")
        if len(set(self.replaces)) != len(self.replaces):
            raise ValueError("extension contribution replaces contains duplicates")


@dataclass(frozen=True, slots=True)
class ExtensionManifest:
    """Portable identity and capability declaration for one extension."""

    id: str
    name: str
    version: str
    runtime: ExtensionRuntime
    entry: str = ""
    entries: tuple[str, ...] = ()
    contributions: tuple[ExtensionContribution, ...] = ()
    description: str = ""
    dependencies: tuple[ExtensionDependency, ...] = ()
    permissions: tuple[ExtensionPermission, ...] = ()
    api_version: int = EXTENSION_API_VERSION
    homepage: str = ""
    license: str = ""

    def __post_init__(self) -> None:
        _require_identifier(self.id, "extension id")
        _require_text(self.name, "extension name")
        _require_text(self.version, "extension version")
        if not isinstance(self.runtime, ExtensionRuntime):
            raise TypeError("extension runtime must be an ExtensionRuntime")
        if not isinstance(self.entry, str):
            raise TypeError("extension entry must be a string")
        if not isinstance(self.entries, tuple) or not all(
            isinstance(entry, str) and entry for entry in self.entries
        ):
            raise TypeError("extension entries must be a tuple of non-empty strings")
        activation_entries = self.activation_entries
        if len(set(activation_entries)) != len(activation_entries):
            raise ValueError("extension entries contains duplicates")
        for entry in activation_entries:
            if Path(entry).is_absolute():
                raise ValueError("extension entry must be relative to the package root")
            if ".." in Path(entry).parts:
                raise ValueError("extension entry cannot escape the package root")
        if self.api_version != EXTENSION_API_VERSION:
            raise ValueError(
                f"unsupported extension API version {self.api_version}; "
                f"expected {EXTENSION_API_VERSION}"
            )
        _require_tuple_of(
            self.contributions,
            ExtensionContribution,
            "extension contributions",
        )
        _require_tuple_of(
            self.dependencies,
            ExtensionDependency,
            "extension dependencies",
        )
        _require_tuple_of(
            self.permissions,
            ExtensionPermission,
            "extension permissions",
        )
        for value, label in (
            (self.description, "extension description"),
            (self.homepage, "extension homepage"),
            (self.license, "extension license"),
        ):
            if not isinstance(value, str):
                raise TypeError(f"{label} must be a string")

        contribution_keys = [
            (contribution.kind, contribution.name)
            for contribution in self.contributions
        ]
        if len(set(contribution_keys)) != len(contribution_keys):
            raise ValueError("extension manifest contains duplicate contributions")
        permission_names = [permission.name for permission in self.permissions]
        if len(set(permission_names)) != len(permission_names):
            raise ValueError("extension manifest contains duplicate permissions")

    @property
    def activation_entries(self) -> tuple[str, ...]:
        """Return every runtime entry while preserving the v1 single-entry form."""
        return self.entries or ((self.entry,) if self.entry else ())


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _require_identifier(value: object, label: str) -> str:
    text = _require_text(value, label)
    if _IDENTIFIER.fullmatch(text) is None:
        raise ValueError(
            f"{label} must use lowercase letters, digits, dots, underscores, or hyphens"
        )
    return text


def _require_tuple_of(value: object, item_type: type, label: str) -> None:
    if not isinstance(value, tuple) or not all(
        isinstance(item, item_type) for item in value
    ):
        raise TypeError(f"{label} must be a tuple of {item_type.__name__}")
