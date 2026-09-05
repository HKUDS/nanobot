"""Tests for /stop preserving partial context from interrupted turns.

When /stop cancels an active task, the runtime checkpoint (tool results,
assistant messages accumulated so far) should be materialized into session
history rather than silently discarded.

See: https://github.com/HKUDS/nanobot/issues/2966
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.session.recovery import RUNTIME_CHECKPOINT_KEY


def _make_provider():
    """Create an LLM provider mock with required attributes."""
    from types import SimpleNamespace
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = SimpleNamespace(max_tokens=4096, temperature=0.1, reasoning_effort=None)
    provider.estimate_prompt_tokens.return_value = (10_000, "test")
    return provider


def _make_loop(tmp_path: Path) -> AgentLoop:
    """Create a real AgentLoop with mocked provider — avoids patching __init__."""
    bus = MessageBus()
    provider = _make_provider()
    with patch("nanobot.agent.loop.ContextBuilder"), \
         patch("nanobot.agent.loop.SessionManager", autospec=True), \
         patch("nanobot.agent.loop.SubagentManager") as mock_subagent_manager:
        mock_subagent_manager.return_value.cancel_by_session = AsyncMock(return_value=0)
        return AgentLoop(bus=bus, provider=provider, workspace=tmp_path)


@pytest.mark.asyncio
async def test_dispatch_cancellation_restores_checkpoint():
    """Regression for #2966: /stop interrupting _dispatch must materialize the
    in-flight runtime checkpoint into session.messages before the cancellation
    unwinds, so the next turn can see the partial work.

    This exercises the real _dispatch path (locks, pending queues, the
    CancelledError handler), so a future refactor that drops the cancel-time
    restore is caught by CI instead of silently regressing.
    """
    from nanobot.bus.events import InboundMessage
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    workspace = MagicMock()
    workspace.__truediv__ = MagicMock(return_value=MagicMock())

    with patch("nanobot.agent.loop.ContextBuilder"), \
         patch("nanobot.agent.loop.SessionManager", autospec=True), \
         patch("nanobot.agent.loop.SubagentManager") as mock_subagent_manager:
        mock_subagent_manager.return_value.cancel_by_session = AsyncMock(return_value=0)
        loop = AgentLoop(bus=bus, provider=provider, workspace=workspace)

    checkpoint_key = RUNTIME_CHECKPOINT_KEY
    session = SimpleNamespace(
        key="test:c1",
        metadata={
            checkpoint_key: {
                "phase": "awaiting_tools",
                "iteration": 0,
                "assistant_message": {
                    "role": "assistant",
                    "content": "Let me search.",
                    "tool_calls": [
                        {
                            "id": "tc_1",
                            "type": "function",
                            "function": {"name": "web_search", "arguments": "{}"},
                        }
                    ],
                },
                "completed_tool_results": [
                    {"role": "tool", "tool_call_id": "tc_1", "content": "Search hit."},
                ],
                "pending_tool_calls": [],
            }
        },
        messages=[{"role": "user", "content": "Search for something"}],
    )

    loop.sessions.get_or_create_async = AsyncMock(return_value=session)
    loop.sessions.save_async = AsyncMock()

    async def _cancel(*_args, **_kwargs):
        raise asyncio.CancelledError()

    loop._process_message = _cancel

    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="work")

    with pytest.raises(asyncio.CancelledError):
        await loop._dispatch(msg)

    roles = [m.get("role") for m in session.messages]
    assert roles == ["user", "assistant", "tool"], (
        "Expected the assistant message and completed tool result from the "
        f"interrupted turn to be materialized into session.messages; got {roles}"
    )
    assert checkpoint_key not in session.metadata, \
        "Checkpoint metadata should be cleared after restore"
    assert loop.sessions.save_async.called, \
        "Session should be persisted so the restored state survives process restart"


@pytest.mark.asyncio
async def test_dispatch_cancellation_keeps_checkpoint_for_gateway_shutdown(tmp_path: Path) -> None:
    """Gateway shutdown preserves the checkpoint; an explicit stop restores it."""
    loop = _make_loop(tmp_path)
    loop.preserve_inflight_turns_on_shutdown()
    checkpoint_key = RUNTIME_CHECKPOINT_KEY
    checkpoint = {
        "phase": "final_response",
        "assistant_message": {"role": "assistant", "content": "finished"},
        "completed_tool_results": [],
        "pending_tool_calls": [],
    }
    session = SimpleNamespace(
        metadata={checkpoint_key: checkpoint},
        messages=[],
        provider_state=None,
    )
    loop.sessions.get_or_create_async.return_value = session

    async def _cancel(*_args: object, **_kwargs: object) -> None:
        raise asyncio.CancelledError()

    loop._process_message = _cancel  # type: ignore[method-assign]

    from nanobot.bus.events import InboundMessage

    with pytest.raises(asyncio.CancelledError):
        await loop._dispatch(
            InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="work")
        )

    assert session.metadata[checkpoint_key] == checkpoint
    assert session.messages == []
