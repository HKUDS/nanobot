"""Release identities shared by packaging and channel-aware update discovery.

This module validates data and selects artifacts. It never installs packages, trusts
arbitrary download URLs, or treats a build manifest as publication approval.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from typing import Annotated, Literal, Self

from packaging.specifiers import SpecifierSet
from packaging.tags import Tag
from packaging.utils import parse_wheel_filename
from packaging.version import Version
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Channel = Literal["stable", "preview"]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Commit = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]

# Minimums verified against BOTH Bun and the embedded OpenTUI library.
PLATFORMS = {
    "darwin-arm64": "macosx_13_0_arm64",
    "darwin-x64": "macosx_13_0_x86_64",
    "linux-arm64": "manylinux_2_17_aarch64",
    "linux-x64": "manylinux_2_17_x86_64",
    "win32-x64": "win_amd64",
}
RELEASE_DOWNLOAD = "https://github.com/HKUDS/nanobot/releases/download"


def release_version(value: str) -> str:
    """Accept canonical versions we publish, not epochs, local builds or refs."""
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:\.dev\d+|\.post\d+)?", value):
        raise ValueError("Expected a stable or development release version")
    if str(Version(value)) != value:
        raise ValueError("Release version must be canonical")
    return value


def release_filenames(version: str) -> set[str]:
    """The complete upload set, excluding the intermediate universal wheel."""
    release_version(version)
    names = {f"nanobot_ai-{version}-py3-none-{platform}.whl" for platform in PLATFORMS.values()}
    names.add(f"nanobot_ai-{version}.tar.gz")
    for target in PLATFORMS:
        asset = f"nanobot-tui-{target}" + (".exe" if target == "win32-x64" else "")
        names.update((f"{asset}.zip", f"{asset}.zip.sha256"))
    return names


class ReleaseRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ReleaseArtifact(ReleaseRecord):
    filename: str = Field(pattern=r"^[A-Za-z0-9_.-]+$", max_length=200)
    size: int = Field(gt=0, le=2 * 1024**3)
    sha256: Sha256


class ReleaseManifest(ReleaseRecord):
    schema_version: Literal[1] = 1
    version: str
    source_commit: Commit
    candidate_commit: Commit
    requires_python: str
    artifacts: list[ReleaseArtifact] = Field(min_length=16, max_length=16)

    _version = field_validator("version")(release_version)

    @field_validator("requires_python")
    @classmethod
    def validate_python(cls, value: str) -> str:
        if not value or len(value) > 200:
            raise ValueError("A bounded Python version requirement is required")
        SpecifierSet(value)
        return value

    @model_validator(mode="after")
    def complete_artifacts(self) -> Self:
        if {item.filename for item in self.artifacts} != release_filenames(self.version):
            raise ValueError("Manifest must contain the complete, matching five-platform release")
        return self

    def wheel_for(self, *, python_version: str, supported_tags: Iterable[Tag]) -> ReleaseArtifact:
        """Select using the target interpreter's tags, never the browser platform."""
        if not SpecifierSet(self.requires_python).contains(python_version, prereleases=True):
            raise ValueError(f"Release {self.version} requires Python {self.requires_python}")
        wheels = {
            tag: artifact
            for artifact in self.artifacts if artifact.filename.endswith(".whl")
            for tag in parse_wheel_filename(artifact.filename)[3]
        }
        for tag in supported_tags:
            if tag in wheels:
                return wheels[tag]
        raise ValueError("No compatible release wheel; use the documented source/classic path")

    def artifact_url(self, artifact: ReleaseArtifact) -> str:
        if artifact not in self.artifacts:
            raise ValueError("Artifact does not belong to this release")
        return f"{RELEASE_DOWNLOAD}/v{self.version}/{artifact.filename}#sha256={artifact.sha256}"


class ReleasePointer(ReleaseRecord):
    version: str
    candidate_commit: Commit
    manifest_sha256: Sha256

    _version = field_validator("version")(release_version)

    @property
    def manifest_url(self) -> str:
        return f"{RELEASE_DOWNLOAD}/v{self.version}/release-manifest.json"

    def verify_manifest(self, payload: bytes) -> ReleaseManifest:
        if len(payload) > 64 * 1024 or hashlib.sha256(payload).hexdigest() != self.manifest_sha256:
            raise ValueError("Release manifest size or checksum mismatch")
        manifest = ReleaseManifest.model_validate_json(payload)
        if (manifest.version, manifest.candidate_commit) != (self.version, self.candidate_commit):
            raise ValueError("Release manifest identity does not match the selected candidate")
        return manifest


class ReleaseCatalogue(ReleaseRecord):
    schema_version: Literal[1] = 1
    generation: int = Field(gt=0)
    stable: ReleasePointer | None = None
    preview: ReleasePointer | None = None
    withdrawn: dict[str, str] = Field(default_factory=dict, max_length=1000)

    @model_validator(mode="after")
    def validate_channels(self) -> Self:
        if self.stable and Version(self.stable.version).is_prerelease:
            raise ValueError("Stable channel cannot contain a prerelease")
        if self.preview and not Version(self.preview.version).is_devrelease:
            raise ValueError("Preview pointer must identify a development release")
        for version, reason in self.withdrawn.items():
            release_version(version)
            if not reason.strip() or len(reason) > 2000:
                raise ValueError("A bounded withdrawal reason is required")
        return self

    def validate_successor(self, previous: Self) -> None:
        """A new index generation cannot rewrite already observed releases."""
        if self.generation < previous.generation or (self.generation == previous.generation and self != previous):
            raise ValueError("Release catalogue changed without a newer generation")
        if not previous.withdrawn.keys() <= self.withdrawn.keys():
            raise ValueError("Release catalogue cannot reinstate withdrawn versions")
        for old, new in ((previous.stable, self.stable), (previous.preview, self.preview)):
            if old is None:
                continue
            if new is None:
                raise ValueError("Release channel cannot erase a published pointer; withdraw the version instead")
            if Version(new.version) < Version(old.version):
                raise ValueError("Release channel cannot move to an older version")
            if new.version == old.version and new != old:
                raise ValueError("Published version cannot change its commit or manifest")

    def latest(self, channel: Channel, *, minimum_generation: int = 0) -> ReleasePointer | None:
        if self.generation < minimum_generation:
            raise ValueError("Release catalogue is older than the last accepted generation")
        candidates = [self.stable] if channel == "stable" else [self.stable, self.preview]
        eligible = [item for item in candidates if item and item.version not in self.withdrawn]
        return max(eligible, key=lambda item: Version(item.version), default=None)
