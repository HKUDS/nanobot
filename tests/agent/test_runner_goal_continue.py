from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.runner_helpers import make_run_spec
from nanobot.agent.hook import AgentHook
from nanobot.agent.runner import AgentRunner
from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import (
    LLMProvider,
    LLMResponse,
    LLMUsage,
    ProviderConversationState,
    ToolCallRequest,
)
from nanobot.utils.runtime import EMPTY_FINAL_RESPONSE_MESSAGE


@pytest.fixture
def run_spec():
    provider = MagicMock(spec=LLMProvider)
    provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="all done"))
    provider.supports_native_compaction.return_value = False
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="tool result")
    return make_run_spec(
        provider,
        initial_messages=[{"role": "user", "content": "do task"}],
        tools=tools,
        model="test-model",
        max_iterations=3,
        max_tool_result_chars=AgentDefaults().max_tool_result_chars,
    )


@pytest.mark.parametrize("callback", [None, AsyncMock(return_value=None)], ids=["absent", "no-request"])
async def test_runner_completes_without_a_continuation_request(run_spec, callback):
    run_spec.continuation_callback = callback
    result = await AgentRunner().run(run_spec)
    assert result.stop_reason == "completed"
    assert result.final_content == "all done"
    assert run_spec.runtime.provider.chat_stream_with_retry.await_count == 1


async def test_continuation_extends_budget_without_reset(run_spec):
    run_spec.max_iterations = 1
    total_rounds = 14
    calls = 0

    async def respond(**kwargs):
        nonlocal calls
        calls += 1
        if calls > 1:
            assert kwargs["messages"][-1]["content"] == f"Continue goal step {calls - 1}."
        return LLMResponse(
            content="all done" if calls == total_rounds else f"Progress {calls}.",
            usage=LLMUsage.reported(input_tokens=1, output_tokens=1),
        )

    async def continuation():
        return f"Continue goal step {calls}." if calls < total_rounds else None

    run_spec.runtime.provider.chat_stream_with_retry.side_effect = respond
    run_spec.continuation_callback = AsyncMock(side_effect=continuation)
    run_spec.hook = AgentHook()
    run_spec.hook.before_iteration = AsyncMock()

    result = await AgentRunner().run(run_spec)

    assert result.stop_reason == "completed"
    assert result.final_content == "all done"
    assert result.had_injections is True
    assert calls == total_rounds
    assert run_spec.continuation_callback.await_count == total_rounds
    assert [
        call.args[0].iteration for call in run_spec.hook.before_iteration.await_args_list
    ] == list(range(total_rounds))
    continuations = [row for row in result.messages if row.get("_hidden_history")]
    assert len(continuations) == total_rounds - 1
    assert all(row["_hidden_history"] == {"kind": "internal_continuation"} for row in continuations)
    assert len(result.round_usages) == total_rounds
    assert result.usage.request_count == total_rounds
    assert result.usage.total_tokens == total_rounds * 2


@pytest.mark.parametrize("finalize,finalization_fails", [(True, False), (False, False), (True, True)])
async def test_goal_closing_after_tool_overrun_gets_bounded_finalization(run_spec, finalize, finalization_fails):
    run_spec.max_iterations = 1
    run_spec.finalize_on_max_iterations = finalize
    run_spec.max_iterations_message = "limit reached"
    goal_active = True
    tool_rounds = 14
    completed_tools = 0

    async def respond(**kwargs):
        if goal_active:
            assert kwargs["tools"] is not None
            return LLMResponse(
                content=None,
                tool_calls=[ToolCallRequest(id=f"work-{completed_tools}", name="work", arguments={})],
                usage=LLMUsage.reported(input_tokens=1, output_tokens=1),
            )
        assert kwargs["tools"] is None
        assert kwargs["messages"][-2]["content"] == "goal completed"
        assert kwargs["messages"][-1]["content"] == (
            "Please provide your response to the user based on the conversation above."
        )
        return LLMResponse(
            content="Provider unavailable." if finalization_fails else "All goal work is complete.",
            finish_reason="error" if finalization_fails else "stop",
            usage=LLMUsage.reported(input_tokens=2, output_tokens=3),
        )

    async def execute(*_args, **_kwargs):
        nonlocal goal_active, completed_tools
        completed_tools += 1
        goal_active = completed_tools < tool_rounds
        return "work completed" if goal_active else "goal completed"

    async def continuation():
        return "Continue the goal." if goal_active else None

    run_spec.runtime.provider.chat_stream_with_retry.side_effect = respond
    run_spec.tools.execute.side_effect = execute
    run_spec.continuation_callback = AsyncMock(side_effect=continuation)
    run_spec.hook = AgentHook()
    run_spec.hook.finalize_content = MagicMock(side_effect=lambda _context, content: content)

    result = await AgentRunner().run(run_spec)

    assert completed_tools == tool_rounds
    assert result.tools_used == ["work"] * tool_rounds
    if finalization_fails:
        assert result.stop_reason == "empty_final_response"
        assert result.error == result.final_content == EMPTY_FINAL_RESPONSE_MESSAGE
    else:
        assert result.stop_reason == ("completed" if finalize else "max_iterations")
        assert result.final_content == ("All goal work is complete." if finalize else "limit reached")
    assert result.pending_stream_content == (result.final_content if finalize else None)
    assert result.messages[-1]["content"] == result.final_content
    assert run_spec.runtime.provider.chat_stream_with_retry.await_count == tool_rounds + int(finalize)
    assert run_spec.continuation_callback.await_count == tool_rounds
    assert result.usage.request_count == tool_rounds + int(finalize)
    assert len(result.round_usages) == tool_rounds + int(finalize)
    if finalize and not finalization_fails:
        assert run_spec.hook.finalize_content.call_args.args[0].iteration == tool_rounds


@pytest.mark.parametrize("finish_reason", ["error", "refusal", "content_filter"])
@pytest.mark.parametrize("tool_name", ["work", ""], ids=["valid-call", "malformed-call"])
async def test_runner_does_not_auto_continue_terminal_provider_response(run_spec, finish_reason, tool_name):
    run_spec.max_iterations = 1
    run_spec.runtime.provider.chat_stream_with_retry.side_effect = [
        LLMResponse(
            content="Provider stopped this request.", finish_reason=finish_reason,
            tool_calls=[ToolCallRequest(id="blocked", name=tool_name, arguments={})],
        ),
        AssertionError("terminal response must not trigger another model request"),
    ]
    callback = AsyncMock(return_value="Continue working.")
    run_spec.continuation_callback = callback

    result = await AgentRunner().run(run_spec)

    assert result.stop_reason == ("error" if finish_reason == "error" else "completed")
    assert result.final_content == "Provider stopped this request."
    assert run_spec.runtime.provider.chat_stream_with_retry.await_count == 1
    run_spec.tools.execute.assert_not_awaited()
    callback.assert_not_awaited()


@pytest.mark.parametrize("response_kind", ["text", "tool"])
async def test_real_followup_precedes_goal_at_iteration_cap(run_spec, response_kind):
    followup = {"role": "user", "content": "Stop the goal and answer this instead."}
    pending = []
    goal_active = True
    requests = []
    run_spec.max_iterations = 1

    async def respond(**kwargs):
        requests.append(kwargs["messages"])
        if len(requests) == 1:
            pending.append(followup)
            return (
                LLMResponse(content="Goal checkpoint.") if response_kind == "text" else
                LLMResponse(content=None, tool_calls=[
                    ToolCallRequest(id="work", name="work", arguments={}),
                ])
            )
        assert kwargs["messages"][-1] == followup
        assert not goal_active
        return LLMResponse(content="Follow-up answered.")

    async def drain():
        nonlocal goal_active
        batch = list(pending)
        pending.clear()
        if batch:
            goal_active = False
        return batch

    async def continuation():
        return "Continue the goal." if goal_active else None

    run_spec.runtime.provider.chat_stream_with_retry.side_effect = respond
    run_spec.injection_callback = drain
    run_spec.continuation_callback = continuation
    result = await AgentRunner().run(run_spec)

    assert len(requests) == 2
    assert pending == []
    assert result.stop_reason == "completed"
    assert result.final_content == "Follow-up answered."
    assert result.had_injections is True


@pytest.mark.parametrize("response_kind", ["text", "tool"])
async def test_runner_propagates_continuation_failure(run_spec, response_kind):
    run_spec.max_iterations = 1
    if response_kind == "tool":
        run_spec.runtime.provider.chat_stream_with_retry.return_value = LLMResponse(
            content=None, tool_calls=[ToolCallRequest(id="work", name="work", arguments={})],
        )
    run_spec.continuation_callback = AsyncMock(side_effect=RuntimeError("goal lookup failed"))
    with pytest.raises(RuntimeError, match="goal lookup failed"):
        await AgentRunner().run(run_spec)
    assert run_spec.runtime.provider.chat_stream_with_retry.await_count == 1


@pytest.mark.parametrize("response_kind", ["text", "tool"])
async def test_continuation_preserves_transcript_checkpoints_and_provider_state(run_spec, tmp_path, response_kind):
    from nanobot.agent.tools.filesystem import ListDirTool
    from nanobot.agent.tools.registry import ToolRegistry

    (tmp_path / "evidence.txt").write_text("evidence", encoding="utf-8")
    tools = ToolRegistry()
    tools.register(ListDirTool(workspace=tmp_path, allowed_dir=tmp_path))
    run_spec.tools = tools
    run_spec.max_iterations = 1
    state = ProviderConversationState(
        kind="openai_responses", provider="openai:test", model="test-model",
        version=1, payload={"items": []},
    )
    final_state = ProviderConversationState(
        kind="openai_responses", provider="openai:test", model="test-model",
        version=1, payload={"items": [{"type": "message", "role": "assistant"}]},
    )
    run_spec.runtime.provider.can_resume_conversation_state.return_value = True
    goal_active = True
    requests = []

    async def respond(**kwargs):
        nonlocal goal_active
        requests.append(kwargs)
        if len(requests) == 1:
            return (
                LLMResponse(content="Observed evidence.", provider_state=state)
                if response_kind == "text" else
                LLMResponse(content=None, provider_state=state, tool_calls=[
                    ToolCallRequest(id="list", name="list_dir", arguments={"path": "."}),
                ])
            )
        goal_active = False
        return LLMResponse(content="Final evidence summary.", provider_state=final_state)

    async def continuation():
        return "Continue." if goal_active else None

    run_spec.runtime.provider.chat_stream_with_retry.side_effect = respond
    run_spec.continuation_callback = continuation
    run_spec.checkpoint_callback = AsyncMock()
    run_spec.hook = AgentHook()
    run_spec.hook.wants_streaming = MagicMock(return_value=True)
    run_spec.hook.on_stream_end = AsyncMock()

    result = await AgentRunner().run(run_spec)

    assert result.stop_reason == "completed"
    assert result.final_content == "Final evidence summary."
    assert len(requests) == 2
    assert [call.kwargs["resuming"] for call in run_spec.hook.on_stream_end.await_args_list] == [True, False]
    checkpoint = run_spec.checkpoint_callback.await_args.args[0]
    assert checkpoint["phase"] == "final_response"
    assert checkpoint["iteration"] == 1
    assert checkpoint["assistant_message"] == result.messages[-1]
    assert checkpoint["preceding_messages"] == result.messages[1:-1]
    assert checkpoint["provider_state"] == result.provider_state
    assert result.provider_state is not None
    assert result.provider_state.payload == final_state.payload
    assert result.provider_state.pending_messages == []
    resumed_state = requests[1]["provider_context"].conversation_state
    assert resumed_state.payload == state.payload
    if response_kind == "text":
        assert resumed_state.pending_messages == [{
            "role": "user", "content": "Continue.",
            "_hidden_history": {"kind": "internal_continuation"},
        }]
    else:
        assert resumed_state.pending_messages[0]["role"] == "tool"
        assert "evidence.txt" in resumed_state.pending_messages[0]["content"]
