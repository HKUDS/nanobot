"""Resolve and revalidate exact release artifacts without installing anything.

Stable releases are read from PyPI; previews use the project's protected catalogue.
Neither source can provide commands, another repository, or arbitrary download hosts.
"""

from __future__ import annotations

import asyncio
import hashlib
import platform
import re
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from email.parser import BytesParser
from pathlib import Path
from typing import Literal, Self
from urllib.parse import unquote, urljoin, urlsplit
from uuid import uuid4
from zipfile import ZipFile

import httpx
from filelock import FileLock
from packaging.specifiers import SpecifierSet
from packaging.tags import Tag, sys_tags
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import Version
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nanobot.release_trust import verify_release_approval
from nanobot.releases import (
    RELEASE_DOWNLOAD,
    Channel,
    ReleaseArtifact,
    ReleaseCatalogue,
    ReleaseManifest,
    ReleasePointer,
    ReleaseRecord,
    release_filenames,
    release_version,
)
from nanobot.security.network import PinnedDNSAsyncTransport
from nanobot.utils.atomic_file import atomic_write_lines

CATALOGUE_URL = "https://raw.githubusercontent.com/HKUDS/nanobot/release-index/catalogue.json"
PYPI_URL = "https://pypi.org/pypi/nanobot-ai"
_DOWNLOAD_HOSTS = {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com",
                   "files.pythonhosted.org"}
_METADATA_HOSTS = {"pypi.org", "raw.githubusercontent.com", *_DOWNLOAD_HOSTS}


class ReleaseFeedError(RuntimeError):
    """No verified update can be offered or downloaded."""

    def __init__(self, message: str, *, code: Literal["unavailable", "publishing", "unsupported", "withdrawn"] = "unavailable") -> None:
        super().__init__(message)
        self.code = code


def _url(url: str, hosts: set[str]) -> str:
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in hosts
            or parsed.username is not None or parsed.password is not None
            or parsed.port not in (None, 443) or parsed.fragment):
        raise ValueError("Release URL must use an approved HTTPS host")
    return url


class ReleaseTarget(ReleaseRecord):
    version: str
    artifact: ReleaseArtifact
    url: str
    source: Literal["pypi", "github"]
    pointer: ReleasePointer | None = None
    catalogue_generation: int = Field(default=0, ge=0)

    _version = field_validator("version")(release_version)

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        name, version, _, tags = parse_wheel_filename(self.artifact.filename)
        if name != "nanobot-ai" or str(version) != self.version or any(t.platform == "any" for t in tags):
            raise ValueError("Expected a matching native nanobot wheel")
        _url(self.url, {"files.pythonhosted.org"} if self.source == "pypi" else {"github.com"})
        if unquote(urlsplit(self.url).path.rsplit("/", 1)[-1]) != self.artifact.filename:
            raise ValueError("Wheel URL and filename differ")
        if self.source == "github":
            expected = f"https://github.com/HKUDS/nanobot/releases/download/v{self.version}/{self.artifact.filename}"
            if self.url != expected or not self.pointer or self.pointer.version != self.version or self.catalogue_generation < 1:
                raise ValueError("GitHub target must identify the exact official candidate")
        elif self.pointer is not None or self.catalogue_generation or Version(self.version).is_prerelease:
            raise ValueError("PyPI discovery is for stable releases")
        return self


class _PyPIInfo(BaseModel):
    name: str
    version: str
    requires_python: str


class _PyPIFile(BaseModel):
    model_config = ConfigDict(strict=True)
    filename: str
    size: int = Field(gt=0, le=2 * 1024**3)
    url: str
    digests: dict[str, str]
    yanked: bool
    requires_python: str | None = None


class _PyPIRelease(BaseModel):
    info: _PyPIInfo
    urls: list[_PyPIFile] = Field(min_length=1, max_length=100)


class _CatalogueCache(ReleaseRecord):
    catalogue: ReleaseCatalogue
    etag: str | None = Field(default=None, max_length=200)

    @field_validator("etag")
    @classmethod
    def header_value(cls, value: str | None) -> str | None:
        if value is not None and ("\r" in value or "\n" in value):
            raise ValueError("Invalid catalogue ETag")
        return value


class ReleaseFeed:
    """One bounded HTTP client for checking, exact-target revalidation and download.

    The cache is only a generation/ETag guard. Network failure is never a successful
    fresh check. A supplied transport is the test seam; production uses pinned DNS.
    """

    def __init__(self, cache_dir: Path, *, transport: httpx.AsyncBaseTransport | None = None,
                 python_version: str | None = None, supported_tags: list[Tag] | None = None) -> None:
        self.cache_dir = cache_dir
        self.python_version = python_version or platform.python_version()
        self.tags = list(sys_tags()) if supported_tags is None else supported_tags
        self.client = httpx.AsyncClient(
            transport=transport or PinnedDNSAsyncTransport(), trust_env=False,
            timeout=20, follow_redirects=False,
            headers={"User-Agent": "nanobot-release-check", "Accept-Encoding": "identity"},
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.client.aclose()

    @asynccontextmanager
    async def _stream(self, url: str, *, hosts: set[str], etag: str | None = None) -> AsyncGenerator[httpx.Response]:
        """Validate every redirect and keep the final response open for its reader."""
        headers = {"If-None-Match": etag} if etag else {}
        for _ in range(4):
            _url(url, hosts)
            async with self.client.stream("GET", url, headers=headers) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise ReleaseFeedError("Release redirect has no destination")
                    url = urljoin(url, location)
                    headers = {}
                    continue
                yield response
                return
        raise ReleaseFeedError("Too many release redirects")

    async def _read(self, url: str, *, limit: int, etag: str | None = None) -> tuple[bytes | None, str | None]:
        async with self._stream(url, hosts=_METADATA_HOSTS, etag=etag) as response:
            if response.status_code == 304 and etag is not None:
                return None, etag
            response.raise_for_status()
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > limit:
                    raise ReleaseFeedError("Release metadata exceeds its size limit")
            return bytes(data), response.headers.get("etag")

    def _cached(self) -> _CatalogueCache | None:
        path = self.cache_dir / "catalogue.json"
        if not path.exists():
            return None
        if path.stat().st_size > 512 * 1024:
            raise ReleaseFeedError("Release cache is invalid; no update was selected")
        return _CatalogueCache.model_validate_json(path.read_bytes())

    async def catalogue(self) -> ReleaseCatalogue:
        cached = self._cached()
        payload, etag = await self._read(CATALOGUE_URL, limit=256 * 1024, etag=cached.etag if cached else None)
        if payload is None:
            if cached is None:
                raise ReleaseFeedError("Release catalogue returned no data")
            candidate = cached
        else:
            candidate = _CatalogueCache(catalogue=ReleaseCatalogue.model_validate_json(payload), etag=etag)
        self.cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        with FileLock(str(self.cache_dir / "catalogue.lock"), timeout=5):
            previous = self._cached()
            if previous:
                try:
                    candidate.catalogue.validate_successor(previous.catalogue)
                except ValueError as exc:
                    raise ReleaseFeedError(str(exc)) from exc
            atomic_write_lines(self.cache_dir / "catalogue.json", [candidate.model_dump_json()])
        return candidate.catalogue

    async def stable(self, version: str | None = None) -> ReleaseTarget:
        suffix = f"/{release_version(version)}" if version else ""
        payload, _ = await self._read(f"{PYPI_URL}{suffix}/json", limit=4 * 1024 * 1024)
        release = _PyPIRelease.model_validate_json(payload or b"")
        identity = release_version(release.info.version)
        if canonicalize_name(release.info.name) != "nanobot-ai" or Version(identity).is_prerelease:
            raise ReleaseFeedError("PyPI did not return a stable nanobot release")
        if version and identity != version:
            raise ReleaseFeedError("PyPI returned a different version than requested")
        required = {name for name in release_filenames(identity) if name.endswith((".whl", ".tar.gz"))}
        if {file.filename for file in release.urls} != required or len(release.urls) != len(required):
            raise ReleaseFeedError("The stable release is incomplete; no source-build fallback was selected", code="publishing")
        if any(file.yanked for file in release.urls):
            raise ReleaseFeedError("The release has been withdrawn from PyPI", code="withdrawn")
        if not SpecifierSet(release.info.requires_python).contains(self.python_version, prereleases=True):
            raise ReleaseFeedError(f"Release requires Python {release.info.requires_python}", code="unsupported")
        for tag in self.tags:
            for file in release.urls:
                if not file.filename.endswith(".whl") or tag not in parse_wheel_filename(file.filename)[3]:
                    continue
                if file.requires_python and not SpecifierSet(file.requires_python).contains(self.python_version, prereleases=True):
                    continue
                return ReleaseTarget(
                    version=identity, source="pypi", url=file.url,
                    artifact=ReleaseArtifact(filename=file.filename, size=file.size, sha256=file.digests["sha256"]),
                )
        raise ReleaseFeedError("No compatible wheel is available for this Python and platform", code="unsupported")

    async def latest(self, channel: Channel) -> ReleaseTarget:
        if channel == "stable":
            return await self.stable()
        catalogue = await self.catalogue()
        pointer = catalogue.latest(channel)
        if pointer is None:
            raise ReleaseFeedError("No eligible preview is available")
        return await self._from_pointer(pointer, catalogue.generation)

    async def discover(self, channel: Channel, current_version: str) -> tuple[ReleaseTarget | None, bool]:
        """Select from one catalogue snapshot and report withdrawal independently.

        Stable installations do not depend on the Preview catalogue. A preview
        leaving that channel still checks its withdrawal status until replaced.
        """
        if channel == "stable" and not Version(current_version).is_prerelease:
            return await self.stable(), False
        try:
            catalogue = await self.catalogue()
        except (ReleaseFeedError, httpx.HTTPError, ValueError, OSError):
            if channel != "stable":
                raise
            # An unavailable Preview index must not prevent leaving Preview for
            # a verified newer final. Do not infer that the installed preview is
            # safe/current when no such successor can replace it.
            target = await self.stable()
            if Version(target.version) <= Version(current_version):
                raise
            return target, False
        withdrawn = current_version in catalogue.withdrawn
        try:
            if channel == "stable":
                return await self.stable(), withdrawn
            pointer = catalogue.latest(channel)
            return (await self._from_pointer(pointer, catalogue.generation) if pointer else None), withdrawn
        except (ReleaseFeedError, httpx.HTTPError, ValueError):
            if withdrawn:
                # A missing/incompatible replacement must not hide a freshly
                # verified warning about the version already running.
                return None, True
            raise

    async def _from_pointer(self, pointer: ReleasePointer, generation: int) -> ReleaseTarget:
        payload, _ = await self._read(pointer.manifest_url, limit=64 * 1024)
        manifest = pointer.verify_manifest(payload or b"")
        try:
            artifact = manifest.wheel_for(python_version=self.python_version, supported_tags=self.tags)
        except ValueError as exc:
            raise ReleaseFeedError("No compatible Preview wheel is available", code="unsupported") from exc
        # A stable successor in the Preview channel must still be available on PyPI.
        if not Version(manifest.version).is_prerelease:
            stable = await self.stable(manifest.version)
            if stable.artifact != artifact:
                raise ReleaseFeedError("GitHub and PyPI stable artifacts differ")
        return ReleaseTarget(version=manifest.version, artifact=artifact, source="github",
                             url=manifest.artifact_url(artifact).split("#", 1)[0],
                             pointer=pointer, catalogue_generation=generation)

    async def revalidate(self, target: ReleaseTarget) -> None:
        """Validate the approved target, never replace it with a new latest version."""
        if target.source == "pypi":
            current = await self.stable(target.version)
        else:
            catalogue = await self.catalogue()
            if catalogue.generation < target.catalogue_generation:
                raise ReleaseFeedError("Release catalogue predates the approved target")
            if target.version in catalogue.withdrawn:
                raise ReleaseFeedError(f"Release withdrawn: {catalogue.withdrawn[target.version]}")
            assert target.pointer is not None
            current = await self._from_pointer(target.pointer, catalogue.generation)
        if (current.artifact, current.url) != (target.artifact, target.url):
            raise ReleaseFeedError("The approved release artifact has changed")
        await self._authorize(target)

    async def _authorize(self, target: ReleaseTarget) -> None:
        """A matching index checksum is not permission to execute new code.

        Apply equally to PyPI/stable and GitHub/Preview, including revalidation
        before handoff. Discovery remains possible for older unsigned releases,
        but they cannot enter an automatic installation transaction.
        """
        base = f"{RELEASE_DOWNLOAD}/v{target.version}/release-manifest.json"
        payload, _ = await self._read(base, limit=64 * 1024)
        signature, _ = await self._read(base + ".sigstore.json", limit=256 * 1024)
        try:
            await asyncio.wait_for(
                asyncio.to_thread(verify_release_approval, payload or b"", signature or b""), timeout=30,
            )
        except TimeoutError as exc:
            # The verifier thread can only read/refresh public trust metadata;
            # it has no installation capability even if its IO finishes later.
            raise ReleaseFeedError("Release approval verification timed out; keep the current version and retry") from exc
        manifest = ReleaseManifest.model_validate_json(payload or b"")
        if manifest.version != target.version or target.artifact not in manifest.artifacts:
            raise ReleaseFeedError("Release approval does not match the selected package")
        if target.pointer is not None:
            target.pointer.verify_manifest(payload or b"")

    async def download(self, target: ReleaseTarget, directory: Path) -> Path:
        """Stage one verified wheel. No execution, install, or extraction occurs."""
        await self.revalidate(target)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        destination = directory / target.artifact.filename
        if destination.exists() or destination.is_symlink():
            _verify_wheel(destination, target)
            return destination
        temporary = directory / f".{uuid4().hex}.part"
        try:
            async with self._stream(target.url, hosts=_DOWNLOAD_HOSTS) as response:
                response.raise_for_status()
                size = 0
                with temporary.open("xb") as handle:
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > target.artifact.size:
                            raise ReleaseFeedError("Release download exceeds its verified size")
                        handle.write(chunk)
                _verify_wheel(temporary, target)
                # Never clobber a file another update already staged.
                try:
                    destination.hardlink_to(temporary)
                except FileExistsError:
                    _verify_wheel(destination, target)
                return destination
        finally:
            temporary.unlink(missing_ok=True)


def _verify_wheel(path: Path, target: ReleaseTarget) -> None:
    if path.is_symlink() or not path.is_file() or path.stat().st_size != target.artifact.size:
        raise ReleaseFeedError("Staged wheel size or file type does not match")
    with path.open("rb") as handle:
        if hashlib.file_digest(handle, "sha256").hexdigest() != target.artifact.sha256:
            raise ReleaseFeedError("Staged wheel checksum does not match")
    with ZipFile(path) as wheel:
        metadata_name = f"nanobot_ai-{target.version}.dist-info/METADATA"
        names = wheel.namelist()
        if len(names) != len(set(names)) or any(re.search(r"(^/|\\|(?:^|/)\.\.(?:/|$))", name) for name in names):
            raise ReleaseFeedError("Invalid wheel member paths")
        if wheel.getinfo(metadata_name).file_size > 256 * 1024:
            raise ReleaseFeedError("Wheel metadata exceeds its size limit")
        metadata = BytesParser().parsebytes(wheel.read(metadata_name))
        if metadata["Name"] != "nanobot-ai" or metadata["Version"] != target.version:
            raise ReleaseFeedError("Wheel metadata does not match the approved release")
