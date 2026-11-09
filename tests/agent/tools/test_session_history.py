from __future__ import annotations

import asyncio
import gc
import json
import sqlite3
import threading
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from datetime import datetime

import pytest

from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.tools.sessions import ReadSessionTool, SearchSessionsTool
from nanobot.runtime_context import RuntimeContextBlock, append_runtime_context
from nanobot.session.automation_spec import AUTOMATION_HISTORY_META
from nanobot.session.history import SessionHistoryReader
from nanobot.session.manager import SessionManager
from nanobot.session.types import SessionType


@pytest.mark.asyncio
@pytest.mark.parametrize("compacted", [False, True])
@pytest.mark.parametrize("tool_name", ["search", "read"])
async def test_session_tools_find_old_matches_in_full_session(
    tmp_path, compacted, tool_name,
):
    manager = SessionManager(tmp_path)
    key = "sdk:history"
    session = manager.get_or_create(key)
    session.metadata.update({"title": "Project notes", "title_user_edited": True})
    for index in range(180):
        text = f"launch decision {index}" if index < 10 else f"unrelated update {index}"
        session.add_message("user", text)
        session.add_message("assistant", f"acknowledged {index}")
    if compacted:
        session.commit_summary_checkpoint("Project updates are complete.")
        assert session.get_history() == []
    manager.save(session)
    manager = SessionManager(tmp_path)

    try:
        with request_context(RequestContext(
            channel="sdk", chat_id="current", session_key="sdk:current",
        )):
            if tool_name == "search":
                output = json.loads(await SearchSessionsTool(manager).execute(query="launch decision"))
                assert [item["session_key"] for item in output["results"]] == [key]
                matches = output["results"][0]["excerpts"]
                expected = range(8, 10)
            else:
                output = json.loads(await ReadSessionTool(manager).execute(
                    session_key=key, query="launch decision",
                ))
                matches = output["messages"]
                expected = range(2, 10)
                latest = json.loads(await ReadSessionTool(manager).execute(session_key=key))
                assert len(latest["messages"]) == 8
                assert [item["message_index"] for item in latest["messages"]] == list(range(352, 360))
                assert latest["messages"][-1]["content"] == "acknowledged 179"
    finally:
        await manager.state.aclose()

    assert [item["content"] for item in matches] == [f"launch decision {i}" for i in expected]
    assert [item["message_index"] for item in matches] == [i * 2 for i in expected]


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["canonical", "transcript", "mixed"])
async def test_session_tools_use_canonical_records_after_restart(history, tmp_path, monkeypatch, state):
    webui_dir = tmp_path / "webui"
    monkeypatch.setattr("nanobot.webui.history.get_webui_dir", lambda: webui_dir)
    manager = history.sessions
    key = "websocket:history"
    if state != "transcript":
        session = manager.get_or_create(key)
        session.metadata.update({"title": "Project notes", "title_user_edited": True})
        session.add_message("user", "canonical needle")
        manager.save(session)
    if state != "canonical":
        history.append(key, {
            "event": "user", "chat_id": "history", "text": "display-only needle",
        })
        history.append(key, {"event": "turn_end", "chat_id": "history"})

    def durable_files():
        return {
            path: path.read_bytes()
            for root in (manager.sessions_dir, webui_dir)
            for path in root.rglob("*.jsonl")
        }

    original = durable_files()
    for _ in range(2):
        manager = history.sessions
        with request_context(RequestContext(
            channel="websocket", chat_id="current", session_key="websocket:current",
        )):
            search = json.loads(await SearchSessionsTool(manager).execute(query="needle"))
            read = await ReadSessionTool(manager).execute(session_key=key, query="needle")
            display_search = json.loads(await SearchSessionsTool(manager).execute(query="display-only"))
        if state == "transcript":
            assert search["results"] == []
            assert json.loads(read)["messages"] == []
        else:
            assert [row["session_key"] for row in search["results"]] == [key]
            assert search["results"][0]["excerpts"][0]["content"] == "canonical needle"
            assert [item["content"] for item in json.loads(read)["messages"]] == ["canonical needle"]
        assert display_search["results"] == []
        assert durable_files() == original


@pytest.mark.asyncio
async def test_session_tools_stream_visible_archived_history_with_casefold_and_original_indices(tmp_path):
    manager = SessionManager(tmp_path)
    key = "sdk:archived"
    session = manager.get_or_create(key)
    session.updated_at = datetime(2025, 1, 2, 3, 4, 5)
    session.messages = [
        {"role": "user", "content": "Straße 0"},
        {"role": "assistant", "content": "STRASSE 1"},
        {"role": "tool", "content": "Straße tool"},
        {"role": "user", "content": "Straße hidden", "_hidden_history": True},
        {"role": "user", "content": "Straße command", "_command": True},
        {"role": "assistant", "content": [
            {"type": "text", "text": "Straße 2"},
            {"type": "image", "url": "unused"},
            {"type": "text", "text": "second line"},
        ], "timestamp": 7},
    ]
    session.messages.extend({"role": "user", "content": f"Straße {i}"} for i in range(3, 12))
    session.commit_summary_checkpoint("Archived earlier context")
    content, marker = append_runtime_context(
        [{"type": "text", "text": "Straße public"}],
        [RuntimeContextBlock(source="private", content="private-context-secret")],
    )
    session.messages.append({"role": "user", "content": content, "_runtime_context": marker})
    session.messages.extend(
        {"role": "assistant", "content": "Straße hidden tail", "_hidden_history": True}
        for _ in range(12)
    )
    session.messages.append({
        "role": "user", "content": "Straße automation-secret", AUTOMATION_HISTORY_META: {"kind": "trigger"},
    })
    manager.save(session)
    manager._store.set_archived_keys([key])

    with request_context(RequestContext(channel="sdk", chat_id="current", session_key="sdk:current")):
        read = json.loads(await ReadSessionTool(manager).execute(session_key=key, query="STRASSE"))
        blocks = json.loads(await ReadSessionTool(manager).execute(session_key=key, query="SECOND LINE"))
        search = json.loads(await SearchSessionsTool(manager).execute(query="STRASSE"))
        secret = json.loads(await SearchSessionsTool(manager).execute(query="private-context-secret"))
        automation = json.loads(await SearchSessionsTool(manager).execute(query="automation-secret"))
        empty = json.loads(await ReadSessionTool(manager).execute(session_key=key, query="not-present"))
    assert [item["message_index"] for item in read["messages"]] == [8, 9, 10, 11, 12, 13, 14, 16]
    assert read["messages"][-1]["content"] == "Straße public"
    assert read["updated_at"] == "2025-01-02T03:04:05"
    assert [(m["message_index"], m["content"], m["timestamp"]) for m in blocks["messages"]] == [
        (5, "Straße 2 second line", 7),
    ]
    assert [row["session_key"] for row in search["results"]] == [key]
    assert search["results"][0]["title"] == "Straße 11"
    assert [item["message_index"] for item in search["results"][0]["excerpts"]] == [14, 16]
    assert secret["results"] == []
    assert automation["results"] == []
    assert empty["messages"] == []
    reader = SessionHistoryReader(manager)
    assert reader.read(key, query="", limit=8, exclude_session_key=key) is None
    await manager.state.aclose()


def test_session_search_ranking_and_visibility_remain_snapshot_based(tmp_path):
    manager = SessionManager(tmp_path)
    manager.types.register(SessionType("custom-public", needs_handle=False, public_history=True))
    manager.types.register(SessionType("custom-private", needs_handle=False, public_history=False))
    examples = [
        ("sdk:body", "notes", "custom-public", "Straße in body", 2025),
        ("sdk:substring", "x Straße", "conversation", "unused", 2023),
        ("sdk:prefix", "Straße plan", "conversation", "unused", 2022),
        ("sdk:exact-old", "Straße", "conversation", "unused", 2020),
        ("sdk:exact-new", "STRASSE", "conversation", "unused", 2021),
        ("sdk:private", "Straße", "custom-private", "Straße", 2026),
        ("sdk:unknown", "Straße", "unregistered", "Straße", 2026),
    ]
    for key, title, kind, content, year in examples:
        session = manager.get_or_create(key)
        session.metadata.update({"title": title, "title_user_edited": True, "session_type": kind})
        session.messages = [{"role": "user", "content": content}]
        session.updated_at = datetime(year, 1, 1)
        manager.save(session)

    reader = SessionHistoryReader(manager)
    assert [match["session_key"] for match in reader.search("STRASSE", limit=3)] == [
        "sdk:exact-new", "sdk:exact-old", "sdk:prefix",
    ]
    matches = reader.search("STRASSE", limit=5, exclude_session_key="sdk:exact-old")
    assert [match["session_key"] for match in matches] == [
        "sdk:exact-new", "sdk:prefix", "sdk:substring", "sdk:body",
    ]
    assert [match["title"] for match in matches] == ["STRASSE", "Straße plan", "x Straße", "notes"]
    assert matches[-1]["messages"][0]["content"] == "Straße in body"
    assert matches[-1]["updated_at"] == "2025-01-01T00:00:00"
    assert reader.read("sdk:private", query="", limit=8) is None
    assert reader.read("sdk:unknown", query="", limit=8) is None
    assert len(reader.search("", limit=2)) == 2
    assert reader.search("unmatched", limit=5) == []


def test_search_keeps_visibility_title_and_messages_consistent(tmp_path, monkeypatch):
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("sdk:history")
    session.metadata["title"] = "Notes"
    session.updated_at = datetime(2024, 1, 1)
    session.messages = [{"role": "user", "content": "old needle"}]
    manager.save(session)
    writer = SessionManager(tmp_path)
    replacement = writer.get_or_create(session.key)
    replacement.metadata.update({"title": "new title", "session_type": "private"})
    replacement.updated_at = datetime(2026, 1, 1)
    replacement.messages = [{"role": "user", "content": "new needle"}]
    original_list = manager.list_sessions

    def list_then_commit():
        rows = original_list()
        writer.save(replacement)
        return rows

    monkeypatch.setattr(manager, "list_sessions", list_then_commit)
    reader = SessionHistoryReader(manager)
    matches = reader.search("needle", limit=5)
    # A search may omit the now-private session rather than pinning one global
    # snapshot; if it returns a match, it must not combine the two versions.
    assert [(match["title"], match["updated_at"], match["messages"][0]["content"]) for match in matches] in (
        [], [("Notes", "2024-01-01T00:00:00", "old needle")],
    )
    assert reader.read(session.key, query="", limit=8) is None


def test_read_uses_one_snapshot_for_header_and_messages(tmp_path, monkeypatch):
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("sdk:history")
    session.metadata["title"] = "old title"
    session.messages = [{"role": "user", "content": "old message"}]
    manager.save(session)
    writer = SessionManager(tmp_path)
    replacement = writer.get_or_create(session.key)
    replacement.metadata["title"] = "new title"
    replacement.messages = [{"role": "user", "content": "new message"}]
    original_public_history = manager.types.public_history

    def commit_after_header(metadata):
        writer.save(replacement)
        return original_public_history(metadata)

    monkeypatch.setattr(manager.types, "public_history", commit_after_header)
    match = SessionHistoryReader(manager).read(session.key, query="", limit=8)
    assert match["title"] == "old title"
    assert [message["content"] for message in match["messages"]] == ["old message"]


def test_session_read_decodes_only_as_far_as_needed(tmp_path, monkeypatch):
    from nanobot.session import sqlite_store

    manager = SessionManager(tmp_path)
    session = manager.get_or_create("sdk:history")
    session.messages = [
        {"role": "user", "content": f"message {i}", "_marker": "history-row"}
        for i in range(100)
    ]
    session.messages.append({
        "role": "user", "content": "hidden", "_marker": "history-row", "_hidden_history": True,
    })
    manager.save(session)
    original_object = sqlite_store._object
    decoded_rows = []

    def count_rows(raw):
        result = original_object(raw)
        if result.get("_marker") == "history-row":
            decoded_rows.append(result)
        return result

    monkeypatch.setattr(sqlite_store, "_object", count_rows)
    reader = SessionHistoryReader(manager)
    result = reader.read(session.key, query="", limit=8)
    assert [message["message_index"] for message in result["messages"]] == list(range(92, 100))
    assert len(decoded_rows) == 9

    decoded_rows.clear()
    result = reader.read(session.key, query="not-present", limit=8)
    assert result["messages"] == []
    assert len(decoded_rows) == 101


@pytest.mark.asyncio
async def test_session_tool_memory_is_bounded_for_long_persisted_history(tmp_path):
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("sdk:history")
    session.metadata["title"] = "notes"
    session.messages = [
        {"role": "user", "content": f"message {i} " + "x" * 2048}
        for i in range(3000)
    ]
    manager.save(session)
    del session
    gc.collect()

    for tool, kwargs in (
        (ReadSessionTool(manager), {"session_key": "sdk:history"}),
        (SearchSessionsTool(manager), {"query": "not-present"}),
    ):
        was_tracing = tracemalloc.is_tracing()
        if not was_tracing:
            tracemalloc.start()
        before, _ = tracemalloc.get_traced_memory()
        tracemalloc.reset_peak()
        try:
            result = json.loads(await tool.execute(**kwargs))
            _, peak = tracemalloc.get_traced_memory()
        finally:
            if not was_tracing:
                tracemalloc.stop()
        assert peak - before < 2 * 1024 * 1024
        if "messages" in result:
            assert [item["message_index"] for item in result["messages"]] == list(range(2992, 3000))
        else:
            assert result["results"] == []
    if manager._state is not None:
        await manager.state.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", ["read", "search"])
async def test_queued_history_tool_cancels_without_starting_a_transaction(tmp_path, monkeypatch, tool_name):
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("sdk:history")
    session.messages = [{"role": "user", "content": "needle"}]
    manager.save(session)
    entered, release, queued, transaction = (threading.Event() for _ in range(4))

    class SignallingExecutor(ThreadPoolExecutor):
        def __init__(self):
            super().__init__(max_workers=1)
            self.submissions = 0

        def submit(self, fn, /, *args, **kwargs):
            future = super().submit(fn, *args, **kwargs)
            self.submissions += 1
            if self.submissions == 2:
                queued.set()
            return future

    def block_executor():
        entered.set()
        assert release.wait(5)

    for method in ("read_batch", "read_consistently"):
        original = getattr(manager, method)

        def tracked(*args, _original=original, **kwargs):
            transaction.set()
            return _original(*args, **kwargs)

        monkeypatch.setattr(manager, method, tracked)

    loop = asyncio.get_running_loop()
    previous_executor = loop._default_executor
    executor = SignallingExecutor()
    loop.set_default_executor(executor)
    blocker = loop.run_in_executor(None, block_executor)
    tool = ReadSessionTool(manager) if tool_name == "read" else SearchSessionsTool(manager)
    kwargs = {"session_key": session.key, "query": "needle"} if tool_name == "read" else {"query": "needle"}

    async def wait_for_event(event):
        while not event.is_set():
            await asyncio.sleep(0.001)

    task = None
    try:
        await asyncio.wait_for(wait_for_event(entered), timeout=5)
        task = asyncio.create_task(tool.execute(**kwargs))
        await asyncio.wait_for(wait_for_event(queued), timeout=5)
        task.cancel()
        completed, _ = await asyncio.wait({task}, timeout=0.5)
        assert task in completed, "a queued history worker blocked cancellation"
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not transaction.is_set()
    finally:
        release.set()
        await blocker
        # A fence ensures any previously queued worker has actually been dequeued.
        await loop.run_in_executor(None, lambda: None)
        if task is not None:
            with suppress(asyncio.CancelledError):
                await task
        loop._default_executor = previous_executor
        executor.shutdown(wait=True)
        if manager._state is not None:
            await manager.state.aclose()
    assert not transaction.is_set(), "cancelled queued work entered the database after return"


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", ["read", "search", "search-refill"])
async def test_cancelled_history_scan_exits_and_releases_wal_snapshot(tmp_path, monkeypatch, tool_name):
    from nanobot.session import sqlite_store

    manager = SessionManager(tmp_path)
    key = "sdk:long-history"
    session = manager.get_or_create(key)
    session.messages = [
        {"role": "user", "content": f"ordinary {i}", "_marker": "long-history"}
        for i in range(3000)
    ]
    manager.save(session)
    if tool_name == "search-refill":
        for i in range(5):
            candidate = manager.get_or_create(f"sdk:candidate-{i}")
            candidate.metadata.update({"title": "not-present", "title_user_edited": True})
            manager.save(candidate)
    db = sqlite3.connect(manager._store.path, isolation_level=None, timeout=0.2)
    db.execute("PRAGMA wal_autocheckpoint=0")
    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    original_object = sqlite_store._object

    def slow_rows(raw):
        result = original_object(raw)
        if result.get("_marker") == "long-history":
            if not entered.is_set():
                entered.set()
                assert release.wait(5)
            time.sleep(0.0005)
        return result

    monkeypatch.setattr(sqlite_store, "_object", slow_rows)
    tool = ReadSessionTool(manager) if tool_name == "read" else SearchSessionsTool(manager)
    if tool_name == "search-refill":
        lookup = tool._handles.alist_all_by_key

        async def reset_before_lookup():
            for i in range(5):
                candidate_key = f"sdk:candidate-{i}"
                await manager.state.reset(candidate_key)
                await manager.state.update_metadata(candidate_key, {"title": "other"})
            return await lookup()

        monkeypatch.setattr(tool._handles, "alist_all_by_key", reset_before_lookup)
    method = {"read": "read", "search": "_start_search", "search-refill": "_complete_search"}[tool_name]
    original = getattr(tool._access, method)

    def tracked(*args, **kwargs):
        try:
            return original(*args, **kwargs)
        finally:
            done.set()

    monkeypatch.setattr(tool._access, method, tracked)
    kwargs = {"session_key": key, "query": "not-present"} if tool_name == "read" else {"query": "not-present"}
    task = asyncio.create_task(tool.execute(**kwargs))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        db.execute("UPDATE sessions SET title='while scanning' WHERE key=?", (key,))
        _, frames, checkpointed = db.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
        assert frames > checkpointed  # The paused reader really holds the older snapshot.
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done(), "cancellation returned while the reader still held a snapshot"
        task.cancel()  # A second stop must not detach the already-started reader.
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await asyncio.to_thread(done.wait, 0.5), "cancelled worker continued scanning"
        db.execute("UPDATE sessions SET title='after cancellation' WHERE key=?", (key,))
        assert db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone() == (0, 0, 0)
    finally:
        release.set()
        await asyncio.to_thread(done.wait, 5)
        db.close()
        if manager._state is not None:
            await manager.state.aclose()


@pytest.mark.asyncio
async def test_cancelled_running_reader_preserves_unexpected_worker_failure(tmp_path, monkeypatch):
    from nanobot.session import sqlite_store

    manager = SessionManager(tmp_path)
    session = manager.get_or_create("sdk:history")
    session.messages = [{"role": "user", "content": "needle", "_marker": "failing-row"}]
    manager.save(session)
    entered, release = threading.Event(), threading.Event()
    original = sqlite_store._object

    def fail_row(raw):
        record = original(raw)
        if record.get("_marker") == "failing-row":
            entered.set()
            assert release.wait(5)
            raise ValueError("failed to decode history")
        return record

    monkeypatch.setattr(sqlite_store, "_object", fail_row)
    task = asyncio.create_task(ReadSessionTool(manager).execute(session_key=session.key))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError) as cancelled:
            await task
        assert isinstance(cancelled.value.__cause__, ValueError)
        assert str(cancelled.value.__cause__) == "failed to decode history"
    finally:
        release.set()
        if not task.done():
            with suppress(asyncio.CancelledError):
                await task
        if manager._state is not None:
            await manager.state.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["reset", "recreate"])
async def test_search_during_replacement_never_mixes_header_and_body(tmp_path, monkeypatch, change):
    manager = SessionManager(tmp_path)
    writer = SessionManager(tmp_path)
    key = "sdk:history"
    session = manager.get_or_create(key)
    session.metadata["title"] = "old title"
    session.messages = [{"role": "user", "content": "needle old content"}]
    manager.save(session)
    captured, release = threading.Event(), threading.Event()
    original_list = manager.list_sessions

    def pause_after_list():
        rows = original_list()
        captured.set()
        assert release.wait(5)
        return rows

    monkeypatch.setattr(manager, "list_sessions", pause_after_list)
    task = asyncio.create_task(SearchSessionsTool(manager).execute(query="needle"))
    try:
        assert await asyncio.to_thread(captured.wait, 5)
        if change == "reset":
            await writer.state.reset(key)
        else:
            assert await writer.state.delete(key)
        await writer.state.import_messages(
            key, [{"role": "user", "content": "needle new content"}], metadata={"title": "new title"},
        )
        release.set()
        results = json.loads(await task)["results"]
        if results:
            assert len(results) == 1
            assert results[0]["title"] == "new title"
            assert results[0]["excerpts"][0]["content"] == "needle new content"
            assert results[0]["handle"] is not None
    finally:
        release.set()
        await writer.state.aclose()
        if manager._state is not None:
            await manager.state.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("by_handle", [False, True])
async def test_read_during_reset_does_not_return_old_history(tmp_path, monkeypatch, by_handle):
    manager = SessionManager(tmp_path)
    writer = SessionManager(tmp_path)
    key = "sdk:history"
    session = manager.get_or_create(key)
    session.messages = [{"role": "user", "content": "old content"}]
    manager.save(session)
    tool = ReadSessionTool(manager)
    handle = await tool._handles.ahandle_for_session(key)
    captured, release = threading.Event(), threading.Event()
    public_history = manager.types.public_history

    def pause_after_header(metadata):
        if not captured.is_set():
            captured.set()
            assert release.wait(5)
        return public_history(metadata)

    monkeypatch.setattr(manager.types, "public_history", pause_after_header)
    reference = f"@{handle.name}" if by_handle else key
    task = asyncio.create_task(tool.execute(session_key=reference))
    try:
        assert await asyncio.to_thread(captured.wait, 5)
        await writer.state.reset(key)
        await writer.state.import_messages(key, [{"role": "user", "content": "new content"}])
        release.set()
        result = await task
        assert result.is_error and "session not found" in str(result)
    finally:
        release.set()
        await writer.state.aclose()
        await manager.state.aclose()


@pytest.mark.asyncio
async def test_search_does_not_hold_a_global_snapshot_between_histories(tmp_path, monkeypatch):
    manager = SessionManager(tmp_path)
    for i in range(2):
        session = manager.get_or_create(f"sdk:{i}")
        session.messages = [{"role": "user", "content": "ordinary"}]
        session.updated_at = datetime(2025, 1, i + 1)
        manager.save(session)
    db = sqlite3.connect(manager._store.path, isolation_level=None, timeout=0.2)
    db.execute("PRAGMA wal_autocheckpoint=0")
    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    entered, release = threading.Event(), threading.Event()
    tool = SearchSessionsTool(manager)
    original_read = tool._access.read

    def pause_before_second(key, **kwargs):
        if key == "sdk:0":
            entered.set()
            assert release.wait(5)
        return original_read(key, **kwargs)

    monkeypatch.setattr(tool._access, "read", pause_before_second)
    task = asyncio.create_task(tool.execute(query="not-present"))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        db.execute("UPDATE sessions SET title='changed' WHERE key='sdk:1'")
        assert db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone() == (0, 0, 0)
        release.set()
        assert json.loads(await task)["results"] == []
    finally:
        release.set()
        db.close()
        if manager._state is not None:
            await manager.state.aclose()


def test_search_preserves_recency_order_when_a_title_changes_during_scan(tmp_path, monkeypatch):
    manager = SessionManager(tmp_path)
    newer = manager.get_or_create("sdk:newer")
    newer.metadata["title"] = "notes"
    newer.messages = [{"role": "user", "content": "needle in body"}]
    newer.updated_at = datetime(2025, 1, 1)
    manager.save(newer)
    older = manager.get_or_create("sdk:older")
    older.metadata["title"] = "needle old"
    older.updated_at = datetime(2020, 1, 1)
    manager.save(older)
    writer = SessionManager(tmp_path)
    changed = writer.get_or_create(newer.key)
    changed.metadata["title"] = "needle new"
    reader = SessionHistoryReader(manager)
    original_read = reader.read

    def change_before_read(key, **kwargs):
        if key == newer.key:
            writer.save(changed)
        return original_read(key, **kwargs)

    monkeypatch.setattr(reader, "read", change_before_read)
    assert [match["session_key"] for match in reader.search("needle", limit=5)] == [
        newer.key, older.key,
    ]
