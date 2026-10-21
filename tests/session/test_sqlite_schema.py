"""Session schema upgrades preserve records and fail atomically."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

import nanobot.session.sqlite_store as sqlite_store
from nanobot.providers.base import ProviderConversationState
from nanobot.session.manager import Session
from nanobot.session.sqlite_store import SqliteSessionStore


def _session() -> Session:
    return Session(
        key="chat:extensions",
        messages=[{"role": "user", "content": "hello", "extension": {"source": "import"}}],
        metadata={
            "title": "Extended session",
            "extension": {"enabled": True},
            "runtime_checkpoint": {
                "phase": "final_response", "iteration": 1, "model": "gpt-test",
                "assistant_message": {"role": "assistant", "content": "checkpoint answer"},
                "completed_tool_results": [], "pending_tool_calls": [], "extension": {"step": 2},
            },
            "pending_user_followups": [{
                "id": "followup", "sender_id": "user", "chat_id": "extensions", "content": "next",
                "media": [], "metadata": {}, "extension": True,
            }],
        },
        provider_state=ProviderConversationState(
            kind="openai_responses", provider="openai", model="gpt-test", version=1,
            payload={"items": [], "extension": {"cursor": "opaque"}},
            pending_messages=[{"role": "assistant", "content": "pending", "extension": True}],
        ),
    )


def _write_legacy(workspace: Path, session: Session) -> Path:
    directory = workspace / "sessions"
    directory.mkdir(parents=True)
    path = directory / "session.jsonl"
    assert session.provider_state is not None
    records = [
        {"_type": "metadata", "key": session.key, "metadata": session.metadata,
         "created_at": session.created_at.isoformat(), "updated_at": session.updated_at.isoformat(),
         "last_archived": session.last_archived},
        {"_type": "provider_state", "state": session.provider_state.to_private_record()},
        *session.messages,
    ]
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
    return path


def _database_snapshot(path: Path) -> tuple[int, str, str]:
    with closing(sqlite3.connect(path)) as db:
        return (
            db.execute("PRAGMA user_version").fetchone()[0],
            db.execute("PRAGMA journal_mode").fetchone()[0],
            "\n".join(db.iterdump()),
        )


def test_ordered_upgrades_preserve_records_and_do_not_repeat_import(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    original = _session()
    source = _write_legacy(workspace, original)
    store = SqliteSessionStore(tmp_path)
    with closing(sqlite3.connect(store.path)) as db:
        schema = Path(__file__).with_name("fixtures") / "sqlite_v1.sql"
        db.executescript(schema.read_text(encoding="utf-8"))
    store.save(original)
    assert _database_snapshot(store.path)[0] == 1

    def add_archived(db: sqlite3.Connection) -> None:
        db.execute("ALTER TABLE sessions ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")

    def index_archived(db: sqlite3.Connection) -> None:
        db.execute("CREATE INDEX sessions_archived ON sessions(archived)")

    monkeypatch.setattr(sqlite_store, "_SCHEMA_MIGRATIONS", (
        *sqlite_store._SCHEMA_MIGRATIONS, add_archived, index_archived,
    ))
    source.write_text("stale malformed source must not be imported again", encoding="utf-8")
    upgraded = SqliteSessionStore(tmp_path)
    upgraded.initialize(workspace)
    assert _database_snapshot(store.path)[0] == 3
    loaded = upgraded.load(original.key)
    assert loaded is not None
    assert loaded.messages == original.messages
    assert loaded.metadata == original.metadata
    assert loaded.provider_state == original.provider_state
    upgraded.save(loaded)

    reopened = SqliteSessionStore(tmp_path)
    reopened.initialize(workspace)
    roundtrip = reopened.load(original.key)
    assert roundtrip is not None
    assert roundtrip.messages == original.messages
    assert roundtrip.metadata == original.metadata
    assert roundtrip.provider_state == original.provider_state
    with closing(sqlite3.connect(store.path)) as db:
        assert db.execute("SELECT archived FROM sessions").fetchall() == [(0,)]
        assert db.execute("SELECT name FROM sqlite_master WHERE name='sessions_archived'").fetchone()
        assert db.execute("SELECT value FROM storage_meta WHERE key='jsonl_import'").fetchone() == ("complete",)


def test_failed_upgrade_rolls_back_schema_version_and_records_then_can_retry(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    store = SqliteSessionStore(tmp_path)
    store.initialize(workspace)
    original = _session()
    store.save(original)
    before = _database_snapshot(store.path)
    migrations = sqlite_store._SCHEMA_MIGRATIONS

    def add_archived(db: sqlite3.Connection) -> None:
        db.execute("ALTER TABLE sessions ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")

    def fail_upgrade(db: sqlite3.Connection) -> None:
        db.execute("UPDATE sessions SET title='partial migration'")
        db.execute("CREATE TABLE migration_partial (value TEXT)")
        raise RuntimeError("migration interrupted")

    monkeypatch.setattr(sqlite_store, "_SCHEMA_MIGRATIONS", (
        *migrations, add_archived, fail_upgrade,
    ))
    with pytest.raises(RuntimeError, match="migration interrupted"):
        store.initialize(workspace)
    assert _database_snapshot(store.path) == before

    def complete_upgrade(db: sqlite3.Connection) -> None:
        db.execute("CREATE INDEX sessions_archived ON sessions(archived)")

    monkeypatch.setattr(sqlite_store, "_SCHEMA_MIGRATIONS", (
        *migrations, add_archived, complete_upgrade,
    ))
    store.initialize(workspace)
    assert _database_snapshot(store.path)[0] == 3
    loaded = store.load(original.key)
    assert loaded is not None
    assert loaded.messages == original.messages
    assert loaded.metadata == original.metadata
    assert loaded.provider_state == original.provider_state


def test_added_columns_allow_import_and_all_session_write_paths(tmp_path, monkeypatch):
    def add_optional_columns(db: sqlite3.Connection) -> None:
        for table in ("storage_meta", "sessions", "messages", "checkpoints", "pending_inputs"):
            db.execute(f"ALTER TABLE {table} ADD COLUMN extension TEXT")
            db.execute(f"ALTER TABLE {table} ADD COLUMN format_version INTEGER NOT NULL DEFAULT 1")

    monkeypatch.setattr(sqlite_store, "_SCHEMA_MIGRATIONS", (
        *sqlite_store._SCHEMA_MIGRATIONS, add_optional_columns,
    ))
    workspace = tmp_path / "workspace"
    imported = _session()
    _write_legacy(workspace, imported)
    store = SqliteSessionStore(tmp_path)
    store.initialize(workspace)
    loaded = store.load(imported.key)
    assert loaded is not None
    assert loaded.messages == imported.messages
    assert loaded.metadata == imported.metadata
    assert loaded.provider_state == imported.provider_state

    created = _session()
    created.key = "chat:new"
    store.save(created)
    created.add_message("assistant", "answer", extension={"keep": True})
    store.save(created, message_start=1)
    assert store.update_metadata(created.key, {"title": "Changed title"})
    current = store.load(created.key)
    assert current is not None
    current.metadata["runtime_checkpoint"]["extension"] = {"step": 3}
    store.save_runtime_checkpoint(current)
    store.replace_metadata(current.key, current.metadata)
    roundtrip = store.load(current.key)
    assert roundtrip is not None
    assert roundtrip.messages == created.messages
    assert roundtrip.metadata == current.metadata
    assert roundtrip.provider_state == current.provider_state
    with closing(sqlite3.connect(store.path)) as db:
        for table in ("storage_meta", "sessions", "messages", "checkpoints", "pending_inputs"):
            rows = db.execute(f"SELECT extension, format_version FROM {table}").fetchall()
            assert rows and all(row == (None, 1) for row in rows)


def test_future_schema_is_rejected_without_modifying_database(tmp_path):
    workspace = tmp_path / "workspace"
    store = SqliteSessionStore(tmp_path)
    store.initialize(workspace)
    store.save(_session())
    future_version = len(sqlite_store._SCHEMA_MIGRATIONS) + 1
    with closing(sqlite3.connect(store.path)) as db:
        db.execute("PRAGMA journal_mode = DELETE")
        db.execute(f"PRAGMA user_version = {future_version}")
    before = _database_snapshot(store.path)
    before_bytes = store.path.read_bytes()
    before_files = {path.name for path in tmp_path.iterdir()}

    with pytest.raises(RuntimeError, match=f"unsupported session database schema: {future_version}"):
        store.initialize(workspace)
    assert _database_snapshot(store.path) == before
    assert store.path.read_bytes() == before_bytes
    assert {path.name for path in tmp_path.iterdir()} == before_files


def test_missing_sqlite_json_support_is_rejected_before_database_changes(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    store = SqliteSessionStore(tmp_path)
    store.initialize(workspace)
    store.save(_session())
    with closing(sqlite3.connect(store.path)) as db:
        db.execute("PRAGMA journal_mode = DELETE")
    before = _database_snapshot(store.path)
    before_bytes = store.path.read_bytes()
    native_connect = sqlite3.connect

    class WithoutJson(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if "json_extract(" in sql:
                raise sqlite3.OperationalError("no such function: json_extract")
            return super().execute(sql, parameters)

    def connect(*args, **kwargs):
        return native_connect(*args, factory=WithoutJson, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", connect)
        with pytest.raises(RuntimeError, match="requires SQLite JSON support"):
            store.initialize(workspace)
    assert _database_snapshot(store.path) == before
    assert store.path.read_bytes() == before_bytes
