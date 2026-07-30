import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Event

import pytest

from nanobot.session import Session, SessionManager
from nanobot.session.manager import JsonlSessionFiles, SQLiteSessionStore


def _session(
    key: str,
    *,
    updated_at: datetime,
    messages: list[dict],
    title: str,
) -> Session:
    return Session(
        key=key,
        messages=messages,
        created_at=datetime(2026, 7, 30, 9, 0),
        updated_at=updated_at,
        metadata={"title": title, "nested": {"language": "中文"}},
        last_consolidated=min(1, len(messages)),
    )


def _write_jsonl(source: JsonlSessionFiles, session: Session) -> None:
    records = [
        {
            "_type": "metadata",
            "key": session.key,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "metadata": session.metadata,
            "last_consolidated": session.last_consolidated,
        },
        *session.messages,
    ]
    source.get_session_path(session.key).write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def test_sqlite_store_round_trips_through_manager(tmp_path) -> None:
    key = "websocket:quote'和中文"
    stored = _session(
        key,
        updated_at=datetime(2026, 7, 30, 10, 0),
        messages=[
            {"role": "user", "content": "hello"},
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "你好"}, {"type": "image", "url": "x"}],
            },
        ],
        title="SQLite session",
    )
    manager = SessionManager(tmp_path)

    manager.save(stored, fsync=True)

    reloaded = SessionManager(tmp_path)
    assert reloaded.get_or_create(key) == stored
    assert (tmp_path / "sessions.db").is_file()
    assert not list((tmp_path / "sessions").glob("*.jsonl"))
    assert reloaded.read_session_file(key) == {
        "key": key,
        "created_at": stored.created_at.isoformat(),
        "updated_at": stored.updated_at.isoformat(),
        "metadata": stored.metadata,
        "messages": stored.messages,
    }
    assert reloaded.read_session_metadata(key) == {
        "key": key,
        "created_at": stored.created_at.isoformat(),
        "updated_at": stored.updated_at.isoformat(),
        "metadata": stored.metadata,
    }


def test_manager_migrates_jsonl_once_and_keeps_source_as_backup(
    tmp_path,
    monkeypatch,
) -> None:
    source = JsonlSessionFiles(tmp_path)
    stored = _session(
        "cli:migrate",
        updated_at=datetime(2026, 7, 30, 10, 0),
        messages=[{"role": "user", "content": "from jsonl"}],
        title="Migrated",
    )
    _write_jsonl(source, stored)
    source_path = source.get_session_path(stored.key)

    manager = SessionManager(tmp_path)

    assert manager.get_or_create(stored.key) == stored
    assert source_path.is_file()

    stored.add_message("assistant", "only in sqlite")
    manager.save(stored)

    def fail_scan(_self) -> None:
        raise AssertionError("JSONL backups should not be scanned after migration")

    monkeypatch.setattr(JsonlSessionFiles, "session_files", fail_scan)
    reloaded = SessionManager(tmp_path)
    assert [message["content"] for message in reloaded.get_or_create(stored.key).messages] == [
        "from jsonl",
        "only in sqlite",
    ]


def test_jsonl_migration_rolls_back_on_invalid_session(tmp_path) -> None:
    source = JsonlSessionFiles(tmp_path)
    valid = _session(
        "cli:valid",
        updated_at=datetime(2026, 7, 30, 10, 0),
        messages=[{"role": "user", "content": "keep me"}],
        title="Valid",
    )
    _write_jsonl(source, valid)
    invalid_path = source.get_session_path("cli:invalid")
    invalid_path.write_text("not json\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Failed to migrate JSONL session"):
        SessionManager(tmp_path)

    with sqlite3.connect(tmp_path / "sessions.db") as connection:
        session_count = connection.execute("SELECT COUNT(*) FROM sessions").fetchone()
        migration_count = connection.execute(
            "SELECT COUNT(*) FROM store_metadata WHERE key = 'jsonl_import_v1'"
        ).fetchone()
    assert session_count == (0,)
    assert migration_count == (0,)
    assert source.get_session_path(valid.key).is_file()
    assert invalid_path.is_file()


def test_jsonl_migration_is_safe_under_concurrent_startup(tmp_path) -> None:
    source = JsonlSessionFiles(tmp_path)
    stored = _session(
        "cli:concurrent-migration",
        updated_at=datetime(2026, 7, 30, 10, 0),
        messages=[{"role": "user", "content": "migrate once"}],
        title="Concurrent",
    )
    _write_jsonl(source, stored)

    with ThreadPoolExecutor(max_workers=8) as executor:
        managers = list(executor.map(lambda _: SessionManager(tmp_path), range(8)))

    assert all(manager.get_or_create(stored.key) == stored for manager in managers)
    with sqlite3.connect(tmp_path / "sessions.db") as connection:
        session_count = connection.execute("SELECT COUNT(*) FROM sessions").fetchone()
        message_count = connection.execute("SELECT COUNT(*) FROM messages").fetchone()
    assert session_count == (1,)
    assert message_count == (1,)


def test_sqlite_store_lists_sessions_with_session_projection(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path)
    older = _session(
        "cli:older",
        updated_at=datetime(2026, 7, 30, 10, 0),
        messages=[{"role": "assistant", "content": "assistant fallback"}],
        title="Older",
    )
    newer = _session(
        "cli:newer",
        updated_at=datetime(2026, 7, 30, 11, 0),
        messages=[
            {"role": "assistant", "content": "not selected"},
            {"role": "user", "content": "first user"},
        ],
        title="Newer",
    )
    store.save(older)
    store.save(newer)

    rows = store.list_sessions()

    assert [row["key"] for row in rows] == ["cli:newer", "cli:older"]
    assert [row["preview"] for row in rows] == ["first user", "assistant fallback"]
    assert [row["title"] for row in rows] == ["Newer", "Older"]
    assert [row["model_preset"] for row in rows] == [None, None]
    assert {row["path"] for row in rows} == {str(store.db_path)}


def test_sqlite_store_replaces_messages_atomically(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path)
    original = _session(
        "cli:replace",
        updated_at=datetime(2026, 7, 30, 10, 0),
        messages=[
            {"role": "user", "content": "one"},
            {"role": "assistant", "content": "two"},
        ],
        title="Original",
    )
    replacement = _session(
        original.key,
        updated_at=datetime(2026, 7, 30, 11, 0),
        messages=[{"role": "user", "content": "replacement"}],
        title="Replacement",
    )
    store.save(original)
    store.save(replacement)
    assert store.load(original.key) == replacement

    invalid = _session(
        original.key,
        updated_at=datetime(2026, 7, 30, 12, 0),
        messages=[{"role": "user", "content": object()}],
        title="Invalid",
    )
    with pytest.raises(TypeError):
        store.save(invalid)

    assert store.load(original.key) == replacement

    failed = _session(
        original.key,
        updated_at=datetime(2026, 7, 30, 13, 0),
        messages=[{"role": "user", "content": "not committed"}],
        title="Failed",
    )
    with sqlite3.connect(store.db_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_message_insert
            BEFORE INSERT ON messages
            WHEN NEW.session_key = 'cli:replace'
            BEGIN
                SELECT RAISE(ABORT, 'forced insert failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="forced insert failure"):
        store.save(failed)

    assert store.load(original.key) == replacement


def test_sqlite_store_delete_cascades_and_is_idempotent(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path)
    session = _session(
        "cli:delete",
        updated_at=datetime(2026, 7, 30, 10, 0),
        messages=[{"role": "user", "content": "delete me"}],
        title="Delete",
    )
    store.save(session)

    assert store.delete(session.key) is True
    assert store.delete(session.key) is False
    assert store.load(session.key) is None
    with sqlite3.connect(store.db_path) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM messages WHERE session_key = ?",
            (session.key,),
        ).fetchone()
    assert count == (0,)


def test_sqlite_store_rejects_unknown_schema_version(tmp_path) -> None:
    db_path = tmp_path / "sessions.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA user_version = 2")

    with pytest.raises(RuntimeError, match="Unsupported SQLite session schema version 2"):
        SQLiteSessionStore(tmp_path)


def test_sqlite_store_initializes_concurrently(tmp_path) -> None:
    with ThreadPoolExecutor(max_workers=8) as executor:
        stores = list(executor.map(lambda _: SQLiteSessionStore(tmp_path), range(8)))

    assert {store.db_path for store in stores} == {tmp_path / "sessions.db"}
    with sqlite3.connect(stores[0].db_path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()
    assert version == (1,)
    assert journal_mode == ("wal",)


def test_sqlite_store_load_uses_one_snapshot(tmp_path, monkeypatch) -> None:
    reader = SQLiteSessionStore(tmp_path)
    writer = SQLiteSessionStore(tmp_path)
    original = _session(
        "cli:snapshot",
        updated_at=datetime(2026, 7, 30, 10, 0),
        messages=[{"role": "user", "content": "before"}],
        title="Before",
    )
    replacement = _session(
        original.key,
        updated_at=datetime(2026, 7, 30, 11, 0),
        messages=[{"role": "user", "content": "after"}],
        title="After",
    )
    reader.save(original)
    metadata_read = Event()
    replacement_saved = Event()
    read_messages = reader._read_messages

    def delayed_read(connection, key):
        metadata_read.set()
        assert replacement_saved.wait(timeout=5)
        return read_messages(connection, key)

    monkeypatch.setattr(reader, "_read_messages", delayed_read)

    def replace_session() -> None:
        assert metadata_read.wait(timeout=5)
        writer.save(replacement)
        replacement_saved.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        loaded_future = executor.submit(reader.load, original.key)
        replaced_future = executor.submit(replace_session)
        loaded = loaded_future.result(timeout=10)
        replaced_future.result(timeout=10)

    assert loaded == original
    assert writer.load(original.key) == replacement
