"""Session persistence and JSONL recovery tests."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from nanobot.session.manager import JsonlSessionFiles, Session, SessionManager


def _write_jsonl(workspace: Path, key: str, lines: list[str]) -> Path:
    path = JsonlSessionFiles(workspace).get_session_path(key)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_manager_saves_only_to_sqlite(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    session = Session(key="test:sqlite")
    session.add_message("user", "hello")

    manager.save(session)

    assert (tmp_path / "sessions.db").is_file()
    assert not list((tmp_path / "sessions").glob("*.jsonl"))
    assert SessionManager(tmp_path).get_or_create(session.key) == session


def test_truncated_jsonl_is_repaired_during_migration(tmp_path: Path) -> None:
    key = "test:truncated"
    _write_jsonl(
        tmp_path,
        key,
        [
            json.dumps(
                {
                    "_type": "metadata",
                    "key": key,
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat(),
                    "metadata": {},
                    "last_consolidated": 0,
                }
            ),
            json.dumps({"role": "user", "content": "hello"}),
            '{"role": "assistant", "content": "partial...',
        ],
    )

    session = SessionManager(tmp_path).get_or_create(key)

    assert session.messages == [{"role": "user", "content": "hello"}]


def test_jsonl_repair_preserves_valid_records(tmp_path: Path) -> None:
    key = "test:mixed"
    _write_jsonl(
        tmp_path,
        key,
        [
            "BROKEN",
            json.dumps({"role": "user", "content": "first"}),
            '{"role": "assistant", "content": "broken',
            json.dumps({"role": "user", "content": "second"}),
        ],
    )

    session = SessionManager(tmp_path).get_or_create(key)

    assert [message["content"] for message in session.messages] == ["first", "second"]


def test_all_corrupt_jsonl_blocks_migration_without_removing_source(tmp_path: Path) -> None:
    path = _write_jsonl(tmp_path, "test:all-bad", ["garbage", "{{invalid json"])

    with pytest.raises(RuntimeError, match="Failed to migrate JSONL session"):
        SessionManager(tmp_path)

    assert path.is_file()


def test_empty_jsonl_migrates_as_empty_session(tmp_path: Path) -> None:
    key = "test:empty"
    path = JsonlSessionFiles(tmp_path).get_session_path(key)
    path.write_text("", encoding="utf-8")

    session = SessionManager(tmp_path).get_or_create(key)

    assert session.key == key
    assert session.messages == []


def test_bad_jsonl_timestamp_uses_fallback_and_clamps_offset(tmp_path: Path) -> None:
    key = "test:bad-time"
    _write_jsonl(
        tmp_path,
        key,
        [
            json.dumps(
                {
                    "_type": "metadata",
                    "key": key,
                    "created_at": "not-a-date",
                    "updated_at": "also-bad",
                    "metadata": {},
                    "last_consolidated": 5,
                }
            ),
            json.dumps({"role": "user", "content": "hi"}),
        ],
    )

    session = SessionManager(tmp_path).get_or_create(key)

    assert session.last_consolidated == 0
    assert isinstance(session.created_at, datetime)


def test_repaired_jsonl_is_available_through_read_and_list(tmp_path: Path) -> None:
    key = "test:read-repair"
    _write_jsonl(
        tmp_path,
        key,
        [
            "NOT VALID JSON",
            json.dumps(
                {
                    "_type": "metadata",
                    "key": key,
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat(),
                    "metadata": {"source": "repair"},
                    "last_consolidated": 0,
                }
            ),
            json.dumps({"role": "user", "content": "survived"}),
        ],
    )
    manager = SessionManager(tmp_path)

    payload = manager.read_session_file(key)

    assert payload is not None
    assert payload["metadata"] == {"source": "repair"}
    assert payload["messages"] == [{"role": "user", "content": "survived"}]
    assert [row["key"] for row in manager.list_sessions()] == [key]
