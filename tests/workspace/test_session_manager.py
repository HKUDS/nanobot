"""Tests for SessionManager with WorkspaceLayout."""

import json
from datetime import date
from pathlib import Path

import pytest

from nanobot.session.manager import Session, SessionManager
from nanobot.workspace.layout import WorkspaceLayout


def _make_layout(tmp_path: Path, channel_name: str = "develop", chat_id: str = "147xxx") -> WorkspaceLayout:
    return WorkspaceLayout(
        workspace=tmp_path, channel="discord",
        channel_name=channel_name, chat_id=chat_id,
    )


class TestSessionManagerGetOrCreate:
    def test_creates_new_session(self, tmp_path: Path):
        mgr = SessionManager(tmp_path)
        layout = _make_layout(tmp_path)
        session = mgr.get_or_create_from_layout(layout)
        assert session.key == "discord:147xxx"
        assert session.messages == []

    def test_returns_cached_session(self, tmp_path: Path):
        mgr = SessionManager(tmp_path)
        layout = _make_layout(tmp_path)
        s1 = mgr.get_or_create_from_layout(layout)
        s1.add_message("user", "hello")
        s2 = mgr.get_or_create_from_layout(layout)
        assert s2 is s1
        assert len(s2.messages) == 1

    def test_legacy_string_key_still_works(self, tmp_path: Path):
        mgr = SessionManager(tmp_path)
        session = mgr.get_or_create("discord:147xxx")
        assert session.key == "discord:147xxx"


class TestSessionManagerSaveLoad:
    def test_save_creates_dated_file(self, tmp_path: Path):
        mgr = SessionManager(tmp_path)
        layout = _make_layout(tmp_path)
        session = mgr.get_or_create_from_layout(layout)
        session.add_message("user", "hello")
        mgr.save(session)
        today = date.today().isoformat()
        expected = layout.session_path(today, 1)
        assert expected.exists()

    def test_load_from_disk(self, tmp_path: Path):
        mgr = SessionManager(tmp_path)
        layout = _make_layout(tmp_path)
        session = mgr.get_or_create_from_layout(layout)
        session.add_message("user", "hello")
        mgr.save(session)

        # Fresh manager, no cache
        mgr2 = SessionManager(tmp_path)
        session2 = mgr2.get_or_create_from_layout(layout)
        assert len(session2.messages) == 1
        assert session2.messages[0]["content"] == "hello"

    def test_internal_metadata_not_persisted(self, tmp_path: Path):
        mgr = SessionManager(tmp_path)
        layout = _make_layout(tmp_path)
        session = mgr.get_or_create_from_layout(layout)
        session.add_message("user", "test")
        mgr.save(session)

        today = date.today().isoformat()
        path = layout.session_path(today, 1)
        with open(path, encoding="utf-8") as f:
            meta_line = json.loads(f.readline())
        assert "_file_path" not in meta_line.get("metadata", {})


class TestSessionManagerNew:
    def test_new_session_preserves_old_file(self, tmp_path: Path):
        mgr = SessionManager(tmp_path)
        layout = _make_layout(tmp_path)
        session = mgr.get_or_create_from_layout(layout)
        session.add_message("user", "old message")
        mgr.save(session)

        today = date.today().isoformat()
        old_path = layout.session_path(today, 1)
        assert old_path.exists()

        mgr.new_session(layout)

        # Old file preserved
        assert old_path.exists()
        with open(old_path, encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
        assert any('"old message"' in l for l in lines)

        # New session is empty
        session2 = mgr.get_or_create_from_layout(layout)
        assert session2.messages == []

        # Save new session to seq 02
        session2.add_message("user", "new message")
        mgr.save(session2)
        new_path = layout.session_path(today, 2)
        assert new_path.exists()


class TestSessionManagerLlmLogPath:
    def test_current_llm_log_path(self, tmp_path: Path):
        mgr = SessionManager(tmp_path)
        layout = _make_layout(tmp_path)
        session = mgr.get_or_create_from_layout(layout)
        mgr.save(session)
        today = date.today().isoformat()
        assert mgr.current_llm_log_path(layout) == layout.llm_log_path(today, 1)
