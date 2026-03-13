from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ACPBackendConfig
from nanobot.dispatch.acp import ACPDispatcher, _ProgressCoalescer, _SessionCapabilities


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
async def test_agentloop_set_model_updates_runtime_model() -> None:
    loop = _make_loop()

    response = await loop._process_message(
        InboundMessage(
            channel="cli",
            sender_id="user",
            chat_id="chat",
            content="/set_model anthropic/claude-3-7-sonnet",
        )
    )

    assert response is not None
    assert response.content == "Model switched to: anthropic/claude-3-7-sonnet"
    assert loop.model == "anthropic/claude-3-7-sonnet"
    assert loop.subagents.model == "anthropic/claude-3-7-sonnet"


@pytest.mark.asyncio
async def test_agentloop_help_mentions_new_commands() -> None:
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
    assert "/models" in response.content
    assert "/set_model" in response.content
    assert "/agents" in response.content
    assert "/set_agent" in response.content


@pytest.mark.asyncio
async def test_agentloop_set_agent_default_is_explicit_noop() -> None:
    loop = _make_loop()

    response = await loop._process_message(
        InboundMessage(
            channel="cli",
            sender_id="user",
            chat_id="chat",
            content="/set_agent default",
        )
    )

    assert response is not None
    assert response.content == "Native backend uses fixed agent: default (no change applied)"


@pytest.mark.asyncio
async def test_agentloop_set_agent_rejects_unknown_agent() -> None:
    loop = _make_loop()

    response = await loop._process_message(
        InboundMessage(
            channel="cli",
            sender_id="user",
            chat_id="chat",
            content="/set_agent build",
        )
    )

    assert response is not None
    assert response.content == "Native backend supports only: default"


class _DummyACPConn:
    def __init__(self) -> None:
        self.model_calls: list[tuple[str, str]] = []
        self.mode_calls: list[tuple[str, str]] = []

    async def set_session_model(self, model_id: str, session_id: str):
        self.model_calls.append((session_id, model_id))

    async def set_session_mode(self, mode_id: str, session_id: str):
        self.mode_calls.append((session_id, mode_id))


class _DummyACPConnWithSession(_DummyACPConn):
    def __init__(self) -> None:
        super().__init__()
        self.new_session_calls: list[tuple[str, list[Any]]] = []

    async def new_session(self, cwd: str, mcp_servers: list[Any]):
        self.new_session_calls.append((cwd, mcp_servers))
        return SimpleNamespace(session_id="sess-new")


class _DummyACPConnPromptOnly:
    async def prompt(self, prompt, session_id):
        del prompt, session_id
        return None


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


@pytest.mark.asyncio
async def test_acp_new_session_applies_configured_default_model_and_agent() -> None:
    bus = MessageBus()
    conn = _DummyACPConnWithSession()
    dispatcher = ACPDispatcher(
        bus=bus,
        workspace=Path("/tmp"),
        acp_config=ACPBackendConfig(
            default_model="anthropic/claude-sonnet-4",
            default_agent="build",
        ),
    )
    dispatcher._conn = cast(Any, conn)

    session_id = await dispatcher._ensure_session("cli:test")

    assert session_id == "sess-new"
    assert conn.new_session_calls
    assert conn.model_calls == [("sess-new", "anthropic/claude-sonnet-4")]
    assert conn.mode_calls == [("sess-new", "build")]
    assert dispatcher._session_caps["sess-new"].current_model == "anthropic/claude-sonnet-4"
    assert dispatcher._session_caps["sess-new"].current_agent == "build"


@pytest.mark.asyncio
async def test_acp_dispatch_forwards_progress_into_bus_outbound() -> None:
    bus = MessageBus()
    dispatcher = ACPDispatcher(
        bus=bus,
        workspace=Path("/tmp"),
        acp_config=ACPBackendConfig(),
    )
    dispatcher._conn = cast(Any, _DummyACPConnPromptOnly())

    async def _ensure_session(session_key: str) -> str:
        del session_key
        return "sess-1"

    async def _fake_process_direct(
        content: str,
        session_key: str,
        channel: str,
        chat_id: str,
        on_progress=None,
    ) -> str:
        del content, session_key, channel, chat_id
        assert on_progress is not None
        await on_progress("phase-1")
        await on_progress("tool-call", tool_hint=True)
        return "final-answer"

    cast(Any, dispatcher)._ensure_session = _ensure_session
    cast(Any, dispatcher).process_direct = _fake_process_direct

    await dispatcher._dispatch(
        InboundMessage(
            channel="telegram",
            sender_id="user",
            chat_id="123",
            content="hello",
            metadata={"message_id": 7},
        )
    )

    out_1 = await bus.consume_outbound()
    out_2 = await bus.consume_outbound()
    out_3 = await bus.consume_outbound()

    assert out_1.content == "phase-1"
    assert out_1.metadata["_progress"] is True
    assert out_1.metadata["_tool_hint"] is False
    assert out_1.metadata["message_id"] == 7

    assert out_2.content == "tool-call"
    assert out_2.metadata["_progress"] is True
    assert out_2.metadata["_tool_hint"] is True
    assert out_2.metadata["message_id"] == 7

    assert out_3.content == "final-answer"
    assert out_3.metadata["message_id"] == 7
    assert "_progress" not in out_3.metadata


@pytest.mark.asyncio
async def test_acp_dispatch_coalesces_text_progress_until_tool_hint() -> None:
    bus = MessageBus()
    dispatcher = ACPDispatcher(
        bus=bus,
        workspace=Path("/tmp"),
        acp_config=ACPBackendConfig(),
    )
    dispatcher._conn = cast(Any, _DummyACPConnPromptOnly())

    async def _ensure_session(session_key: str) -> str:
        del session_key
        return "sess-1"

    async def _fake_process_direct(
        content: str,
        session_key: str,
        channel: str,
        chat_id: str,
        on_progress=None,
    ) -> str:
        del content, session_key, channel, chat_id
        assert on_progress is not None
        await on_progress("我")
        await on_progress("我先")
        await on_progress("我先把")
        await on_progress('read_file("nanobot")', tool_hint=True)
        return "final-answer"

    cast(Any, dispatcher)._ensure_session = _ensure_session
    cast(Any, dispatcher).process_direct = _fake_process_direct

    await dispatcher._dispatch(
        InboundMessage(
            channel="telegram",
            sender_id="user",
            chat_id="123",
            content="hello",
            metadata={"message_id": 11},
        )
    )

    out_1 = await bus.consume_outbound()
    out_2 = await bus.consume_outbound()
    out_3 = await bus.consume_outbound()

    assert out_1.content == "我先把"
    assert out_1.metadata["_progress"] is True
    assert out_1.metadata["_tool_hint"] is False
    assert out_1.metadata["message_id"] == 11

    assert out_2.content == 'read_file("nanobot")'
    assert out_2.metadata["_progress"] is True
    assert out_2.metadata["_tool_hint"] is True

    assert out_3.content == "final-answer"
    assert "_progress" not in out_3.metadata


@pytest.mark.asyncio
async def test_progress_coalescer_idle_timeout_flushes_text() -> None:
    emitted: list[tuple[str, bool]] = []

    async def _publish(content: str, *, tool_hint: bool = False) -> None:
        emitted.append((content, tool_hint))

    coalescer = _ProgressCoalescer(publish=_publish, max_chars=1024, idle_flush_seconds=0.02)
    await coalescer.add_text("abc")
    await asyncio.sleep(0.06)

    assert emitted == [("abc", False)]
