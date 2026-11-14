"""Provider retry-wait notices reach channels behind the ``sendProgress`` gate."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.outbound_events import (
    ProgressEvent,
    RetryWaitEvent,
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
    mgr.channels["websocket"] = _MockChannel({}, mgr.bus)
    return mgr


async def _dispatch_until(manager: ChannelManager, channel: str, expected: int) -> None:
    task = asyncio.create_task(manager._dispatch_outbound())
    try:
        for _ in range(40):
            if manager.channels[channel]._send_mock.await_count >= expected:
                break
            await asyncio.sleep(0.05)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def _sent(manager: ChannelManager, channel: str) -> list:
    return [call.args[0] for call in manager.channels[channel]._send_mock.await_args_list]


_NOTICE = "Model request failed, retry in 30s (attempt 2)."


@pytest.mark.asyncio
async def test_retry_wait_is_delivered_as_progress(manager: ChannelManager) -> None:
    manager.channels["mock"].send_progress = True
    await manager.bus.publish_outbound(
        outbound_message_for_event(
            channel="mock",
            chat_id="42",
            event=RetryWaitEvent(content=_NOTICE),
            content=_NOTICE,
            metadata={"message_id": "7"},
        )
    )
    await manager.bus.publish_outbound(
        outbound_message_for_event(
            channel="mock", chat_id="42", event=ProgressEvent(content="after"), content="after",
        )
    )

    await _dispatch_until(manager, "mock", 2)

    sent = _sent(manager, "mock")
    assert [msg.content for msg in sent] == [_NOTICE, "after"]
    # Channels see an ordinary text-progress event (typing indicators, reactions
    # and progress rendering keep working), with the turn's metadata intact.
    assert isinstance(sent[0].event, ProgressEvent)
    assert not isinstance(sent[0].event, RetryWaitEvent)
    assert sent[0].event.tool_hint is False
    assert sent[0].metadata == {"message_id": "7"}
    assert sent[0].chat_id == "42"


@pytest.mark.asyncio
async def test_retry_wait_respects_the_send_progress_gate(manager: ChannelManager) -> None:
    manager.channels["mock"].send_progress = False
    await manager.bus.publish_outbound(
        outbound_message_for_event(
            channel="mock", chat_id="42", event=RetryWaitEvent(content=_NOTICE), content=_NOTICE,
        )
    )
    await manager.bus.publish_outbound(
        outbound_message_for_event(
            channel="mock", chat_id="42", event=ProgressEvent(content="progress"), content="progress",
        )
    )
    # A final reply still goes out, which also proves the loop drained the notice.
    await manager.bus.publish_outbound(OutboundMessage(channel="mock", chat_id="42", content="final reply"))

    await _dispatch_until(manager, "mock", 1)

    assert [msg.content for msg in _sent(manager, "mock")] == ["final reply"]


@pytest.mark.asyncio
async def test_retry_wait_is_not_forwarded_to_the_websocket_channel(
    manager: ChannelManager,
) -> None:
    # The WebUI already receives the sanitized RetryStatusEvent lifecycle.
    manager.channels["websocket"].send_progress = True
    await manager.bus.publish_outbound(
        outbound_message_for_event(
            channel="websocket", chat_id="42", event=RetryWaitEvent(content=_NOTICE), content=_NOTICE,
        )
    )
    await manager.bus.publish_outbound(
        outbound_message_for_event(
            channel="websocket", chat_id="42", event=ProgressEvent(content="after"), content="after",
        )
    )

    await _dispatch_until(manager, "websocket", 1)

    assert [msg.content for msg in _sent(manager, "websocket")] == ["after"]
