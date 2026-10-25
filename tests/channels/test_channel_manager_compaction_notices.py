"""Channel transports decide whether to render compaction lifecycle events."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from unittest.mock import AsyncMock

import pytest

from nanobot.bus.events import OutboundMessage
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
        return await self._send_mock(msg)


@pytest.fixture
def manager(tmp_path) -> ChannelManager:
    config = Config.model_validate({"channels": {"websocket": {"enabled": False}}})
    mgr = ChannelManager(config, MessageBus(), config_path=tmp_path / "config.json")
    mgr.channels["mock"] = _MockChannel({}, mgr.bus)
    return mgr


@pytest.mark.asyncio
async def test_dispatch_forwards_all_compaction_phases_before_adapter_filtering(
    manager: ChannelManager,
) -> None:
    channel = manager.channels["mock"]
    channel.send_progress = False
    channel.show_compaction_notices = False
    events = [
        ContextCompactionEvent(compaction_id="auto", phase="started"),
        ContextCompactionEvent(compaction_id="auto", phase="succeeded"),
        ContextCompactionEvent(compaction_id="auto-failed", phase="failed"),
        ContextCompactionEvent(compaction_id="auto-cancelled", phase="cancelled"),
        ContextCompactionEvent(compaction_id="c1", phase="started", notify=True),
        ContextCompactionEvent(compaction_id="c1", phase="succeeded", notify=True),
    ]
    await manager.bus.publish_outbound(outbound_message_for_event(
        channel="mock", chat_id="chat", event=ProgressEvent(content="ordinary progress"),
    ))
    messages = [
        outbound_message_for_event(channel="mock", chat_id="chat", event=event)
        for event in events
    ]
    for msg in messages:
        await manager.bus.publish_outbound(msg)
    final = OutboundMessage(channel="mock", chat_id="chat", content="Final")
    await manager.bus.publish_outbound(final)
    delivered = asyncio.Event()

    def record_send(msg):
        if (msg.channel, msg.chat_id, msg.content, msg.event) == ("mock", "chat", "Final", None):
            delivered.set()

    channel._send_mock.side_effect = record_send
    task = asyncio.create_task(manager._dispatch_outbound())
    try:
        await asyncio.wait_for(delivered.wait(), timeout=2)
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=2)

    # The recorder sees the manager -> adapter boundary, not a fake presentation rule.
    received = [call.args[0] for call in channel._send_mock.await_args_list]
    assert received == [*messages, final]
    assert [msg.event for msg in received] == [*events, None]
    assert [msg.content for msg in received[-3:]] == [
        "Compressing context…", "Context compacted.", "Final",
    ]
    assert not manager._outbound_tasks
    assert not manager._outbound_tails


@pytest.mark.parametrize("global_value", [False, True])
@pytest.mark.parametrize("override", [None, False, True])
@pytest.mark.parametrize("key", ["show_compaction_notices", "showCompactionNotices"])
def test_global_notice_policy_and_channel_override(manager, global_value, override, key):
    manager.config.channels.show_compaction_notices = global_value
    section = {} if override is None else {key: override}
    channel = manager._build_channel("mock", _MockChannel, section)
    assert channel.show_compaction_notices is (global_value if override is None else override)


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
