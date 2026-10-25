"""Administrative SQLite repository operations."""

from datetime import datetime

from nanobot.providers.base import ProviderConversationState
from nanobot.session.manager import Session, SessionManager
from nanobot.session.model_selection import SESSION_MODEL_PRESET_METADATA_KEY
from nanobot.session.types import PARENT_SESSION_KEY, SESSION_TYPE_KEY


def test_manager_roundtrips_full_history_and_private_state(tmp_path):
    manager = SessionManager(tmp_path)
    session = Session(key="cli:test", messages=[{"role": "user", "content": str(i)} for i in range(2001)])
    session.provider_state = ProviderConversationState(kind="openai_responses", provider="openai:test",
        model="test-model", version=1, payload={"response_id": "private"})
    manager.save(session)
    loaded = manager.read_session_snapshot(session.key)
    assert loaded is not session
    assert loaded.messages == session.messages
    assert loaded.provider_state == session.provider_state
    assert "provider_state" not in manager.read_session_file(session.key)
    assert manager.list_sessions()[0]["preview"] == "0"


def test_rename_model_preset_is_atomic(tmp_path, monkeypatch):
    manager = SessionManager(tmp_path)
    for key in ("cli:one", "cli:two"):
        manager.save(Session(key=key, metadata={SESSION_MODEL_PRESET_METADATA_KEY: "old"}))
    original = manager._store.update_metadata
    def fail_second(key, values, **kwargs):
        if key == "cli:two":
            raise OSError("disk full")
        return original(key, values, **kwargs)
    import pytest
    with monkeypatch.context() as patch:
        patch.setattr(manager._store, "update_metadata", fail_second)
        with pytest.raises(OSError):
            manager.rename_model_preset("old", "new")
    assert all(manager.get_or_create(key).metadata[SESSION_MODEL_PRESET_METADATA_KEY] == "old"
               for key in ("cli:one", "cli:two"))
    assert manager.rename_model_preset("old", "new") == 2
    assert all(manager.get_or_create(key).metadata[SESSION_MODEL_PRESET_METADATA_KEY] == "new"
               for key in ("cli:one", "cli:two"))


def test_metadata_updates_do_not_replace_messages(tmp_path):
    manager = SessionManager(tmp_path)
    manager.save(Session(key="cli:test", messages=[{"role": "user", "content": "hello"}]))
    assert manager.update_session_metadata("cli:test", {"title": "new"})
    assert manager.read_session_file("cli:test")["messages"] == [{"role": "user", "content": "hello"}]
    assert manager.read_session_metadata("cli:test")["metadata"]["title"] == "new"
    assert not manager.update_session_metadata("cli:missing", {"title": "x"})
    assert manager.delete_session("cli:test")
    assert manager.read_session_file("cli:test") is None


def test_child_headers_select_declared_children_and_preserve_descendant_deletion(tmp_path, monkeypatch):
    manager = SessionManager(tmp_path)
    parent = "chat:项目'\"\\root"
    manager.save(Session(key=parent))
    manager.save(Session(key="chat:unrelated", metadata={"title": "unrelated"}))
    for key, kind, parent_key, second in (
        ("subagent:first", "subagent", parent, 1),
        ("extension:child", "extension", parent, 2),
        ("extension:grandchild", "extension", "extension:child", 3),
    ):
        manager.save(Session(
            key=key, updated_at=datetime(2026, 1, 1, 0, 0, second),
            messages=[{"role": "user", "content": "private transcript"}],
            metadata={
                PARENT_SESSION_KEY: parent_key, SESSION_TYPE_KEY: kind,
                "nested": {"value": key}, "runtime_checkpoint": {"step": 1},
                "pending_user_followups": [{"id": "queued"}],
            },
        ))

    def prohibit_full_listing():
        raise AssertionError("child queries must not materialize unrelated session headers")

    monkeypatch.setattr(manager._store, "list_metadata", prohibit_full_listing)
    assert manager.child_session_keys(parent) == ["extension:child", "subagent:first"]
    rows = manager.list_child_session_metadata(parent)
    assert [row["key"] for row in rows] == ["extension:child", "subagent:first"]
    assert rows[0]["updated_at"] == "2026-01-01T00:00:02"
    assert rows[0]["metadata"] == {
        PARENT_SESSION_KEY: parent, SESSION_TYPE_KEY: "extension",
        "nested": {"value": "extension:child"},
    }
    rows[0]["metadata"]["nested"]["value"] = "detached edit"
    assert manager.list_child_session_metadata(parent)[0]["metadata"]["nested"]["value"] == "extension:child"
    assert manager.read_session_metadata("extension:child")["metadata"]["runtime_checkpoint"] == {"step": 1}

    deleted = []
    manager.set_delete_observer(deleted.append)
    assert manager.delete_session(parent)
    assert set(deleted) == {parent, "subagent:first", "extension:child", "extension:grandchild"}
    assert [row["key"] for row in manager.list_sessions()] == ["chat:unrelated"]
    assert manager.list_child_session_metadata(parent) == []
