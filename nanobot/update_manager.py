"""Read package-manager intent without changing its receipt or exposing source URLs.

These facts supplement an installation-bound update plan. They do not authorize an
installer: the owning manager still resolves its full settings and dependencies.
"""

from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nanobot.releases import ReleaseRecord, Sha256

Source = Literal["registry", "artifact", "source", "unrecognized"]


def _source(url: str | None) -> Source:
    if url is None:
        return "registry"
    parsed = urlsplit(url)
    return "artifact" if parsed.scheme in {"https", "http", "file"} and parsed.path.endswith(".whl") else "source"


class ManagerPolicy(ReleaseRecord):
    """Credential-free summary; the receipt hash binds the complete private record."""

    manager: Literal["uv", "pipx"]
    backend: Literal["uv", "pip"]
    extras: list[str] | None
    version_constraint: str = Field(default="", max_length=1000)
    source: Source
    pinned: bool = False
    locked: bool = False
    injected_packages: list[str] = Field(default_factory=list, max_length=500)
    custom_pip_args: bool = False

    @field_validator("version_constraint")
    @classmethod
    def valid_constraint(cls, value: str) -> str:
        SpecifierSet(value)
        return value

    @field_validator("extras", "injected_packages")
    @classmethod
    def normalized_names(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and (len(value) > 500 or value != sorted(set(value)) or any(
            canonicalize_name(name, validate=True) != name for name in value
        )):
            raise ValueError("Expected unique normalized package or extra names")
        return value

    def restriction(self, version: str) -> str | None:
        """Why this target requires owner intervention, not permission to execute it."""
        if self.pinned:
            return "The package is pinned by its installation owner. Review that pin before updating."
        if self.locked:
            return "The environment uses an owner-managed lock file. Update through that lock workflow."
        if self.manager == "pipx" and (self.version_constraint or self.custom_pip_args):
            return "This pipx installation has constraints or installer options. Review them with its owner; a generic pipx upgrade can discard those settings."
        if self.manager == "uv" and self.source == "artifact":
            return "This uv tool is bound to a wheel URL. Change its source through the installation owner's workflow."
        if self.source in {"source", "unrecognized"} or self.extras is None:
            return "The recorded installation source needs manual review by its owner."
        if not SpecifierSet(self.version_constraint).contains(version, prereleases=True):
            return "This version is outside the installation's recorded version constraints."
        return None


class _UVRequirement(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)
    name: str
    extras: list[str] = Field(default_factory=list)
    specifier: str = ""
    url: str | None = None
    index: str | None = None
    marker: str | None = None


class _UVTool(BaseModel):
    model_config = ConfigDict(strict=True)
    requirements: list[_UVRequirement] = Field(min_length=1, max_length=500)


class _UVReceipt(BaseModel):
    tool: _UVTool


class _PipxPackage(BaseModel):
    model_config = ConfigDict(strict=True)
    package: str
    package_or_url: str
    pinned: bool = False
    lock_file: str | dict[str, str] | None = None
    pip_args: list[str] = Field(default_factory=list)


class _PipxReceipt(BaseModel):
    model_config = ConfigDict(strict=True)
    pipx_metadata_version: str
    main_package: _PipxPackage
    injected_packages: dict[str, _PipxPackage] = Field(default_factory=dict, max_length=500)
    backend: Literal["pip", "uv"] = "pip"


def read_manager_policy(environment: Path, manager: Literal["uv", "pipx"], expected_sha: Sha256) -> ManagerPolicy:
    """Read the exact receipt observed by the fresh interpreter, without rewriting it."""
    path = environment / ("uv-receipt.toml" if manager == "uv" else "pipx_metadata.json")
    try:
        if path.is_symlink() or not path.is_file():
            raise ValueError("Invalid package-manager receipt")
        with path.open("rb") as stream:
            raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024 or hashlib.sha256(raw).hexdigest() != expected_sha:
            raise ValueError("Package-manager receipt changed or exceeds its size limit")
        if manager == "uv":
            receipt = _UVReceipt.model_validate(tomllib.loads(raw.decode("utf-8")))
            main = [item for item in receipt.tool.requirements if canonicalize_name(item.name) == "nanobot-ai"]
            if len(main) != 1:
                raise ValueError("Ambiguous managed package")
            requirement = main[0]
            source = "unrecognized" if requirement.model_extra or requirement.marker else _source(requirement.url)
            return ManagerPolicy(
                manager=manager, backend="uv", source=source,
                extras=sorted({canonicalize_name(extra, validate=True) for extra in requirement.extras}),
                version_constraint=requirement.specifier,
                injected_packages=sorted({canonicalize_name(item.name, validate=True)
                                          for item in receipt.tool.requirements if item is not requirement}),
            )
        pipx = _PipxReceipt.model_validate_json(raw)
        # The fields used here have matching semantics in receipts produced by
        # pipx 1.7.1 (0.5) and 1.17.13 (0.12). Reading an older supported receipt
        # must not require upgrading pipx or migrating its private metadata.
        if pipx.pipx_metadata_version not in {"0.5", "0.12"}:
            raise ValueError("Unknown pipx receipt schema")
        if canonicalize_name(pipx.main_package.package) != "nanobot-ai":
            raise ValueError("Receipt belongs to another package")
        try:
            requested = Requirement(pipx.main_package.package_or_url)
        except InvalidRequirement:
            requested = None
        if requested is not None and canonicalize_name(requested.name) != "nanobot-ai":
            raise ValueError("Receipt names a different package")
        return ManagerPolicy(
            manager=manager, backend=pipx.backend,
            source="unrecognized" if requested is None or requested.marker else (
                "source" if "--editable" in pipx.main_package.pip_args or "-e" in pipx.main_package.pip_args else (
                    _source(requested.url)
                )
            ),
            extras=sorted({canonicalize_name(extra, validate=True) for extra in requested.extras})
            if requested is not None else None,
            version_constraint=str(requested.specifier) if requested is not None else "",
            pinned=pipx.main_package.pinned, locked=pipx.main_package.lock_file is not None,
            custom_pip_args=bool(pipx.main_package.pip_args),
            injected_packages=sorted({canonicalize_name(name, validate=True) for name in pipx.injected_packages}),
        )
    except (OSError, ValueError, TypeError):
        # Parse errors can embed credential-bearing URLs; never relay their text.
        raise ValueError("Could not verify package-manager settings; inspect this installation before updating") from None
