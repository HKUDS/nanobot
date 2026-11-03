import asyncio
import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

import nanobot.webui.sidebar_state as sidebar_state
from nanobot.session.manager import Session, SessionManager
from nanobot.webui.sidebar_state import (
    WebUISidebarState,
    default_webui_sidebar_state,
    read_webui_sidebar_state,
    webui_sidebar_state_path,
    write_webui_sidebar_state,
)


def test_sidebar_state_defaults_when_file_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)

    state = read_webui_sidebar_state()

    assert state == default_webui_sidebar_state()
    assert webui_sidebar_state_path() == tmp_path / "webui" / "sidebar-state.json"


def test_sidebar_state_normalizes_partial_payload(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    path = webui_sidebar_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "pinned_keys": ["websocket:a", "websocket:a", "", 123],
                "archived_keys": ["websocket:b"],
                "session_order": ["websocket:b", "websocket:a", "websocket:b"],
                "title_overrides": {"websocket:a": "  Release notes  ", "bad": ""},
                "project_name_overrides": {"/repo": "  Core  ", "bad": ""},
                "tags_by_key": {"websocket:a": ["work", "work", ""]},
                "collapsed_groups": {"Earlier": 1},
                "workbench": {
                    "version": 1,
                    "tabs": {
                        "tab:websocket:a": {
                            "explicit": True,
                            "title": "  Research  ",
                            "paneKeys": ["websocket:a", "websocket:b", "websocket:a"],
                            "layoutPaneKeys": ["websocket:b", "missing", "websocket:a"],
                            "layout": "invalid-layout",
                            "splitRatios": [0.4, 2, "bad", float("nan")],
                        },
                        "tab:websocket:b": {
                            "paneKeys": ["websocket:b", "websocket:c"],
                            "layout": "bsp",
                        },
                    },
                },
                "view": {
                    "density": "tiny",
                    "show_archived": True,
                    "sort": "nope",
                    "show_previews": True,
                    "show_timestamps": True,
                },
            }
        ),
        encoding="utf-8",
    )

    state = read_webui_sidebar_state()

    assert state["schema_version"] == 1
    assert state["pinned_keys"] == ["websocket:a"]
    assert "archived_keys" not in state
    assert state["session_order"] == ["websocket:b", "websocket:a"]
    assert state["title_overrides"] == {"websocket:a": "Release notes"}
    assert state["project_name_overrides"] == {"/repo": "Core"}
    assert state["tags_by_key"] == {"websocket:a": ["work"]}
    assert state["collapsed_groups"] == {"Earlier": True}
    assert state["workbench"] == {
        "version": 1,
        "tabs": {
            "tab:websocket:a": {
                "explicit": True,
                "title": "Research",
                "paneKeys": ["websocket:a", "websocket:b"],
                "layoutPaneKeys": ["websocket:b", "websocket:a"],
                "layout": "columns",
                "splitRatios": [0.4, 0.95],
            },
        },
    }
    assert state["view"] == {
        "density": "comfortable",
        "show_archived": True,
        "sort": "updated_desc",
    }


def test_sidebar_state_write_is_scoped_to_config_data_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)

    state = write_webui_sidebar_state(
        {
            "pinned_keys": ["websocket:a"],
            "archived_keys": ["websocket:b"],
            "session_order": ["websocket:b", "websocket:a"],
            "title_overrides": {"websocket:a": "Release"},
            "project_name_overrides": {"/repo": "Core"},
            "view": {"density": "compact", "sort": "manual"},
        }
    )

    assert state["pinned_keys"] == ["websocket:a"]
    assert "archived_keys" not in state
    assert state["session_order"] == ["websocket:b", "websocket:a"]
    assert state["title_overrides"] == {"websocket:a": "Release"}
    assert state["project_name_overrides"] == {"/repo": "Core"}
    assert state["view"]["density"] == "compact"
    assert state["view"]["sort"] == "manual"
    assert webui_sidebar_state_path().is_file()
    assert read_webui_sidebar_state() == state


def test_sidebar_state_persists_only_visible_workbench_groups(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    tabs = {
        f"tab:websocket:{index}": {
            "explicit": False,
            "paneKeys": [f"websocket:{index}"],
            "layoutPaneKeys": [f"websocket:{index}"],
            "layout": "columns",
            "splitRatios": [],
        }
        for index in range(2_000)
    }

    state = write_webui_sidebar_state({"workbench": {"version": 1, "tabs": tabs}})

    assert state["workbench"] == {"version": 1, "tabs": {}}
    assert webui_sidebar_state_path().stat().st_size < 2_048


def test_sidebar_state_requires_supported_workbench_version(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)

    state = write_webui_sidebar_state(
        {
            "workbench": {
                "version": 2,
                "tabs": {
                    "tab:websocket:a": {
                        "explicit": True,
                        "paneKeys": ["websocket:a"],
                    }
                },
            }
        }
    )

    assert state["workbench"] == {"version": 1, "tabs": {}}


def test_sidebar_state_serializes_concurrent_writes(monkeypatch) -> None:
    counter_lock = threading.Lock()
    active_writes = 0
    peak_writes = 0

    def fake_write(raw: dict[str, object]) -> dict[str, object]:
        nonlocal active_writes, peak_writes
        with counter_lock:
            active_writes += 1
            peak_writes = max(peak_writes, active_writes)
        time.sleep(0.01)
        with counter_lock:
            active_writes -= 1
        return raw

    monkeypatch.setattr(sidebar_state, "_write_webui_sidebar_state", fake_write)
    payloads = [{"write": index} for index in range(12)]

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(sidebar_state.write_webui_sidebar_state, payloads))

    assert results == payloads
    assert peak_writes == 1


async def test_sidebar_archive_migration_preserves_wire_shape_and_restored_state(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    path = webui_sidebar_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "archived_keys": ["websocket:old", "websocket:empty", "websocket:draft"],
        "pinned_keys": ["websocket:pinned"],
        "collapsed_groups": {"archived:workspace:chats": False},
    }), encoding="utf-8")
    manager = SessionManager(tmp_path)
    manager.save(Session(key="websocket:old", messages=[{"role": "user", "content": "saved"}]))
    await manager.state.fork("websocket:old", "websocket:empty", 0)
    manager.get_or_create("websocket:draft")
    sidebar = WebUISidebarState(manager.state)
    try:
        loaded = await sidebar.read()
        assert loaded["archived_keys"] == ["websocket:empty", "websocket:old"]
        assert loaded["pinned_keys"] == ["websocket:pinned"]
        assert loaded["collapsed_groups"] == {"archived:workspace:chats": False}
        assert "archived_keys" not in json.loads(path.read_text(encoding="utf-8"))
        loaded["archived_keys"].remove("websocket:old")
        saved = await sidebar.write(loaded)
        assert saved["archived_keys"] == ["websocket:empty"]
        assert await manager.state.archived_keys() == ["websocket:empty"]
        assert {session["key"] for session in manager.list_sessions()} == {"websocket:old", "websocket:empty"}
        assert manager.read_session_snapshot("websocket:draft") is None
    finally:
        await manager.state.aclose()

    reopened = SessionManager(tmp_path)
    sidebar = WebUISidebarState(reopened.state)
    try:
        restored = await sidebar.read()
        assert restored["archived_keys"] == ["websocket:empty"]
        assert restored["pinned_keys"] == ["websocket:pinned"]
        changed_preferences = await sidebar.write({"view": {"density": "compact"}})
        assert changed_preferences["archived_keys"] == ["websocket:empty"]
        assert changed_preferences["view"]["density"] == "compact"
        assert "archived_keys" not in json.loads(path.read_text(encoding="utf-8"))
    finally:
        await reopened.state.aclose()


async def test_archive_import_failure_keeps_json_source_for_retry(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    path = webui_sidebar_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    source = json.dumps({"archived_keys": ["websocket:first", "websocket:fail"]})
    path.write_text(source, encoding="utf-8")
    manager = SessionManager(tmp_path)
    for key in ("websocket:first", "websocket:fail"):
        manager.save(Session(key=key))
    with sqlite3.connect(manager._store.path) as db:
        db.execute("""CREATE TRIGGER fail_archive BEFORE INSERT ON session_archives
                      WHEN NEW.key='websocket:fail'
                      BEGIN SELECT RAISE(ABORT, 'archive failed'); END""")
    try:
        with pytest.raises(sqlite3.IntegrityError, match="archive failed"):
            await WebUISidebarState(manager.state).read()
        assert path.read_text(encoding="utf-8") == source
        assert await manager.state.archives_imported() is False
        assert await manager.state.archived_keys() == []
        with sqlite3.connect(manager._store.path) as db:
            assert db.execute("SELECT key FROM session_archives").fetchall() == []
            db.execute("DROP TRIGGER fail_archive")
        assert (await WebUISidebarState(manager.state).read())["archived_keys"] == ["websocket:fail", "websocket:first"]
    finally:
        await manager.state.aclose()


async def test_sidebar_reads_and_preferences_do_not_wait_for_unrelated_session_write(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    manager = SessionManager(tmp_path)
    sidebar = WebUISidebarState(manager.state)
    await manager.state.import_messages("websocket:busy", [{"role": "user", "content": "hello"}])
    await manager.state.import_messages("websocket:archived", [{"role": "user", "content": "saved"}])
    saved = await sidebar.write({"archived_keys": ["websocket:archived"]})
    held, release, entered = threading.Event(), threading.Event(), threading.Event()

    def hold_writer():
        with sqlite3.connect(manager._store.path) as db:
            db.execute("BEGIN IMMEDIATE")
            held.set()
            assert release.wait(10)

    original = manager._store.run_write

    def observe_write(operation):
        entered.set()
        return original(operation)

    holder = asyncio.create_task(asyncio.to_thread(hold_writer))
    writer = None
    try:
        assert await asyncio.to_thread(held.wait, 2)
        monkeypatch.setattr(manager._store, "run_write", observe_write)
        writer = asyncio.create_task(manager.state.update_metadata("websocket:busy", {"title": "Updated"}))
        assert await asyncio.to_thread(entered.wait, 2)
        loaded = await asyncio.wait_for(sidebar.read(), 2)
        assert loaded["archived_keys"] == ["websocket:archived"]
        changed = await asyncio.wait_for(sidebar.write({**saved, "view": {"density": "compact"}}), 2)
        assert changed["archived_keys"] == ["websocket:archived"]
        assert changed["view"]["density"] == "compact"
        assert not writer.done()
    finally:
        release.set()
        await holder
        if writer is not None:
            await writer
        await manager.state.aclose()


async def test_archive_only_update_keeps_preferences_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    manager = SessionManager(tmp_path)
    manager.save(Session(key="websocket:empty"))
    sidebar = WebUISidebarState(manager.state)
    try:
        saved = await sidebar.write({"view": {"density": "compact"}, "archived_keys": []})
        path = webui_sidebar_state_path()
        before = path.read_bytes()
        before_mtime = path.stat().st_mtime_ns
        archived = await sidebar.write({**saved, "archived_keys": ["websocket:empty"]})
        assert archived["archived_keys"] == ["websocket:empty"]
        assert await manager.state.archived_keys() == ["websocket:empty"]
        assert path.read_bytes() == before
        assert path.stat().st_mtime_ns == before_mtime
        restored = await sidebar.write({**saved, "archived_keys": []})
        assert restored["archived_keys"] == []
        assert path.stat().st_mtime_ns == before_mtime
        # A comparison failure must not prevent the existing repair-on-write path.
        for damaged in ("{broken", json.dumps({"view": {"density": []}})):
            path.write_text(damaged, encoding="utf-8")
            repaired = await sidebar.write(saved)
            assert json.loads(path.read_text(encoding="utf-8")) == {key: value for key, value in repaired.items() if key != "archived_keys"}
    finally:
        await manager.state.aclose()


async def test_sidebar_readers_overlap_without_overtaking_queued_write(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    manager = SessionManager(tmp_path)
    manager.save(Session(key="websocket:new"))
    sidebar = WebUISidebarState(manager.state)
    saved = await sidebar.write({"view": {"density": "compact"}, "archived_keys": []})
    entered, release = threading.Event(), threading.Event()
    counter_lock = threading.Lock()
    count = 0
    original = sidebar_state.read_webui_sidebar_state

    def paused_read():
        nonlocal count
        with counter_lock:
            count += 1
            pause = count <= 2
            if count == 2:
                entered.set()
        if pause:
            assert release.wait(10)
        return original()

    monkeypatch.setattr(sidebar_state, "read_webui_sidebar_state", paused_read)
    readers = [asyncio.create_task(sidebar.read()) for _ in range(2)]
    pending = []
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        writer = asyncio.create_task(sidebar.write({**saved, "view": {"density": "comfortable"}, "archived_keys": ["websocket:new"]}))
        later_read = asyncio.create_task(sidebar.read())
        pending.extend([writer, later_read])
        release.set()
        before = await asyncio.gather(*readers)
        assert all(snapshot["archived_keys"] == [] and snapshot["view"]["density"] == "compact" for snapshot in before)
        written, after = await asyncio.gather(writer, later_read)
        assert written["archived_keys"] == after["archived_keys"] == ["websocket:new"]
        assert written["view"]["density"] == after["view"]["density"] == "comfortable"
    finally:
        release.set()
        await asyncio.gather(*readers, *pending, return_exceptions=True)
        await manager.state.aclose()


async def test_failed_archive_read_drains_preference_write_before_releasing_admission(tmp_path, monkeypatch):
    from nanobot.session.state import SessionOperationQueueFullError

    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    manager = SessionManager(tmp_path)
    sidebar = WebUISidebarState(manager.state)
    saved = await sidebar.write({"view": {"density": "comfortable"}, "archived_keys": []})
    entered, release = threading.Event(), threading.Event()
    original = sidebar_state.write_webui_sidebar_preferences

    def paused_write(raw):
        entered.set()
        assert release.wait(10)
        return original(raw)

    async def reject_read():
        raise SessionOperationQueueFullError("session operation queue is full")

    monkeypatch.setattr(sidebar_state, "write_webui_sidebar_preferences", paused_write)
    monkeypatch.setattr(manager.state, "archived_keys", reject_read)
    write = asyncio.create_task(sidebar.write({**saved, "view": {"density": "compact"}}))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        done, _ = await asyncio.wait({write}, timeout=0.05)
        assert not done, "a failed archive read must not leave a preference write outside admission"
    finally:
        release.set()
        with pytest.raises(SessionOperationQueueFullError):
            await write
        await manager.state.aclose()
    assert json.loads(webui_sidebar_state_path().read_text(encoding="utf-8"))["view"]["density"] == "compact"
