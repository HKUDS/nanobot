"""Tests for ProfileCache and ProfileStore."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nanobot.agent.memory.profile_io import ProfileCache, ProfileStore


class TestProfileCache:
    def test_read_returns_empty_dict_when_file_missing(self, tmp_path):
        persistence = MagicMock()
        cache = ProfileCache(_path=tmp_path / "profile.json", _persistence=persistence)
        result = cache.read()
        assert result == {}
        persistence.read_json.assert_not_called()

    def test_read_loads_from_disk_on_first_call(self, tmp_path):
        profile_file = tmp_path / "profile.json"
        profile_file.write_text('{"preferences": ["tea"]}')
        persistence = MagicMock()
        persistence.read_json.return_value = {"preferences": ["tea"]}
        cache = ProfileCache(_path=profile_file, _persistence=persistence)
        result = cache.read()
        assert result == {"preferences": ["tea"]}
        persistence.read_json.assert_called_once_with(profile_file)

    def test_read_uses_cache_on_second_call(self, tmp_path):
        profile_file = tmp_path / "profile.json"
        profile_file.write_text('{"preferences": ["tea"]}')
        persistence = MagicMock()
        persistence.read_json.return_value = {"preferences": ["tea"]}
        cache = ProfileCache(_path=profile_file, _persistence=persistence)
        cache.read()
        cache.read()  # second call
        persistence.read_json.assert_called_once()  # still only one disk read

    def test_write_updates_cache_atomically(self, tmp_path):
        profile_file = tmp_path / "profile.json"
        profile_file.write_text("{}")
        persistence = MagicMock()
        persistence.read_json.return_value = {}

        def _write_json(path, data):
            path.write_text(json.dumps(data))

        persistence.write_json.side_effect = _write_json
        cache = ProfileCache(_path=profile_file, _persistence=persistence)
        data = {"preferences": ["coffee"]}
        cache.write(data)
        # next read must return the written value without hitting disk again
        persistence.read_json.reset_mock()
        result = cache.read()
        assert result == data
        persistence.read_json.assert_not_called()

    def test_invalidate_forces_reload(self, tmp_path):
        profile_file = tmp_path / "profile.json"
        profile_file.write_text('{"preferences": ["tea"]}')
        persistence = MagicMock()
        persistence.read_json.return_value = {"preferences": ["tea"]}
        cache = ProfileCache(_path=profile_file, _persistence=persistence)
        cache.read()
        cache.invalidate()
        cache.read()
        assert persistence.read_json.call_count == 2


class TestProfileStoreReadWrite:
    def _make_store(self, tmp_path):
        persistence = MagicMock()
        mem0 = MagicMock()
        profile_file = tmp_path / "profile.json"
        profile_file.write_text("{}")
        persistence.read_json.return_value = None
        return ProfileStore(persistence, profile_file, mem0)

    def test_read_profile_returns_dict(self, tmp_path):
        store = self._make_store(tmp_path)
        result = store.read_profile()
        assert isinstance(result, dict)

    def test_write_profile_and_read_back(self, tmp_path):
        persistence = MagicMock()
        mem0 = MagicMock()
        profile_file = tmp_path / "profile.json"
        profile_file.write_text("{}")
        persistence.write_json.side_effect = lambda path, data: None
        store = ProfileStore(persistence, profile_file, mem0)
        store.write_profile({"preferences": ["tea"], "stable_facts": []})
        # ProfileCache.write() updates _data in-memory; read_profile reads from cache
        result = store.read_profile()
        assert result["preferences"] == ["tea"]
