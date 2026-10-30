from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import pytest

import nanobot.webui.session_list_index as session_list_index
from nanobot.cron.session_turns import CRON_HISTORY_META
from nanobot.providers.base import ProviderConversationState
from nanobot.security.workspace_access import WORKSPACE_SCOPE_METADATA_KEY
from nanobot.session.automation_turns import AUTOMATION_HISTORY_META
from nanobot.session.history_visibility import HIDDEN_HISTORY_META
from nanobot.session.manager import SessionManager
from nanobot.session.model_selection import SESSION_MODEL_PRESET_METADATA_KEY
from nanobot.session.recovery import RECOVERY_METADATA_KEY
from nanobot.session.types import SESSION_TYPE_KEY, SessionType


def test_webui_session_list_reads_previews_without_loading_history(tmp_path, monkeypatch):
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("websocket:indexed")
    session.metadata[SESSION_MODEL_PRESET_METADATA_KEY] = "fast"
    session.add_message("user", "indexed preview")
    manager.save(session)
    assert list_webui_sessions(manager)[0]["preview"] == "indexed preview"

    def fail_load(*args, **kwargs):
        raise AssertionError("sidebar must not load conversation history or rewrite unchanged cache")

    monkeypatch.setattr(manager._store, "load", fail_load)
    monkeypatch.setattr(manager, "read_session_metadata", fail_load)
    rows = list_webui_sessions(manager)
    assert rows[0]["key"] == "websocket:indexed"
    assert rows[0]["preview"] == "indexed preview"
    assert rows[0]["model_preset"] == "fast"


def test_webui_session_list_refreshes_after_model_preset_rename(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("websocket:renamed-preset")
    session.metadata[SESSION_MODEL_PRESET_METADATA_KEY] = "openai"
    session.add_message("user", "hello")
    manager.save(session)

    assert list_webui_sessions(manager)[0]["model_preset"] == "openai"

    assert manager.rename_model_preset("openai", "Codex") == 1

    assert list_webui_sessions(manager)[0]["model_preset"] == "Codex"


def test_webui_session_list_surfaces_pending_recovery_state(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("websocket:needs-attention")
    session.add_message("user", "the interrupted task")
    session.metadata[RECOVERY_METADATA_KEY] = {
        "status": "awaiting_user",
        "recovery_id": "recovery-123",
        "reason": "uncertain_tool_state",
        "attempts": 1,
        "checkpoint": {"tool_args": "secret"},
    }
    manager.save(session)

    row = list_webui_sessions(manager)[0]

    assert row["recovery_state"] == {
        "status": "awaiting_user",
        "recovery_id": "recovery-123",
        "reason": "uncertain_tool_state",
        "attempts": 1,
    }


def test_webui_session_list_indexes_workspace_scope_and_preserves_null(
    tmp_path: Path,
) -> None:
    manager = SessionManager(tmp_path)
    project = tmp_path / "project"
    project.mkdir()

    scoped = manager.get_or_create("websocket:scoped")
    scoped.metadata[WORKSPACE_SCOPE_METADATA_KEY] = {
        "project_path": str(project),
        "access_mode": "full",
        "future_extension": "x" * 5000,
    }
    manager.save(scoped)
    explicit_null = manager.get_or_create("websocket:null")
    explicit_null.metadata[WORKSPACE_SCOPE_METADATA_KEY] = None
    manager.save(explicit_null)
    manager.save(manager.get_or_create("websocket:missing"))

    rows = {row["key"]: row for row in list_webui_sessions(manager)}

    assert session_list_index.indexed_workspace_scope(rows["websocket:scoped"]) == (
        True,
        {"project_path": str(project), "access_mode": "full"},
    )
    assert session_list_index.indexed_workspace_scope(rows["websocket:null"]) == (True, None)
    assert session_list_index.indexed_workspace_scope(rows["websocket:missing"]) == (False, None)

    scoped.metadata[WORKSPACE_SCOPE_METADATA_KEY]["access_mode"] = "restricted"
    manager.save(scoped)

    refreshed = {row["key"]: row for row in list_webui_sessions(manager)}
    assert session_list_index.indexed_workspace_scope(refreshed["websocket:scoped"])[1] == {
        "project_path": str(project),
        "access_mode": "restricted",
    }


def test_webui_session_list_refreshes_after_concurrent_metadata_change(tmp_path, monkeypatch):
    manager = SessionManager(tmp_path)
    key = "websocket:scope-race"
    session = manager.get_or_create(key)
    session.metadata[WORKSPACE_SCOPE_METADATA_KEY] = {"project_path": str(tmp_path), "access_mode": "full"}
    manager.save(session)
    original = manager.list_session_metadata

    def racing_read():
        snapshot = original()
        manager.update_session_metadata(key, {WORKSPACE_SCOPE_METADATA_KEY: {
            "project_path": str(tmp_path), "access_mode": "restricted",
        }})
        return snapshot

    monkeypatch.setattr(manager, "list_session_metadata", racing_read)
    first = list_webui_sessions(manager)[0]
    second = list_webui_sessions(manager)[0]
    assert session_list_index.indexed_workspace_scope(first)[1]["access_mode"] == "full"
    assert session_list_index.indexed_workspace_scope(second)[1]["access_mode"] == "restricted"


def test_webui_session_list_sees_committed_snapshot_during_write(tmp_path):
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("websocket:concurrent")
    session.add_message("user", "before")
    manager.save(session)
    session.messages[0]["content"] = "after"
    with ThreadPoolExecutor(max_workers=1) as executor:
        def write() -> None:
            manager.save(session)
            rows = executor.submit(list_webui_sessions, manager).result(timeout=3)
            assert rows[0]["preview"] == "before"

        manager._store.run_write(write)
        assert list_webui_sessions(manager)[0]["preview"] == "after"


def test_webui_session_list_rejects_invalid_internal_model_preset_metadata(
    tmp_path: Path,
) -> None:
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("websocket:custom-metadata")
    session.metadata["model_preset"] = 7
    session.metadata[SESSION_MODEL_PRESET_METADATA_KEY] = {"invalid": True}
    session.add_message("user", "custom metadata")
    manager.save(session)

    with pytest.raises(ValueError, match="session model preset must be a non-empty string"):
        list_webui_sessions(manager)

    assert manager.get_or_create(session.key).metadata["model_preset"] == 7


def test_webui_session_list_reflects_changed_preview(tmp_path: Path, monkeypatch) -> None:
    manager = SessionManager(tmp_path)
    first = manager.get_or_create("websocket:first")
    first.add_message("user", "first")
    manager.save(first)
    second = manager.get_or_create("websocket:second")
    second.add_message("user", "second before")
    manager.save(second)

    assert {row["preview"] for row in list_webui_sessions(manager)} == {"first", "second before"}

    second.messages.clear()
    second.add_message("user", "second after")
    manager.save(second)

    rows = list_webui_sessions(manager)

    assert {row["preview"] for row in rows} == {"first", "second after"}


def test_webui_session_list_skips_provider_state_before_preview_budget(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("websocket:private-state")
    session.provider_state = ProviderConversationState(
        kind="openai_responses",
        provider="openai:test",
        model="test-model",
        version=1,
        payload={"items": [{"encrypted_content": "x" * 200}]},
    )
    session.add_message("user", "visible preview")
    manager.save(session)

    assert list_webui_sessions(manager)[0]["preview"] == "visible preview"


def test_webui_session_list_drops_deleted_index_rows(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("websocket:deleted")
    session.add_message("user", "gone")
    manager.save(session)

    assert list_webui_sessions(manager)[0]["key"] == "websocket:deleted"

    assert manager.delete_session("websocket:deleted") is True

    assert list_webui_sessions(manager) == []


def test_webui_session_list_skips_cron_internal_user_preview(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("websocket:cron-preview")
    session.add_message(
        "user",
        "Scheduled cron job triggered: 30s-test\n\nInternal reminder prompt",
        **{CRON_HISTORY_META: True},
    )
    session.add_message("assistant", "提醒已经到期。")
    manager.save(session)

    assert list_webui_sessions(manager)[0]["preview"] == "提醒已经到期。"


def test_webui_session_list_skips_trigger_internal_user_preview(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("websocket:trigger-preview")
    session.add_message(
        "user",
        "Local trigger received: PR review",
        **{AUTOMATION_HISTORY_META: {"kind": "local_trigger", "trigger_id": "trg_123"}},
    )
    session.add_message("assistant", "PR #4502 已经开始 review。")
    manager.save(session)

    assert list_webui_sessions(manager)[0]["preview"] == "PR #4502 已经开始 review。"


def test_webui_session_list_skips_hidden_history_user_preview(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("websocket:hidden-preview")
    session.add_message(
        "user",
        "internal subagent result",
        **{HIDDEN_HISTORY_META: {"kind": "subagent_result", "subagent_task_id": "sub-1"}},
    )
    session.add_message("assistant", "subagent summary")
    manager.save(session)

    assert list_webui_sessions(manager)[0]["preview"] == "subagent summary"


def test_webui_session_list_sorts_by_message_activity_not_maintenance_timestamp(
    tmp_path: Path,
) -> None:
    manager = SessionManager(tmp_path)
    old = manager.get_or_create("websocket:old")
    old.created_at = datetime(2026, 6, 1, 10, 0, 0)
    old.add_message("user", "old first visible activity")
    old.messages[-1]["timestamp"] = "2026-06-01T10:00:00"
    old.add_message("assistant", "automation result")
    old.messages[-1]["timestamp"] = "2026-06-05T10:00:00"
    old.updated_at = datetime(2026, 6, 30, 17, 40, 0)
    manager.save(old)

    newer = manager.get_or_create("websocket:newer")
    newer.created_at = datetime(2026, 6, 4, 10, 0, 0)
    newer.add_message("user", "newer real activity")
    newer.messages[-1]["timestamp"] = "2026-06-04T10:00:00"
    newer.updated_at = datetime(2026, 6, 4, 10, 0, 0)
    manager.save(newer)

    rows = list_webui_sessions(manager)

    assert [row["key"] for row in rows] == ["websocket:old", "websocket:newer"]
    assert rows[0]["updated_at"] == "2026-06-05T10:00:00"


def list_webui_sessions(manager: SessionManager) -> list[dict]:
    return session_list_index.list_webui_sessions(manager)


async def test_sidebar_allocates_handles_then_reads_during_pending_write(tmp_path, monkeypatch):
    import asyncio
    import threading
    from types import SimpleNamespace

    from websockets.datastructures import Headers
    from websockets.http11 import Request

    from nanobot.bus.queue import MessageBus
    from nanobot.channels.websocket.runtime import WebSocketConfig
    from nanobot.webui.gateway_services import build_gateway_services

    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path / "data")
    manager = SessionManager(tmp_path / "workspace")
    state = manager.state
    key = "websocket:busy"
    await state.get(key)
    await state.update_metadata(key, {"title": "committed"})
    gateway = build_gateway_services(
        config=WebSocketConfig(), bus=MessageBus(), session_manager=manager,
        static_dist_path=None, workspace_path=tmp_path / "workspace",
        default_restrict_to_workspace=True, runtime_model_name=lambda: "test-model",
        runtime_surface="gateway", runtime_capabilities_overrides=None,
    )
    token = gateway.tokens.issue_api_token(60)
    connection = SimpleNamespace(remote_address=("127.0.0.1", 12345))
    request = Request("/api/sessions", Headers({"Authorization": f"Bearer {token}"}))
    started, release = threading.Event(), threading.Event()
    original = manager._store.replace_metadata

    def blocked(session_key, metadata, **kwargs):
        started.set()
        assert release.wait(5)
        return original(session_key, metadata, **kwargs)

    try:
        first = await gateway.http.dispatch(connection, request)
        assert first.status_code == 200
        first_row, = json.loads(first.body)["sessions"]
        persisted = await state.read_metadata(key)
        assert first_row["handle"]["name"] == persisted["metadata"]["session_handle"]
        monkeypatch.setattr(manager._store, "replace_metadata", blocked)
        write = asyncio.create_task(state.update_metadata(key, {"title": "next"}))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            response = await asyncio.wait_for(gateway.http.dispatch(connection, request), 0.5)
            assert response.status_code == 200
            row, = json.loads(response.body)["sessions"]
            assert row["title"] == "committed"
            assert row["handle"] == first_row["handle"]
        finally:
            release.set()
            await write
    finally:
        release.set()
        await state.aclose()


def test_sidebar_uses_durable_display_summary_and_filters_private_sessions(history):
    sessions = history.sessions
    sessions.types.register(SessionType("internal", needs_handle=False, public_history=False))
    for key in ("websocket:visible", "websocket:private"):
        history.append(key, {"event": "user", "text": "  display\n preview  ", "created_at_ms": 1760000001000})
        history.append(key, {"event": "message", "text": "answer", "created_at_ms": 1760000002000})
    private = sessions.get_or_create("websocket:private")
    private.metadata[SESSION_TYPE_KEY] = "internal"
    sessions.save(private)
    rows = list_webui_sessions(sessions)
    assert [row["key"] for row in rows] == ["websocket:visible"]
    assert rows[0]["preview"] == "display preview"
    assert datetime.fromisoformat(rows[0]["updated_at"]).timestamp() == 1760000002
    history.append("websocket:visible", {"event": "turn_end", "created_at_ms": 1760000003000})
    assert datetime.fromisoformat(list_webui_sessions(sessions)[0]["updated_at"]).timestamp() == 1760000003
    sessions.delete_session("websocket:visible")
    assert list_webui_sessions(sessions) == []
