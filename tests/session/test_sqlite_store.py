import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from threading import Event
from typing import cast

import pytest

from nanobot.providers.base import ProviderConversationState
from nanobot.session import Session, SessionManager
from nanobot.session.manager import JsonlSessionFiles, SQLiteSessionStore


def _provider_state(secret: str) -> ProviderConversationState:
    return ProviderConversationState(
        kind="openai_responses",
        provider="openai:https://api.openai.com/v1",
        model="gpt-5.6",
        version=1,
        payload={
            "items": [
                {
                    "type": "reasoning",
                    "encrypted_content": secret,
                }
            ]
        },
        pending_messages=[{"role": "user", "content": "continue"}],
    )


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
    if session.provider_state is not None:
        records.insert(
            1,
            {
                "_type": "provider_state",
                "state": session.provider_state.to_private_record(),
            },
        )
    source.get_session_path(session.key).write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def _create_v1_database(
    workspace: Path,
    session: Session,
    *,
    migration_marker: str | None = None,
) -> None:
    with sqlite3.connect(workspace / "sessions.db") as connection:
        connection.executescript(
            """
            CREATE TABLE sessions (
                key TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata TEXT NOT NULL,
                last_consolidated INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE messages (
                session_key TEXT NOT NULL,
                position INTEGER NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY (session_key, position),
                FOREIGN KEY (session_key) REFERENCES sessions(key) ON DELETE CASCADE
            );
            CREATE TABLE store_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            PRAGMA user_version = 1;
            """
        )
        connection.execute(
            """
            INSERT INTO sessions (
                key, created_at, updated_at, metadata, last_consolidated
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                session.key,
                session.created_at.isoformat(),
                session.updated_at.isoformat(),
                json.dumps(session.metadata),
                session.last_consolidated,
            ),
        )
        connection.executemany(
            "INSERT INTO messages (session_key, position, payload) VALUES (?, ?, ?)",
            [
                (session.key, position, json.dumps(message))
                for position, message in enumerate(session.messages)
            ],
        )
        if migration_marker is not None:
            connection.execute(
                "INSERT INTO store_metadata (key, value) VALUES (?, ?)",
                ("jsonl_import_v1", migration_marker),
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


def test_sqlite_store_keeps_provider_state_private_across_restart(tmp_path) -> None:
    secret = "encrypted-reasoning-blob"
    stored = _session(
        "websocket:private-state",
        updated_at=datetime(2026, 7, 30, 10, 0),
        messages=[{"role": "user", "content": "hello"}],
        title="Private state",
    )
    stored.provider_state = _provider_state(secret)
    manager = SessionManager(tmp_path)

    manager.save(stored, fsync=True)
    reloaded = SessionManager(tmp_path)

    assert reloaded.get_or_create(stored.key).provider_state == stored.provider_state
    public_payloads = [
        reloaded.read_session_file(stored.key),
        reloaded.read_session_metadata(stored.key),
        reloaded.list_sessions(),
    ]
    assert secret not in json.dumps(public_payloads, ensure_ascii=False)

    with sqlite3.connect(tmp_path / "sessions.db") as connection:
        private_metadata, public_metadata = connection.execute(
            "SELECT private_metadata, metadata FROM sessions WHERE key = ?",
            (stored.key,),
        ).fetchone()
        message_payloads = connection.execute(
            "SELECT payload FROM messages WHERE session_key = ?",
            (stored.key,),
        ).fetchall()
    assert json.loads(private_metadata)["provider_state"] == (
        stored.provider_state.to_private_record()
    )
    assert secret not in public_metadata
    assert all(secret not in payload for (payload,) in message_payloads)

    stored.provider_state = None
    manager.save(stored)

    assert SessionManager(tmp_path).get_or_create(stored.key).provider_state is None
    with sqlite3.connect(tmp_path / "sessions.db") as connection:
        private_metadata = connection.execute(
            "SELECT private_metadata FROM sessions WHERE key = ?",
            (stored.key,),
        ).fetchone()
    assert private_metadata == ("{}",)


def test_session_metadata_remains_extensible_across_migration_restart_and_fork(
    tmp_path,
) -> None:
    future_metadata = {
        "future_feature": {
            "nested": [
                1,
                None,
                True,
                {"language": "中文", "ratio": 0.75},
            ]
        }
    }
    source = JsonlSessionFiles(tmp_path)
    stored = _session(
        "websocket:extensible-metadata",
        updated_at=datetime(2026, 7, 30, 10, 0),
        messages=[{"role": "user", "content": "preserve metadata"}],
        title="Extensible",
    )
    stored.metadata.update(future_metadata)
    _write_jsonl(source, stored)

    manager = SessionManager(tmp_path)
    assert manager.read_session_metadata(stored.key)["metadata"]["future_feature"] == (
        future_metadata["future_feature"]
    )
    assert manager.list_sessions()[0]["key"] == stored.key
    assert manager.read_session_file(stored.key)["metadata"]["future_feature"] == (
        future_metadata["future_feature"]
    )

    reloaded = SessionManager(tmp_path)
    forked = reloaded.fork_session_before_user_index(
        stored.key,
        "websocket:extensible-metadata-fork",
        1,
    )

    assert forked is not None
    assert forked.metadata["future_feature"] == future_metadata["future_feature"]
    assert SessionManager(tmp_path).get_or_create(forked.key).metadata["future_feature"] == (
        future_metadata["future_feature"]
    )


def test_jsonl_migration_preserves_provider_state_without_public_leakage(tmp_path) -> None:
    secret = "migrated-encrypted-state"
    source = JsonlSessionFiles(tmp_path)
    stored = _session(
        "cli:migrate-private-state",
        updated_at=datetime(2026, 7, 30, 10, 0),
        messages=[{"role": "user", "content": "public history"}],
        title="Migrated private state",
    )
    stored.provider_state = _provider_state(secret)
    _write_jsonl(source, stored)

    manager = SessionManager(tmp_path)
    migrated = manager.get_or_create(stored.key)

    assert migrated.provider_state == stored.provider_state
    assert migrated.messages == stored.messages
    assert secret not in json.dumps(manager.read_session_file(stored.key))
    assert secret not in json.dumps(manager.list_sessions())


def test_jsonl_migration_drops_invalid_provider_state_from_public_history(tmp_path) -> None:
    key = "cli:invalid-private-state"
    source = JsonlSessionFiles(tmp_path)
    source.get_session_path(key).write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "_type": "metadata",
                        "key": key,
                        "created_at": datetime(2026, 7, 30, 9, 0).isoformat(),
                        "updated_at": datetime(2026, 7, 30, 10, 0).isoformat(),
                        "metadata": {},
                        "last_consolidated": 0,
                    }
                ),
                json.dumps(
                    {
                        "_type": "provider_state",
                        "state": {"kind": "openai_responses"},
                    }
                ),
                json.dumps({"role": "user", "content": "safe"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    manager = SessionManager(tmp_path)
    migrated = manager.get_or_create(key)

    assert migrated.provider_state is None
    assert migrated.messages == [{"role": "user", "content": "safe"}]
    assert manager.read_session_file(key)["messages"] == migrated.messages


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

    def fail_reload(_self, _key) -> None:
        raise AssertionError("JSONL backups should not be re-imported after migration")

    monkeypatch.setattr(JsonlSessionFiles, "load_for_migration", fail_reload)
    reloaded = SessionManager(tmp_path)
    assert [message["content"] for message in reloaded.get_or_create(stored.key).messages] == [
        "from jsonl",
        "only in sqlite",
    ]


@pytest.mark.parametrize("change_kind", ["modified", "new"])
def test_jsonl_backup_changes_after_migration_fail_closed(
    tmp_path,
    change_kind,
) -> None:
    source = JsonlSessionFiles(tmp_path)
    stored = _session(
        "cli:rollback-source",
        updated_at=datetime(2026, 7, 30, 10, 0),
        messages=[{"role": "user", "content": "before rollback"}],
        title="Before rollback",
    )
    _write_jsonl(source, stored)
    SessionManager(tmp_path)

    if change_kind == "modified":
        rollback = _session(
            stored.key,
            updated_at=datetime(2026, 7, 30, 11, 0),
            messages=[
                *stored.messages,
                {"role": "assistant", "content": "written during rollback"},
            ],
            title="During rollback",
        )
    else:
        rollback = _session(
            "cli:created-during-rollback",
            updated_at=datetime(2026, 7, 30, 11, 0),
            messages=[{"role": "user", "content": "new during rollback"}],
            title="Created during rollback",
        )
    _write_jsonl(source, rollback)

    with pytest.raises(RuntimeError, match="changed after SQLite migration"):
        SessionManager(tmp_path)

    assert SQLiteSessionStore(tmp_path).load(stored.key) == stored
    assert source.get_session_path(rollback.key).is_file()


def test_jsonl_backup_deletion_after_migration_fails_closed(tmp_path) -> None:
    source = JsonlSessionFiles(tmp_path)
    stored = _session(
        "cli:deleted-during-rollback",
        updated_at=datetime(2026, 7, 30, 10, 0),
        messages=[{"role": "user", "content": "do not resurrect"}],
        title="Deleted during rollback",
    )
    _write_jsonl(source, stored)
    SessionManager(tmp_path)
    source.get_session_path(stored.key).unlink()

    with pytest.raises(RuntimeError, match="changed after SQLite migration"):
        SessionManager(tmp_path)

    assert SQLiteSessionStore(tmp_path).load(stored.key) == stored


def test_jsonl_backup_content_hash_detects_same_stat_rewrite(tmp_path) -> None:
    source = JsonlSessionFiles(tmp_path)
    stored = _session(
        "cli:same-stat-rewrite",
        updated_at=datetime(2026, 7, 30, 10, 0),
        messages=[{"role": "user", "content": "before"}],
        title="Same stat",
    )
    _write_jsonl(source, stored)
    SessionManager(tmp_path)
    path = source.get_session_path(stored.key)
    original_stat = path.stat()
    rewritten = path.read_text(encoding="utf-8").replace("before", "during")
    path.write_text(rewritten, encoding="utf-8")
    assert path.stat().st_size == original_stat.st_size
    os.utime(
        path,
        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
    )

    with pytest.raises(RuntimeError, match="changed after SQLite migration"):
        SessionManager(tmp_path)

    assert SQLiteSessionStore(tmp_path).load(stored.key) == stored


def test_jsonl_backup_touch_with_same_content_does_not_block_startup(tmp_path) -> None:
    source = JsonlSessionFiles(tmp_path)
    stored = _session(
        "cli:touched-backup",
        updated_at=datetime(2026, 7, 30, 10, 0),
        messages=[{"role": "user", "content": "unchanged"}],
        title="Touched",
    )
    _write_jsonl(source, stored)
    SessionManager(tmp_path)
    source.get_session_path(stored.key).touch()

    assert SessionManager(tmp_path).get_or_create(stored.key) == stored


def test_legacy_count_marker_is_upgraded_without_reimporting_jsonl(tmp_path) -> None:
    source = JsonlSessionFiles(tmp_path)
    stored = _session(
        "cli:legacy-marker",
        updated_at=datetime(2026, 7, 30, 10, 0),
        messages=[{"role": "user", "content": "already imported"}],
        title="Legacy marker",
    )
    _write_jsonl(source, stored)
    _create_v1_database(tmp_path, stored, migration_marker="1")

    manager = SessionManager(tmp_path)

    assert manager.get_or_create(stored.key) == stored
    with sqlite3.connect(tmp_path / "sessions.db") as connection:
        marker = connection.execute(
            "SELECT value FROM store_metadata WHERE key = 'jsonl_import_v1'"
        ).fetchone()
        version = connection.execute("PRAGMA user_version").fetchone()
        private_metadata = connection.execute(
            "SELECT private_metadata FROM sessions WHERE key = ?",
            (stored.key,),
        ).fetchone()
    assert marker is not None
    assert json.loads(marker[0])["version"] == 1
    assert version == (2,)
    assert private_metadata == ("{}",)


def test_legacy_count_marker_rejects_newer_jsonl_backup(tmp_path) -> None:
    stored = _session(
        "cli:legacy-marker-rollback",
        updated_at=datetime(2026, 7, 30, 10, 0),
        messages=[{"role": "user", "content": "already imported"}],
        title="Legacy marker",
    )
    rollback = _session(
        stored.key,
        updated_at=stored.updated_at,
        messages=[
            *stored.messages,
            {"role": "assistant", "content": "written during rollback"},
        ],
        title="Legacy marker",
    )
    _write_jsonl(JsonlSessionFiles(tmp_path), rollback)
    _create_v1_database(tmp_path, stored, migration_marker="1")

    with pytest.raises(RuntimeError, match="may have changed after SQLite migration"):
        SessionManager(tmp_path)

    assert SQLiteSessionStore(tmp_path).load(stored.key) == stored


def test_legacy_count_marker_rejects_truncated_jsonl_backup(tmp_path) -> None:
    stored = _session(
        "cli:legacy-marker-truncated",
        updated_at=datetime(2026, 7, 30, 10, 0),
        messages=[
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "second"},
        ],
        title="Legacy marker",
    )
    truncated = _session(
        stored.key,
        updated_at=stored.updated_at,
        messages=stored.messages[:1],
        title="Legacy marker",
    )
    truncated.last_consolidated = stored.last_consolidated
    _write_jsonl(JsonlSessionFiles(tmp_path), truncated)
    _create_v1_database(tmp_path, stored, migration_marker="1")

    with pytest.raises(RuntimeError, match="may have changed after SQLite migration"):
        SessionManager(tmp_path)

    assert SQLiteSessionStore(tmp_path).load(stored.key) == stored


def test_legacy_count_marker_rejects_missing_jsonl_backup(tmp_path) -> None:
    keep = _session(
        "cli:legacy-marker-keep",
        updated_at=datetime(2026, 7, 30, 10, 0),
        messages=[{"role": "user", "content": "keep"}],
        title="Keep",
    )
    deleted = _session(
        "cli:legacy-marker-deleted",
        updated_at=datetime(2026, 7, 30, 10, 0),
        messages=[{"role": "user", "content": "deleted during rollback"}],
        title="Deleted",
    )
    _write_jsonl(JsonlSessionFiles(tmp_path), keep)
    _create_v1_database(tmp_path, keep, migration_marker="2")
    with sqlite3.connect(tmp_path / "sessions.db") as connection:
        connection.execute(
            """
            INSERT INTO sessions (
                key, created_at, updated_at, metadata, last_consolidated
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                deleted.key,
                deleted.created_at.isoformat(),
                deleted.updated_at.isoformat(),
                json.dumps(deleted.metadata),
                deleted.last_consolidated,
            ),
        )
        connection.executemany(
            "INSERT INTO messages (session_key, position, payload) VALUES (?, ?, ?)",
            [
                (deleted.key, position, json.dumps(message))
                for position, message in enumerate(deleted.messages)
            ],
        )

    with pytest.raises(RuntimeError, match="may have changed after SQLite migration"):
        SessionManager(tmp_path)

    assert SQLiteSessionStore(tmp_path).load(deleted.key) == deleted


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


def test_jsonl_parsing_happens_outside_sqlite_write_lock(tmp_path, monkeypatch) -> None:
    source = JsonlSessionFiles(tmp_path)
    stored = _session(
        "cli:lock-free-prepare",
        updated_at=datetime(2026, 7, 30, 10, 0),
        messages=[{"role": "user", "content": "prepare outside lock"}],
        title="Lock free prepare",
    )
    _write_jsonl(source, stored)
    store = SQLiteSessionStore(tmp_path)
    load_started = Event()
    release_load = Event()
    load_for_migration = source.load_for_migration

    def delayed_load(key):
        load_started.set()
        assert release_load.wait(timeout=5)
        return load_for_migration(key)

    monkeypatch.setattr(source, "load_for_migration", delayed_load)

    with ThreadPoolExecutor(max_workers=1) as executor:
        migration = executor.submit(store.migrate_from_jsonl, source)
        assert load_started.wait(timeout=5)
        try:
            with sqlite3.connect(store.db_path, timeout=0.2) as connection:
                connection.execute("PRAGMA busy_timeout = 200")
                connection.execute("BEGIN IMMEDIATE")
                connection.rollback()
        finally:
            release_load.set()
        assert migration.result(timeout=5) == 1


def test_jsonl_hashing_happens_outside_sqlite_write_lock(tmp_path, monkeypatch) -> None:
    source = JsonlSessionFiles(tmp_path)
    stored = _session(
        "cli:lock-free-hash",
        updated_at=datetime(2026, 7, 30, 10, 0),
        messages=[{"role": "user", "content": "hash outside lock"}],
        title="Lock free hash",
    )
    _write_jsonl(source, stored)
    store = SQLiteSessionStore(tmp_path)
    hash_started = Event()
    release_hash = Event()
    current_signatures = store._current_jsonl_signatures

    def delayed_hash(_cls, jsonl_source):
        hash_started.set()
        assert release_hash.wait(timeout=5)
        return current_signatures(jsonl_source)

    monkeypatch.setattr(
        SQLiteSessionStore,
        "_current_jsonl_signatures",
        classmethod(delayed_hash),
    )

    with ThreadPoolExecutor(max_workers=1) as executor:
        migration = executor.submit(store.migrate_from_jsonl, source)
        assert hash_started.wait(timeout=5)
        try:
            with sqlite3.connect(store.db_path, timeout=0.2) as connection:
                connection.execute("PRAGMA busy_timeout = 200")
                connection.execute("BEGIN IMMEDIATE")
                connection.rollback()
        finally:
            release_hash.set()
        assert migration.result(timeout=5) == 1


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
    original.provider_state = _provider_state("original-state")
    replacement.provider_state = _provider_state("replacement-state")
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
    failed.provider_state = _provider_state("failed-state")
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


def test_sqlite_store_rejects_non_object_message_without_overwrite(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path)
    original = _session(
        "cli:invalid-dynamic-message",
        updated_at=datetime(2026, 7, 30, 10, 0),
        messages=[{"role": "user", "content": "preserve me"}],
        title="Original",
    )
    store.save(original)
    invalid = _session(
        original.key,
        updated_at=datetime(2026, 7, 30, 11, 0),
        messages=[{"role": "user", "content": "replacement"}],
        title="Invalid",
    )
    invalid.messages.append(
        cast(dict[str, object], cast(object, ["not", "an", "object"]))
    )

    with pytest.raises(ValueError, match="session records must be JSON objects"):
        store.save(invalid)

    assert store.load(original.key) == original


def test_sqlite_store_corruption_fails_closed_without_replacing_session(tmp_path) -> None:
    stored = _session(
        "cli:corrupt-message",
        updated_at=datetime(2026, 7, 30, 10, 0),
        messages=[{"role": "user", "content": "preserve me"}],
        title="Corrupt",
    )
    store = SQLiteSessionStore(tmp_path)
    store.save(stored)
    with sqlite3.connect(store.db_path) as connection:
        connection.execute(
            "UPDATE messages SET payload = '[]' WHERE session_key = ?",
            (stored.key,),
        )

    manager = SessionManager(tmp_path)
    with pytest.raises(RuntimeError, match="Failed to load SQLite session"):
        manager.get_or_create(stored.key)

    assert manager.get_cached(stored.key) is None
    with sqlite3.connect(store.db_path) as connection:
        session_count = connection.execute(
            "SELECT COUNT(*) FROM sessions WHERE key = ?",
            (stored.key,),
        ).fetchone()
        payload = connection.execute(
            "SELECT payload FROM messages WHERE session_key = ?",
            (stored.key,),
        ).fetchone()
    assert session_count == (1,)
    assert payload == ("[]",)


def test_sqlite_store_metadata_corruption_fails_closed_for_all_reads(tmp_path) -> None:
    stored = _session(
        "cli:corrupt-metadata",
        updated_at=datetime(2026, 7, 30, 10, 0),
        messages=[{"role": "user", "content": "preserve me"}],
        title="Corrupt metadata",
    )
    store = SQLiteSessionStore(tmp_path)
    store.save(stored)
    with sqlite3.connect(store.db_path) as connection:
        connection.execute(
            "UPDATE sessions SET metadata = '[]' WHERE key = ?",
            (stored.key,),
        )
    manager = SessionManager(tmp_path)

    with pytest.raises(RuntimeError, match="Failed to load SQLite session"):
        manager.get_or_create(stored.key)
    with pytest.raises(RuntimeError, match="Failed to read SQLite session metadata"):
        manager.read_session_metadata(stored.key)
    with pytest.raises(RuntimeError, match="Failed to list SQLite sessions"):
        manager.list_sessions()

    with sqlite3.connect(store.db_path) as connection:
        metadata = connection.execute(
            "SELECT metadata FROM sessions WHERE key = ?",
            (stored.key,),
        ).fetchone()
    assert metadata == ("[]",)


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


def test_manager_keeps_sqlite_session_when_backup_delete_fails(
    tmp_path,
    monkeypatch,
) -> None:
    source = JsonlSessionFiles(tmp_path)
    stored = _session(
        "cli:locked-backup",
        updated_at=datetime(2026, 7, 30, 10, 0),
        messages=[{"role": "user", "content": "do not resurrect"}],
        title="Locked backup",
    )
    _write_jsonl(source, stored)
    manager = SessionManager(tmp_path)
    backup = source.get_session_path(stored.key)
    unlink = Path.unlink

    def fail_locked_backup(path, *args, **kwargs):
        if path == backup:
            raise PermissionError("backup is locked")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_locked_backup)

    with pytest.raises(PermissionError, match="backup is locked"):
        manager.delete_session(stored.key)

    assert backup.is_file()
    assert SQLiteSessionStore(tmp_path).load(stored.key) == stored


def test_manager_delete_updates_migration_manifest_before_key_reuse(tmp_path) -> None:
    source = JsonlSessionFiles(tmp_path)
    stored = _session(
        "cli:delete-and-reuse",
        updated_at=datetime(2026, 7, 30, 10, 0),
        messages=[{"role": "user", "content": "old history"}],
        title="Old history",
    )
    _write_jsonl(source, stored)
    manager = SessionManager(tmp_path)

    assert manager.delete_session(stored.key) is True
    reloaded = SessionManager(tmp_path)
    assert reloaded.read_session_file(stored.key) is None

    replacement = _session(
        stored.key,
        updated_at=datetime(2026, 7, 30, 11, 0),
        messages=[{"role": "user", "content": "new history"}],
        title="New history",
    )
    reloaded.save(replacement)

    assert SessionManager(tmp_path).get_or_create(stored.key) == replacement


def test_concurrent_deletes_do_not_restore_manifest_entries(tmp_path) -> None:
    source = JsonlSessionFiles(tmp_path)
    sessions = [
        _session(
            f"cli:concurrent-delete-{index}",
            updated_at=datetime(2026, 7, 30, 10, index),
            messages=[{"role": "user", "content": str(index)}],
            title=f"Delete {index}",
        )
        for index in range(2)
    ]
    for session in sessions:
        _write_jsonl(source, session)
    manager = SessionManager(tmp_path)

    with ThreadPoolExecutor(max_workers=2) as executor:
        deleted = list(executor.map(manager.delete_session, [s.key for s in sessions]))

    assert deleted == [True, True]
    with sqlite3.connect(tmp_path / "sessions.db") as connection:
        marker = connection.execute(
            "SELECT value FROM store_metadata WHERE key = 'jsonl_import_v1'"
        ).fetchone()
    assert marker is not None
    assert json.loads(marker[0])["files"] == {}

    manager.save(sessions[1])
    assert SessionManager(tmp_path).get_or_create(sessions[1].key) == sessions[1]


def test_sqlite_store_migrates_v1_schema_in_place(tmp_path) -> None:
    stored = _session(
        "cli:schema-v1",
        updated_at=datetime(2026, 7, 30, 10, 0),
        messages=[{"role": "user", "content": "keep v1 data"}],
        title="Schema v1",
    )
    _create_v1_database(tmp_path, stored)

    store = SQLiteSessionStore(tmp_path)

    assert store.load(stored.key) == stored
    with sqlite3.connect(store.db_path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(sessions)").fetchall()
        }
    assert version == (2,)
    assert "private_metadata" in columns


def test_sqlite_store_rejects_unknown_schema_version(tmp_path) -> None:
    db_path = tmp_path / "sessions.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA user_version = 3")

    with pytest.raises(RuntimeError, match="Unsupported SQLite session schema version 3"):
        SQLiteSessionStore(tmp_path)


def test_sqlite_store_initializes_concurrently(tmp_path) -> None:
    with ThreadPoolExecutor(max_workers=8) as executor:
        stores = list(executor.map(lambda _: SQLiteSessionStore(tmp_path), range(8)))

    assert {store.db_path for store in stores} == {tmp_path / "sessions.db"}
    with sqlite3.connect(stores[0].db_path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()
    assert version == (2,)
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
    original.provider_state = _provider_state("before-state")
    replacement.provider_state = _provider_state("after-state")
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
