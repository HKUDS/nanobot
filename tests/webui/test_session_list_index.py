from __future__ import annotations

import io
import json
import os
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


@pytest.fixture(autouse=True)
def _isolate_webui_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    webui_dir = tmp_path / "webui"
    webui_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(session_list_index, "get_webui_dir", lambda: webui_dir)


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
    monkeypatch.setattr(session_list_index, "_read_index_rows", fail_load)
    monkeypatch.setattr(session_list_index, "_write_index_rows", fail_load)
    rows = list_webui_sessions(manager)
    assert rows[0]["key"] == "websocket:indexed"
    assert rows[0]["preview"] == "indexed preview"
    assert rows[0]["model_preset"] == "fast"


def test_webui_session_list_private_rows_suppress_transcript_fallback(tmp_path, monkeypatch):
    manager = SessionManager(tmp_path)
    manager.types.register(SessionType("internal", needs_handle=False, public_history=False))
    webui_dir = tmp_path / "webui"
    private_key, transcript_key = "websocket:internal", "websocket:transcript-only"
    for key in (private_key, transcript_key):
        (webui_dir / f"{SessionManager.safe_key(key)}.jsonl").write_text(
            json.dumps({"event": "user", "chat_id": key.removeprefix("websocket:"),
                        "text": "transcript preview"}) + "\n",
            encoding="utf-8",
        )
    assert {row["key"] for row in list_webui_sessions(manager)} == {private_key, transcript_key}

    public = manager.get_or_create("websocket:public")
    public.add_message("user", "public preview")
    manager.save(public)
    private = manager.get_or_create(private_key)
    private.metadata[SESSION_TYPE_KEY] = "internal"
    private.add_message("user", "private preview")
    manager.save(private)
    unknown = manager.get_or_create("websocket:unregistered")
    unknown.metadata[SESSION_TYPE_KEY] = "unregistered"
    manager.save(unknown)

    def individual_metadata_unavailable(*_args, **_kwargs):
        pytest.fail("sidebar visibility must use the existing metadata query snapshot")

    monkeypatch.setattr(manager, "read_session_metadata", individual_metadata_unavailable)
    rows = {row["key"]: row for row in list_webui_sessions(manager)}
    assert set(rows) == {public.key, transcript_key}
    assert rows[public.key]["preview"] == "public preview"
    assert rows[transcript_key]["preview"] == "transcript preview"
    assert {row["key"] for row in list_webui_sessions(manager)} == set(rows)


def test_webui_session_list_scans_empty_display_directory_once_per_request(tmp_path, monkeypatch):
    manager = SessionManager(tmp_path)
    keys = {"websocket:first", "websocket:second", "websocket:third"}
    for key in keys:
        manager.save(manager.get_or_create(key))
    list_webui_sessions(manager)
    webui_dir = tmp_path / "webui"
    original_stat, original_scandir = Path.stat, os.scandir
    scans = []

    def stored_files_only(path, *args, **kwargs):
        assert path.parent != webui_dir, "sidebar must not probe absent per-session display files"
        return original_stat(path, *args, **kwargs)

    def scan(path):
        scans.append(Path(path))
        return original_scandir(path)

    monkeypatch.setattr(Path, "stat", stored_files_only)
    monkeypatch.setattr(session_list_index.os, "scandir", scan)
    for _ in range(2):
        assert {row["key"] for row in list_webui_sessions(manager)} == keys
    assert scans == [webui_dir, webui_dir]


def test_webui_session_list_snapshot_tracks_all_display_artifacts(tmp_path):
    manager = SessionManager(tmp_path)
    webui_dir = tmp_path / "webui"
    key = "websocket:artifacts"
    stem = SessionManager.safe_key(key)
    segments = webui_dir / f"{stem}.segments"
    segments.mkdir()
    active = webui_dir / f"{stem}.jsonl"
    active.write_text('{"event":"user","chat_id":"artifacts","text":"active question"}\n', encoding="utf-8")
    segment = segments / "000001.jsonl"
    segment.write_text('{"event":"user","chat_id":"artifacts","text":"older question"}\n', encoding="utf-8")
    other_files = [webui_dir / f"{stem}.json", segments / "manifest.json",
                   segments / "state.json", segments / "delivery.json"]
    for path in other_files:
        path.write_text("{}\n", encoding="utf-8")
    all_files = [active, segment, *other_files]
    base_ns = int(datetime(2026, 1, 1).timestamp() * 1_000_000_000)
    for path in all_files:
        os.utime(path, ns=(base_ns, base_ns))

    row, = list_webui_sessions(manager)
    assert row["preview"] == "older question"
    cache = json.loads((manager.sessions_dir / ".webui_session_index.json").read_text(encoding="utf-8"))
    cached, = cache["sessions"]
    assert cached["webui_activity_files"] == len(all_files)
    assert cached["webui_activity_size"] == sum(path.stat().st_size for path in all_files)
    state_file = segments / "state.json"
    state_file.write_text('{"active":true}\n', encoding="utf-8")
    newer_ns = base_ns + 1_000_000_000
    os.utime(state_file, ns=(newer_ns, newer_ns))
    refreshed, = list_webui_sessions(manager)
    assert refreshed["updated_at"] == datetime.fromtimestamp(newer_ns / 1_000_000_000).isoformat()
    other_files[0].unlink()
    other_files[-1].unlink()
    list_webui_sessions(manager)
    cached, = json.loads((manager.sessions_dir / ".webui_session_index.json").read_text(encoding="utf-8"))["sessions"]
    assert cached["webui_activity_files"] == len(all_files) - 2
    assert cached["webui_activity_size"] == sum(path.stat().st_size for path in all_files if path.exists())


def test_webui_session_list_activity_uses_host_filename_case_semantics(tmp_path):
    manager = SessionManager(tmp_path)
    key = "websocket:MixedCase"
    session = manager.get_or_create(key)
    session.add_message("user", "stored question")
    session.messages[0]["timestamp"] = "2026-01-01T00:00:00"
    session.updated_at = datetime(2026, 1, 1)
    manager.save(session)
    path = tmp_path / "webui" / f"{SessionManager.safe_key(key).swapcase()}.jsonl"
    path.write_text('{"event":"turn_end","chat_id":"MixedCase"}\n', encoding="utf-8")
    activity = datetime(2026, 1, 2)
    activity_ns = int(activity.timestamp() * 1_000_000_000)
    os.utime(path, ns=(activity_ns, activity_ns))
    row, = list_webui_sessions(manager)
    assert row["updated_at"] == (activity.isoformat() if os.name == "nt" else "2026-01-01T00:00:00")


def test_webui_session_list_keeps_transcript_only_key_case(tmp_path):
    key = "websocket:MixedCase"
    path = tmp_path / "webui" / f"{SessionManager.safe_key(key)}.jsonl"
    path.write_text('{"event":"user","chat_id":"MixedCase","text":"question"}\n', encoding="utf-8")
    row, = list_webui_sessions(SessionManager(tmp_path))
    assert row["key"] == key and row["preview"] == "question"


def test_webui_session_list_rejects_display_file_and_segment_symlinks(tmp_path):
    manager = SessionManager(tmp_path)
    webui_dir = tmp_path / "webui"
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "000000.jsonl"
    target.write_text('{"event":"user","chat_id":"linked","text":"outside secret"}\n', encoding="utf-8")
    safe_segments = webui_dir / "websocket_safe.segments"
    safe_segments.mkdir()
    (safe_segments / "000001.jsonl").write_text(
        '{"event":"user","chat_id":"safe","text":"safe question"}\n', encoding="utf-8",
    )
    try:
        (webui_dir / "websocket_linked.jsonl").symlink_to(target)
        (webui_dir / "websocket_directory.segments").symlink_to(outside, target_is_directory=True)
        (safe_segments / "000000.jsonl").symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    row, = list_webui_sessions(manager)
    assert row["key"] == "websocket:safe" and row["preview"] == "safe question"



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
    key = "websocket:unique-index-temp"
    transcript = tmp_path / "webui" / f"{SessionManager.safe_key(key)}.jsonl"
    transcript.write_text(
        '{"event":"user","chat_id":"unique-index-temp","text":"hello"}\n',
        encoding="utf-8",
    )
    manager = SessionManager(tmp_path)
    stale_shared_tmp = manager.sessions_dir / ".webui_session_index.json.tmp"
    stale_bytes = b"pre-existing shared temp\x00\xff"
    stale_shared_tmp.write_bytes(stale_bytes)

    row, = list_webui_sessions(manager)

    assert row["key"] == key
    assert row["preview"] == "hello"
    cache = json.loads((manager.sessions_dir / ".webui_session_index.json").read_text(encoding="utf-8"))
    cached_row, = cache["sessions"]
    assert cached_row["key"] == key
    assert cached_row["preview"] == "hello"
    assert stale_shared_tmp.read_bytes() == stale_bytes
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
    assert manager.read_session_snapshot(key) is None
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

    rows = list_webui_sessions(manager)

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


def test_webui_session_list_fallback_time_when_missing(tmp_path: Path) -> None:
    legacy = tmp_path / "sessions"
    legacy.mkdir()
    path = legacy / "websocket_missing-time.jsonl"
    path.write_text(
        '{"_type": "metadata", "key": "websocket:missing-time"}\n'
        '{"_type": "message", "role": "user", "content": "hello"}\n',
        encoding="utf-8",
    )
    manager = SessionManager(tmp_path)

    rows = list_webui_sessions(manager)
    assert len(rows) == 1
    assert rows[0]["key"] == "websocket:missing-time"
    assert rows[0]["created_at"] is not None
    assert rows[0]["updated_at"] is not None
    datetime.fromisoformat(rows[0]["created_at"])
    datetime.fromisoformat(rows[0]["updated_at"])


def test_session_manager_list_sessions_fallback_time_when_missing(tmp_path: Path) -> None:
    legacy = tmp_path / "sessions"
    legacy.mkdir()
    path = legacy / "websocket_missing-time2.jsonl"
    path.write_text(
        '{"_type": "metadata", "key": "websocket:missing-time2"}\n'
        '{"_type": "message", "role": "user", "content": "hello"}\n',
        encoding="utf-8",
    )
    manager = SessionManager(tmp_path)

    sessions = manager.list_sessions()
    assert len(sessions) == 1
    assert sessions[0]["key"] == "websocket:missing-time2"
    assert sessions[0]["created_at"] is not None
    assert sessions[0]["updated_at"] is not None
    datetime.fromisoformat(sessions[0]["created_at"])
    datetime.fromisoformat(sessions[0]["updated_at"])
