from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from nanobot.apps import discovery


@pytest.mark.asyncio
async def test_discovery_returns_fallback_then_caches_remote_registry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    remote = {
        "schema_version": 1,
        "updated_at": "2026-08-12T01:00:00Z",
        "featured": ["mcp:notion", "cli:obsidian"],
    }
    monkeypatch.setattr(discovery, "_fetch_remote", lambda: remote)

    initial = await discovery.discovery_payload(data_dir=tmp_path)
    assert initial["featured"][0] == "mcp:github"
    assert initial["refresh_pending"] is True

    await asyncio.gather(*discovery._refresh_tasks.values())
    cached = await discovery.discovery_payload(data_dir=tmp_path)
    assert cached == remote


@pytest.mark.asyncio
async def test_discovery_keeps_last_valid_registry_when_refresh_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cached = {
        "schema_version": 1,
        "updated_at": "2026-08-11T01:00:00Z",
        "featured": ["mcp:github"],
    }
    discovery._write_cache(tmp_path / "apps-discovery.json", cached)
    monkeypatch.setattr(discovery, "CACHE_TTL_S", -1)
    monkeypatch.setattr(
        discovery,
        "_fetch_remote",
        lambda: (_ for _ in ()).throw(OSError("offline")),
    )

    payload = await discovery.discovery_payload(data_dir=tmp_path)
    assert payload == {**cached, "refresh_pending": True}
    await asyncio.gather(*discovery._refresh_tasks.values())
    assert discovery._read_cache(tmp_path / "apps-discovery.json") == cached


@pytest.mark.parametrize(
    "featured",
    [[], ["unknown:github"], ["mcp:github", "mcp:github"], ["mcp:github"] * 13],
)
def test_discovery_rejects_invalid_featured_lists(featured: list[str]) -> None:
    assert discovery._validated_payload({
        "schema_version": 1,
        "updated_at": "2026-08-12T01:00:00Z",
        "featured": featured,
    }) is None
