"""Administrative SQLite repository operations."""

from nanobot.providers.base import ProviderConversationState
from nanobot.session.manager import Session, SessionManager
from nanobot.session.model_selection import SESSION_MODEL_PRESET_METADATA_KEY


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
