import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Event

import pytest

from nanobot.session import Session, SessionManager
from nanobot.session.manager import SQLiteSessionStore


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
    manager = SessionManager(tmp_path, store=SQLiteSessionStore(tmp_path))

    manager.save(stored, fsync=True)

    reloaded = SessionManager(tmp_path, store=SQLiteSessionStore(tmp_path))
    assert reloaded.get_or_create(key) == stored
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


def test_sqlite_store_lists_sessions_with_jsonl_projection(tmp_path) -> None:
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
