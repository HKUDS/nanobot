"""Tests for ChannelManager's centralized leaked-tool-call-markup filter.

Reporter scenario 2026-08-11: a raw unexecuted tool-call block (e.g. from a
model finalizing with no tools offered) must never reach a user-facing
channel verbatim. This is filtered once in ChannelManager._send_once before
any channel's send() is invoked, so every channel gets the same protection
without each implementation needing its own copy of the check.
"""

from unittest.mock import AsyncMock

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.channels.manager import ChannelManager
from nanobot.config.schema import Config


class MockChannel(BaseChannel):
    """Mock channel for testing."""

    name = "mock"
    display_name = "Mock"

    def __init__(self, config, bus):
        super().__init__(config, bus)
        self._send_mock = AsyncMock()

    async def start(self):
        pass

    async def stop(self):
        pass

    async def send(self, msg):
        return await self._send_mock(msg)


@pytest.fixture
def config():
    return Config.model_validate({"channels": {"websocket": {"enabled": False}}})


@pytest.fixture
def bus():
    return MessageBus()


@pytest.fixture
def channel(config, bus):
    return MockChannel(config, bus)


@pytest.mark.asyncio
async def test_send_once_blocks_leaked_tool_call_markup(channel) -> None:
    leaked = (
        "<tool_call>\n<function=write_stdin>\n<parameter=session_id>\n"
        "51c8aae161d1\n</parameter>\n</function>\n</tool_call>"
    )
    msg = OutboundMessage(channel="mock", chat_id="alice", content=leaked)

    await ChannelManager._send_once(channel, msg)

    channel._send_mock.assert_awaited_once()
    sent_msg = channel._send_mock.await_args.args[0]
    assert "<tool_call" not in sent_msg.content
    assert "<function=" not in sent_msg.content
    assert "formatting issue" in sent_msg.content


@pytest.mark.asyncio
async def test_send_once_blocks_leaked_plural_tool_calls_tag(channel) -> None:
    """Regression check for the plural <tool_calls> wrapper tag the original
    regex missed (verified live: <tool_call\\b doesn't match <tool_calls>)."""
    leaked = "<tool_calls><function=foo></function></tool_calls>"
    msg = OutboundMessage(channel="mock", chat_id="alice", content=leaked)

    await ChannelManager._send_once(channel, msg)

    sent_msg = channel._send_mock.await_args.args[0]
    assert "<tool_calls" not in sent_msg.content
    assert "formatting issue" in sent_msg.content


@pytest.mark.asyncio
async def test_send_once_passes_through_normal_content_unchanged(channel) -> None:
    """Negative case for the leak filter -- ordinary replies, including ones
    that mention code or angle brackets in prose, must not be mangled."""
    normal = "Scan complete: 3 findings, all low severity. See <link> in the dashboard."
    msg = OutboundMessage(channel="mock", chat_id="alice", content=normal)

    await ChannelManager._send_once(channel, msg)

    sent_msg = channel._send_mock.await_args.args[0]
    assert sent_msg.content == normal
