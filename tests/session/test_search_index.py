"""The canonical history index preserves search results and skips body scans."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.session.history import SessionHistoryReader
from nanobot.session.manager import Session, SessionManager, SessionStore
from nanobot.session.search_index import _INDEX_FILENAME


def _save(manager: SessionManager, key: str, content: str, title: str = "Notes") -> Session:
    session = manager.get_or_create(key)
    session.metadata.update({"title": title, "title_user_edited": True})
    session.add_message("user", content)
    manager.save(session)
    return session


@pytest.mark.parametrize("content,query", [
    ("Quarterly budget decision", "budget"),
    ("The road is called Straße.", "STRASSE"),
    ("今天天气怎么样", "天气怎么"),
    ("今天天气怎么样", "天气"),
    ('A literal "quoted" term.', '"quoted"'),
    ("A literal*marker in text.", "literal*marker"),
    ("A null\x00suffix in text.", "null\x00suffix"),
])
def test_index_preserves_literal_substring_search(tmp_path: Path, content: str, query: str) -> None:
    manager = SessionManager(tmp_path)
    _save(manager, "sdk:target", content)
    _save(manager, "sdk:other", "Unrelated")
    reader = SessionHistoryReader(manager)

    for _ in range(2):
        matches = reader.search(query, 5)
        assert [match["session_key"] for match in matches] == ["sdk:target"]
        assert matches[0]["messages"][0]["content"] == content


def test_warm_index_reads_only_matching_session_bodies(tmp_path: Path, monkeypatch) -> None:
    manager = SessionManager(tmp_path)
    for index in range(20):
        _save(manager, f"sdk:ordinary-{index}", "Ordinary conversation")
    _save(manager, "sdk:target", "zebra decision")
    reader = SessionHistoryReader(manager)
    assert reader.search("zebra", 5)

    calls: list[str] = []
    original = manager.read_session_file

    def counted_read(key: str):
        calls.append(key)
        return original(key)

    monkeypatch.setattr(manager, "read_session_file", counted_read)
    # A fresh tool/reader instance reuses the durable cache too.
    reader = SessionHistoryReader(manager)
    matches = reader.search("zebra", 5)
    assert [match["session_key"] for match in matches] == ["sdk:target"]
    assert calls == ["sdk:target"]

    calls.clear()
    assert reader.search("absent keyword", 5) == []
    assert calls == []


def test_rewrite_without_timestamp_or_size_change_refreshes_index(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    session = _save(manager, "sdk:target", "old needle")
    reader = SessionHistoryReader(manager)
    assert reader.search("old needle", 5)
    updated = session.updated_at
    session.messages[0]["content"] = "new marker"
    manager.save(session)
    assert session.updated_at == updated

    assert reader.search("old needle", 5) == []
    matches = reader.search("new marker", 5)
    assert [match["session_key"] for match in matches] == ["sdk:target"]


def test_new_deleted_and_recreated_sessions_refresh_index(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    _save(manager, "sdk:initial", "Ordinary history")
    reader = SessionHistoryReader(manager)
    assert reader.search("needle", 5) == []

    _save(manager, "sdk:target", "new needle")
    assert [match["session_key"] for match in reader.search("needle", 5)] == ["sdk:target"]
    manager.delete_session("sdk:target")
    assert reader.search("needle", 5) == []
    _save(manager, "sdk:target", "replacement marker")
    assert reader.search("needle", 5) == []
    assert [match["session_key"] for match in reader.search("marker", 5)] == ["sdk:target"]


def test_cache_failure_keeps_canonical_search_working(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    _save(manager, "sdk:target", "canonical needle")
    # A directory blocks SQLite from opening its cache at the intended path.
    (manager.sessions_dir / _INDEX_FILENAME).mkdir()
    reader = SessionHistoryReader(manager)
    assert [match["session_key"] for match in reader.search("needle", 5)] == ["sdk:target"]
    _save(manager, "sdk:later", "later needle")
    assert {match["session_key"] for match in reader.search("needle", 5)} == {
        "sdk:target", "sdk:later",
    }
    (manager.sessions_dir / _INDEX_FILENAME).rmdir()
    assert reader.search("needle", 5)
    assert (manager.sessions_dir / _INDEX_FILENAME).is_file()


def test_corrupt_cache_is_rebuilt_without_changing_history(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    _save(manager, "sdk:target", "canonical needle")
    reader = SessionHistoryReader(manager)
    assert reader.search("needle", 5)
    canonical = {path: path.read_bytes() for path in manager.sessions_dir.glob("*.jsonl")}
    (manager.sessions_dir / _INDEX_FILENAME).write_bytes(b"broken SQLite cache")

    assert [match["session_key"] for match in reader.search("needle", 5)] == ["sdk:target"]
    assert all(path.read_bytes() == content for path, content in canonical.items())
    with sqlite3.connect(manager.sessions_dir / _INDEX_FILENAME) as connection:
        assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",)


def test_save_during_sqlite_query_is_checked_without_blocking_writer(tmp_path: Path, monkeypatch) -> None:
    manager = SessionManager(tmp_path)
    _save(manager, "sdk:target", "Ordinary history")
    reader = SessionHistoryReader(manager)
    assert reader.search("new needle", 5) == []
    original = reader._search_index._matches

    with ThreadPoolExecutor(max_workers=1) as executor:
        def matches_after_save(connection, needle):
            executor.submit(_save, manager, "sdk:target", "new needle").result(timeout=3)
            return original(connection, needle)

        monkeypatch.setattr(reader._search_index, "_matches", matches_after_save)
        matches = reader.search("new needle", 5)
    assert [match["session_key"] for match in matches] == ["sdk:target"]
    assert matches[0]["messages"][0]["content"] == "new needle"


def test_custom_store_keeps_its_own_search_data(tmp_path: Path) -> None:
    store = MagicMock(spec=SessionStore)
    store.list_sessions.return_value = [{"key": "sdk:custom", "title": "Notes"}]
    payload = {
        "metadata": {"title": "Notes"}, "updated_at": None,
        "messages": [{"role": "user", "content": "custom needle"}],
    }
    store.read_metadata.return_value = payload
    store.read.return_value = payload
    manager = SessionManager(tmp_path, store=store)

    matches = SessionHistoryReader(manager).search("needle", 5)
    assert [match["session_key"] for match in matches] == ["sdk:custom"]
    assert matches[0]["messages"][0]["content"] == "custom needle"
    assert not (manager.sessions_dir / _INDEX_FILENAME).exists()


def test_index_remains_workspace_scoped(tmp_path: Path) -> None:
    first = SessionManager(tmp_path / "first")
    second = SessionManager(tmp_path / "second")
    _save(first, "sdk:target", "first needle")
    _save(second, "sdk:target", "second marker")

    assert SessionHistoryReader(first).search("needle", 5)
    assert SessionHistoryReader(second).search("needle", 5) == []
    assert SessionHistoryReader(second).search("marker", 5)


def test_threaded_searches_share_the_canonical_snapshot(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    _save(manager, "sdk:target", "canonical needle")
    reader = SessionHistoryReader(manager)
    assert reader.search("needle", 5)

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: reader.search("needle", 5), range(8)))
    assert all([match["session_key"] for match in result] == ["sdk:target"] for result in results)
