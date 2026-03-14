from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ACPBackendConfig
from nanobot.dispatch.acp import ACPDispatcher, _SessionCapabilities


def _make_loop():
    from nanobot.agent.loop import AgentLoop

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    workspace = MagicMock()
    workspace.__truediv__ = MagicMock(return_value=MagicMock())

    with (
        patch("nanobot.agent.loop.ContextBuilder"),
        patch("nanobot.agent.loop.SessionManager"),
        patch("nanobot.agent.loop.SubagentManager") as mock_sub_mgr,
    ):
        mock_sub_mgr.return_value.cancel_by_session = AsyncMock(return_value=0)
        loop = AgentLoop(bus=bus, provider=provider, workspace=workspace)
    return loop


@pytest.mark.asyncio
async def test_agentloop_help_matches_main_command_set() -> None:
    loop = _make_loop()

    response = await loop._process_message(
        InboundMessage(
            channel="cli",
            sender_id="user",
            chat_id="chat",
            content="/help",
        )
    )

    assert response is not None
    assert "/restart" in response.content
    assert "/models" not in response.content
    assert "/set_model" not in response.content


class _DummyACPConn:
    def __init__(self) -> None:
        self.model_calls: list[tuple[str, str]] = []
        self.mode_calls: list[tuple[str, str]] = []

    async def set_session_model(self, model_id: str, session_id: str):
        self.model_calls.append((session_id, model_id))

    async def set_session_mode(self, mode_id: str, session_id: str):
        self.mode_calls.append((session_id, mode_id))


def _make_acp_dispatcher() -> tuple[ACPDispatcher, MessageBus, _DummyACPConn]:
    bus = MessageBus()
    conn = _DummyACPConn()
    dispatcher = ACPDispatcher(
        bus=bus,
        workspace=Path("/tmp"),
        acp_config=ACPBackendConfig(),
    )
    dispatcher._conn = cast(Any, conn)
    caps = _SessionCapabilities()
    caps.available_models = ["opencode/big-pickle", "anthropic/claude-sonnet-4"]
    caps.current_model = "opencode/big-pickle"
    caps.available_agents = ["build", "plan"]
    caps.current_agent = "build"
    dispatcher._session_caps["sess-1"] = caps

    async def _ensure_session(session_key: str) -> str:
        _ = session_key
        return "sess-1"

    dispatcher._ensure_session = _ensure_session  # type: ignore[method-assign]
    return dispatcher, bus, conn


@pytest.mark.asyncio
async def test_acp_models_command_lists_cached_models() -> None:
    dispatcher, bus, _ = _make_acp_dispatcher()
    await dispatcher._dispatch(
        InboundMessage(
            channel="cli",
            sender_id="user",
            chat_id="chat",
            content="/models",
        )
    )
    out = await bus.consume_outbound()
    assert "Available models:" in out.content
    assert "opencode/big-pickle" in out.content


@pytest.mark.asyncio
async def test_acp_set_model_and_set_agent_call_connection() -> None:
    dispatcher, bus, conn = _make_acp_dispatcher()

    await dispatcher._dispatch(
        InboundMessage(
            channel="cli",
            sender_id="user",
            chat_id="chat",
            content="/set_model anthropic/claude-sonnet-4",
        )
    )
    out_model = await bus.consume_outbound()
    assert out_model.content == "Model switched to: anthropic/claude-sonnet-4"
    assert conn.model_calls == [("sess-1", "anthropic/claude-sonnet-4")]

    await dispatcher._dispatch(
        InboundMessage(
            channel="cli",
            sender_id="user",
            chat_id="chat",
            content="/set_agent plan",
        )
    )
    out_agent = await bus.consume_outbound()
    assert out_agent.content == "Agent switched to: plan"
    assert conn.mode_calls == [("sess-1", "plan")]
