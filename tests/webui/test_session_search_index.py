"""Tests for the FTS5 session search mirror.

The index is a rebuildable mirror over the JSONL store; every test uses a
temporary workspace so the per-workspace database file is isolated.
"""

from __future__ import annotations

from pathlib import Path

from nanobot.session.manager import SessionManager
from nanobot.webui.session_access import WebuiSessionAccess
from nanobot.webui.session_search_index import (
    _INDEX_FILENAME,
    SessionSearchIndex,
)


def _save_session(manager: SessionManager, key: str, title: str, messages: list[tuple[str, str]]) -> None:
    session = manager.get_or_create(key)
    session.metadata["title"] = title
    session.metadata["title_user_edited"] = True
    for role, text in messages:
        session.add_message(role, text)
    manager.save(session)


def _search(manager: SessionManager, query: str, limit: int = 10):
    return WebuiSessionAccess(manager).search(query, limit)


class TestSessionSearchIndex:
    def test_english_keyword_found_via_index(self, tmp_path: Path) -> None:
        manager = SessionManager(tmp_path)
        _save_session(manager, "websocket:a", "Quarterly review", [
            ("user", "Can we review the quarterly budget numbers?"),
            ("assistant", "Sure."),
        ])
        _save_session(manager, "websocket:b", "Other", [("user", "hello")])

        matches = _search(manager, "budget")
        assert [m["session_key"] for m in matches] == ["websocket:a"]
        assert matches[0]["messages"]  # excerpt present

    def test_cjk_keyword_found_via_index(self, tmp_path: Path) -> None:
        manager = SessionManager(tmp_path)
        _save_session(manager, "websocket:cjk", "闲聊", [
            ("user", "今天天气怎么样？"),
            ("assistant", "看起来是晴天。"),
        ])

        matches = _search(manager, "天气怎么")
        assert [m["session_key"] for m in matches] == ["websocket:cjk"]
        assert matches[0]["messages"]

    def test_short_cjk_query_falls_back_to_legacy_scan(self, tmp_path: Path) -> None:
        manager = SessionManager(tmp_path)
        _save_session(manager, "websocket:cjk", "闲聊", [
            ("user", "今天天气怎么样？"),
        ])

        # Two characters is below the trigram minimum; legacy scan must still find it.
        matches = _search(manager, "天气")
        assert [m["session_key"] for m in matches] == ["websocket:cjk"]

    def test_deep_history_keyword_beyond_preview_found(self, tmp_path: Path) -> None:
        manager = SessionManager(tmp_path)
        _save_session(manager, "websocket:deep", "Deep", [
            ("user", "tell me about the zebra crossing project"),
            *(("user", f"filler {i}") for i in range(250)),
        ])

        matches = _search(manager, "zebra")
        assert [m["session_key"] for m in matches] == ["websocket:deep"]

    def test_no_match_returns_empty(self, tmp_path: Path) -> None:
        manager = SessionManager(tmp_path)
        _save_session(manager, "websocket:a", "Budget", [("user", "hello")])

        assert _search(manager, "zzz-no-such-term") == []

    def test_updated_session_is_reindexed(self, tmp_path: Path) -> None:
        manager = SessionManager(tmp_path)
        _save_session(manager, "websocket:a", "Budget", [("user", "hello")])
        assert _search(manager, "budget") != []

        _save_session(manager, "websocket:a", "Budget", [
            ("user", "now mentioning zebra too"),
        ])
        matches = _search(manager, "zebra")
        assert [m["session_key"] for m in matches] == ["websocket:a"]

    def test_deleted_session_is_removed_from_index(self, tmp_path: Path) -> None:
        manager = SessionManager(tmp_path)
        _save_session(manager, "websocket:a", "Budget", [("user", "hello")])
        assert _search(manager, "budget") != []

        manager.delete_session("websocket:a")
        assert _search(manager, "budget") == []

    def test_index_file_is_created_per_workspace(self, tmp_path: Path) -> None:
        manager = SessionManager(tmp_path)
        _save_session(manager, "websocket:a", "Budget", [("user", "hello")])
        _search(manager, "budget")

        assert (Path(manager.sessions_dir) / _INDEX_FILENAME).exists()

    def test_fallback_when_index_cannot_open(self, tmp_path: Path, monkeypatch) -> None:
        manager = SessionManager(tmp_path)
        _save_session(manager, "websocket:a", "Budget", [("user", "hello")])

        index = SessionSearchIndex(manager)
        # Force the DB open to fail; search must still return the right answer.
        monkeypatch.setattr(index, "_usable", lambda: False)
        access = WebuiSessionAccess(manager)
        access._search_index = index  # pyright: ignore[reportPrivateUsage]
        matches = access.search("budget", 10)
        assert [m["session_key"] for m in matches] == ["websocket:a"]
