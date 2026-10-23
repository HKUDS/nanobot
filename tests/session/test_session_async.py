"""Admission, ordering, and shutdown at the asynchronous session boundary."""

import asyncio
import sqlite3
import threading

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.session.manager import SessionManager
from nanobot.session.state import SessionOperationQueueFullError, SessionState


@pytest.mark.parametrize("channel", ["cli", "telegram", "system"])
async def test_non_websocket_followup_does_not_access_storage(tmp_path, monkeypatch, channel):
    manager = SessionManager(tmp_path)

    def unexpected_transaction(*args, **kwargs):
        pytest.fail("a non-recoverable follow-up must not access session storage")

    monkeypatch.setattr(manager._store, "transaction", unexpected_transaction)
    state = manager.state
    try:
        assert await state.queue_followup(
            f"{channel}:chat",
            InboundMessage(channel=channel, sender_id="u", chat_id="chat", content="follow-up"),
        ) is None
    finally:
        await state.aclose()


async def test_writes_run_in_submission_order(tmp_path):
    state = SessionManager(tmp_path).state
    await state.get("chat:a")
    await asyncio.gather(*(state.update_metadata("chat:a", {"title": str(i)}) for i in range(50)))
    assert (await state.get("chat:a")).metadata["title"] == "49"
    await state.aclose()


async def test_close_drains_accepted_operations(tmp_path, monkeypatch):
    manager = SessionManager(tmp_path)
    state = manager.state
    await state.get("chat:a")
    started, release = threading.Event(), threading.Event()
    original = manager._store.replace_metadata

    def blocked(key, metadata, **kwargs):
        started.set()
        release.wait(5)
        return original(key, metadata, **kwargs)

    monkeypatch.setattr(manager._store, "replace_metadata", blocked)
    task = asyncio.create_task(state.update_metadata("chat:a", {"title": "committed"}))
    assert await asyncio.to_thread(started.wait, 2)
    close = asyncio.create_task(state.aclose())
    await asyncio.sleep(0)
    assert not close.done()
    release.set()
    await asyncio.gather(task, close)
    assert manager.get_or_create("chat:a").metadata["title"] == "committed"
    with pytest.raises(RuntimeError, match="closed"):
        await state.update_metadata("chat:a", {"title": "late"})


async def test_full_owner_rejects_without_creating_waiters(tmp_path, monkeypatch):
    manager = SessionManager(tmp_path)
    state = SessionState(manager._store, capacity=1, workers=1)
    await state.get("chat:a")
    started, release = threading.Event(), threading.Event()
    original = manager._store.replace_metadata

    def blocked(key, metadata, **kwargs):
        started.set()
        release.wait(5)
        return original(key, metadata, **kwargs)

    monkeypatch.setattr(manager._store, "replace_metadata", blocked)
    accepted = asyncio.create_task(state.update_metadata("chat:a", {"title": "accepted"}))
    assert await asyncio.to_thread(started.wait, 2)

    with pytest.raises(SessionOperationQueueFullError, match="queue is full"):
        await state.update_metadata("chat:b", {"title": "rejected"})

    release.set()
    await accepted
    assert await state.read("chat:b") is None
    await state.aclose()


async def test_slow_session_does_not_block_unrelated_session(tmp_path, monkeypatch):
    manager = SessionManager(tmp_path)
    state = SessionState(manager._store, capacity=4, workers=2)
    await state.get("chat:a")
    await state.get("chat:b")
    await state.update_metadata("chat:b", {"title": "ready"})
    started, release = threading.Event(), threading.Event()
    original = manager._store.replace_metadata

    def blocked(key, metadata, **kwargs):
        if key == "chat:a":
            started.set()
            release.wait(5)
        return original(key, metadata, **kwargs)

    monkeypatch.setattr(manager._store, "replace_metadata", blocked)
    slow = asyncio.create_task(state.update_metadata("chat:a", {"title": "slow"}))
    assert await asyncio.to_thread(started.wait, 2)
    other = await asyncio.wait_for(state.read("chat:b"), timeout=0.25)
    assert other is not None and other.metadata["title"] == "ready"
    release.set()
    await slow
    await state.aclose()


async def test_close_timeout_does_not_cancel_internal_drain(tmp_path, monkeypatch):
    manager = SessionManager(tmp_path)
    state = manager.state
    await state.get("chat:a")
    started, release = threading.Event(), threading.Event()
    original = manager._store.replace_metadata

    def blocked(key, metadata, **kwargs):
        started.set()
        release.wait(5)
        return original(key, metadata, **kwargs)

    monkeypatch.setattr(manager._store, "replace_metadata", blocked)
    accepted = asyncio.create_task(state.update_metadata("chat:a", {"title": "committed"}))
    assert await asyncio.to_thread(started.wait, 2)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(state.aclose(), timeout=0.05)
    with pytest.raises(RuntimeError, match="closed"):
        await state.update_metadata("chat:b", {"title": "late"})
    release.set()
    await accepted
    await state.aclose()
    assert manager.get_or_create("chat:a").metadata["title"] == "committed"


async def test_global_barrier_orders_both_sides_of_admission(tmp_path):
    state = SessionManager(tmp_path).state
    started, release = threading.Event(), threading.Event()
    order = []

    def first():
        started.set()
        assert release.wait(5)
        order.append("first")

    first_task = asyncio.create_task(state._execute("chat:a", first))
    tasks = [first_task]
    try:
        assert await asyncio.to_thread(started.wait, 2)
        tasks.append(asyncio.create_task(state._execute(None, lambda: order.append("barrier"))))
        await asyncio.sleep(0)
        tasks.append(asyncio.create_task(state._execute("chat:b", lambda: order.append("later"))))
        await asyncio.sleep(0)
        assert state._admitted == 3
        assert order == []
        release.set()
        await asyncio.gather(*tasks)
        assert order == ["first", "barrier", "later"]
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await state.aclose()


async def test_fork_waits_for_target_and_blocks_later_target_read(tmp_path, monkeypatch):
    state = SessionManager(tmp_path).state
    await state.import_messages("chat:source", [{"role": "user", "content": "kept"}])
    target_started, target_release = threading.Event(), threading.Event()
    fork_started, fork_release = threading.Event(), threading.Event()
    original_load = state._load

    def paused_source(key, *, history=True):
        if key == "chat:source":
            fork_started.set()
            assert fork_release.wait(5)
        return original_load(key, history=history)

    def target_operation():
        target_started.set()
        assert target_release.wait(5)

    monkeypatch.setattr(state, "_load", paused_source)
    tasks = [asyncio.create_task(state._execute("chat:target", target_operation))]
    try:
        assert await asyncio.to_thread(target_started.wait, 2)
        fork = asyncio.create_task(state.fork("chat:source", "chat:target", 1))
        tasks.append(fork)
        await asyncio.sleep(0)
        read = asyncio.create_task(state.read("chat:target"))
        tasks.append(read)
        await asyncio.sleep(0)
        assert state._admitted == 3
        assert not fork_started.is_set()
        target_release.set()
        assert await asyncio.to_thread(fork_started.wait, 2)
        assert not read.done()
        fork_release.set()
        result = await fork
        snapshot = await read
        assert result is not None and snapshot is not None
        assert result.generation == snapshot.generation
        assert snapshot.messages[0]["content"] == "kept"
    finally:
        target_release.set()
        fork_release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await state.aclose()


async def test_failed_predecessor_does_not_poison_key_or_global_barrier(tmp_path):
    state = SessionManager(tmp_path).state
    order = []

    def fail():
        raise ValueError("injected")

    failed = asyncio.create_task(state._execute("chat:a", fail))
    same_key = asyncio.create_task(state._execute("chat:a", lambda: order.append("same")))
    barrier = asyncio.create_task(state._execute(None, lambda: order.append("barrier")))
    results = await asyncio.gather(failed, same_key, barrier, return_exceptions=True)
    assert isinstance(results[0], ValueError)
    assert results[1:] == [None, None]
    assert order == ["same", "barrier"]
    assert state._admitted == 0
    assert state._key_tails == {}
    assert state._global_tail is None
    await state.aclose()


async def test_cancel_before_coroutine_starts_submits_no_command(tmp_path):
    state = SessionManager(tmp_path).state
    task = asyncio.create_task(state.get("chat:unaccepted"))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert state._admitted == 0
    assert await state.read("chat:unaccepted") is None
    await state.aclose()


async def test_followup_can_initialize_first_turn_but_cannot_revive_deleted_session(tmp_path):
    from nanobot.session.recovery import pending_followups
    from nanobot.session.sqlite_store import SessionConflictError

    state = SessionManager(tmp_path).state
    message = InboundMessage(channel="websocket", sender_id="u", chat_id="a", content="second")
    assert await state.queue_followup("websocket:a", message)
    session = await state.get("websocket:a")
    assert [item.content for item in pending_followups(session)] == ["second"]
    await state.delete(session.key)
    with pytest.raises(SessionConflictError, match="existing session"):
        await state.queue_followup(session.key, message)
    assert await state.read(session.key) is None
    await state.aclose()


async def test_followup_rejects_discarded_or_replaced_generation(tmp_path):
    from nanobot.session.sqlite_store import SessionConflictError

    state = SessionManager(tmp_path).state
    session = await state.register_transient("websocket:private")
    message = InboundMessage(
        channel="websocket", sender_id="u", chat_id="private", content="private",
        require_existing_session=True, session_generation=session.generation,
    )
    await state.discard(session.key)
    with pytest.raises(SessionConflictError, match="existing session"):
        await state.queue_followup(session.key, message)
    replacement = await state.register_transient(session.key)
    with pytest.raises(SessionConflictError, match="replaced session"):
        await state.queue_followup(session.key, message)
    assert (await state.get(replacement.key)).metadata == {}
    await state.aclose()


async def test_display_metadata_reads_committed_snapshot_during_write(tmp_path, monkeypatch):
    manager = SessionManager(tmp_path)
    state = manager.state
    await state.get("websocket:busy")
    await state.update_metadata("websocket:busy", {"title": "committed"})
    started, release = threading.Event(), threading.Event()
    original = manager._store.replace_metadata

    def blocked(key, metadata, **kwargs):
        started.set()
        assert release.wait(5)
        return original(key, metadata, **kwargs)

    monkeypatch.setattr(manager._store, "replace_metadata", blocked)
    write = asyncio.create_task(state.update_metadata("websocket:busy", {"title": "next"}))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        rows = await asyncio.wait_for(state.list_metadata(), timeout=0.5)
        assert rows[0]["metadata"]["title"] == "committed"
        rows[0]["metadata"]["title"] = "local edit"
    finally:
        release.set()
        await write
    assert (await state.list_metadata())[0]["metadata"]["title"] == "next"
    await state.aclose()


async def test_cached_header_preserves_policy_and_offsets_without_history(tmp_path):
    state = SessionManager(tmp_path).state
    await state.import_messages("chat:header", [
        {"role": "user", "content": "input"}, {"role": "assistant", "content": "answer"},
    ])
    draft = await state.get("chat:header")
    draft.last_archived = 1
    draft.metadata["nested"] = {"value": "committed"}
    await state.prepare_input(draft)
    header = state.peek_header("chat:header")
    assert header is not None
    assert header.messages == []
    assert header.last_archived == 1
    assert header.generation == draft.generation
    assert header.policy == draft.policy
    header.metadata["nested"]["value"] = "local edit"
    assert state.peek_metadata("chat:header")["nested"]["value"] == "committed"
    assert len(state.peek("chat:header").messages) == 2
    await state.aclose()


async def test_missing_get_keeps_creation_before_a_later_delete(tmp_path, monkeypatch):
    state = SessionManager(tmp_path).state
    started, release = threading.Event(), threading.Event()
    original = state._load
    first = True

    def paused_read(key, *, history=True):
        nonlocal first
        if first:
            first = False
            started.set()
            assert release.wait(5)
        return original(key, history=history)

    monkeypatch.setattr(state, "_load", paused_read)
    get = asyncio.create_task(state.get("chat:new"))
    tasks = [get]
    try:
        assert await asyncio.to_thread(started.wait, 2)
        deleted = asyncio.create_task(state.delete("chat:new"))
        tasks.append(deleted)
        await asyncio.sleep(0)
        assert not deleted.done()
        release.set()
        assert (await get).persisted
        assert await deleted
        assert await state.read("chat:new") is None
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await state.aclose()


async def test_metadata_peek_and_header_do_not_expose_history_or_shared_metadata(tmp_path):
    state = SessionManager(tmp_path).state
    try:
        assert state.peek_metadata("chat:missing") is None
        empty = await state.get_header("chat:empty")
        assert empty.messages == [] and empty.persisted
        assert state.peek_metadata(empty.key) == {}
        assert empty._baseline is None
        await state.import_messages("chat:history", [{"role": "user", "content": "retained"}])
        await state.update_metadata("chat:history", {"custom": {"values": ["saved"]}})
        await state.commit_summary(await state.get("chat:history"), "Saved context", archive_end=1)
        header = await state.get_header("chat:history")
        assert header.messages == [] and header._baseline is None
        assert header.last_archived > 0
        header.metadata["custom"]["values"].append("header edit")
        metadata = state.peek_metadata("chat:history")
        metadata["custom"]["values"].append("peek edit")
        loaded = await state.get("chat:history")
        assert loaded.generation == header.generation
        assert loaded.last_archived == header.last_archived
        assert loaded.messages[0]["content"] == "retained"
        assert loaded.metadata["custom"]["values"] == ["saved"]
        await state.register_transient("chat:private")
        assert state.peek_metadata("chat:private") == {}
        await state.update_metadata("chat:private", {"custom": {"values": ["private"]}})
        private = state.peek_metadata("chat:private")
        private["custom"]["values"].append("peek edit")
        assert state.peek_metadata("chat:private")["custom"]["values"] == ["private"]
    finally:
        await state.aclose()


async def test_connection_open_failure_does_not_poison_the_owner(tmp_path, monkeypatch):
    state = SessionManager(tmp_path).state
    connect = sqlite3.connect
    first = True

    def fail_first(*args, **kwargs):
        nonlocal first
        if first:
            first = False
            raise sqlite3.OperationalError("database is locked")
        return connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", fail_first)
    try:
        with pytest.raises(sqlite3.OperationalError, match="database is locked"):
            await state.get("chat:retry")
        assert state._admitted == 0
        draft = await state.get("chat:retry")
        draft.add_message("user", "accepted after lock was released")
        await state.prepare_input(draft)
        assert (await state.get(draft.key)).messages[-1]["content"] == "accepted after lock was released"
    finally:
        await state.aclose()


async def test_history_peek_does_not_hold_the_metadata_control_lock(tmp_path, monkeypatch):
    import nanobot.session.state as owner
    from nanobot.session.manager import Session

    state = SessionManager(tmp_path).state
    await state.import_messages("chat:child", [{"role": "user", "content": "history"}])
    await state.update_metadata("chat:child", {"title": "committed"})
    started, release = threading.Event(), threading.Event()
    deepcopy = owner.deepcopy

    def paused_copy(value):
        if isinstance(value, Session):
            started.set()
            assert release.wait(5)
        return deepcopy(value)

    monkeypatch.setattr(owner, "deepcopy", paused_copy)
    history = asyncio.create_task(asyncio.to_thread(state.peek, "chat:child"))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        assert state.peek_metadata("chat:child")["title"] == "committed"
        assert not history.done()
    finally:
        release.set()
        await history
        await state.aclose()
