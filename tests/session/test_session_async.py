"""Admission, ordering, and shutdown at the asynchronous session boundary."""

import asyncio
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
