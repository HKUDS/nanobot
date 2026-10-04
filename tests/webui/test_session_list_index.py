from __future__ import annotations

import io
import json
import os
import threading
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


@pytest.fixture(autouse=True)
def _isolate_webui_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    webui_dir = tmp_path / "webui"
    webui_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(session_list_index, "get_webui_dir", lambda: webui_dir)


def test_webui_session_list_reuses_valid_index_without_scanning_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("websocket:indexed")
    session.metadata[SESSION_MODEL_PRESET_METADATA_KEY] = "fast"
    session.add_message("user", "indexed preview")
    manager.save(session)

    assert list_webui_sessions(manager)[0]["preview"] == "indexed preview"
    assert list_webui_sessions(manager)[0]["model_preset"] == "fast"

    def fail_scan(session_manager: SessionManager, path: Path, webui_dir: Path) -> None:
        raise AssertionError(f"unexpected session file scan: {path}")

    monkeypatch.setattr(session_list_index, "_scan_session_row", fail_scan)

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
        # Private checkpoint details must never leak into the sidebar index.
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


def test_webui_session_index_uses_unique_temp_file(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("websocket:unique-index-temp")
    session.add_message("user", "hello")
    manager.save(session)
    stale_shared_tmp = manager.sessions_dir / ".webui_session_index.json.tmp"
    stale_shared_tmp.write_text("stale", encoding="utf-8")

    assert list_webui_sessions(manager)[0]["preview"] == "hello"

    assert stale_shared_tmp.read_text(encoding="utf-8") == "stale"
    assert not list(manager.sessions_dir.glob(".webui_session_index.json.*.tmp"))


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


def test_webui_session_list_does_not_cache_old_snapshot_with_new_signature(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = SessionManager(tmp_path)
    session_key = "websocket:scope-race"
    session = manager.get_or_create(session_key)
    session.metadata[WORKSPACE_SCOPE_METADATA_KEY] = {
        "project_path": str(tmp_path),
        "access_mode": "full",
    }
    session.add_message("user", "hello")
    manager.save(session)
    session_path = manager._get_session_path(session_key)
    original_open = open
    scope_changed = False

    class RacingReader(io.StringIO):
        def __next__(self) -> str:
            nonlocal scope_changed
            if not scope_changed:
                scope_changed = True
                current = manager.get_or_create(session_key)
                current.metadata[WORKSPACE_SCOPE_METADATA_KEY] = {
                    "project_path": str(tmp_path),
                    "access_mode": "restricted",
                }
                manager.save(current)
            return super().__next__()

    def racing_open(path, *args, **kwargs):
        if Path(path) == session_path:
            with original_open(path, *args, **kwargs) as source:
                return RacingReader(source.read())
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(session_list_index, "open", racing_open, raising=False)

    first = list_webui_sessions(manager)[0]
    second = list_webui_sessions(manager)[0]

    assert session_list_index.indexed_workspace_scope(first)[1]["access_mode"] == "full"
    assert session_list_index.indexed_workspace_scope(second)[1]["access_mode"] == "restricted"


def test_webui_session_scan_does_not_overlap_session_save(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = SessionManager(
        tmp_path / "workspace",
        sessions_root=tmp_path / "runtime",
    )
    session = manager.get_or_create("websocket:windows-reader")
    session.add_message("user", "before")
    manager.save(session)
    session_path = manager._get_session_path(session.key)
    session.messages[0]["content"] = "after"

    reader_open = threading.Event()
    release_reader = threading.Event()
    save_started = threading.Event()
    save_lock_attempted = threading.Event()
    write_entered = threading.Event()
    original_open = open
    store = manager._jsonl_store
    original_acquire = store._session_files_lock.acquire
    original_save_unlocked = store._save_unlocked

    class BlockingReader:
        def __init__(self, file):
            self.file = file

        def __enter__(self):
            entered = self.file.__enter__()
            reader_open.set()
            if not release_reader.wait(5):
                raise AssertionError("timed out waiting to release the session reader")
            return entered

        def __exit__(self, *args):
            try:
                return self.file.__exit__(*args)
            finally:
                reader_open.clear()

    def blocking_open(path, *args, **kwargs):
        file = original_open(path, *args, **kwargs)
        if Path(path) == session_path:
            return BlockingReader(file)
        return file

    def observed_acquire(*args, **kwargs):
        if save_started.is_set():
            save_lock_attempted.set()
        return original_acquire(*args, **kwargs)

    def observed_save_unlocked(session, *, fsync=False):
        write_entered.set()
        assert not reader_open.is_set(), "save entered while the canonical file was open"
        return original_save_unlocked(session, fsync=fsync)

    monkeypatch.setattr(session_list_index, "open", blocking_open, raising=False)
    monkeypatch.setattr(store._session_files_lock, "acquire", observed_acquire)
    monkeypatch.setattr(store, "_save_unlocked", observed_save_unlocked)

    def save_session() -> None:
        save_started.set()
        manager.save(session)

    with ThreadPoolExecutor(max_workers=2) as executor:
        list_future = executor.submit(list_webui_sessions, manager)
        try:
            assert reader_open.wait(5)
            save_future = executor.submit(save_session)
            assert save_lock_attempted.wait(5)
            assert not write_entered.is_set()
        finally:
            release_reader.set()

        assert list_future.result(timeout=5)[0]["preview"] == "before"
        save_future.result(timeout=5)

    assert write_entered.is_set()
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


def test_webui_session_list_rescans_only_changed_file(tmp_path: Path, monkeypatch) -> None:
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

    original_scan = session_list_index._scan_session_row
    scanned: list[str] = []

    def record_scan(
        session_manager: SessionManager,
        path: Path,
        webui_dir: Path,
    ) -> dict | None:
        scanned.append(path.name)
        return original_scan(session_manager, path, webui_dir)

    monkeypatch.setattr(session_list_index, "_scan_session_row", record_scan)

    rows = list_webui_sessions(manager)

    assert scanned == [manager._get_session_path("websocket:second").name]
    assert {row["preview"] for row in rows} == {"first", "second after"}


def test_webui_session_list_skips_provider_state_before_preview_budget(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(session_list_index, "_SESSION_LIST_PREVIEW_MAX_CHARS", 100)
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


def test_webui_session_list_recovers_transcript_without_canonical_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webui_dir = tmp_path / "webui"
    webui_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(session_list_index, "get_webui_dir", lambda: webui_dir)
    key = "websocket:restored"
    transcript = webui_dir / f"{SessionManager.safe_key(key)}.jsonl"
    transcript.write_text(
        '{"event":"user","chat_id":"restored","text":"original question",'
        '"created_at_ms":1785502800000}\n'
        '{"event":"message","chat_id":"restored","text":"original answer",'
        '"created_at_ms":1785502801000}\n'
        '{"event":"turn_end","chat_id":"restored","created_at_ms":1785502802000}\n',
        encoding="utf-8",
    )
    manager = SessionManager(tmp_path / "workspace")

    [row] = list_webui_sessions(manager)

    assert row["key"] == key
    assert row["preview"] == "original question"
    assert row["created_at"] == datetime.fromtimestamp(1785502800).isoformat()
    assert not manager._get_session_path(key).exists()
    assert manager.list_sessions() == []

    reloaded = SessionManager(tmp_path / "workspace")
    assert [row["key"] for row in list_webui_sessions(reloaded)] == [key]


def test_webui_session_list_recovers_colon_chat_id_from_transcript(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webui_dir = tmp_path / "webui"
    webui_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(session_list_index, "get_webui_dir", lambda: webui_dir)
    key = "websocket:scope:child"
    transcript = webui_dir / f"{SessionManager.safe_key(key)}.jsonl"
    transcript.write_text(
        '{"event":"user","chat_id":"scope:child","text":"scoped history"}\n',
        encoding="utf-8",
    )

    [row] = list_webui_sessions(SessionManager(tmp_path / "workspace"))

    assert row["key"] == key
    assert row["preview"] == "scoped history"


def test_webui_session_list_normalizes_transcript_preview(tmp_path: Path) -> None:
    key = "websocket:long-preview"
    transcript = tmp_path / "webui" / f"{SessionManager.safe_key(key)}.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "event": "user",
                "chat_id": "long-preview",
                "text": "first\n\n" + "word " * 100,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    [row] = list_webui_sessions(SessionManager(tmp_path / "workspace"))

    assert row["preview"].startswith("first word")
    assert "\n" not in row["preview"]
    assert row["preview"].endswith("…")


def test_webui_session_list_tolerates_invalid_transcript_timestamp(
    tmp_path: Path,
) -> None:
    key = "websocket:bad-time"
    transcript = tmp_path / "webui" / f"{SessionManager.safe_key(key)}.jsonl"
    transcript.write_text(
        '{"event":"user","chat_id":"bad-time","text":"still visible",'
        '"created_at_ms":1e100}\n',
        encoding="utf-8",
    )

    [row] = list_webui_sessions(SessionManager(tmp_path / "workspace"))

    assert row["preview"] == "still visible"
    datetime.fromisoformat(row["created_at"])


def test_webui_session_list_ignores_invalid_transcript_chat_id(tmp_path: Path) -> None:
    transcript = tmp_path / "webui" / "websocket_.._outside.jsonl"
    transcript.write_text(
        '{"event":"user","chat_id":"../outside","text":"do not expose"}\n',
        encoding="utf-8",
    )

    assert list_webui_sessions(SessionManager(tmp_path / "workspace")) == []


def test_webui_session_list_recovers_segment_only_transcript(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webui_dir = tmp_path / "webui"
    webui_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(session_list_index, "get_webui_dir", lambda: webui_dir)
    key = "websocket:segmented"
    segments = webui_dir / f"{SessionManager.safe_key(key)}.segments"
    segments.mkdir()
    (segments / "000001.jsonl").write_text(
        '{"event":"user","chat_id":"segmented","text":"older segment"}\n'
        '{"event":"turn_end","chat_id":"segmented"}\n',
        encoding="utf-8",
    )

    [row] = list_webui_sessions(SessionManager(tmp_path / "workspace"))

    assert row["key"] == key
    assert row["preview"] == "older segment"


def test_webui_session_list_prefers_canonical_metadata_without_duplicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webui_dir = tmp_path / "webui"
    webui_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(session_list_index, "get_webui_dir", lambda: webui_dir)
    key = "websocket:canonical"
    (webui_dir / f"{SessionManager.safe_key(key)}.jsonl").write_text(
        '{"event":"user","chat_id":"canonical","text":"display copy"}\n',
        encoding="utf-8",
    )
    manager = SessionManager(tmp_path / "workspace")
    session = manager.get_or_create(key)
    session.metadata["title"] = "Canonical title"
    session.add_message("user", "canonical preview")
    manager.save(session)

    rows = list_webui_sessions(manager)

    assert len(rows) == 1
    assert rows[0]["key"] == key
    assert rows[0]["preview"] == "canonical preview"


def test_webui_session_list_reuses_unchanged_transcript_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webui_dir = tmp_path / "webui"
    webui_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(session_list_index, "get_webui_dir", lambda: webui_dir)
    key = "websocket:cached-transcript"
    (webui_dir / f"{SessionManager.safe_key(key)}.jsonl").write_text(
        '{"event":"user","chat_id":"cached-transcript","text":"cached"}\n',
        encoding="utf-8",
    )
    manager = SessionManager(tmp_path / "workspace")
    assert list_webui_sessions(manager)[0]["preview"] == "cached"

    def fail_scan(*args, **kwargs):
        raise AssertionError("unchanged transcript should reuse its index row")

    monkeypatch.setattr(session_list_index, "_scan_transcript_row", fail_scan)

    assert list_webui_sessions(manager)[0]["preview"] == "cached"


def test_webui_session_list_does_not_cache_changed_transcript_with_old_signature(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webui_dir = tmp_path / "webui"
    key = "websocket:transcript-race"
    transcript = webui_dir / f"{SessionManager.safe_key(key)}.jsonl"
    transcript.write_text(
        '{"event":"user","chat_id":"transcript-race","text":"initial"}\n',
        encoding="utf-8",
    )
    manager = SessionManager(tmp_path / "workspace")
    assert list_webui_sessions(manager)[0]["preview"] == "initial"
    transcript.write_text(
        '{"event":"user","chat_id":"transcript-race","text":"first scan"}\n',
        encoding="utf-8",
    )

    original_open = open
    changed = False

    class RacingReader(io.StringIO):
        def __next__(self) -> str:
            nonlocal changed
            if not changed:
                changed = True
                transcript.write_text(
                    '{"event":"user","chat_id":"transcript-race","text":"second scan"}\n',
                    encoding="utf-8",
                )
            return super().__next__()

    def racing_open(path, *args, **kwargs):
        if Path(path) == transcript:
            with original_open(path, *args, **kwargs) as source:
                return RacingReader(source.read())
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(session_list_index, "open", racing_open, raising=False)

    first = list_webui_sessions(manager)
    second = list_webui_sessions(manager)

    assert first[0]["preview"] == "first scan"
    assert second[0]["preview"] == "second scan"


def test_webui_session_list_drops_deleted_transcript_index_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webui_dir = tmp_path / "webui"
    webui_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(session_list_index, "get_webui_dir", lambda: webui_dir)
    key = "websocket:deleted-transcript"
    transcript = webui_dir / f"{SessionManager.safe_key(key)}.jsonl"
    transcript.write_text(
        '{"event":"user","chat_id":"deleted-transcript","text":"delete me"}\n',
        encoding="utf-8",
    )
    manager = SessionManager(tmp_path / "workspace")
    assert list_webui_sessions(manager)[0]["key"] == key

    transcript.unlink()

    assert list_webui_sessions(manager) == []


def test_webui_session_list_keeps_runtime_instances_isolated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_dir = tmp_path / "instance-a" / "webui"
    second_dir = tmp_path / "instance-b" / "webui"
    first_dir.mkdir(parents=True)
    second_dir.mkdir(parents=True)
    (first_dir / "websocket_first.jsonl").write_text(
        '{"event":"user","chat_id":"first","text":"first instance"}\n',
        encoding="utf-8",
    )
    (second_dir / "websocket_second.jsonl").write_text(
        '{"event":"user","chat_id":"second","text":"second instance"}\n',
        encoding="utf-8",
    )
    manager = SessionManager(tmp_path / "workspace")

    monkeypatch.setattr(session_list_index, "get_webui_dir", lambda: first_dir)
    assert [row["key"] for row in list_webui_sessions(manager)] == ["websocket:first"]

    monkeypatch.setattr(session_list_index, "get_webui_dir", lambda: second_dir)
    assert [row["key"] for row in list_webui_sessions(manager)] == ["websocket:second"]


def test_webui_session_list_ignores_legacy_stem(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    legacy_path = manager.sessions_dir / "websocket_legacy.jsonl"
    legacy_path.write_text(
        '{"_type":"metadata","key":"websocket:legacy",'
        '"created_at":"2025-01-01T00:00:00",'
        '"updated_at":"2025-01-01T00:00:00","metadata":{}}\n',
        encoding="utf-8",
    )

    assert list_webui_sessions(manager) == []
    assert legacy_path.exists()


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


def test_webui_session_list_uses_webui_transcript_activity_for_sort(
    tmp_path: Path,
    monkeypatch,
) -> None:
    webui_dir = tmp_path / "webui"
    webui_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(session_list_index, "get_webui_dir", lambda: webui_dir)

    manager = SessionManager(tmp_path)
    old_session = manager.get_or_create("websocket:old-metadata")
    old_session.created_at = datetime(2026, 6, 15, 10, 0, 0)
    old_session.updated_at = datetime(2026, 6, 15, 10, 0, 0)
    old_session.add_message("user", "old metadata")
    old_session.messages[-1]["timestamp"] = "2026-06-15T10:00:00"
    old_session.updated_at = datetime(2026, 6, 15, 10, 0, 0)
    manager.save(old_session)

    newer_metadata = manager.get_or_create("websocket:newer-metadata")
    newer_metadata.created_at = datetime(2026, 6, 15, 11, 0, 0)
    newer_metadata.updated_at = datetime(2026, 6, 15, 11, 0, 0)
    newer_metadata.add_message("user", "newer metadata")
    newer_metadata.messages[-1]["timestamp"] = "2026-06-15T11:00:00"
    newer_metadata.updated_at = datetime(2026, 6, 15, 11, 0, 0)
    manager.save(newer_metadata)

    transcript = webui_dir / "websocket_old-metadata.jsonl"
    transcript.write_text(
        '{"event":"turn_end","chat_id":"old-metadata"}\n',
        encoding="utf-8",
    )
    activity_ns = int(datetime(2026, 6, 15, 12, 0, 0).timestamp() * 1_000_000_000)
    os.utime(transcript, ns=(activity_ns, activity_ns))

    rows = list_webui_sessions(manager)

    assert [row["key"] for row in rows] == [
        "websocket:old-metadata",
        "websocket:newer-metadata",
    ]
    assert rows[0]["updated_at"].startswith("2026-06-15T12:00:00")


def test_webui_session_list_rescans_when_transcript_changes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    webui_dir = tmp_path / "webui"
    webui_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(session_list_index, "get_webui_dir", lambda: webui_dir)

    manager = SessionManager(tmp_path)
    session = manager.get_or_create("websocket:transcript-change")
    session.created_at = datetime(2026, 6, 15, 10, 0, 0)
    session.updated_at = datetime(2026, 6, 15, 10, 0, 0)
    session.add_message("user", "preview")
    session.messages[-1]["timestamp"] = "2026-06-15T10:00:00"
    session.updated_at = datetime(2026, 6, 15, 10, 0, 0)
    manager.save(session)

    assert list_webui_sessions(manager)[0]["preview"] == "preview"

    transcript = webui_dir / "websocket_transcript-change.jsonl"
    transcript.write_text(
        '{"event":"turn_end","chat_id":"transcript-change"}\n',
        encoding="utf-8",
    )
    activity_ns = int(datetime(2026, 6, 15, 12, 30, 0).timestamp() * 1_000_000_000)
    os.utime(transcript, ns=(activity_ns, activity_ns))

    original_scan = session_list_index._scan_session_row
    scanned: list[str] = []

    def record_scan(
        session_manager: SessionManager,
        path: Path,
        webui_dir: Path,
    ) -> dict | None:
        scanned.append(path.name)
        return original_scan(session_manager, path, webui_dir)

    monkeypatch.setattr(session_list_index, "_scan_session_row", record_scan)

    rows = list_webui_sessions(manager)

    assert scanned == [manager._get_session_path("websocket:transcript-change").name]
    assert rows[0]["updated_at"].startswith("2026-06-15T12:30:00")


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


def test_webui_session_list_fallback_time_when_missing(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    path = manager._get_session_path("websocket:missing-time")
    path.write_text(
        '{"_type": "metadata", "key": "websocket:missing-time"}\n'
        '{"_type": "message", "role": "user", "content": "hello"}\n',
        encoding="utf-8",
    )

    rows = list_webui_sessions(manager)
    assert len(rows) == 1
    assert rows[0]["key"] == "websocket:missing-time"
    assert rows[0]["created_at"] is not None
    assert rows[0]["updated_at"] is not None
    datetime.fromisoformat(rows[0]["created_at"])
    datetime.fromisoformat(rows[0]["updated_at"])


def test_session_manager_list_sessions_fallback_time_when_missing(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    path = manager._get_session_path("websocket:missing-time2")
    path.write_text(
        '{"_type": "metadata", "key": "websocket:missing-time2"}\n'
        '{"_type": "message", "role": "user", "content": "hello"}\n',
        encoding="utf-8",
    )

    sessions = manager.list_sessions()
    assert len(sessions) == 1
    assert sessions[0]["key"] == "websocket:missing-time2"
    assert sessions[0]["created_at"] is not None
    assert sessions[0]["updated_at"] is not None
    datetime.fromisoformat(sessions[0]["created_at"])
    datetime.fromisoformat(sessions[0]["updated_at"])
