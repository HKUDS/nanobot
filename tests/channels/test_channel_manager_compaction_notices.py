"""Channel transports decide whether to render compaction lifecycle events."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from nanobot.bus.outbound_events import (
    ContextCompactionEvent,
    ProgressEvent,
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
        if isinstance(msg.event, ContextCompactionEvent) and not msg.event.notify:
            return
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


def _sent_contents(manager: ChannelManager) -> list[str]:
    return [call.args[0].content for call in manager.channels["mock"]._send_mock.await_args_list]


@pytest.mark.asyncio
async def test_channel_receives_automatic_compaction_but_does_not_render_it(
    manager: ChannelManager,
) -> None:
    manager.channels["mock"].send_progress = False
    for event in (
        ProgressEvent(content="ordinary progress"),
        ContextCompactionEvent(compaction_id="auto", phase="started"),
        ContextCompactionEvent(compaction_id="auto", phase="succeeded"),
        ContextCompactionEvent(compaction_id="auto-failed", phase="failed"),
        ContextCompactionEvent(compaction_id="auto-cancelled", phase="cancelled"),
        ContextCompactionEvent(compaction_id="c1", phase="started", notify=True),
        ContextCompactionEvent(compaction_id="c1", phase="succeeded", notify=True),
    ):
        await manager.bus.publish_outbound(
            outbound_message_for_event(channel="mock", chat_id="chat", event=event)
        )

    await _dispatch_until(manager, 2)

    contents = _sent_contents(manager)
    assert "ordinary progress" not in contents
    assert contents == ["Compressing context…", "Context compacted."]
