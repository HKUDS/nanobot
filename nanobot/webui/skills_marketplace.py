"""Search and install skills from public Agent Skills catalogs."""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil
import stat
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from nanobot.agent.skills import SkillsLoader
from nanobot.security.network import PinnedDNSAsyncTransport
from nanobot.security.workspace_policy import WorkspaceBoundaryError, require_path_within

_PROVIDER_ALL = "all"
_PROVIDER_SKILLS_SH = "skills_sh"
_PROVIDER_SKILLHUB = "skillhub"
_PROVIDERS = {_PROVIDER_ALL, _PROVIDER_SKILLS_SH, _PROVIDER_SKILLHUB}
_SEARCH_URL = "https://skills.sh/api/search"
_TRENDING_URL = "https://skills.sh/api/skills/trending/0"
_SKILL_PAGE_BASE_URL = "https://www.skills.sh"
_SKILLHUB_API_BASE_URL = "https://api.skillhub.cn"
_SKILLHUB_SEARCH_URL = f"{_SKILLHUB_API_BASE_URL}/api/v1/search"
_SKILLHUB_TRENDING_URL = f"{_SKILLHUB_API_BASE_URL}/api/v1/showcase/trending"
_SKILLHUB_DOWNLOAD_URL = f"{_SKILLHUB_API_BASE_URL}/api/v1/download"
_SKILLHUB_PAGE_BASE_URL = "https://skillhub.cn"
_ALL_TIME_URLS = (
    "https://skills.sh/api/skills/all-time/0",
    "https://skills.sh/api/skills/all-time/1",
)
_TREND_VALUES_RE = re.compile(r'\\"values\\":\s*\[([0-9,\s]+)\]')
_SOURCE_RE = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?/"
    r"[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,98}[A-Za-z0-9])?$"
)
_SKILL_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._+-]{0,63})$")
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_INSTALL_TIMEOUT_SECONDS = 120
_WEEKLY_CACHE_TTL_SECONDS = 300
_SKILLHUB_MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
_SKILLHUB_MAX_UNPACKED_BYTES = 100 * 1024 * 1024
_SKILLHUB_MAX_FILES = 1_000
# The skills CLI's OpenClaw adapter copies into <workspace>/skills, nanobot's layout too.
_CLI_AGENT = "openclaw"
_weekly_cache: dict[tuple[str, str], list[int]] = {}
_weekly_cache_expires_at = 0.0


class SkillsMarketplaceError(Exception):
    """A safe error that can be returned to the WebUI."""

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def skills_install_supported() -> bool:
    """Return whether the official skills CLI can be launched."""
    return shutil.which("npx") is not None


async def trending_marketplace_skills(
    workspace_path: Path,
    *,
    limit: int = 8,
    provider: str = _PROVIDER_ALL,
) -> dict[str, Any]:
    """Return provider-aware marketplace rankings without mixing metric semantics."""
    selected = _valid_provider(provider)
    if selected == _PROVIDER_SKILLHUB:
        return await _trending_skillhub_skills(workspace_path, limit=limit)
    if selected == _PROVIDER_SKILLS_SH:
        return await _trending_skills_sh_skills(workspace_path, limit=limit)

    results = await asyncio.gather(
        _trending_skills_sh_skills(workspace_path, limit=limit),
        _trending_skillhub_skills(workspace_path, limit=limit),
        return_exceptions=True,
    )
    payloads = [result for result in results if isinstance(result, dict)]
    if not payloads:
        raise SkillsMarketplaceError(
            "skill marketplaces are temporarily unavailable",
            status=502,
        )
    return {
        "skills": [
            skill
            for payload in payloads
            for skill in payload.get("skills", [])
            if isinstance(skill, dict)
        ],
        "period": "mixed",
        "provider": _PROVIDER_ALL,
        "install_supported": any(bool(payload.get("install_supported")) for payload in payloads),
    }


async def _trending_skills_sh_skills(
    workspace_path: Path,
    *,
    limit: int,
) -> dict[str, Any]:
    """Return a source-diverse snapshot of skills.sh's real 24-hour leaderboard."""
    try:
        async with _skills_client() as client:
            response = await client.get(_TRENDING_URL)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SkillsMarketplaceError(
            "skills.sh trending skills are temporarily unavailable",
            status=502,
        ) from exc

    installed = _installed_skill_names(workspace_path)
    rows = payload.get("skills", []) if isinstance(payload, dict) else []
    skills: list[dict[str, Any]] = []
    seen_sources: set[str] = set()
    for rank, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        source = row.get("source")
        if not isinstance(source, str) or source in seen_sources:
            continue
        skill = _marketplace_skill(row, installed, rank=rank)
        if skill is None:
            continue
        seen_sources.add(source)
        skills.append(skill)
        if len(skills) >= min(max(limit, 1), 20):
            break

    return {
        "skills": skills,
        "period": "24h",
        "provider": _PROVIDER_SKILLS_SH,
        "install_supported": skills_install_supported(),
    }


async def search_marketplace_skills(
    query: str,
    workspace_path: Path,
    *,
    limit: int = 20,
    provider: str = _PROVIDER_ALL,
) -> dict[str, Any]:
    """Search one or all catalogs and annotate locally installed results."""
    normalized = " ".join(query.split())
    if len(normalized) < 2:
        raise SkillsMarketplaceError("search query must contain at least 2 characters")
    if len(normalized) > 100:
        raise SkillsMarketplaceError("search query is too long")

    selected = _valid_provider(provider)
    if selected == _PROVIDER_SKILLHUB:
        return await _search_skillhub_skills(normalized, workspace_path, limit=limit)
    if selected == _PROVIDER_SKILLS_SH:
        return await _search_skills_sh_skills(normalized, workspace_path, limit=limit)

    results = await asyncio.gather(
        _search_skills_sh_skills(normalized, workspace_path, limit=limit),
        _search_skillhub_skills(normalized, workspace_path, limit=limit),
        return_exceptions=True,
    )
    payloads = [result for result in results if isinstance(result, dict)]
    if not payloads:
        raise SkillsMarketplaceError(
            "skill marketplaces are temporarily unavailable",
            status=502,
        )
    return {
        "query": normalized,
        "skills": [
            skill
            for payload in payloads
            for skill in payload.get("skills", [])
            if isinstance(skill, dict)
        ],
        "provider": _PROVIDER_ALL,
        "install_supported": any(bool(payload.get("install_supported")) for payload in payloads),
    }


async def _search_skills_sh_skills(
    normalized: str,
    workspace_path: Path,
    *,
    limit: int,
) -> dict[str, Any]:
    try:
        async with _skills_client() as client:
            response = await client.get(
                _SEARCH_URL,
                params={"q": normalized, "limit": min(max(limit, 1), 50)},
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SkillsMarketplaceError(
            "skills.sh search is temporarily unavailable",
            status=502,
        ) from exc

    installed = _installed_skill_names(workspace_path)
    rows = payload.get("skills", []) if isinstance(payload, dict) else []
    skills = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        skill = _marketplace_skill(row, installed)
        if skill is not None:
            skills.append(skill)

    return {
        "query": normalized,
        "skills": skills,
        "provider": _PROVIDER_SKILLS_SH,
        "install_supported": skills_install_supported(),
    }


async def _search_skillhub_skills(
    normalized: str,
    workspace_path: Path,
    *,
    limit: int,
) -> dict[str, Any]:
    try:
        async with _skillhub_client() as client:
            response = await client.get(
                _SKILLHUB_SEARCH_URL,
                params={"q": normalized, "limit": min(max(limit, 1), 50)},
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SkillsMarketplaceError(
            "SkillHub search is temporarily unavailable",
            status=502,
        ) from exc

    installed = _installed_skill_names(workspace_path)
    rows = payload.get("results", []) if isinstance(payload, dict) else []
    skills = [
        skill
        for row in rows
        if isinstance(row, dict)
        if (skill := _skillhub_skill(row, installed)) is not None
    ]
    return {
        "query": normalized,
        "skills": skills,
        "provider": _PROVIDER_SKILLHUB,
        "install_supported": True,
    }


async def _trending_skillhub_skills(
    workspace_path: Path,
    *,
    limit: int,
) -> dict[str, Any]:
    try:
        async with _skillhub_client() as client:
            response = await client.get(_SKILLHUB_TRENDING_URL)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SkillsMarketplaceError(
            "SkillHub trending skills are temporarily unavailable",
            status=502,
        ) from exc

    installed = _installed_skill_names(workspace_path)
    rows = payload.get("skills", []) if isinstance(payload, dict) else []
    skills: list[dict[str, Any]] = []
    for rank, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        skill = _skillhub_skill(row, installed, rank=rank)
        if skill is not None:
            skills.append(skill)
        if len(skills) >= min(max(limit, 1), 20):
            break
    return {
        "skills": skills,
        "period": "trending",
        "provider": _PROVIDER_SKILLHUB,
        "install_supported": True,
    }


async def marketplace_skill_trends(
    skill_ids: list[str] | None = None,
) -> dict[str, dict[str, list[int]]]:
    """Return install history independently, filling requested cache misses."""
    requested = _valid_skill_refs(skill_ids or [])
    async with _skills_client() as client:
        weekly_installs = await _load_weekly_installs(client)
        missing = [ref for ref in requested if ref not in weekly_installs]
        if missing:
            weekly_installs.update(await _load_skill_page_trends(client, missing))

    selected = requested or list(weekly_installs)
    return {
        "trends": {
            f"{source}/{skill_id}": values
            for source, skill_id in selected
            if (values := weekly_installs.get((source, skill_id))) is not None
        }
    }


async def install_marketplace_skill(
    source: str,
    skill_id: str,
    workspace_path: Path,
    *,
    provider: str = _PROVIDER_SKILLS_SH,
    version: str = "",
) -> dict[str, Any]:
    """Install one normalized marketplace result into ``<workspace>/skills``."""
    selected = _valid_provider(provider, allow_all=False)
    if selected == _PROVIDER_SKILLHUB:
        return await _install_skillhub_skill(skill_id, version, workspace_path)
    return await _install_skills_sh_skill(source, skill_id, workspace_path)


async def _install_skills_sh_skill(
    source: str,
    skill_id: str,
    workspace_path: Path,
) -> dict[str, Any]:
    if not _SOURCE_RE.fullmatch(source):
        raise SkillsMarketplaceError("invalid skill source")
    if not _valid_skill_id(skill_id):
        raise SkillsMarketplaceError("invalid skill name")

    loader = SkillsLoader(workspace_path)
    existing = {entry["name"]: entry for entry in loader.list_skills(filter_unavailable=False)}
    if skill_id in existing:
        return {"installed": True, "already_installed": True, "name": skill_id}

    workspace = workspace_path.expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    try:
        require_path_within(
            workspace / "skills",
            workspace,
            message="skills directory must stay inside the workspace",
        )
    except WorkspaceBoundaryError as exc:
        raise SkillsMarketplaceError(str(exc), status=403) from exc

    npx = shutil.which("npx")
    if npx is None:
        raise SkillsMarketplaceError(
            "Node.js with npx is required to install skills",
            status=503,
        )

    env = os.environ.copy()
    env["DISABLE_TELEMETRY"] = "1"
    command = (
        npx,
        "--yes",
        "skills@latest",
        "add",
        source,
        "--skill",
        skill_id,
        "--agent",
        _CLI_AGENT,
        "--copy",
        "--yes",
    )

    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(workspace),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        output, _ = await asyncio.wait_for(
            process.communicate(),
            timeout=_INSTALL_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        process.kill()
        await process.communicate()
        raise SkillsMarketplaceError("skill installation timed out", status=504) from exc

    if process.returncode != 0:
        detail = _safe_output_tail(output)
        message = "skill installation failed"
        if detail:
            message = f"{message}: {detail}"
        raise SkillsMarketplaceError(message, status=502)

    installed = next(
        (
            entry
            for entry in loader.list_skills(filter_unavailable=False)
            if entry["source"] == "workspace" and entry["name"] == skill_id
        ),
        None,
    )
    if installed is None:
        raise SkillsMarketplaceError(
            "installer completed but the skill was not found in this workspace",
            status=502,
        )
    return {"installed": True, "already_installed": False, "name": skill_id}


async def _install_skillhub_skill(
    skill_id: str,
    requested_version: str,
    workspace_path: Path,
) -> dict[str, Any]:
    if not _valid_skill_id(skill_id):
        raise SkillsMarketplaceError("invalid SkillHub skill name")
    if requested_version and _VERSION_RE.fullmatch(requested_version) is None:
        raise SkillsMarketplaceError("invalid SkillHub skill version")

    loader = SkillsLoader(workspace_path)
    existing = {entry["name"]: entry for entry in loader.list_skills(filter_unavailable=False)}
    if skill_id in existing:
        return {
            "installed": True,
            "already_installed": True,
            "name": skill_id,
            "provider": _PROVIDER_SKILLHUB,
        }

    workspace = workspace_path.expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    try:
        skills_root = require_path_within(
            workspace / "skills",
            workspace,
            message="skills directory must stay inside the workspace",
        )
    except WorkspaceBoundaryError as exc:
        raise SkillsMarketplaceError(str(exc), status=403) from exc
    skills_root.mkdir(parents=True, exist_ok=True)
    target = skills_root / skill_id

    try:
        async with _skillhub_client() as client:
            version = requested_version or await _skillhub_latest_version(client, skill_id)
            signature = await _skillhub_signature(client, skill_id, version)
            expected_hash = signature.get("content_hash")
            if not isinstance(expected_hash, str) or not re.fullmatch(
                r"[0-9a-fA-F]{64}",
                expected_hash,
            ):
                raise SkillsMarketplaceError(
                    "SkillHub did not provide a valid package fingerprint",
                    status=502,
                )

            with tempfile.TemporaryDirectory(
                prefix=".skillhub-install-",
                dir=skills_root,
            ) as temporary:
                temporary_path = Path(temporary)
                archive_path = temporary_path / f"{skill_id}.zip"
                stage_path = temporary_path / "stage"
                await _download_skillhub_archive(
                    client,
                    skill_id,
                    version,
                    archive_path,
                )
                actual_hash = _validate_skillhub_archive(archive_path)
                if actual_hash.lower() != expected_hash.lower():
                    raise SkillsMarketplaceError(
                        "SkillHub package fingerprint did not match",
                        status=502,
                    )
                _extract_skillhub_archive(archive_path, stage_path)
                if target.exists():
                    return {
                        "installed": True,
                        "already_installed": True,
                        "name": skill_id,
                        "provider": _PROVIDER_SKILLHUB,
                    }
                os.replace(stage_path, target)
    except SkillsMarketplaceError:
        raise
    except (httpx.HTTPError, OSError, zipfile.BadZipFile) as exc:
        raise SkillsMarketplaceError(
            "SkillHub skill installation failed",
            status=502,
        ) from exc

    installed = next(
        (
            entry
            for entry in loader.list_skills(filter_unavailable=False)
            if entry["source"] == "workspace" and entry["name"] == skill_id
        ),
        None,
    )
    if installed is None:
        raise SkillsMarketplaceError(
            "installer completed but the skill was not found in this workspace",
            status=502,
        )
    return {
        "installed": True,
        "already_installed": False,
        "name": skill_id,
        "provider": _PROVIDER_SKILLHUB,
        "version": version,
    }


async def _skillhub_latest_version(client: httpx.AsyncClient, skill_id: str) -> str:
    response = await client.get(
        f"{_SKILLHUB_API_BASE_URL}/api/v1/skills/{quote(skill_id, safe='')}"
    )
    response.raise_for_status()
    payload = response.json()
    latest = payload.get("latestVersion", {}) if isinstance(payload, dict) else {}
    version = latest.get("version") if isinstance(latest, dict) else None
    if not isinstance(version, str) or _VERSION_RE.fullmatch(version) is None:
        raise SkillsMarketplaceError(
            "SkillHub did not return a valid skill version",
            status=502,
        )
    return version


async def _skillhub_signature(
    client: httpx.AsyncClient,
    skill_id: str,
    version: str,
) -> dict[str, Any]:
    response = await client.get(
        f"{_SKILLHUB_API_BASE_URL}/api/v1/open/skills/"
        f"{quote(skill_id, safe='')}/versions/{quote(version, safe='')}/signature"
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise SkillsMarketplaceError(
            "SkillHub returned an invalid package fingerprint",
            status=502,
        )
    return payload


async def _download_skillhub_archive(
    client: httpx.AsyncClient,
    skill_id: str,
    version: str,
    destination: Path,
) -> None:
    redirect = await client.get(
        _SKILLHUB_DOWNLOAD_URL,
        params={"slug": skill_id, "version": version},
    )
    if redirect.status_code not in {301, 302, 303, 307, 308}:
        redirect.raise_for_status()
        raise SkillsMarketplaceError(
            "SkillHub returned an unexpected download response",
            status=502,
        )
    location = redirect.headers.get("location", "")
    if not _valid_skillhub_download_url(location):
        raise SkillsMarketplaceError(
            "SkillHub returned an unsafe download location",
            status=502,
        )

    received = 0
    async with client.stream(
        "GET",
        location,
        headers={"Accept": "application/zip,application/octet-stream"},
    ) as response:
        response.raise_for_status()
        declared = response.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > _SKILLHUB_MAX_DOWNLOAD_BYTES:
            raise SkillsMarketplaceError("SkillHub package is too large", status=413)
        with destination.open("wb") as output:
            async for chunk in response.aiter_bytes():
                received += len(chunk)
                if received > _SKILLHUB_MAX_DOWNLOAD_BYTES:
                    raise SkillsMarketplaceError("SkillHub package is too large", status=413)
                output.write(chunk)


def _valid_skillhub_download_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        hostname = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.username is None
        and parsed.password is None
        and port in {None, 443}
        and hostname.endswith(".myqcloud.com")
    )


def _validated_skillhub_entries(
    archive: zipfile.ZipFile,
) -> list[tuple[zipfile.ZipInfo, str]]:
    entries: list[tuple[zipfile.ZipInfo, str]] = []
    seen: set[str] = set()
    unpacked = 0
    for info in archive.infolist():
        raw_name = info.filename.replace("\\", "/")
        path = PurePosixPath(raw_name)
        normalized = path.as_posix()
        mode = info.external_attr >> 16
        kind = stat.S_IFMT(mode)
        if (
            not normalized
            or "\x00" in normalized
            or path.is_absolute()
            or ".." in path.parts
            or (path.parts and ":" in path.parts[0])
            or kind == stat.S_IFLNK
            or kind not in {0, stat.S_IFREG, stat.S_IFDIR}
        ):
            raise SkillsMarketplaceError(
                f"SkillHub package contains an unsafe path: {raw_name}",
                status=422,
            )
        if info.is_dir():
            continue
        if normalized in seen:
            raise SkillsMarketplaceError(
                f"SkillHub package contains a duplicate path: {normalized}",
                status=422,
            )
        seen.add(normalized)
        unpacked += info.file_size
        if len(entries) >= _SKILLHUB_MAX_FILES:
            raise SkillsMarketplaceError("SkillHub package contains too many files", status=413)
        if unpacked > _SKILLHUB_MAX_UNPACKED_BYTES:
            raise SkillsMarketplaceError(
                "SkillHub package expands beyond the size limit", status=413
            )
        entries.append((info, normalized))
    if "SKILL.md" not in seen:
        raise SkillsMarketplaceError(
            "SkillHub package does not contain a root SKILL.md",
            status=422,
        )
    return entries


def _validate_skillhub_archive(archive_path: Path) -> str:
    hashed: list[tuple[str, str]] = []
    with zipfile.ZipFile(archive_path, "r") as archive:
        for info, normalized in _validated_skillhub_entries(archive):
            if _skillhub_hash_ignored(normalized):
                continue
            digest = hashlib.sha256()
            with archive.open(info, "r") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
            hashed.append((normalized, digest.hexdigest()))
    combined = hashlib.sha256()
    for normalized, digest in sorted(hashed):
        combined.update(f"{normalized}:{digest}\n".encode())
    return combined.hexdigest()


def _skillhub_hash_ignored(path: str) -> bool:
    parts = PurePosixPath(path).parts
    basename = parts[-1] if parts else ""
    return (
        path == "_meta.json"
        or "__MACOSX" in parts
        or basename == ".DS_Store"
        or basename.startswith("._")
        or basename.lower() == "thumbs.db"
    )


def _extract_skillhub_archive(archive_path: Path, destination: Path) -> None:
    destination.mkdir()
    with zipfile.ZipFile(archive_path, "r") as archive:
        for info, normalized in _validated_skillhub_entries(archive):
            target = destination.joinpath(*PurePosixPath(normalized).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info, "r") as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            mode = (info.external_attr >> 16) & 0o777
            if mode:
                target.chmod(mode & 0o755)


def _skills_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=PinnedDNSAsyncTransport(),
        timeout=10.0,
        follow_redirects=False,
    )


def _skillhub_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=PinnedDNSAsyncTransport(),
        timeout=httpx.Timeout(30.0, connect=10.0),
        follow_redirects=False,
    )


def _installed_skill_names(workspace_path: Path) -> set[str]:
    return {
        entry["name"]
        for entry in SkillsLoader(workspace_path).list_skills(filter_unavailable=False)
    }


def _marketplace_skill(
    row: dict[str, Any],
    installed: set[str],
    *,
    rank: int | None = None,
) -> dict[str, Any] | None:
    source = row.get("source")
    skill_id = row.get("skillId")
    if not isinstance(source, str) or not _SOURCE_RE.fullmatch(source):
        return None
    if not isinstance(skill_id, str) or not _valid_skill_id(skill_id):
        return None
    display_name = row.get("name")
    if not isinstance(display_name, str) or not display_name.strip():
        display_name = skill_id
    installs = row.get("installs")
    skill: dict[str, Any] = {
        "id": f"{source}/{skill_id}",
        "skill_id": skill_id,
        "name": display_name.strip(),
        "source": source,
        "provider": _PROVIDER_SKILLS_SH,
        "installs": installs if isinstance(installs, int) and installs >= 0 else 0,
        "url": f"https://skills.sh/{source}/{skill_id}",
        "installed": skill_id in installed,
        "install_supported": skills_install_supported(),
        "metric": "installs_24h" if rank is not None else "installs_total",
    }
    if rank is not None:
        skill["rank"] = rank
    return skill


def _skillhub_skill(
    row: dict[str, Any],
    installed: set[str],
    *,
    rank: int | None = None,
) -> dict[str, Any] | None:
    skill_id = row.get("slug")
    if not isinstance(skill_id, str) or not _valid_skill_id(skill_id):
        return None
    display_name = row.get("displayName") or row.get("name") or skill_id
    if not isinstance(display_name, str) or not display_name.strip():
        display_name = skill_id

    namespace = row.get("namespace")
    handle = namespace.get("handle") if isinstance(namespace, dict) else None
    if not isinstance(handle, str) or not handle.strip():
        owner = row.get("owner_name") or row.get("ownerName")
        handle = owner if isinstance(owner, str) and owner.strip() else "community"
    source = f"@{handle.strip()}/{skill_id}"

    installs = row.get("installs")
    downloads = row.get("downloads")
    publisher = row.get("publisher")
    verified = bool(isinstance(publisher, dict) and publisher.get("verified") is True)
    labels = row.get("labels")
    requires_api_key = bool(
        isinstance(labels, dict) and str(labels.get("requires_api_key", "")).lower() == "true"
    )
    version = row.get("version")
    if not isinstance(version, str) or _VERSION_RE.fullmatch(version) is None:
        version = ""

    skill: dict[str, Any] = {
        "id": f"{_PROVIDER_SKILLHUB}:{skill_id}",
        "skill_id": skill_id,
        "name": display_name.strip(),
        "source": source,
        "provider": _PROVIDER_SKILLHUB,
        "installs": installs if isinstance(installs, int) and installs >= 0 else 0,
        "downloads": downloads if isinstance(downloads, int) and downloads >= 0 else 0,
        "url": f"{_SKILLHUB_PAGE_BASE_URL}/{quote(handle.strip(), safe='')}/"
        f"{quote(skill_id, safe='')}",
        "installed": skill_id in installed,
        "install_supported": True,
        "metric": "installs_total",
        "version": version,
        "verified": verified,
        "requires_api_key": requires_api_key,
    }
    if rank is not None:
        skill["rank"] = rank
    return skill


async def _load_weekly_installs(
    client: httpx.AsyncClient,
) -> dict[tuple[str, str], list[int]]:
    global _weekly_cache, _weekly_cache_expires_at

    now = time.monotonic()
    if now < _weekly_cache_expires_at:
        return _weekly_cache

    responses = await asyncio.gather(
        *(client.get(url) for url in _ALL_TIME_URLS),
        return_exceptions=True,
    )
    history: dict[tuple[str, str], list[int]] = {}
    successful = False
    for response in responses:
        if isinstance(response, BaseException):
            continue
        try:
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            continue
        successful = True
        rows = payload.get("skills", []) if isinstance(payload, dict) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            source = row.get("source")
            skill_id = row.get("skillId")
            values = row.get("weeklyInstalls")
            if isinstance(source, str) and isinstance(skill_id, str) and isinstance(values, list):
                clean = [
                    value
                    for value in values
                    if isinstance(value, int) and not isinstance(value, bool) and value >= 0
                ]
                if len(clean) >= 2:
                    history[(source, skill_id)] = clean

    if successful:
        _weekly_cache = history
        _weekly_cache_expires_at = now + _WEEKLY_CACHE_TTL_SECONDS
    return history


def _valid_skill_refs(skill_ids: list[str]) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    for value in skill_ids[:20]:
        if not isinstance(value, str) or "/" not in value:
            continue
        source, skill_id = value.rsplit("/", 1)
        ref = (source, skill_id)
        if _SOURCE_RE.fullmatch(source) and _valid_skill_id(skill_id) and ref not in refs:
            refs.append(ref)
    return refs


async def _load_skill_page_trends(
    client: httpx.AsyncClient,
    refs: list[tuple[str, str]],
) -> dict[tuple[str, str], list[int]]:
    semaphore = asyncio.Semaphore(6)

    async def fetch(ref: tuple[str, str]) -> tuple[tuple[str, str], list[int]]:
        source, skill_id = ref
        try:
            async with semaphore:
                response = await client.get(f"{_SKILL_PAGE_BASE_URL}/{source}/{skill_id}")
            response.raise_for_status()
        except httpx.HTTPError:
            return ref, []

        match = _TREND_VALUES_RE.search(response.text)
        if match is None:
            return ref, []
        values = [int(value) for value in match.group(1).split(",") if value.strip()]
        return ref, values if len(values) >= 2 else []

    return dict(await asyncio.gather(*(fetch(ref) for ref in refs)))


def _valid_skill_id(value: str) -> bool:
    return len(value) <= 64 and _SKILL_RE.fullmatch(value) is not None


def _valid_provider(value: str, *, allow_all: bool = True) -> str:
    normalized = value.strip().lower() or _PROVIDER_ALL
    allowed = _PROVIDERS if allow_all else _PROVIDERS - {_PROVIDER_ALL}
    if normalized not in allowed:
        raise SkillsMarketplaceError("invalid skill marketplace provider")
    return normalized


def _safe_output_tail(output: bytes | None) -> str:
    if not output:
        return ""
    text = _ANSI_RE.sub("", output.decode("utf-8", errors="replace"))
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return " · ".join(lines[-3:])[-600:]
