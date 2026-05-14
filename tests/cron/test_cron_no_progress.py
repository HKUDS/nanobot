"""Verify that cron job execution does not leak intermediate progress messages
to the bus.

When the agent works through a cron task it produces progress events (thinking
text and tool-call hints) that are intended for interactive sessions only.
For scheduled jobs the user expects a single final result, not a stream of
intermediate messages.  The fix mirrors the approach already used by the
heartbeat handler: pass a no-op on_progress to process_direct() so that
_bus_progress is never installed as the fallback.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse, ToolCallRequest


def _make_loop(tmp_path: Path) -> tuple[AgentLoop, MessageBus]:
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")
    return loop, bus


def _collect_outbound(bus: MessageBus) -> list[OutboundMessage]:
    """Drain all messages currently in the outbound queue."""
    messages: list[OutboundMessage] = []
    while True:
        try:
            messages.append(bus.outbound.get_nowait())
        except Exception:
            break
    return messages


@pytest.mark.asyncio
async def test_cron_job_produces_no_progress_messages(tmp_path: Path) -> None:
    """process_direct with a no-op on_progress must not publish _progress messages."""
    loop, bus = _make_loop(tmp_path)

    tool_call = ToolCallRequest(id="c1", name="read_file", arguments={"path": "x.txt"})
    responses = iter([
        LLMResponse(content="Checking…", tool_calls=[tool_call]),
        LLMResponse(content="Here is the summary.", tool_calls=[]),
    ])
    loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(responses))
    loop.tools.get_definitions = MagicMock(return_value=[])
    loop.tools.execute = AsyncMock(return_value="file content")

    async def _silent(*_args, **_kwargs) -> None:
        pass

    await loop.process_direct(
        "Summarise the file",
        session_key="cron:test123",
        channel="telegram",
        chat_id="user42",
        on_progress=_silent,
    )

    outbound = _collect_outbound(bus)
    progress_messages = [m for m in outbound if (m.metadata or {}).get("_progress")]
    assert progress_messages == [], (
        f"Expected no progress messages but got: {[m.content for m in progress_messages]}"
    )


@pytest.mark.asyncio
async def test_without_on_progress_bus_receives_progress_messages(tmp_path: Path) -> None:
    """Confirm the bug: without on_progress, _bus_progress forwards intermediate
    messages to the bus.  This test documents the behaviour that the fix prevents.
    """
    loop, bus = _make_loop(tmp_path)

    tool_call = ToolCallRequest(id="c1", name="read_file", arguments={"path": "x.txt"})
    responses = iter([
        LLMResponse(content="Checking…", tool_calls=[tool_call]),
        LLMResponse(content="Here is the summary.", tool_calls=[]),
    ])
    loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(responses))
    loop.tools.get_definitions = MagicMock(return_value=[])
    loop.tools.execute = AsyncMock(return_value="file content")

    # No on_progress passed — _bus_progress fallback is active
    await loop.process_direct(
        "Summarise the file",
        session_key="cron:test456",
        channel="telegram",
        chat_id="user42",
    )

    outbound = _collect_outbound(bus)
    progress_messages = [m for m in outbound if (m.metadata or {}).get("_progress")]
    assert progress_messages, "Expected progress messages to appear when on_progress is not suppressed"
