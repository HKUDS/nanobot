"""The watchdog uses the real loop's session lock and cancellation boundaries."""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.config.schema import GoalRecoveryConfig
from nanobot.session.goal_recovery import GOAL_RECOVERY_KEY, GoalRecoveryWatchdog


def install(loop):
    session = loop.sessions.get_or_create("telegram:chat")
    session.metadata["goal_state"] = {
        "status": "active", "objective": "verify project", "started_at": "2026-01-01",
    }
    session.updated_at = datetime(2026, 1, 1)
    loop.sessions.save(session)
    watchdog = GoalRecoveryWatchdog(
        loop.sessions, loop.bus, GoalRecoveryConfig(enabled=True),
        is_busy=loop.is_session_busy, is_channel_enabled=lambda _: True,
        clock=lambda: datetime.now().timestamp() + 1200,
    )
    loop.goal_recovery = watchdog
    return watchdog, session


async def test_claim_is_rechecked_after_waiting_for_real_session_lock(loop_factory):
    loop = loop_factory()
    watchdog, session = install(loop)
    await watchdog.tick()
    message = loop.bus.inbound.get_nowait()
    loop._process_message = AsyncMock()
    lock = loop._get_session_lock(session.key)
    await lock.acquire()
    task = asyncio.create_task(loop._dispatch(message))
    await asyncio.sleep(0)
    session.metadata["goal_state"]["status"] = "cancelled"
    loop.sessions.save(session)
    lock.release()
    await task
    loop._process_message.assert_not_awaited()
    await loop.aclose()


async def test_duplicate_dispatch_runs_once_and_model_error_backs_off(loop_factory):
    loop = loop_factory()
    watchdog, session = install(loop)
    await watchdog.tick()
    message = loop.bus.inbound.get_nowait()

    async def process(msg, *, pending_queue, delivery):
        delivery.record_stop_reason("error")
        return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content="provider failed")

    loop._process_message = AsyncMock(side_effect=process)
    await asyncio.gather(loop._dispatch(message), loop._dispatch(message))
    loop._process_message.assert_awaited_once()
    assert session.metadata[GOAL_RECOVERY_KEY]["status"] == "failed"
    assert session.metadata[GOAL_RECOVERY_KEY]["failures"] == 1
    await loop.aclose()


@pytest.mark.parametrize("shutdown", [False, True])
async def test_loop_cancellation_distinguishes_user_stop_from_shutdown(loop_factory, shutdown):
    loop = loop_factory()
    watchdog, session = install(loop)
    await watchdog.tick()
    message = loop.bus.inbound.get_nowait()
    entered = asyncio.Event()

    async def process(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    loop._process_message = AsyncMock(side_effect=process)
    task = asyncio.create_task(loop._dispatch(message))
    await entered.wait()
    if shutdown:
        loop.preserve_inflight_turns_on_shutdown()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert session.metadata[GOAL_RECOVERY_KEY]["status"] == ("failed" if shutdown else "paused")
    await loop.aclose()


async def test_direct_call_lock_is_busy_and_new_direct_input_supersedes_claim(loop_factory):
    loop = loop_factory()
    watchdog, session = install(loop)
    lock = loop._get_session_lock(session.key)
    async with lock:
        assert loop.is_session_busy(session.key)
        await watchdog.tick()
        assert loop.bus.inbound.empty()
    await watchdog.tick()
    queued = loop.bus.inbound.get_nowait()
    loop._process_message = AsyncMock(return_value=None)
    await loop.process_direct("/stop", session_key=session.key, channel="telegram", chat_id="chat")
    assert not watchdog.claim(queued)
    assert session.metadata[GOAL_RECOVERY_KEY]["status"] == "paused"
    await loop.aclose()
