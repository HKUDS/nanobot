"""Cancellation settlement guarantees for native SessionManager mutations."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import pytest

from nanobot.session.manager import Session, SessionManager


async def _cancel_blocked_mutation(
    task: asyncio.Task[Any],
    *,
    started: threading.Event,
    release: threading.Event,
) -> None:
    assert await asyncio.to_thread(started.wait, 1)
    try:
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done(), "cancellation escaped before the mutation worker settled"
    finally:
        release.set()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=1)


async def test_save_async_cancellation_waits_for_durable_write_and_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = SessionManager(tmp_path)
    session = Session(key="test:cancel-save")
    session.add_message("user", "persist exactly once")
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    save_calls = 0
    original_save = manager._store.save

    def blocked_save(target: Session, *, fsync: bool = False) -> None:
        nonlocal save_calls
        save_calls += 1
        started.set()
        assert release.wait(timeout=1)
        original_save(target, fsync=fsync)
        finished.set()

    monkeypatch.setattr(manager._store, "save", blocked_save)
    task = asyncio.create_task(manager.save_async(session))

    await _cancel_blocked_mutation(task, started=started, release=release)

    assert finished.is_set()
    assert save_calls == 1
    assert manager.get_cached(session.key) is session
    durable = manager.read_session_file(session.key)
    assert durable is not None
    assert durable["messages"][0]["content"] == "persist exactly once"

    await asyncio.sleep(0.05)
    assert save_calls == 1
    assert manager.read_session_file(session.key) == durable


async def test_update_metadata_async_cancellation_waits_for_file_and_cache_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("test:cancel-metadata")
    session.metadata["title"] = "before"
    manager.save(session)
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    update_calls = 0
    original_update = manager._store.update_metadata

    def blocked_update(
        key: str,
        updates: dict[str, Any],
        *,
        fsync: bool = False,
    ) -> bool:
        nonlocal update_calls
        update_calls += 1
        started.set()
        assert release.wait(timeout=1)
        updated = original_update(key, updates, fsync=fsync)
        finished.set()
        return updated

    monkeypatch.setattr(manager._store, "update_metadata", blocked_update)
    task = asyncio.create_task(
        manager.update_session_metadata_async(
            session.key,
            {"title": "after", "settled": True},
        )
    )

    await _cancel_blocked_mutation(task, started=started, release=release)

    assert finished.is_set()
    assert update_calls == 1
    assert session.metadata["title"] == "after"
    assert session.metadata["settled"] is True
    durable = manager.read_session_file(session.key)
    assert durable is not None
    assert durable["metadata"]["title"] == "after"
    assert durable["metadata"]["settled"] is True

    await asyncio.sleep(0.05)
    assert update_calls == 1
    assert manager.read_session_file(session.key) == durable


async def test_delete_async_cancellation_waits_for_file_cache_and_observer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("test:cancel-delete")
    session.add_message("user", "delete me")
    manager.save(session)
    observed: list[str] = []
    manager.set_delete_observer(observed.append)
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    delete_calls = 0
    original_delete = manager._store.delete

    def blocked_delete(key: str) -> bool:
        nonlocal delete_calls
        delete_calls += 1
        started.set()
        assert release.wait(timeout=1)
        deleted = original_delete(key)
        finished.set()
        return deleted

    monkeypatch.setattr(manager._store, "delete", blocked_delete)
    task = asyncio.create_task(manager.delete_session_async(session.key))

    await _cancel_blocked_mutation(task, started=started, release=release)

    assert finished.is_set()
    assert delete_calls == 1
    assert manager.read_session_file(session.key) is None
    assert manager.get_cached(session.key) is None
    assert observed == [session.key]

    await asyncio.sleep(0.05)
    assert delete_calls == 1
    assert observed == [session.key]
    assert manager.read_session_file(session.key) is None
