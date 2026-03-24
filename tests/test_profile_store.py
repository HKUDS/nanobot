"""Tests for ProfileCache and ProfileStore."""

from __future__ import annotations

from pathlib import Path

from nanobot.memory.persistence.profile_io import ProfileCache, ProfileStore
from nanobot.memory.unified_db import UnifiedMemoryDB


class TestProfileCache:
    def test_read_returns_empty_dict_when_file_missing(self):
        cache = ProfileCache()
        result = cache.read()
        assert result == {}

    def test_read_loads_from_disk_on_first_call(self):
        cache = ProfileCache()
        cache.write({"preferences": ["tea"]})
        result = cache.read()
        assert result == {"preferences": ["tea"]}

    def test_read_uses_cache_on_second_call(self):
        cache = ProfileCache()
        cache.write({"preferences": ["tea"]})
        result1 = cache.read()
        result2 = cache.read()
        assert result1 == result2 == {"preferences": ["tea"]}

    def test_write_updates_cache_atomically(self):
        cache = ProfileCache()
        data = {"preferences": ["coffee"]}
        cache.write(data)
        result = cache.read()
        assert result == data

    def test_invalidate_forces_reload(self):
        cache = ProfileCache()
        cache.write({"preferences": ["tea"]})
        assert cache.read() == {"preferences": ["tea"]}
        cache.invalidate()
        assert cache.read() == {}


class TestProfileStoreReadWrite:
    def _make_store(self, tmp_path: Path) -> ProfileStore:
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir(exist_ok=True)
        db = UnifiedMemoryDB(mem_dir / "memory.db", dims=32)
        return ProfileStore(db=db)

    def test_read_profile_returns_dict(self, tmp_path: Path):
        store = self._make_store(tmp_path)
        result = store.read_profile()
        assert isinstance(result, dict)

    def test_write_profile_and_read_back(self, tmp_path: Path):
        store = self._make_store(tmp_path)
        store.write_profile({"preferences": ["tea"], "stable_facts": []})
        result = store.read_profile()
        assert result["preferences"] == ["tea"]
