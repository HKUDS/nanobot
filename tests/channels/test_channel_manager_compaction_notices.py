"""Context-compaction notices on channels with ``send_progress`` off.

A compaction emits ``ContextCompactionEvent`` start/finish notices. The
outcome (compacted / failed / cancelled) is always delivered because it
changes the context of every later turn; the "Compressing context…" start
notice is transient progress text and follows the channel's progress
setting, so such a channel receives one notice per compaction instead of
two (#5719).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from nanobot.bus.outbound_events import (
    ContextCompactionEvent,
    outbound_message_for_event,
)
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.channels.manager import ChannelManager
from nanobot.config.schema import Config


class _MockChannel(BaseChannel):
    name = "mock"
    display_name = "Mock"

    def __init__(self, config, bus):
        super().__init__(config, bus)
        self._send_mock = AsyncMock()

    async def start(self):  # pragma: no cover - not exercised
        pass

    async def stop(self):  # pragma: no cover - not exercised
        pass

    async def send(self, msg):
        return await self._send_mock(msg)


@pytest.fixture
def manager() -> ChannelManager:
    config = Config.model_validate({"channels": {"websocket": {"enabled": False}}})
    mgr = ChannelManager(config, MessageBus())
    mgr.channels["mock"] = _MockChannel({}, mgr.bus)
    return mgr


async def _dispatch_until(manager: ChannelManager, expected: int) -> None:
    task = asyncio.create_task(manager._dispatch_outbound())
    try:
        for _ in range(40):
            if manager.channels["mock"]._send_mock.await_count >= expected:
                break
            await asyncio.sleep(0.05)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def _compaction(phase: str):
    return outbound_message_for_event(
        channel="mock",
        chat_id="c1",
        event=ContextCompactionEvent(compaction_id="cmp-1", phase=phase),
    )


@pytest.mark.asyncio
async def test_only_the_outcome_is_delivered_when_progress_is_off(manager):
    channel = manager.channels["mock"]
    channel.send_progress = False
    await manager.bus.publish_outbound(_compaction("started"))
    await manager.bus.publish_outbound(_compaction("succeeded"))

    await _dispatch_until(manager, expected=1)

    contents = [call.args[0].content for call in channel._send_mock.await_args_list]
    assert contents == ["Context compacted."]


@pytest.mark.asyncio
async def test_start_and_outcome_are_delivered_when_progress_is_on(manager):
    channel = manager.channels["mock"]
    channel.send_progress = True
    await manager.bus.publish_outbound(_compaction("started"))
    await manager.bus.publish_outbound(_compaction("succeeded"))

    await _dispatch_until(manager, expected=2)

    contents = [call.args[0].content for call in channel._send_mock.await_args_list]
    assert contents == ["Compressing context…", "Context compacted."]


@pytest.mark.asyncio
async def test_failed_and_cancelled_outcomes_are_delivered_when_progress_is_off(manager):
    channel = manager.channels["mock"]
    channel.send_progress = False
    await manager.bus.publish_outbound(_compaction("started"))
    await manager.bus.publish_outbound(_compaction("failed"))
    await manager.bus.publish_outbound(_compaction("cancelled"))

    await _dispatch_until(manager, expected=2)

    contents = [call.args[0].content for call in channel._send_mock.await_args_list]
    assert contents == ["Unable to compact context.", "Context compaction cancelled."]
