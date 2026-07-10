import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.context import (
    RequestContext,
    bind_request_context,
    current_request_context,
    reset_request_context,
)
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse, ToolCallRequest


class _ContextRecordingTool:
    name = "cron"
    concurrency_safe = False

    def __init__(self) -> None:
        self.contexts: list[dict] = []

    def set_context(self, ctx: RequestContext) -> None:
        self.contexts.append({
            "channel": ctx.channel,
            "chat_id": ctx.chat_id,
            "metadata": ctx.metadata,
            "session_key": ctx.session_key,
        })

    async def execute(self, **_kwargs) -> str:
        return "created"


class _Tools:
    def __init__(self, tool: _ContextRecordingTool) -> None:
        self.tool = tool

    @property
    def tool_names(self) -> list[str]:
        return ["cron"]

    def get(self, name: str):
        return self.tool if name == "cron" else None

    def get_definitions(self) -> list:
        return []

    def prepare_call(self, name: str, arguments: dict):
        return (self.tool, arguments, None) if name == "cron" else (None, arguments, None)


@pytest.mark.asyncio
async def test_loop_hook_preserves_metadata_when_resetting_tool_context(tmp_path: Path) -> None:
    provider = MagicMock()
    calls = {"n": 0}

    async def chat_with_retry(**_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return LLMResponse(
                content=None,
                tool_calls=[ToolCallRequest(id="call_1", name="cron", arguments={"action": "add"})],
            )
        return LLMResponse(content="done", tool_calls=[])

    provider.chat_with_retry = chat_with_retry
    provider.get_default_model.return_value = "test-model"

    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )
    cron = _ContextRecordingTool()
    loop.tools = _Tools(cron)

    metadata = {"slack": {"thread_ts": "111.222", "channel_type": "channel"}}
    await loop._run_agent_loop(
        [],
        channel="slack",
        chat_id="C123",
        metadata=metadata,
        session_key="slack:C123:111.222",
    )

    assert cron.contexts[-1] == {
        "channel": "slack",
        "chat_id": "C123",
        "metadata": metadata,
        "session_key": "slack:C123:111.222",
    }


def test_request_context_nested_bind_restores_outer_context() -> None:
    outer = RequestContext(channel="slack", chat_id="outer", session_key="slack:outer")
    inner = RequestContext(channel="email", chat_id="inner", session_key="email:inner")

    outer_token = bind_request_context(outer)
    try:
        assert current_request_context() is outer
        inner_token = bind_request_context(inner)
        try:
            assert current_request_context() is inner
        finally:
            reset_request_context(inner_token)
        assert current_request_context() is outer
    finally:
        reset_request_context(outer_token)

    assert current_request_context() is None


@pytest.mark.asyncio
async def test_request_context_bindings_are_isolated_between_concurrent_tasks() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    async def observe(ctx: RequestContext, *, wait_first: bool) -> RequestContext | None:
        token = bind_request_context(ctx)
        try:
            if wait_first:
                entered.set()
                await release.wait()
            else:
                await entered.wait()
                release.set()
            await asyncio.sleep(0)
            return current_request_context()
        finally:
            reset_request_context(token)

    first = RequestContext(channel="feishu", chat_id="first", session_key="feishu:first")
    second = RequestContext(channel="telegram", chat_id="second", session_key="telegram:second")

    observed = await asyncio.gather(
        observe(first, wait_first=True),
        observe(second, wait_first=False),
    )

    assert observed == [first, second]
    assert current_request_context() is None


@pytest.mark.asyncio
async def test_agent_loop_restores_outer_request_context_after_runner_exception(
    tmp_path: Path,
) -> None:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )
    outer = RequestContext(channel="test", chat_id="outer", session_key="test:outer")

    async def fail_run(_spec):
        current = current_request_context()
        assert current is not None
        assert current.channel == "slack"
        assert current.chat_id == "C123"
        assert current.session_key == "slack:C123:111.222"
        raise RuntimeError("runner failed")

    loop.runner.run = AsyncMock(side_effect=fail_run)
    outer_token = bind_request_context(outer)
    try:
        with pytest.raises(RuntimeError, match="runner failed"):
            await loop._run_agent_loop(
                [],
                channel="slack",
                chat_id="C123",
                session_key="slack:C123:111.222",
            )
        assert current_request_context() is outer
    finally:
        reset_request_context(outer_token)

    assert current_request_context() is None
