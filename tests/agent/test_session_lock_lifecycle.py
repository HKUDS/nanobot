from __future__ import annotations

import asyncio
import gc
from unittest.mock import MagicMock

import pytest


def _make_loop(loop_factory):
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    return loop_factory(provider=provider)


def test_idle_agent_session_locks_are_released(loop_factory):
    loop = _make_loop(loop_factory)

    for index in range(1000):
        lock = loop._get_session_lock(f"api:temporary-{index}")

    del lock
    gc.collect()

    assert len(loop._session_locks) == 0


@pytest.mark.asyncio
async def test_waiter_keeps_agent_session_lock_alive(loop_factory):
    loop = _make_loop(loop_factory)
    owner_lock = loop._get_session_lock("api:shared")
    await owner_lock.acquire()
    waiter_started = asyncio.Event()
    waiter_entered = asyncio.Event()

    async def wait_for_lock() -> None:
        lock = loop._get_session_lock("api:shared")
        waiter_started.set()
        async with lock:
            waiter_entered.set()

    waiter = asyncio.create_task(wait_for_lock())
    await waiter_started.wait()

    assert loop._get_session_lock("api:shared") is owner_lock
    assert not waiter_entered.is_set()

    owner_lock.release()
    await waiter
    del owner_lock
    gc.collect()

    assert "api:shared" not in loop._session_locks
