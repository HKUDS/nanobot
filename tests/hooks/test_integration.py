"""Integration tests: HookCenter with AgentLoop."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.hook import AgentHook
from nanobot.hooks.center import HookCenter, reset_center
from nanobot.hooks.context import HookContext


@pytest.fixture(autouse=True)
def _reset_global():
    reset_center()
    yield
    reset_center()


def _make_loop(tmp_path, hooks=None):
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation.max_tokens = 4096

    with patch("nanobot.agent.loop.ContextBuilder"), \
         patch("nanobot.agent.loop.SessionManager"), \
         patch("nanobot.agent.loop.SubagentManager") as mock_sub_mgr, \
         patch("nanobot.agent.loop.Consolidator"), \
         patch("nanobot.agent.loop.Dream"):
        mock_sub_mgr.return_value.cancel_by_session = AsyncMock(return_value=0)
        loop = AgentLoop(
            bus=bus, provider=provider, workspace=tmp_path, hooks=hooks,
        )
    return loop


class TestAgentLoopIntegration:
    def test_loop_initializes_hook_center(self, tmp_path):
        loop = _make_loop(tmp_path)
        assert hasattr(loop, "_hook_center")
        assert isinstance(loop._hook_center, HookCenter)

    def test_loop_discovers_plugins_on_init(self, tmp_path):
        async def my_handler(ctx: HookContext) -> None:
            pass

        with patch(
            "nanobot.hooks.discovery.discover_hook_plugins",
            return_value={"test_plugin": {"my.point": my_handler}},
        ):
            loop = _make_loop(tmp_path)

        assert len(loop._hook_center.get_handlers("my.point")) == 1

    @pytest.mark.asyncio
    async def test_existing_agent_hooks_still_work(self, tmp_path):
        from nanobot.providers.base import LLMResponse

        events: list[str] = []

        class TrackingHook(AgentHook):
            async def before_iteration(self, context):
                events.append("before_iter")

        loop = _make_loop(tmp_path, hooks=[TrackingHook()])
        loop.provider.chat_with_retry = AsyncMock(
            return_value=LLMResponse(content="done", tool_calls=[], usage={})
        )
        loop.tools.get_definitions = MagicMock(return_value=[])

        content, _, _, _, _ = await loop._run_agent_loop(
            [{"role": "user", "content": "hi"}]
        )
        assert content == "done"
        assert "before_iter" in events

    @pytest.mark.asyncio
    async def test_plugin_failure_does_not_crash_loop(self, tmp_path):
        with patch(
            "nanobot.hooks.discovery.discover_hook_plugins",
            side_effect=RuntimeError("boom"),
        ):
            loop = _make_loop(tmp_path)

        assert isinstance(loop._hook_center, HookCenter)

    def test_standard_hook_points_registered(self, tmp_path):
        loop = _make_loop(tmp_path)
        points = loop._hook_center.get_point_names()
        assert "agent.before_iteration" in points
        assert "agent.after_iteration" in points
        assert "agent.before_execute_tools" in points
        assert "agent.on_stream_end" in points

    @pytest.mark.asyncio
    async def test_emit_fired_on_before_iteration(self, tmp_path):
        from nanobot.providers.base import LLMResponse

        received: list[HookContext] = []

        async def capture_handler(ctx: HookContext):
            received.append(ctx)
            return None

        loop = _make_loop(tmp_path)
        loop._hook_center.register_handler("agent.before_iteration", capture_handler)
        loop.provider.chat_with_retry = AsyncMock(
            return_value=LLMResponse(content="ok", tool_calls=[], usage={})
        )
        loop.tools.get_definitions = MagicMock(return_value=[])

        await loop._run_agent_loop([{"role": "user", "content": "hi"}])
        assert len(received) >= 1
        assert received[0].data["iteration"] == 0

    @pytest.mark.asyncio
    async def test_cancel_before_iteration_stops_run(self, tmp_path):
        from nanobot.hooks.context import HookResult
        from nanobot.providers.base import LLMResponse

        llm_calls = 0

        async def cancel_handler(ctx: HookContext):
            return HookResult(action="cancel", reason="blocked")

        loop = _make_loop(tmp_path)
        loop._hook_center.register_handler("agent.before_iteration", cancel_handler)
        loop.provider.chat_with_retry = AsyncMock(
            side_effect=lambda *a, **kw: (
                llm_calls.__add__(1) or LLMResponse(content="ok", tool_calls=[], usage={})
            )
        )
        loop.tools.get_definitions = MagicMock(return_value=[])

        content, tools_used, _, stop_reason, _ = await loop._run_agent_loop(
            [{"role": "user", "content": "hi"}]
        )
        assert stop_reason == "hook_cancelled"

    @pytest.mark.asyncio
    async def test_cancel_before_execute_tools_stops_run(self, tmp_path):
        from nanobot.hooks.context import HookResult
        from nanobot.providers.base import LLMResponse, ToolCallRequest

        async def cancel_handler(ctx: HookContext):
            if ctx.get("tool_calls"):
                return HookResult(action="cancel", reason="no_tools")
            return None

        tc = ToolCallRequest(
            id="call_1", name="read_file", arguments={"path": "/tmp/test"}
        )
        loop = _make_loop(tmp_path)
        loop._hook_center.register_handler("agent.before_execute_tools", cancel_handler)
        loop.provider.chat_with_retry = AsyncMock(
            return_value=LLMResponse(content="", tool_calls=[tc], usage={})
        )
        loop.tools.get_definitions = MagicMock(return_value=[])

        content, tools_used, _, stop_reason, _ = await loop._run_agent_loop(
            [{"role": "user", "content": "hi"}]
        )
        assert stop_reason == "hook_cancelled"
