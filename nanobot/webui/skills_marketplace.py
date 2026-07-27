"""Search and install skills from the skills.sh catalog."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

import httpx

from nanobot.agent.skills import SkillsLoader
from nanobot.security.network import PinnedDNSAsyncTransport

_SEARCH_URL = "https://skills.sh/api/search"
_TRENDING_URL = "https://skills.sh/api/skills/trending/0"
_SKILL_PAGE_BASE_URL = "https://www.skills.sh"
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
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_INSTALL_TIMEOUT_SECONDS = 120
_WEEKLY_CACHE_TTL_SECONDS = 300
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
        "install_supported": skills_install_supported(),
    }


async def search_marketplace_skills(
    query: str,
    workspace_path: Path,
    *,
    limit: int = 20,
) -> dict[str, Any]:
    """Search skills.sh and annotate results already installed in this workspace."""
    normalized = " ".join(query.split())
    if len(normalized) < 2:
        raise SkillsMarketplaceError("search query must contain at least 2 characters")
    if len(normalized) > 100:
        raise SkillsMarketplaceError("search query is too long")

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
        "install_supported": skills_install_supported(),
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
) -> dict[str, Any]:
    """Install one skills.sh result into ``<workspace>/skills``."""
    if not _SOURCE_RE.fullmatch(source):
        raise SkillsMarketplaceError("invalid skill source")
    if not _valid_skill_id(skill_id):
        raise SkillsMarketplaceError("invalid skill name")

    loader = SkillsLoader(workspace_path)
    existing = {
        entry["name"]: entry
        for entry in loader.list_skills(filter_unavailable=False)
    }
    if skill_id in existing:
        return {"installed": True, "already_installed": True, "name": skill_id}

    npx = shutil.which("npx")
    if npx is None:
        raise SkillsMarketplaceError(
            "Node.js with npx is required to install skills",
            status=503,
        )

    workspace = workspace_path.expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
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


def _skills_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=PinnedDNSAsyncTransport(),
        timeout=10.0,
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
        "installs": installs if isinstance(installs, int) and installs >= 0 else 0,
        "url": f"https://skills.sh/{source}/{skill_id}",
        "installed": skill_id in installed,
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
            if (
                isinstance(source, str)
                and isinstance(skill_id, str)
                and isinstance(values, list)
            ):
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
        if (
            _SOURCE_RE.fullmatch(source)
            and _valid_skill_id(skill_id)
            and ref not in refs
        ):
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
                response = await client.get(
                    f"{_SKILL_PAGE_BASE_URL}/{source}/{skill_id}"
                )
            response.raise_for_status()
        except httpx.HTTPError:
            return ref, []

        match = _TREND_VALUES_RE.search(response.text)
        if match is None:
            return ref, []
        values = [
            int(value)
            for value in match.group(1).split(",")
            if value.strip()
        ]
        return ref, values if len(values) >= 2 else []

    return dict(await asyncio.gather(*(fetch(ref) for ref in refs)))


def _valid_skill_id(value: str) -> bool:
    return len(value) <= 64 and _SKILL_RE.fullmatch(value) is not None


def _safe_output_tail(output: bytes | None) -> str:
    if not output:
        return ""
    text = _ANSI_RE.sub("", output.decode("utf-8", errors="replace"))
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return " · ".join(lines[-3:])[-600:]
