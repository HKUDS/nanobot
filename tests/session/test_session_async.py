"""Admission, ordering, and shutdown at the asynchronous session boundary."""

import asyncio
import threading

import pytest

from nanobot.session.manager import SessionManager


async def test_writes_run_in_submission_order(tmp_path):
    state = SessionManager(tmp_path).state
    await asyncio.gather(*(state.update_metadata("chat:a", {"title": str(i)}) for i in range(50)))
    assert (await state.get("chat:a")).metadata["title"] == "49"
    await state.aclose()


async def test_close_drains_accepted_operations(tmp_path, monkeypatch):
    manager = SessionManager(tmp_path)
    state = manager.state
    started, release = threading.Event(), threading.Event()
    original = manager._store.save
    def blocked(session, **kwargs):
        started.set()
        release.wait(5)
        return original(session, **kwargs)
    monkeypatch.setattr(manager._store, "save", blocked)
    task = asyncio.create_task(state.update_metadata("chat:a", {"title": "committed"}))
    await asyncio.to_thread(started.wait, 2)
    close = asyncio.create_task(state.aclose())
    await asyncio.sleep(0)
    assert not close.done()
    release.set()
    await asyncio.gather(task, close)
    assert manager.get_or_create("chat:a").metadata["title"] == "committed"
    with pytest.raises(RuntimeError, match="closed"):
        await state.update_metadata("chat:a", {"title": "late"})


async def test_cancel_before_admission_does_not_write(tmp_path):
    state = SessionManager(tmp_path).state
    for _ in range(32):
        await state._slots.acquire()
    task = asyncio.create_task(state.update_metadata("chat:a", {"title": "unaccepted"}))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    for _ in range(32):
        state._slots.release()
    assert await state.read("chat:a") is None
    await state.aclose()
