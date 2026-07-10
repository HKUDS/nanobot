"""Temporary change-amplification probe for the runtime foundation."""

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.tools.context import RequestContext, current_request_context, request_context
from nanobot.agent.tools.spawn import SpawnTool
from nanobot.providers.base import GenerationSettings, LLMResponse


@pytest.mark.asyncio
async def test_runtime_probe_reaches_all_consumers_without_new_plumbing(loop_factory) -> None:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings(temperature=0.1, max_tokens=1024)
    provider.chat_with_retry = AsyncMock(
        return_value=LLMResponse(content="ok", tool_calls=[]),
    )
    loop = loop_factory(provider=provider, context_window_tokens=32_768)
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock()
    loop._schedule_background = lambda coro: coro.close()

    runtime = replace(loop.llm_runtime(), runtime_probe="session:probe")
    seen: dict[str, object] = {}
    original_runner_run = loop.runner.run

    async def observe_runner(spec):
        seen["runner"] = spec.runtime
        seen["request_context"] = current_request_context()
        return await original_runner_run(spec)

    loop.runner.run = observe_runner
    await loop.process_direct("probe", session_key="sdk:probe", runtime=runtime)

    assert seen["runner"] is runtime
    request_ctx = seen["request_context"]
    assert isinstance(request_ctx, RequestContext)
    assert request_ctx.runtime is runtime
    assert all(
        call.kwargs["runtime"] is runtime
        for call in loop.consolidator.maybe_consolidate_by_tokens.call_args_list
    )

    async def observe_subagent(*args):
        seen["subagent"] = args[5]

    loop.subagents._run_subagent = AsyncMock(side_effect=observe_subagent)
    tool = SpawnTool(loop.subagents)
    with request_context(request_ctx):
        result = await tool.execute(task="observe the runtime probe")

    tasks = list(loop.subagents._running_tasks.values())
    await asyncio.gather(*tasks)

    assert "started" in result
    assert seen["subagent"] is runtime
    assert runtime.runtime_probe == "session:probe"
