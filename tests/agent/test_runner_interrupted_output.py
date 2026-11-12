"""Model failures retain the assistant text already delivered to the user."""

from __future__ import annotations

from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.runner_helpers import make_run_spec
from nanobot.agent.progress_hook import AgentProgressHook
from nanobot.agent.runner import _PERSISTED_MODEL_ERROR_PLACEHOLDER, AgentRunner
from nanobot.config.schema import ModelPresetConfig
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from nanobot.providers.fallback_provider import FallbackProvider
from nanobot.providers.model_api import ModelAPICapabilities
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.openai_responses import parse_response_output
from nanobot.providers.unconfigured_provider import UnconfiguredProvider
from nanobot.utils.progress_events import output_events


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["The answer is 42.", "The answer starts with"])
async def test_failed_stream_retains_real_reply_for_the_next_request(text):
    provider = MagicMock(spec=LLMProvider)
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock()

    async def fail_after_output(**kwargs):
        await kwargs["on_thinking_delta"]("private reasoning")
        await kwargs["on_content_delta"]("<think>hidden thought</think>" + text)
        return LLMResponse(
            content="network diagnostic, not assistant text",
            finish_reason="error",
            error_kind="connection",
            tool_calls=[ToolCallRequest(id="unfinished", name="exec", arguments={})],
        )

    provider.chat_stream_with_retry = AsyncMock(side_effect=fail_after_output)
    continue_goal = AsyncMock(return_value="continue the goal")
    checkpoints = []
    result = await AgentRunner().run(make_run_spec(
        provider, initial_messages=[{"role": "user", "content": "question"}],
        tools=tools, model="test", max_iterations=2, max_tool_result_chars=1000,
        hook=AgentProgressHook(streaming=True),
        continuation_callback=continue_goal,
        checkpoint_callback=AsyncMock(side_effect=checkpoints.append),
    ))

    assert result.stop_reason == "error"
    assert result.failure_error_kind == "connection"
    assert result.messages[-1]["content"] == text
    assert result.messages[-1]["_interrupted"] is True
    assert result.final_content == result.error == "network diagnostic, not assistant text"
    assert checkpoints == []
    continue_goal.assert_not_awaited()
    tools.execute.assert_not_awaited()

    provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="follow-up"))
    await AgentRunner().run(make_run_spec(
        provider,
        initial_messages=[*result.messages, {"role": "user", "content": "explain that"}],
        tools=tools, model="test", max_iterations=1, max_tool_result_chars=1000,
    ))
    sent = provider.chat_stream_with_retry.await_args.kwargs["messages"]
    assert [message["content"] for message in sent if message.get("role") == "assistant"] == [text]


@pytest.mark.asyncio
async def test_failed_stream_keeps_visible_segments_across_hosted_tools_and_recovery():
    provider = MagicMock(spec=LLMProvider)
    tools = MagicMock()
    tools.get_definitions.return_value = []
    visible = []

    async def show(delta):
        visible.append(delta)

    async def fail_after_segments(**kwargs):
        await kwargs["on_content_delta"]("<thi")
        await kwargs["on_content_delta"]("nk>hidden</think>Before search.")
        await kwargs["on_tool_call_delta"]({
            "kind": "hosted_tool", "phase": "start", "call_id": "search-1",
            "name": "web_search", "arguments": {},
        })
        await kwargs["on_content_delta"]("<think>unfinished hidden thought")
        await kwargs["on_stream_recover"]()
        await kwargs["on_content_delta"]("<thinking>new hidden thought</thinking>After search.")
        return LLMResponse(content="connection lost", finish_reason="error", error_kind="connection")

    provider.chat_stream_with_retry = AsyncMock(side_effect=fail_after_segments)
    result = await AgentRunner().run(make_run_spec(
        provider, initial_messages=[{"role": "user", "content": "search"}],
        tools=tools, model="test", max_iterations=1, max_tool_result_chars=1000,
        hook=AgentProgressHook(output_events(on_stream=show), streaming=True),
    ))

    assert visible == ["Before search.", "After search."]
    assert result.messages[-1]["content"] == "Before search.\n\nAfter search."
    assert result.messages[-1]["_interrupted"] is True
    assert result.stop_reason == "error"


@pytest.mark.asyncio
async def test_reasoning_only_failure_does_not_claim_a_preserved_reply():
    provider = MagicMock(spec=LLMProvider)
    tools = MagicMock()
    tools.get_definitions.return_value = []

    async def fail_after_reasoning(**kwargs):
        await kwargs["on_thinking_delta"]("native private reasoning")
        await kwargs["on_content_delta"]("<think>unfinished private reasoning")
        return LLMResponse(content="connection lost", finish_reason="error", error_kind="connection")

    provider.chat_stream_with_retry = AsyncMock(side_effect=fail_after_reasoning)
    result = await AgentRunner().run(make_run_spec(
        provider, initial_messages=[{"role": "user", "content": "question"}],
        tools=tools, model="test", max_iterations=1, max_tool_result_chars=1000,
        hook=AgentProgressHook(streaming=True),
    ))

    assert result.messages[-1]["content"] == _PERSISTED_MODEL_ERROR_PLACEHOLDER
    assert result.messages[-1].get("_interrupted") is not True
    assert result.stop_reason == "error"


@pytest.mark.asyncio
async def test_nonstreaming_provider_error_is_not_observed_as_assistant_body():
    provider = UnconfiguredProvider("test")
    tools = MagicMock()
    tools.get_definitions.return_value = []
    show = AsyncMock()
    result = await AgentRunner().run(make_run_spec(
        provider, initial_messages=[{"role": "user", "content": "question"}],
        tools=tools, model="test", max_iterations=1, max_tool_result_chars=1000,
        hook=AgentProgressHook(output_events(on_stream=show), streaming=True),
    ))

    assert result.stop_reason == "error"
    assert result.failure_error_kind == "unknown"
    assert result.error == result.final_content
    assert "Open Settings → Models" in result.final_content
    assert result.messages[-1]["content"] == _PERSISTED_MODEL_ERROR_PLACEHOLDER
    assert result.messages[-1].get("_interrupted") is not True
    show.assert_not_awaited()


class _StreamingProvider(LLMProvider):
    def __init__(self, steps):
        super().__init__(provider_name="test")
        self.steps = iter(steps)
        self.calls = 0

    def get_default_model(self):
        return "test"

    async def chat(self, **kwargs):
        raise AssertionError("expected a streaming request")

    async def chat_stream(self, **kwargs):
        self.calls += 1
        text, response = next(self.steps)
        await kwargs["on_content_delta"](text)
        return response


@pytest.mark.asyncio
@pytest.mark.parametrize("fallback_fails", [False, True])
async def test_retry_and_fallback_preserve_failed_segments_only_on_terminal_error(
    monkeypatch, fallback_fails,
):
    monkeypatch.setattr(LLMProvider, "_CHAT_RETRY_DELAYS", (0,))
    timeout = LLMResponse(content="stream timeout diagnostic", finish_reason="error", error_kind="timeout")
    primary = _StreamingProvider([
        ("First attempt.", timeout), ("Second attempt.", timeout),
    ])
    final = LLMResponse(
        content="fallback connection diagnostic" if fallback_fails else "Backup answer.",
        finish_reason="error" if fallback_fails else "stop",
        error_kind="connection" if fallback_fails else None,
    )
    fallback = _StreamingProvider([("Backup answer.", final)])
    provider = FallbackProvider(
        primary, [ModelPresetConfig(model="backup", provider="custom")],
        lambda _preset: fallback,
    )
    tools = MagicMock()
    tools.get_definitions.return_value = []
    result = await AgentRunner().run(make_run_spec(
        provider, initial_messages=[{"role": "user", "content": "question"}],
        tools=tools, model="test", max_iterations=1, max_tool_result_chars=1000,
        hook=AgentProgressHook(streaming=True),
    ))

    assert primary.calls == 2
    assert fallback.calls == 1
    assistant = [message for message in result.messages if message["role"] == "assistant"]
    assert len(assistant) == 1
    if fallback_fails:
        assert assistant[0]["content"] == "First attempt.\n\nSecond attempt.\n\nBackup answer."
        assert assistant[0]["_interrupted"] is True
        assert result.stop_reason == "error"
        assert result.final_content == "fallback connection diagnostic"
    else:
        assert assistant[0]["content"] == "Backup answer."
        assert assistant[0].get("_interrupted") is not True
        assert result.stop_reason == "completed"
        assert result.final_content == "Backup answer."


@pytest.mark.asyncio
@pytest.mark.parametrize("midturn", [False, True])
async def test_native_next_request_contains_preserved_reply_without_repeating_completed_tool(
    monkeypatch, midturn,
):
    provider = OpenAICompatProvider(
        api_key="test", default_model="test", model_api=ModelAPICapabilities(
            supported_apis=("responses",), preferred_api="responses",
        ),
    )
    monkeypatch.setattr(provider, "_ensure_client", AsyncMock(return_value=MagicMock()))
    requests = []
    injections = []
    checkpoints = []
    followup = {"role": "user", "content": "explain that"}

    async def send(_client, body, **kwargs):
        requests.append(deepcopy(body["input"]))
        if len(requests) == 1:
            return parse_response_output({
                "status": "completed", "output": [{
                    "type": "function_call", "id": "fc_1", "call_id": "call_1",
                    "name": "read_file", "arguments": "{}",
                }],
            }, state_provider=kwargs["provider"], state_model=body["model"],
                state_input_items=body["input"])
        if len(requests) == 2:
            await kwargs["on_content_delta"]("Preserved conclusion.")
            if midturn:
                injections.append(followup)
            raise ConnectionError("connection lost after reply")
        return LLMResponse(content="follow-up answer")

    async def drain():
        batch = list(injections)
        injections.clear()
        return batch

    monkeypatch.setattr(provider._responses, "sdk_request", send)
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="completed tool output")
    result = await AgentRunner().run(make_run_spec(
        provider, initial_messages=[{"role": "user", "content": "question"}],
        tools=tools, model="test", max_iterations=3, max_tool_result_chars=1000,
        hook=AgentProgressHook(streaming=True), injection_callback=drain,
        checkpoint_callback=AsyncMock(side_effect=checkpoints.append),
    ))
    if not midturn:
        assert result.stop_reason == "error"
        assert result.messages[-1]["_interrupted"] is True
        assert result.provider_state is not None
        await AgentRunner().run(make_run_spec(
            provider, initial_messages=[*result.messages, followup], tools=tools,
            model="test", max_iterations=1, max_tool_result_chars=1000,
            provider_state=result.provider_state.with_pending_messages([
                *result.provider_state.pending_messages, followup,
            ]),
        ))
    else:
        assert result.stop_reason == "completed"

    assert len(requests) == 3
    assert requests[2][-2:] == [{
        "type": "message", "role": "assistant", "status": "completed",
        "content": [{"type": "output_text", "text": "Preserved conclusion."}],
    }, {
        "role": "user", "content": [{"type": "input_text", "text": "explain that"}],
    }]
    assert [item for item in requests[2] if item.get("type") == "function_call_output"] == [{
        "type": "function_call_output", "call_id": "call_1", "output": "completed tool output",
    }]
    assert not any(checkpoint["assistant_message"].get("_interrupted") for checkpoint in checkpoints)
    tools.execute.assert_awaited_once_with("read_file", {})
    await provider.aclose()
