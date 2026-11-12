import json
import sqlite3
from datetime import datetime

import nanobot.session.sqlite_store as sqlite_store
from nanobot.session.manager import Session, SessionManager
from nanobot.session.types import PARENT_SESSION_KEY, SESSION_TYPE_KEY


def test_subagent_metadata_matches_only_requested_turns(tmp_path, monkeypatch):
    manager = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "storage")
    parent = "chat:项目'\"\\root"
    turn_id = "turn-雪'\"\\"

    def save(key, task, *, owner=parent, kind="subagent", second=0):
        manager.save(Session(
            key=key, updated_at=datetime(2026, 1, 1, 0, 0, second),
            messages=[{"role": "user", "content": "private transcript"}],
            metadata={
                PARENT_SESSION_KEY: owner, SESSION_TYPE_KEY: kind, "subagent_task": task,
                "runtime_checkpoint": {"step": 1}, "pending_user_followups": [{"id": "queued"}],
            },
        ))

    save("subagent:turn", {"origin_turn_id": turn_id, "state": "running"}, second=1)
    save("subagent:unmatched", {"origin_turn_id": "unmatched"}, second=2)
    save("subagent:other-parent", {"origin_turn_id": turn_id}, owner="chat:other", second=3)
    save("extension:child", {"origin_turn_id": turn_id}, kind="extension", second=4)
    save("subagent:grandchild", {"origin_turn_id": turn_id}, owner="subagent:turn", second=5)
    save("subagent:blank", {"origin_turn_id": ""}, second=6)
    save("subagent:no-origin", {"state": "running"}, second=7)
    # Message-only attribution is not a turn and must not match the turn read.
    save("subagent:message-only", {"origin_message_id": turn_id}, second=8)

    def prohibit_listing(*_args, **_kwargs):
        raise AssertionError("filtered metadata must not load all child or session headers")

    monkeypatch.setattr(manager._store, "list_metadata", prohibit_listing)
    monkeypatch.setattr(manager._store, "list_child_session_metadata", prohibit_listing)
    decode = sqlite_store._object
    decoded = []

    def track_decode(raw):
        metadata = decode(raw)
        decoded.append(metadata)
        return metadata

    monkeypatch.setattr(sqlite_store, "_object", track_decode)
    rows = manager.list_subagent_session_metadata(parent, turn_ids=[turn_id, turn_id])
    assert {row["key"] for row in rows} == {"subagent:turn"}
    assert len(decoded) == len(rows)
    only = rows[0]
    assert only["updated_at"] == "2026-01-01T00:00:01"
    assert only["metadata"]["subagent_task"]["state"] == "running"
    assert "runtime_checkpoint" not in only["metadata"]
    assert "pending_user_followups" not in only["metadata"]
    only["metadata"]["subagent_task"]["state"] = "changed"
    assert manager.list_subagent_session_metadata(parent, turn_ids=[turn_id])[0]["metadata"][
        "subagent_task"
    ]["state"] == "running"

    assert manager.list_subagent_session_metadata(parent, turn_ids=[]) == []
    assert manager.list_subagent_session_metadata(parent, turn_ids=[""]) == []
    assert manager.list_subagent_session_metadata(
        "chat:missing' OR 1=1 --", turn_ids=[turn_id],
    ) == []


def test_subagent_origin_index_follows_metadata_updates(tmp_path):
    manager = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "storage")
    key, parent, other = "subagent:task", "chat:parent", "chat:other"
    manager.save(Session(key=key, metadata={
        SESSION_TYPE_KEY: "subagent", PARENT_SESSION_KEY: parent,
        "subagent_task": {"origin_turn_id": "turn"},
    }))

    def keys(owner):
        return [row["key"] for row in manager.list_subagent_session_metadata(
            owner, turn_ids=["turn"],
        )]

    assert keys(parent) == [key]
    assert manager.update_session_metadata(key, {"subagent_task": {"state": "running"}})
    assert keys(parent) == []
    assert manager.update_session_metadata(key, {
        "subagent_task": {"origin_turn_id": "turn"}, PARENT_SESSION_KEY: other,
    })
    assert keys(parent) == []
    assert keys(other) == [key]


def test_subagent_origin_index_upgrades_and_supports_large_batches(tmp_path, monkeypatch):
    workspace, root = tmp_path / "workspace", tmp_path / "storage"
    parent = "chat:upgrade"
    turn_ids = [f"turn-{i}" for i in range(4000)]
    with monkeypatch.context() as patch:
        patch.setattr(sqlite_store, "_SCHEMA_MIGRATIONS", sqlite_store._SCHEMA_MIGRATIONS[:5])
        manager = SessionManager(workspace, sessions_root=root)

        def seed():
            for key, owner, task in (
                ("subagent:turn", parent, {"origin_turn_id": turn_ids[-1]}),
                ("subagent:no-origin", parent, {"state": "done"}),
                *(
                    (f"subagent:unrelated-{i}", parent, {"origin_turn_id": f"not-in-page-{i}"})
                    for i in range(150)
                ),
            ):
                manager.save(Session(key=key, metadata={
                    SESSION_TYPE_KEY: "subagent", PARENT_SESSION_KEY: owner, "subagent_task": task,
                }))

        manager._store.run_write(seed)
        with manager._store.transaction(write=False) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 5

    upgraded = SessionManager(workspace, sessions_root=root)
    # Reopening upgrades only once and retains already persisted metadata.
    upgraded = SessionManager(workspace, sessions_root=root)
    with upgraded._store.transaction(write=False) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == len(sqlite_store._SCHEMA_MIGRATIONS)
        plan = [row[3] for row in db.execute(
            "EXPLAIN QUERY PLAN " + sqlite_store._SUBAGENT_METADATA_QUERY,
            (parent, json.dumps(turn_ids)),
        )]
        assert any(
            "SEARCH sessions USING INDEX sessions_subagent_origin_turn_id" in detail
            and "<expr>=? AND <expr>=?" in detail
            for detail in plan
        ), plan
        # The API must not consume one SQLite variable per requested ID.
        db.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 10)
        rows = upgraded.list_subagent_session_metadata(parent, turn_ids=turn_ids)

    assert {row["key"] for row in rows} == {"subagent:turn"}
    assert rows[0]["metadata"]["subagent_task"] == {"origin_turn_id": turn_ids[-1]}
