"""Caller-controlled continuation respects live state and the runner budget."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.runner_helpers import make_run_spec
from nanobot.agent.runner import AgentRunner
from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMProvider, LLMResponse


@pytest.fixture
def run_spec():
    provider = MagicMock(spec=LLMProvider)
    provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="all done"))
    tools = MagicMock()
    tools.get_definitions.return_value = []
    return make_run_spec(
        provider,
        initial_messages=[{"role": "user", "content": "do task"}],
        tools=tools,
        model="test-model",
        max_iterations=3,
        max_tool_result_chars=AgentDefaults().max_tool_result_chars,
    )


@pytest.mark.parametrize("callback", [None, lambda: None], ids=["absent", "no-request"])
async def test_runner_completes_without_a_continuation_request(run_spec, callback):
    run_spec.continuation_callback = callback

    result = await AgentRunner().run(run_spec)

    assert result.stop_reason == "completed"
    assert result.final_content == "all done"
    assert run_spec.runtime.provider.chat_stream_with_retry.await_count == 1


@pytest.mark.parametrize("max_iterations,finalize", [(1, True), (3, True), (8, False)])
async def test_continuation_injects_text_without_exceeding_budget(run_spec, max_iterations, finalize):
    continuation = "Continue working toward the active sustained goal."
    run_spec.max_iterations = max_iterations
    run_spec.finalize_on_max_iterations = finalize
    run_spec.continuation_callback = lambda: continuation

    result = await AgentRunner().run(run_spec)

    assert result.stop_reason == "max_iterations"
    requests = run_spec.runtime.provider.chat_stream_with_retry.await_args_list
    assert len(requests) == max_iterations + int(finalize)
    assert {"role": "user", "content": continuation} in result.messages
    if max_iterations > 1:
        assert {"role": "user", "content": continuation} in requests[1].kwargs["messages"]
    if finalize:
        assert not requests[-1].kwargs.get("tools")


async def test_runner_does_not_request_continuation_on_error(run_spec):
    run_spec.runtime.provider.chat_stream_with_retry.return_value = LLMResponse(
        content=None, finish_reason="error",
    )
    callback = MagicMock(return_value="Continue working.")
    run_spec.continuation_callback = callback

    result = await AgentRunner().run(run_spec)

    assert result.stop_reason == "error"
    assert run_spec.runtime.provider.chat_stream_with_retry.await_count == 1
    callback.assert_not_called()


async def test_runner_reads_continuation_state_after_each_response(run_spec):
    continuation = None
    calls = 0

    async def respond(**kwargs):
        nonlocal continuation, calls
        calls += 1
        if calls == 1:
            continuation = "Write the article draft."
            return LLMResponse(content="The goal is now active.")
        assert {"role": "user", "content": continuation} in kwargs["messages"]
        continuation = None
        return LLMResponse(content="The draft is complete.")

    run_spec.runtime.provider.chat_stream_with_retry.side_effect = respond
    run_spec.continuation_callback = lambda: continuation

    result = await AgentRunner().run(run_spec)

    assert calls == 2
    assert result.stop_reason == "completed"
    assert result.final_content == "The draft is complete."
