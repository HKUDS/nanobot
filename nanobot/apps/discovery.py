"""Small, fail-safe registry for the Apps page Featured section."""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import urllib.request
from pathlib import Path
from typing import Any, cast

REGISTRY_URL = "https://nanobot.wiki/registry/v1/discovery.json"
CACHE_TTL_S = 60 * 60
_MAX_RESPONSE_BYTES = 64 * 1024
_APP_ID_RE = re.compile(r"^(?:cli|mcp):[a-z0-9][a-z0-9._-]*$")
_FALLBACK = {
    "schema_version": 1,
    "updated_at": "2026-08-12T00:00:00Z",
    "featured": [
        "mcp:github",
        "mcp:playwright",
        "mcp:notion",
        "mcp:figma",
        "mcp:context7",
        "cli:obsidian",
        "mcp:linear",
        "cli:browser",
        "cli:1password-cli",
        "cli:blender",
        "cli:libreoffice",
        "cli:zotero",
    ],
}
_refresh_tasks: dict[Path, asyncio.Task[None]] = {}


def _validated_payload(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    payload = cast(dict[str, object], value)
    if payload.get("schema_version") != 1:
        return None
    updated_at = payload.get("updated_at")
    raw_featured = payload.get("featured")
    if not isinstance(updated_at, str) or not updated_at.strip():
        return None
    if not isinstance(raw_featured, list):
        return None
    featured_values = cast(list[object], raw_featured)
    if not 1 <= len(featured_values) <= 12:
        return None
    featured: list[str] = []
    for item in featured_values:
        if not isinstance(item, str) or _APP_ID_RE.fullmatch(item) is None:
            return None
        featured.append(item)
    if len(featured) != len(set(featured)):
        return None
    return {
        "schema_version": 1,
        "updated_at": updated_at,
        "featured": featured,
    }


def _read_cache(path: Path) -> dict[str, Any] | None:
    try:
        return _validated_payload(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return None


def _fetch_remote() -> dict[str, Any]:
    request = urllib.request.Request(
        REGISTRY_URL,
        headers={"Accept": "application/json", "User-Agent": "nanobot-apps/1"},
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        raw = response.read(_MAX_RESPONSE_BYTES + 1)
    if len(raw) > _MAX_RESPONSE_BYTES:
        raise ValueError("Apps discovery response is too large")
    payload = _validated_payload(json.loads(raw))
    if payload is None:
        raise ValueError("Invalid Apps discovery response")
    return payload


def _write_cache(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


async def _refresh(path: Path) -> None:
    try:
        payload = await asyncio.to_thread(_fetch_remote)
        await asyncio.to_thread(_write_cache, path, payload)
    except Exception:
        # Discovery is optional: the bundled list remains usable offline.
        pass


def _schedule_refresh(path: Path) -> None:
    task = _refresh_tasks.get(path)
    if task is not None and not task.done():
        return
    task = asyncio.create_task(_refresh(path))
    _refresh_tasks[path] = task
    task.add_done_callback(lambda completed: _refresh_tasks.pop(path, None))


async def discovery_payload(*, data_dir: Path) -> dict[str, Any]:
    """Return cached Featured IDs immediately and refresh stale data in the background."""
    cache_path = data_dir / "apps-discovery.json"
    cached = _read_cache(cache_path)
    try:
        fresh = cached is not None and time.time() - cache_path.stat().st_mtime < CACHE_TTL_S
    except OSError:
        fresh = False
    if fresh and cached is not None:
        return cached
    _schedule_refresh(cache_path)
    return {**(cached or _FALLBACK), "refresh_pending": True}
