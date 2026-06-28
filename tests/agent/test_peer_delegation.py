"""Tests for A2A peer-agent delegation (#4179).

Covers the peer roster, role-scoped subagent execution (custom system prompt +
model), the ``delegate`` tool's gating/validation, and the cross-delegation
depth guard that bounds A→B→C chains.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from nanobot.agent.runner import AgentRunResult
from nanobot.agent.subagent import (
    _CURRENT_DELEGATION_DEPTH,
    SubagentManager,
    SubagentStatus,
    current_delegation_depth,
)
from nanobot.agent.tools.context import RequestContext, ToolContext
from nanobot.agent.tools.delegate import DelegateTool
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import AgentsConfig, PeerAgentConfig
from nanobot.providers.base import LLMProvider


def _manager(peers=None, max_delegation_depth=3, max_concurrent_subagents=8):
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "parent-model"
    return SubagentManager(
        provider=provider,
        workspace=Path("/tmp"),
        bus=MessageBus(),
        model="parent-model",
        max_tool_result_chars=16_000,
        max_concurrent_subagents=max_concurrent_subagents,
        peers={p.name: p for p in (peers or [])},
        max_delegation_depth=max_delegation_depth,
    )


def _status():
    return SubagentStatus(task_id="t1", label="l", task_description="task", started_at=0.0)


# --- Role-scoped execution ---------------------------------------------------


@pytest.mark.asyncio
async def test_peer_system_prompt_and_model_reach_runner():
    """A peer's system prompt and model override the generic subagent persona."""
    peer = PeerAgentConfig(
        name="researcher",
        role="gathers sources",
        system_prompt="You are Researcher. Find primary sources.",
        model="peer-model",
    )
    sm = _manager(peers=[peer])
    sm.runner.run = AsyncMock(
        return_value=AgentRunResult(final_content="ok", messages=[], stop_reason="completed")
    )
    sm._announce_result = AsyncMock()

    await sm._run_subagent(
        "t1", "task", "researcher", {"channel": "cli", "chat_id": "direct"}, _status(),
        peer_cfg=peer, delegation_depth=1,
    )

    spec = sm.runner.run.call_args.args[0]
    assert spec.model == "peer-model"
    assert spec.initial_messages[0]["content"] == "You are Researcher. Find primary sources."


@pytest.mark.asyncio
async def test_peer_without_overrides_falls_back_to_defaults():
    """A peer with no system_prompt/model reuses the shared subagent prompt/model."""
    peer = PeerAgentConfig(name="writer", role="drafts replies")
    sm = _manager(peers=[peer])
    sm.runner.run = AsyncMock(
        return_value=AgentRunResult(final_content="ok", messages=[], stop_reason="completed")
    )
    sm._announce_result = AsyncMock()

    await sm._run_subagent(
        "t1", "task", "writer", {"channel": "cli", "chat_id": "direct"}, _status(),
        peer_cfg=peer, delegation_depth=1,
    )

    spec = sm.runner.run.call_args.args[0]
    assert spec.model == "parent-model"
    # Default subagent prompt is rendered, not an empty/peer-specific one.
    assert spec.initial_messages[0]["content"]
    assert "You are Researcher" not in spec.initial_messages[0]["content"]


@pytest.mark.asyncio
async def test_non_peer_subagent_unaffected():
    """Plain spawn (no peer) keeps the default model and prompt."""
    sm = _manager()
    sm.runner.run = AsyncMock(
        return_value=AgentRunResult(final_content="ok", messages=[], stop_reason="completed")
    )
    sm._announce_result = AsyncMock()

    await sm._run_subagent(
        "t1", "task", "label", {"channel": "cli", "chat_id": "direct"}, _status(),
    )

    spec = sm.runner.run.call_args.args[0]
    assert spec.model == "parent-model"


@pytest.mark.asyncio
async def test_delegation_depth_visible_during_run():
    """The running peer observes its delegation depth via the contextvar."""
    peer = PeerAgentConfig(name="researcher")
    sm = _manager(peers=[peer])
    seen = {}

    async def _capture(spec):
        seen["depth"] = current_delegation_depth()
        return AgentRunResult(final_content="ok", messages=[], stop_reason="completed")

    sm.runner.run = AsyncMock(side_effect=_capture)
    sm._announce_result = AsyncMock()

    await sm._run_subagent(
        "t1", "task", "researcher", {"channel": "cli", "chat_id": "direct"}, _status(),
        peer_cfg=peer, delegation_depth=2,
    )

    assert seen["depth"] == 2
    # Restored after the run completes.
    assert current_delegation_depth() == 0


# --- delegate tool: gating + validation -------------------------------------


def _ctx(manager):
    return ToolContext(config=None, workspace="/tmp", subagent_manager=manager)


def test_delegate_tool_disabled_without_peers():
    assert DelegateTool.enabled(_ctx(_manager())) is False


def test_delegate_tool_enabled_with_peers():
    sm = _manager(peers=[PeerAgentConfig(name="researcher")])
    assert DelegateTool.enabled(_ctx(sm)) is True


def test_delegate_tool_description_lists_roster():
    sm = _manager(peers=[PeerAgentConfig(name="researcher", role="finds sources")])
    tool = DelegateTool(manager=sm)
    assert "researcher" in tool.description
    assert "finds sources" in tool.description


@pytest.mark.asyncio
async def test_delegate_unknown_peer_errors():
    sm = _manager(peers=[PeerAgentConfig(name="researcher")])
    sm.spawn = AsyncMock()
    tool = DelegateTool(manager=sm)
    tool.set_context(RequestContext(channel="cli", chat_id="direct", session_key="cli:direct"))

    result = await tool.execute(peer="ghost", task="do it")

    assert "unknown peer" in result.lower()
    assert "researcher" in result
    sm.spawn.assert_not_awaited()


@pytest.mark.asyncio
async def test_delegate_forwards_peer_and_increments_depth():
    sm = _manager(peers=[PeerAgentConfig(name="researcher")])
    sm.spawn = AsyncMock(return_value="started")
    tool = DelegateTool(manager=sm)
    tool.set_context(RequestContext(channel="cli", chat_id="direct", session_key="cli:direct"))

    token = _CURRENT_DELEGATION_DEPTH.set(1)
    try:
        result = await tool.execute(peer="researcher", task="find sources")
    finally:
        _CURRENT_DELEGATION_DEPTH.reset(token)

    assert result == "started"
    kwargs = sm.spawn.call_args.kwargs
    assert kwargs["peer"] == "researcher"
    assert kwargs["delegation_depth"] == 2


# --- depth guard (floor control) --------------------------------------------


@pytest.mark.asyncio
async def test_delegate_refused_at_max_depth():
    sm = _manager(peers=[PeerAgentConfig(name="researcher")], max_delegation_depth=2)
    sm.spawn = AsyncMock()
    tool = DelegateTool(manager=sm)
    tool.set_context(RequestContext(channel="cli", chat_id="direct", session_key="cli:direct"))

    token = _CURRENT_DELEGATION_DEPTH.set(2)  # already at the cap
    try:
        result = await tool.execute(peer="researcher", task="recurse")
    finally:
        _CURRENT_DELEGATION_DEPTH.reset(token)

    assert "maximum delegation depth" in result.lower()
    sm.spawn.assert_not_awaited()


@pytest.mark.asyncio
async def test_delegate_allowed_below_max_depth():
    sm = _manager(peers=[PeerAgentConfig(name="researcher")], max_delegation_depth=2)
    sm.spawn = AsyncMock(return_value="started")
    tool = DelegateTool(manager=sm)
    tool.set_context(RequestContext(channel="cli", chat_id="direct", session_key="cli:direct"))

    token = _CURRENT_DELEGATION_DEPTH.set(1)  # below the cap
    try:
        result = await tool.execute(peer="researcher", task="ok")
    finally:
        _CURRENT_DELEGATION_DEPTH.reset(token)

    assert result == "started"
    sm.spawn.assert_awaited_once()


# --- config validation -------------------------------------------------------


def test_duplicate_peer_names_rejected():
    with pytest.raises(ValidationError, match="duplicate peer name"):
        AgentsConfig(peers=[PeerAgentConfig(name="researcher"), PeerAgentConfig(name="researcher")])


def test_unique_peer_names_accepted():
    cfg = AgentsConfig(peers=[PeerAgentConfig(name="researcher"), PeerAgentConfig(name="writer")])
    assert [p.name for p in cfg.peers] == ["researcher", "writer"]
