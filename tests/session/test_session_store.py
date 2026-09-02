import json
from unittest.mock import MagicMock

import nanobot.session as session_api
from nanobot.providers.base import ProviderConversationState
from nanobot.session import Session, SessionManager
from nanobot.session.manager import SessionStore
from nanobot.session.model_selection import SESSION_MODEL_PRESET_METADATA_KEY


def test_store_types_are_not_public_session_api() -> None:
    assert not hasattr(session_api, "SessionStore")
    assert not hasattr(session_api, "JsonlSessionStore")


def test_manager_delegates_persistence_to_store(tmp_path) -> None:
    stored = Session(key="cli:test")
    stored.add_message("user", "hello")
    payload = {
        "key": stored.key,
        "created_at": stored.created_at.isoformat(),
        "updated_at": stored.updated_at.isoformat(),
        "metadata": {},
        "messages": stored.messages,
    }
    metadata = {
        "key": stored.key,
        "created_at": stored.created_at.isoformat(),
        "updated_at": stored.updated_at.isoformat(),
        "metadata": {},
    }
    listing = [
        {
            "key": stored.key,
            "created_at": stored.created_at.isoformat(),
            "updated_at": stored.updated_at.isoformat(),
            "title": "",
            "preview": "hello",
            "path": "session.db",
        }
    ]
    store = MagicMock(spec=SessionStore)
    store.load.return_value = stored
    store.read.return_value = payload
    store.read_metadata.return_value = metadata
    store.list_sessions.return_value = listing
    store.delete.return_value = True
    manager = SessionManager(tmp_path, store=store)

    assert manager.get_or_create(stored.key) is stored
    assert manager.get_or_create(stored.key) is stored
    store.load.assert_called_once_with(stored.key)

    manager.save(stored, fsync=True)
    store.save.assert_called_once_with(stored, fsync=True)
    assert manager.read_session_file(stored.key) == payload
    assert manager.read_session_metadata(stored.key) == metadata
    assert manager.list_sessions() == listing

    assert manager.delete_session(stored.key) is True
    store.delete.assert_called_once_with(stored.key)
    assert manager.get_cached(stored.key) is None


def test_manager_renames_model_preset_in_live_and_persisted_sessions(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    sessions_root = tmp_path / "sessions"
    manager = SessionManager(workspace, sessions_root=sessions_root)
    selected = manager.get_or_create("websocket:selected")
    selected.metadata[SESSION_MODEL_PRESET_METADATA_KEY] = "openai"
    manager.save(selected)
    other = manager.get_or_create("websocket:other")
    other.metadata[SESSION_MODEL_PRESET_METADATA_KEY] = "backup"
    manager.save(other)
    transient = manager.get_or_create_transient("websocket:temporary")
    transient.metadata[SESSION_MODEL_PRESET_METADATA_KEY] = "openai"

    assert manager.rename_model_preset("openai", "Codex") == 2
    assert selected.metadata[SESSION_MODEL_PRESET_METADATA_KEY] == "Codex"
    assert transient.metadata[SESSION_MODEL_PRESET_METADATA_KEY] == "Codex"

    reloaded = SessionManager(workspace, sessions_root=sessions_root)
    assert (
        reloaded.get_or_create("websocket:selected").metadata[
            SESSION_MODEL_PRESET_METADATA_KEY
        ]
        == "Codex"
    )
    assert (
        reloaded.get_or_create("websocket:other").metadata[
            SESSION_MODEL_PRESET_METADATA_KEY
        ]
        == "backup"
    )


def test_read_session_snapshot_does_not_populate_runtime_cache(tmp_path) -> None:
    stored = Session(key="websocket:context")
    store = MagicMock(spec=SessionStore)
    store.load.return_value = stored
    manager = SessionManager(tmp_path, store=store)

    assert manager.read_session_snapshot(stored.key) is stored
    assert manager.get_cached(stored.key) is None
    store.load.assert_called_once_with(stored.key)


def test_manager_preserves_full_session_before_store_save(tmp_path) -> None:
    store = MagicMock(spec=SessionStore)
    manager = SessionManager(tmp_path, store=store)
    session = Session(
        key="cli:large",
        messages=[
            {
                "role": "user" if index % 2 == 0 else "assistant",
                "content": str(index),
            }
            for index in range(2_001)
        ],
    )

    manager.save(session)

    assert len(session.messages) == 2_001
    assert session.messages[0]["content"] == "0"
    assert session.messages[-1]["content"] == "2000"
    store.save.assert_called_once_with(session, fsync=False)


def test_runtime_checkpoint_does_not_rewrite_long_session(tmp_path) -> None:
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("websocket:long")
    for index in range(256):
        session.add_message("user", f"{index}:" + "x" * 4096)
    manager.save(session)

    main_path = manager._get_session_path(session.key)
    main_before = main_path.read_bytes()
    stat_before = main_path.stat()
    session.metadata["runtime_checkpoint"] = {
        "phase": "tools_completed",
        "assistant_message": {"role": "assistant", "content": "working"},
        "completed_tool_results": [],
        "pending_tool_calls": [],
    }
    session.provider_state = ProviderConversationState(
        kind="openai_responses",
        provider="openai:test",
        model="test-model",
        version=1,
        payload={"response_id": "private-response"},
    )

    manager.save_runtime_checkpoint(session)

    checkpoint_path = manager._get_runtime_checkpoint_path(session.key)
    assert main_path.read_bytes() == main_before
    assert main_path.stat().st_ino == stat_before.st_ino
    assert main_path.stat().st_mtime_ns == stat_before.st_mtime_ns
    assert checkpoint_path.stat().st_size < len(main_before) // 100

    restored = SessionManager(tmp_path).get_or_create(session.key)
    assert restored.metadata["runtime_checkpoint"]["phase"] == "tools_completed"
    assert restored.provider_state is not None
    assert restored.provider_state.payload == {"response_id": "private-response"}


def test_load_migrates_legacy_write_stdin_history(tmp_path) -> None:
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("websocket:legacy-exec")
    session.messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "write_stdin",
                        "arguments": json.dumps(
                            {
                                "session_id": "abc",
                                "chars": "yes\n",
                                "wait_for": "ready",
                                "wait_timeout_ms": 5000,
                                "yield_time_ms": 0,
                                "max_output_tokens": 1000,
                            }
                        ),
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call-1",
            "name": "write_stdin",
            "content": "ready",
        },
    ]
    session.provider_state = ProviderConversationState(
        kind="openai_responses",
        provider="openai:test",
        model="test-model",
        version=1,
        payload={"response_id": "legacy-response"},
    )
    manager.save(session)

    restored = SessionManager(tmp_path).get_or_create(session.key)
    function = restored.messages[0]["tool_calls"][0]["function"]
    arguments = json.loads(function["arguments"])

    assert function["name"] == "exec_session"
    assert arguments == {
        "session_id": "abc",
        "wait_for": "ready",
        "input": "yes\n",
        "timeout_ms": 5000,
    }
    assert restored.messages[1]["name"] == "exec_session"
    assert restored.provider_state is None


def test_load_migrates_legacy_write_stdin_runtime_checkpoint(tmp_path) -> None:
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("websocket:legacy-checkpoint")
    session.add_message("user", "continue")
    manager.save(session)
    legacy_call = {
        "id": "call-1",
        "type": "function",
        "function": {
            "name": "write_stdin",
            "arguments": {"session_id": "abc", "chars": "", "yield_time_ms": 1000},
        },
    }
    session.metadata["runtime_checkpoint"] = {
        "phase": "awaiting_tools",
        "assistant_message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [legacy_call],
        },
        "completed_tool_results": [],
        "pending_tool_calls": [legacy_call],
    }
    session.provider_state = ProviderConversationState(
        kind="openai_responses",
        provider="openai:test",
        model="test-model",
        version=1,
        payload={"response_id": "legacy-response"},
    )
    manager.save_runtime_checkpoint(session)

    restored = SessionManager(tmp_path).get_or_create(session.key)
    checkpoint = restored.metadata["runtime_checkpoint"]
    pending_function = checkpoint["pending_tool_calls"][0]["function"]

    assert pending_function == {
        "name": "exec_session",
        "arguments": {"session_id": "abc", "input": "", "timeout_ms": 1000},
    }
    assert checkpoint["assistant_message"]["tool_calls"][0]["function"] == pending_function
    assert restored.provider_state is None


def test_completed_session_supersedes_stale_checkpoint(tmp_path) -> None:
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("websocket:completed")
    session.add_message("user", "question")
    manager.save(session)
    session.metadata["runtime_checkpoint"] = {"phase": "awaiting_tools"}
    manager.save_runtime_checkpoint(session)
    checkpoint_path = manager._get_runtime_checkpoint_path(session.key)
    stale_checkpoint = checkpoint_path.read_bytes()

    session.metadata.pop("runtime_checkpoint")
    session.add_message("assistant", "answer")
    manager.save(session)
    assert not checkpoint_path.exists()

    # Emulate a process dying after the main record was committed but before an
    # obsolete sidecar could be removed. The base fingerprint keeps it stale.
    checkpoint_path.write_bytes(stale_checkpoint)
    restored = SessionManager(tmp_path).get_or_create(session.key)
    assert "runtime_checkpoint" not in restored.metadata
    assert restored.messages[-1]["content"] == "answer"
    assert not checkpoint_path.exists()


def test_delete_session_removes_runtime_checkpoint(tmp_path) -> None:
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("websocket:delete")
    session.add_message("user", "question")
    manager.save(session)
    session.metadata["runtime_checkpoint"] = {"phase": "awaiting_tools"}
    manager.save_runtime_checkpoint(session)
    checkpoint_path = manager._get_runtime_checkpoint_path(session.key)
    assert checkpoint_path.exists()

    assert manager.delete_session(session.key) is True
    assert not checkpoint_path.exists()


def test_invalid_runtime_checkpoint_is_discarded(tmp_path) -> None:
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("websocket:invalid-checkpoint")
    session.add_message("user", "question")
    manager.save(session)
    checkpoint_path = manager._get_runtime_checkpoint_path(session.key)
    checkpoint_path.write_text("{truncated", encoding="utf-8")

    restored = SessionManager(tmp_path).get_or_create(session.key)

    assert "runtime_checkpoint" not in restored.metadata
    assert not checkpoint_path.exists()
