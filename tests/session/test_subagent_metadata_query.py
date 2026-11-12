import json
import sqlite3
from datetime import datetime

import nanobot.session.sqlite_store as sqlite_store
from nanobot.session.manager import Session, SessionManager
from nanobot.session.types import PARENT_SESSION_KEY, SESSION_TYPE_KEY


def test_subagent_metadata_matches_only_attributed_children(tmp_path, monkeypatch):
    manager = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "storage")
    parent = "chat:项目'\"\\root"
    input_id = "input-雪' OR 1=1 --"
    message_id = "message-雪'\"\\"
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

    save("subagent:input", {"origin_input_id": input_id, "state": "running"}, second=1)
    save("subagent:message", {"origin_message_id": message_id, "origin_turn_id": "other"}, second=2)
    save("subagent:turn", {"origin_message_id": "replayed", "origin_turn_id": turn_id}, second=3)
    save("subagent:both", {"origin_message_id": message_id, "origin_turn_id": turn_id}, second=4)
    save("subagent:wrong-input", {
        "origin_input_id": "other", "origin_message_id": message_id, "origin_turn_id": turn_id,
    }, second=5)
    save("subagent:null-input", {
        "origin_input_id": None, "origin_message_id": message_id, "origin_turn_id": turn_id,
    }, second=6)
    save("subagent:empty-input", {
        "origin_input_id": "", "origin_message_id": message_id, "origin_turn_id": turn_id,
    }, second=7)
    save("subagent:space-input", {
        "origin_input_id": " ", "origin_message_id": message_id, "origin_turn_id": turn_id,
    }, second=8)
    save("subagent:unmatched", {"origin_message_id": "unmatched"}, second=9)
    save("subagent:other-parent", {"origin_input_id": input_id}, owner="chat:other", second=10)
    save("extension:child", {"origin_input_id": input_id}, kind="extension", second=11)
    save("subagent:grandchild", {"origin_input_id": input_id}, owner="subagent:input", second=12)
    save("subagent:legacy-empty", {"origin_message_id": "", "origin_turn_id": ""}, second=13)

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
    rows = manager.list_subagent_session_metadata(
        parent, input_ids=[input_id, input_id, ""], message_ids=[message_id], turn_ids=[turn_id],
    )
    assert [row["key"] for row in rows] == [
        "subagent:both", "subagent:turn", "subagent:message", "subagent:input",
    ]
    assert len(decoded) == len(rows)
    assert rows[-1]["updated_at"] == "2026-01-01T00:00:01"
    assert rows[-1]["metadata"]["subagent_task"]["state"] == "running"
    assert all("runtime_checkpoint" not in row["metadata"] for row in rows)
    assert all("pending_user_followups" not in row["metadata"] for row in rows)
    rows[-1]["metadata"]["subagent_task"]["state"] = "changed"
    assert manager.list_subagent_session_metadata(
        parent, input_ids=(input_id,), message_ids=(), turn_ids=(),
    )[0]["metadata"]["subagent_task"]["state"] == "running"

    assert {row["key"] for row in manager.list_subagent_session_metadata(
        parent, input_ids=[], message_ids=[message_id], turn_ids=[],
    )} == {"subagent:message", "subagent:both"}
    assert {row["key"] for row in manager.list_subagent_session_metadata(
        parent, input_ids=[], message_ids=[], turn_ids=[turn_id],
    )} == {"subagent:turn", "subagent:both"}
    assert [row["key"] for row in manager.list_subagent_session_metadata(
        parent, input_ids=[" "], message_ids=[], turn_ids=[],
    )] == ["subagent:space-input"]
    assert manager.list_subagent_session_metadata(
        parent, input_ids=[], message_ids=[], turn_ids=[],
    ) == []
    assert manager.list_subagent_session_metadata(
        parent, input_ids=[""], message_ids=[""], turn_ids=[""],
    ) == []
    assert manager.list_subagent_session_metadata(
        "chat:missing' OR 1=1 --", input_ids=[input_id], message_ids=[message_id], turn_ids=[turn_id],
    ) == []


def test_subagent_origin_indexes_follow_metadata_updates(tmp_path):
    manager = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "storage")
    key, parent, other = "subagent:task", "chat:parent", "chat:other"
    manager.save(Session(key=key, metadata={
        SESSION_TYPE_KEY: "subagent", PARENT_SESSION_KEY: parent,
        "subagent_task": {"origin_message_id": "message", "origin_turn_id": "turn"},
    }))

    def keys(owner):
        return [row["key"] for row in manager.list_subagent_session_metadata(
            owner, input_ids=["input"], message_ids=["message"], turn_ids=["turn"],
        )]

    assert keys(parent) == [key]
    assert manager.update_session_metadata(key, {"subagent_task": {
        "origin_input_id": None, "origin_message_id": "message", "origin_turn_id": "turn",
    }})
    assert keys(parent) == []
    assert manager.update_session_metadata(key, {"subagent_task": {
        "origin_input_id": "input", "origin_message_id": "message", "origin_turn_id": "turn",
    }, PARENT_SESSION_KEY: other})
    assert keys(parent) == []
    assert keys(other) == [key]
    assert manager.update_session_metadata(key, {"subagent_task": {"origin_turn_id": "turn"}})
    assert keys(other) == [key]


def test_subagent_origin_indexes_upgrade_and_support_large_batches(tmp_path, monkeypatch):
    workspace, root = tmp_path / "workspace", tmp_path / "storage"
    parent = "chat:upgrade"
    input_ids = [f"input-{i}" for i in range(4000)]
    message_ids = [f"message-{i}" for i in range(4000)]
    turn_ids = [f"turn-{i}" for i in range(4000)]
    with monkeypatch.context() as patch:
        patch.setattr(sqlite_store, "_SCHEMA_MIGRATIONS", sqlite_store._SCHEMA_MIGRATIONS[:5])
        manager = SessionManager(workspace, sessions_root=root)

        def seed():
            for key, owner, task in (
                ("subagent:new", parent, {"origin_input_id": input_ids[-1]}),
                ("subagent:legacy-message", parent, {"origin_message_id": message_ids[-1]}),
                ("subagent:legacy-turn", parent, {"origin_turn_id": turn_ids[-1]}),
                ("subagent:unknown", parent, {"origin_input_id": None, "origin_turn_id": turn_ids[-1]}),
                ("subagent:other", "chat:other", {"origin_input_id": input_ids[-1]}),
                *(
                    (f"subagent:unrelated-{i}", parent, {"origin_input_id": f"not-in-page-{i}"})
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
        params = tuple(value for ids in (input_ids, message_ids, turn_ids)
                       for value in (parent, json.dumps(ids)))
        plan = [row[3] for row in db.execute("EXPLAIN QUERY PLAN " + sqlite_store._SUBAGENT_METADATA_QUERY, params)]
        for field in ("origin_input_id", "origin_message_id", "origin_turn_id"):
            assert any(
                f"SEARCH sessions USING INDEX sessions_subagent_{field}" in detail
                and "<expr>=? AND <expr>=?" in detail
                for detail in plan
            ), plan
        # The API must not consume one SQLite variable per requested ID.
        db.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 10)
        rows = upgraded.list_subagent_session_metadata(
            parent, input_ids=input_ids, message_ids=message_ids, turn_ids=turn_ids,
        )

    assert {row["key"] for row in rows} == {
        "subagent:new", "subagent:legacy-message", "subagent:legacy-turn",
    }
    assert next(row for row in rows if row["key"] == "subagent:new")["metadata"]["subagent_task"] == {
        "origin_input_id": input_ids[-1],
    }
