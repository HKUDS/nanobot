"""Provider retry-wait notices use an opt-in channel hook.

``ChannelManager`` must not drop ``RetryWaitEvent`` before dispatch, and it
must not turn the notice into a normal ``send()`` chat message. Channels
that can render a backoff (an edited status, an ephemeral activity) override
``send_retry_wait``. The base hook is a no-op, independent of ``send_progress``.
"""

from __future__ import annotations

import asyncio

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.outbound_events import RetryWaitEvent, outbound_message_for_event
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.channels.manager import ChannelManager
from nanobot.config.schema import Config

_RETRY_TEXT = "Model request failed, retry in 1s (attempt 1)."


class _RecordingChannel(BaseChannel):
    name = "mock"
    display_name = "Mock"

    def __init__(self, config, bus):
        super().__init__(config, bus)
        self.sent: list[OutboundMessage] = []
        self.retry_notices: list[OutboundMessage] = []

    async def start(self) -> None:  # pragma: no cover - not exercised
        return None

    async def stop(self) -> None:  # pragma: no cover - not exercised
        return None

    async def send(self, msg: OutboundMessage) -> None:
        self.sent.append(msg)

    async def send_retry_wait(self, msg: OutboundMessage) -> None:
        self.retry_notices.append(msg)


class _DefaultChannel(BaseChannel):
    """Uses the base retry-wait hook and records only chat sends."""

    name = "mock"
    display_name = "Mock"

    def __init__(self, config, bus):
        super().__init__(config, bus)
        self.sent: list[OutboundMessage] = []

    async def start(self) -> None:  # pragma: no cover - not exercised
        return None

    async def stop(self) -> None:  # pragma: no cover - not exercised
        return None

    async def send(self, msg: OutboundMessage) -> None:
        self.sent.append(msg)


def _manager(channel: BaseChannel) -> ChannelManager:
    config = Config.model_validate({"channels": {"websocket": {"enabled": False}}})
    manager = ChannelManager(config, MessageBus())
    channel.send_progress = False
    manager.channels["mock"] = channel
    return manager


async def _dispatch_until(manager: ChannelManager, ready) -> None:
    task = asyncio.create_task(manager._dispatch_outbound())
    try:
        for _ in range(40):
            if ready():
                break
            await asyncio.sleep(0.05)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def _publish_retry_then_answer(manager: ChannelManager) -> None:
    await manager.bus.publish_outbound(outbound_message_for_event(
        channel="mock",
        chat_id="chat1",
        event=RetryWaitEvent(content=_RETRY_TEXT),
    ))
    await manager.bus.publish_outbound(OutboundMessage(
        channel="mock",
        chat_id="chat1",
        content="final answer",
    ))


@pytest.mark.asyncio
async def test_retry_wait_reaches_hook_without_send_progress_or_chat_send() -> None:
    channel = _RecordingChannel({}, MessageBus())
    manager = _manager(channel)
    await _publish_retry_then_answer(manager)

    await _dispatch_until(
        manager,
        lambda: len(channel.retry_notices) >= 1 and len(channel.sent) >= 1,
    )

    assert [msg.content for msg in channel.retry_notices] == [_RETRY_TEXT]
    assert isinstance(channel.retry_notices[0].event, RetryWaitEvent)
    assert [msg.content for msg in channel.sent] == ["final answer"]


@pytest.mark.asyncio
async def test_default_retry_wait_hook_does_not_post_a_chat_message() -> None:
    channel = _DefaultChannel({}, MessageBus())
    manager = _manager(channel)
    await _publish_retry_then_answer(manager)

    await _dispatch_until(manager, lambda: len(channel.sent) >= 1)

    assert [msg.content for msg in channel.sent] == ["final answer"]
