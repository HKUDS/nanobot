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
        if isinstance(msg.event, ContextCompactionEvent) and not (
            msg.event.notify or self.show_compaction_notices
        ):
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


@pytest.mark.parametrize("global_value", [False, True])
@pytest.mark.parametrize("override", [None, False, True])
@pytest.mark.parametrize("key", ["show_compaction_notices", "showCompactionNotices"])
async def test_global_notice_policy_and_channel_override(manager, global_value, override, key):
    manager.config.channels.show_compaction_notices = global_value
    section = {} if override is None else {key: override}
    channel = manager._build_channel("mock", _MockChannel, section)
    assert channel.show_compaction_notices is (global_value if override is None else override)
    channel.send_progress = False  # Ordinary progress and compaction are independent policies.
    manager.channels["mock"] = channel

    for phase in ("started", "succeeded", "failed", "cancelled"):
        for notify in (False, True):
            await channel.send(outbound_message_for_event(
                channel="mock", chat_id="chat",
                event=ContextCompactionEvent("compact", phase, notify=notify),
            ))

    assert channel._send_mock.await_count == (8 if channel.show_compaction_notices else 4)


def test_global_notice_config_round_trip_and_rebuild(manager):
    assert Config().channels.show_compaction_notices is False
    manager.config = Config.model_validate({"channels": {"showCompactionNotices": True}})
    manager.config = Config.model_validate_json(manager.config.model_dump_json(by_alias=True))
    assert manager._build_channel("mock", _MockChannel, {}).show_compaction_notices is True
    # Rebuilding an adapter after a config change must resolve the new default.
    manager.config.channels.show_compaction_notices = False
    assert manager._build_channel("mock", _MockChannel, {}).show_compaction_notices is False
    assert manager._build_channel(
        "mock", _MockChannel, {"showCompactionNotices": True},
    ).show_compaction_notices
