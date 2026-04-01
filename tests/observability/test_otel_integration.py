"""Integration test: OTelHook is composed with _LoopHook in AgentLoop."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.providers.base import LLMResponse


@pytest.mark.asyncio
async def test_run_agent_loop_composes_otel_hook_when_enabled(tmp_path):
    """When otel.enabled=True, _run_agent_loop should use CompositeHook with OTelHook."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    with (
        patch("nanobot.agent.loop.ContextBuilder"),
        patch("nanobot.agent.loop.SessionManager"),
        patch("nanobot.agent.loop.SubagentManager") as MockSubMgr,
    ):
        MockSubMgr.return_value.cancel_by_session = AsyncMock(return_value=0)
        loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path)

    from nanobot.config.schema import OtelConfig

    loop._otel_config = OtelConfig(enabled=True)

    with (
        patch("nanobot.observability.otel.setup_otel"),
        patch("nanobot.observability.otel.get_meter", return_value=None),
        patch("nanobot.observability.otel.get_tracer", return_value=None),
    ):
        original_run = loop.runner.run
        captured_hook = {"hook": None}

        async def spy_run(spec):
            captured_hook["hook"] = spec.hook
            return await original_run(spec)

        loop.runner.run = spy_run

        provider.chat_with_retry = AsyncMock(
            return_value=LLMResponse(
                content="hello",
                tool_calls=[],
                usage={},
            )
        )
        loop.tools.get_definitions = MagicMock(return_value=[])

        await loop._run_agent_loop(
            [{"role": "user", "content": "hi"}],
            channel="telegram",
            chat_id="123",
        )

    from nanobot.agent.hook_composite import CompositeHook
    from nanobot.observability.hook import OTelHook

    assert isinstance(captured_hook["hook"], CompositeHook)
    assert any(isinstance(h, OTelHook) for h in captured_hook["hook"]._hooks)
