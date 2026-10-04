import asyncio
import threading
from pathlib import Path

import pytest

from nanobot.session.manager import Session, SessionManager


@pytest.mark.asyncio
async def test_concurrent_existing_loads_preserve_live_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = SessionManager(tmp_path)
    parent = manager.get_or_create("test:parent")
    parent.add_message("user", "hello")
    manager.save(parent)
    manager.invalidate(parent.key)
    loaded = threading.Barrier(3)
    release = threading.Event()
    original_load = manager._load

    def blocked_load(key: str) -> Session | None:
        session = original_load(key)
        loaded.wait(timeout=10)
        if not release.wait(timeout=10):
            raise TimeoutError("test release was never signalled")
        return session

    monkeypatch.setattr(manager, "_load", blocked_load)
    tasks = [asyncio.create_task(manager.get_existing(parent.key)) for _ in range(2)]
    try:
        await asyncio.to_thread(loaded.wait, 10)
        manager.invalidate("test:unrelated")
        release.set()
        first, second = await asyncio.wait_for(asyncio.gather(*tasks), timeout=10)
        assert first is not None
        assert first is second is manager.get_cached(parent.key)
        assert first.messages == parent.messages
        assert manager._pending_session_loads == {}
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_cancelled_existing_load_does_not_populate_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = SessionManager(tmp_path)
    parent = manager.get_or_create("test:parent")
    manager.save(parent)
    manager.invalidate(parent.key)
    loaded = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    original_load = manager._load

    def blocked_load(key: str) -> Session | None:
        session = original_load(key)
        loaded.set()
        if not release.wait(timeout=10):
            raise TimeoutError("test release was never signalled")
        finished.set()
        return session

    monkeypatch.setattr(manager, "_load", blocked_load)
    task = asyncio.create_task(manager.get_existing(parent.key))
    try:
        assert await asyncio.to_thread(loaded.wait, 10)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()
        assert await asyncio.to_thread(finished.wait, 10)
        assert manager.get_cached(parent.key) is None
        assert manager._pending_session_loads == {}
        assert manager.read_session_file(parent.key) is not None
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
