"""Tests for ChannelManager routing of model reasoning content.

Reasoning is delivered through plugin streaming primitives
(``send_reasoning_delta`` / ``send_reasoning_end``) so each channel
controls in-place rendering — mirroring the existing answer ``send_delta``
/ ``stream_end`` pair. The manager forwards reasoning frames only to
channels that opt in via ``channel.show_reasoning``; plugins without a
low-emphasis UI primitive keep the base no-op and the content silently
drops at dispatch.

One-shot reasoning frames are represented as typed progress events and
``BaseChannel.send_reasoning`` expands them to a single delta + end pair so
plugins only implement the streaming primitives.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from unittest.mock import AsyncMock

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.outbound_events import (
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
        self._delta_mock = AsyncMock()
        self._end_mock = AsyncMock()
        self._file_edit_mock = AsyncMock()
        self.received = []

    async def start(self):  # pragma: no cover - not exercised
        pass

    async def stop(self):  # pragma: no cover - not exercised
        pass

    async def send(self, msg):
        await self._send_mock(msg)
        self.received.append(("send", msg))

    async def send_reasoning_delta(self, chat_id, delta, metadata=None, *, stream_id=None):
        await self._delta_mock(chat_id, delta, metadata, stream_id=stream_id)
        self.received.append(("delta", chat_id, delta, metadata, stream_id))

    async def send_reasoning_end(self, chat_id, metadata=None, *, stream_id=None):
        await self._end_mock(chat_id, metadata, stream_id=stream_id)
        self.received.append(("end", chat_id, metadata, stream_id))

    async def send_file_edit_events(self, chat_id, edits, metadata=None):
        return await self._file_edit_mock(chat_id, edits, metadata)


@pytest.fixture
def manager(tmp_path) -> ChannelManager:
    config = Config.model_validate({"channels": {"websocket": {"enabled": False}}})
    mgr = ChannelManager(config, MessageBus(), config_path=tmp_path / "config.json")
    mgr.channels["mock"] = _MockChannel({}, mgr.bus)
    return mgr


def test_websocket_gateway_uses_configured_workspace_restriction(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "nanobot.webui.workspaces.read_webui_default_access_mode",
        lambda: "default",
    )
    config = Config.model_validate(
        {
            "agents": {"defaults": {"workspace": str(tmp_path)}},
            "tools": {"restrictToWorkspace": True},
            "channels": {
                "websocket": {
                    "enabled": True,
                    "websocketRequiresToken": False,
                },
            },
        }
    )

    mgr = ChannelManager(
        config, MessageBus(), webui_static_dist=False, config_path=tmp_path / "config.json",
    )
    channel = mgr.channels["websocket"]

    scope = channel.gateway.workspaces.default_scope()
    assert scope.project_path == tmp_path
    assert scope.restrict_to_workspace is True


@pytest.mark.asyncio
async def test_reasoning_delta_routes_to_send_reasoning_delta(manager):
    channel = manager.channels["mock"]
    msg = outbound_message_for_event(
        channel="mock",
        chat_id="c1",
        event=ProgressEvent(content="step-by-step", reasoning_delta=True, stream_id="r1"),
    )
    await manager._send_once(channel, msg)
    channel._delta_mock.assert_awaited_once()
    args = channel._delta_mock.await_args.args
    assert args[0] == "c1"
    assert args[1] == "step-by-step"
    assert channel._delta_mock.await_args.kwargs["stream_id"] == "r1"
    channel._send_mock.assert_not_awaited()
    channel._end_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_reasoning_end_routes_to_send_reasoning_end(manager):
    channel = manager.channels["mock"]
    msg = outbound_message_for_event(
        channel="mock",
        chat_id="c1",
        event=ProgressEvent(reasoning_end=True, stream_id="r1"),
    )
    await manager._send_once(channel, msg)
    channel._end_mock.assert_awaited_once()
    assert channel._end_mock.await_args.kwargs["stream_id"] == "r1"
    channel._delta_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_one_shot_reasoning_expands_to_delta_plus_end(manager):
    """One-shot reasoning expands to a single delta + end."""
    channel = manager.channels["mock"]
    msg = outbound_message_for_event(
        channel="mock",
        chat_id="c1",
        event=ProgressEvent(content="one-shot reasoning", reasoning=True),
    )
    await manager._send_once(channel, msg)
    channel._delta_mock.assert_awaited_once()
    channel._end_mock.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("show_reasoning", [False, True])
@pytest.mark.parametrize("send_progress", [False, True])
async def test_dispatch_reasoning_visibility_is_independent_of_progress(
    manager, show_reasoning, send_progress,
):
    channel = manager.channels["mock"]
    channel.show_reasoning = show_reasoning
    channel.send_progress = send_progress
    events = [
        ProgressEvent(content="first ", reasoning_delta=True, stream_id="r1"),
        ProgressEvent(content="second", reasoning_delta=True, stream_id="r1"),
        ProgressEvent(reasoning_end=True, stream_id="r1"),
        ProgressEvent(content="one-shot reasoning", reasoning=True, stream_id="r2"),
        ProgressEvent(content="ordinary progress"),
    ]
    messages = [
        outbound_message_for_event(channel="mock", chat_id="c1", event=event)
        for event in events
    ]
    for msg in messages:
        await manager.bus.publish_outbound(msg)

    final = await _dispatch_through_final(manager)

    expected = []
    if show_reasoning:
        expected.extend([
            ("delta", "c1", "first ", messages[0].metadata, "r1"),
            ("delta", "c1", "second", messages[1].metadata, "r1"),
            ("end", "c1", messages[2].metadata, "r1"),
            ("delta", "c1", "one-shot reasoning", messages[3].metadata, "r2"),
            ("end", "c1", messages[3].metadata, "r2"),
        ])
    if send_progress:
        expected.append(("send", messages[-1]))
    assert channel.received == [*expected, ("send", final)]


@pytest.mark.asyncio
async def test_dispatch_silently_drops_reasoning_for_unknown_channel(manager):
    await manager.bus.publish_outbound(outbound_message_for_event(
        channel="ghost",
        chat_id="c1",
        event=ProgressEvent(content="nobody home", reasoning_delta=True, stream_id="ghost-r1"),
    ))

    final = await _dispatch_through_final(manager)

    channel = manager.channels["mock"]
    assert channel.received == [("send", final)]
    channel._delta_mock.assert_not_awaited()
    channel._end_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_base_channel_reasoning_primitives_are_noop_safe():
    """Plugins that don't override the streaming primitives must not blow up."""

    class _Plain(BaseChannel):
        name = "plain"
        display_name = "Plain"

        async def start(self):  # pragma: no cover
            pass

        async def stop(self):  # pragma: no cover
            pass

        async def send(self, msg):  # pragma: no cover
            pass

    channel = _Plain({}, MessageBus())
    assert await channel.send_reasoning_delta("c", "x") is None
    assert await channel.send_reasoning_end("c") is None
    # And the one-shot wrapper translates without raising.
    assert await channel.send_reasoning(
        OutboundMessage(channel="plain", chat_id="c", content="x", metadata={})
    ) is None


@pytest.mark.asyncio
async def test_file_edit_events_route_to_channel_capability(manager):
    channel = manager.channels["mock"]
    edits = [{"version": 1, "phase": "start", "path": "src/app.py"}]
    msg = outbound_message_for_event(
        channel="mock",
        chat_id="c1",
        event=ProgressEvent(file_edit_events=edits),
    )

    await manager._send_once(channel, msg)

    channel._file_edit_mock.assert_awaited_once_with(
        "c1", edits, msg.metadata
    )
    channel._send_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_base_channel_file_edit_events_are_noop_safe():
    class _Plain(BaseChannel):
        name = "plain"
        display_name = "Plain"

        async def start(self):  # pragma: no cover
            pass

        async def stop(self):  # pragma: no cover
            pass

        async def send(self, msg):  # pragma: no cover
            raise AssertionError("file edit events should not call send")

    channel = _Plain({}, MessageBus())
    assert await channel.send_file_edit_events("c", [{"path": "a.py"}]) is None


async def _dispatch_through_final(manager: ChannelManager) -> OutboundMessage:
    """A same-destination send acknowledges completion of earlier callbacks."""
    final = OutboundMessage(channel="mock", chat_id="c1", content="Final")
    delivered = asyncio.Event()

    def record_send(msg):
        if (msg.channel, msg.chat_id, msg.content, msg.event) == ("mock", "c1", "Final", None):
            delivered.set()

    manager.channels["mock"]._send_mock.side_effect = record_send
    await manager.bus.publish_outbound(final)
    task = asyncio.create_task(manager._dispatch_outbound())
    try:
        await asyncio.wait_for(delivered.wait(), timeout=2)
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=2)
    assert not manager._outbound_tasks
    assert not manager._outbound_tails
    return final
