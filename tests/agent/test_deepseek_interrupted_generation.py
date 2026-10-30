from __future__ import annotations

import json
from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from openai import AsyncOpenAI

from agent.runner_helpers import make_run_spec
from nanobot.agent.progress_hook import AgentProgressHook
from nanobot.agent.runner import _PERSISTED_MODEL_ERROR_PLACEHOLDER, AgentRunner
from nanobot.config.schema import ModelPresetConfig
from nanobot.providers.fallback_provider import FallbackProvider
from nanobot.providers.model_api import ModelAPICapabilities
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import find_by_name
from nanobot.utils.progress_events import output_events

_PARTIAL = "The answer starts but"
_IMAGE = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGOokGMAAAGoAJdKOWLCAAAAAElFTkSuQmCC"
)
_CHAT = ModelAPICapabilities(("chat_completions",), "chat_completions")


class _Peer:
    def __init__(self, reason, *, response_fallback=False, first_tool=False, partial=_PARTIAL):
        self.reason = reason
        self.response_fallback = response_fallback
        self.first_tool = first_tool
        self.partial = partial
        self.requests = []

    def __call__(self, request):
        body = json.loads(request.content)
        self.requests.append((request.url.path, body))
        if request.url.path.endswith("/responses"):
            assert self.response_fallback
            return httpx.Response(400, json={"error": {"message": "Responses API not supported"}})

        chat_requests = [path for path, _ in self.requests if path.endswith("/chat/completions")]
        first_tool = self.first_tool and len(chat_requests) == 1
        if first_tool:
            reason, text = "tool_calls", None
        elif len(chat_requests) <= (2 if self.first_tool else 1):
            reason = self.reason
            text = "Complete answer." if reason == "stop" else self.partial
        else:
            reason, text = "stop", "Complete answer."
        tool = {
            "id": "call_1" if first_tool else "unfinished",
            "type": "function",
            "function": {"name": "read_file", "arguments": '{"path":"example.txt"}'},
        }
        # Include an unfinished call with the interrupted answer: it must never execute.
        tool_calls = [tool] if first_tool or self.first_tool and reason != "stop" else []
        usage = {"prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 7}
        if not body.get("stream"):
            return httpx.Response(200, json={
                "id": "chat_1", "object": "chat.completion", "created": 1, "model": body["model"],
                "choices": [{"index": 0, "finish_reason": reason, "message": {
                    "role": "assistant", "content": text, "tool_calls": tool_calls,
                }}], "usage": usage,
            })

        delta = {"content": text}
        if tool_calls:
            delta["tool_calls"] = [{"index": 0, **tool}]
        events = [
            {"id": "chat_1", "object": "chat.completion.chunk", "created": 1, "model": body["model"],
             "choices": [{"index": 0, "finish_reason": None, "delta": delta}]},
            {"id": "chat_1", "object": "chat.completion.chunk", "created": 1, "model": body["model"],
             "choices": [{"index": 0, "finish_reason": reason, "delta": {}}], "usage": usage},
        ]
        sse = "".join(f"data: {json.dumps(event)}\n\n" for event in events) + "data: [DONE]\n\n"
        return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})


@pytest.fixture
async def make_provider():
    providers = []

    def make(peer, *, spec="deepseek", response_fallback=False):
        provider = OpenAICompatProvider(
            api_key="fixture", default_model="deepseek-flash" if spec == "deepseek" else "gpt-4o",
            spec=find_by_name(spec), model_api=None if response_fallback else _CHAT,
        )
        provider._client = AsyncOpenAI(
            api_key="fixture", max_retries=0,
            base_url="https://api.deepseek.com" if spec == "deepseek" else "https://api.openai.com/v1",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(peer)),
        )
        providers.append(provider)
        return provider

    yield make
    for provider in providers:
        await provider.aclose()


def _image_messages():
    return [{"role": "user", "content": [
        {"type": "text", "text": "What is in this image?"},
        {"type": "image_url", "image_url": {"url": _IMAGE}},
    ]}]


@pytest.mark.parametrize("reason", ["insufficient_system_resource", "aborted"])
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("response_fallback", [False, True])
async def test_sdk_chat_interruption_is_terminal_even_with_images(
    make_provider, reason, streaming, response_fallback,
):
    peer = _Peer(reason, response_fallback=response_fallback)
    provider = make_provider(peer, response_fallback=response_fallback)
    messages = _image_messages()
    original = deepcopy(messages)
    call = provider.chat_stream_with_retry if streaming else provider.chat_with_retry

    result = await call(messages, retry_mode="persistent")

    assert result.finish_reason == "error"
    assert result.error_kind == "generation_interrupted"
    assert result.error_code == reason
    assert result.error_should_retry is False
    assert _PARTIAL not in (result.content or "")
    assert result.usage is not None and result.usage.input_tokens == 4
    assert not result.should_execute_tools
    paths = [path for path, _ in peer.requests]
    assert paths == (["/responses"] if response_fallback else []) + ["/chat/completions"]
    assert _IMAGE in json.dumps(peer.requests[-1][1]["messages"])
    assert messages == original


@pytest.mark.parametrize("reason", ["insufficient_system_resource", "aborted"])
async def test_runner_preserves_visible_partial_but_reports_failure_without_replaying_tools(
    make_provider, reason,
):
    peer = _Peer(reason, first_tool=True)
    primary = make_provider(peer)
    backup = MagicMock()
    provider = FallbackProvider(
        primary, [ModelPresetConfig(model="backup", provider="custom")], backup,
    )
    tools = MagicMock()
    tools.get_definitions.return_value = [{
        "type": "function", "function": {"name": "read_file", "parameters": {
            "type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"],
        }},
    }]
    tools.execute = AsyncMock(return_value="read complete")
    show = AsyncMock()
    end = AsyncMock()
    checkpoints = []
    result = await AgentRunner().run(make_run_spec(
        provider, initial_messages=_image_messages(), tools=tools, model="deepseek-flash",
        max_iterations=3, max_tool_result_chars=1000, provider_retry_mode="persistent",
        hook=AgentProgressHook(output_events(on_stream=show, on_stream_end=end), streaming=True),
        checkpoint_callback=AsyncMock(side_effect=checkpoints.append),
    ))

    assert len(peer.requests) == 2
    backup.assert_not_called()
    tools.execute.assert_awaited_once_with("read_file", {"path": "example.txt"})
    show.assert_awaited_once_with(_PARTIAL)
    assert end.await_args_list[-1].kwargs == {"resuming": False}
    assert result.stop_reason == "error"
    assert result.failure_error_kind == "unknown"
    assert result.error == result.final_content
    assert result.error and reason in result.error and _PARTIAL not in result.error
    assert result.messages[-1]["content"] == _PARTIAL
    assert result.messages[-1]["_interrupted"] is True
    assert [checkpoint["phase"] for checkpoint in checkpoints] == ["awaiting_tools", "tools_completed"]

    followup = await AgentRunner().run(make_run_spec(
        provider, initial_messages=[*result.messages, {"role": "user", "content": "explain that"}],
        tools=tools, model="deepseek-flash", max_iterations=1, max_tool_result_chars=1000,
    ))
    assert followup.stop_reason == "completed"
    assert followup.final_content == "Complete answer."
    replay = peer.requests[-1][1]["messages"]
    assert [m["content"] for m in replay if m.get("role") == "assistant" and m.get("content")] == [_PARTIAL]
    assert any(m.get("role") == "tool" and m.get("content") == "read complete" for m in replay)
    tools.execute.assert_awaited_once_with("read_file", {"path": "example.txt"})


@pytest.mark.parametrize("reason", ["insufficient_system_resource", "aborted"])
async def test_runner_without_streaming_does_not_present_partial_as_error_or_answer(make_provider, reason):
    peer = _Peer(reason)
    provider = make_provider(peer)
    tools = MagicMock()
    tools.get_definitions.return_value = []
    result = await AgentRunner().run(make_run_spec(
        provider, initial_messages=_image_messages(), tools=tools, model="deepseek-flash",
        max_iterations=1, max_tool_result_chars=1000, hook=AgentProgressHook(streaming=False),
    ))

    assert len(peer.requests) == 1
    assert result.stop_reason == "error"
    assert result.error == result.final_content
    assert result.error and _PARTIAL not in result.error
    assert result.messages[-1]["content"] == _PERSISTED_MODEL_ERROR_PLACEHOLDER


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("spec", ["deepseek", "openai"])
async def test_normal_stop_succeeds_for_deepseek_and_other_provider(make_provider, streaming, spec):
    peer = _Peer("stop")
    provider = make_provider(peer, spec=spec)
    call = provider.chat_stream_with_retry if streaming else provider.chat_with_retry
    result = await call([{"role": "user", "content": "hello"}])

    assert result.finish_reason == "stop"
    assert result.error_kind is None
    assert result.content == "Complete answer."
    assert len(peer.requests) == 1


@pytest.mark.parametrize("streaming", [False, True])
async def test_persistent_model_fallback_does_not_retry_empty_interruption_with_images(
    make_provider, streaming,
):
    peer = _Peer("aborted", partial=None)
    primary = make_provider(peer)
    backup = MagicMock()
    provider = FallbackProvider(
        primary, [ModelPresetConfig(model="backup", provider="custom")], backup,
    )
    messages = _image_messages()
    original = deepcopy(messages)
    call = provider.chat_stream_with_retry if streaming else provider.chat_with_retry

    result = await call(messages, retry_mode="persistent")

    assert result.finish_reason == "error"
    assert result.error_kind == "generation_interrupted"
    assert len(peer.requests) == 1
    backup.assert_not_called()
    assert _IMAGE in json.dumps(peer.requests[0][1]["messages"])
    assert messages == original


@pytest.mark.parametrize("streaming", [False, True])
async def test_default_deepseek_responses_path_remains_unchanged(make_provider, streaming):
    requests = []
    output = [{"type": "message", "role": "assistant", "status": "completed", "content": [
        {"type": "output_text", "text": "A complete answer."},
    ]}]
    response = {
        "id": "resp_1", "object": "response", "status": "completed", "output": output,
        "usage": {"input_tokens": 4, "output_tokens": 3, "total_tokens": 7},
    }

    def handle(request):
        body = json.loads(request.content)
        requests.append(request.url.path)
        assert request.url.path == "/responses"
        if not body.get("stream"):
            return httpx.Response(200, json=response)
        events = [
            {"type": "response.output_text.delta", "delta": "A complete answer."},
            {"type": "response.completed", "response": response},
        ]
        sse = "".join(f"data: {json.dumps(event)}\n\n" for event in events) + "data: [DONE]\n\n"
        return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})

    provider = make_provider(handle, response_fallback=True)
    show = AsyncMock()
    if streaming:
        result = await provider.chat_stream_with_retry(
            [{"role": "user", "content": "hello"}], on_content_delta=show,
        )
        show.assert_awaited_once_with("A complete answer.")
    else:
        result = await provider.chat_with_retry([{"role": "user", "content": "hello"}])

    assert requests == ["/responses"]
    assert result.finish_reason == "stop"
    assert result.error_kind is None
    assert result.content == "A complete answer."
    assert result.provider_state is not None


async def test_chat_fallback_interruption_preserves_prior_responses_state_and_tool_result(make_provider):
    requests = []
    chat = _Peer("aborted")
    tool_item = {
        "type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "read_file",
        "arguments": '{"path":"example.txt"}', "status": "completed",
    }
    answer_item = {"type": "message", "role": "assistant", "status": "completed", "content": [
        {"type": "output_text", "text": "Follow-up answer."},
    ]}

    def handle(request):
        body = json.loads(request.content)
        requests.append((request.url.path, body))
        if request.url.path == "/chat/completions":
            return chat(request)
        response_number = sum(path == "/responses" for path, _ in requests)
        if response_number == 2:
            return httpx.Response(400, json={"error": {"message": "Responses API not supported"}})
        item = tool_item if response_number == 1 else answer_item
        response = {"id": f"resp_{response_number}", "object": "response", "status": "completed",
                    "output": [item], "usage": {"input_tokens": 4, "output_tokens": 3}}
        events = ([{"type": "response.output_item.done", "output_index": 0, "item": item}]
                  if response_number == 1 else
                  [{"type": "response.output_text.delta", "delta": "Follow-up answer."}])
        events.append({"type": "response.completed", "response": response})
        sse = "".join(f"data: {json.dumps(event)}\n\n" for event in events) + "data: [DONE]\n\n"
        return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})

    provider = make_provider(handle, response_fallback=True)
    tools = MagicMock()
    tools.get_definitions.return_value = [{
        "type": "function", "function": {"name": "read_file", "parameters": {
            "type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"],
        }},
    }]
    tools.execute = AsyncMock(return_value="read complete")
    show = AsyncMock()
    result = await AgentRunner().run(make_run_spec(
        provider, initial_messages=[{"role": "user", "content": "question"}], tools=tools,
        model="deepseek-flash", max_iterations=2, max_tool_result_chars=1000,
        hook=AgentProgressHook(output_events(on_stream=show), streaming=True),
    ))

    assert [path for path, _ in requests] == ["/responses", "/responses", "/chat/completions"]
    assert result.stop_reason == "error"
    assert result.messages[-1]["_interrupted"] is True
    assert result.provider_state is not None
    show.assert_awaited_once_with(_PARTIAL)
    tools.execute.assert_awaited_once_with("read_file", {"path": "example.txt"})

    followup = {"role": "user", "content": "explain that"}
    next_result = await AgentRunner().run(make_run_spec(
        provider, initial_messages=[*result.messages, followup], tools=tools,
        model="deepseek-flash", max_iterations=1, max_tool_result_chars=1000,
        provider_state=result.provider_state.with_pending_messages([
            *result.provider_state.pending_messages, followup,
        ]),
    ))
    assert next_result.stop_reason == "completed"
    assert next_result.final_content == "Follow-up answer."
    replay = requests[-1][1]["input"]
    assert [item for item in replay if item.get("type") == "function_call_output"] == [{
        "type": "function_call_output", "call_id": "call_1", "output": "read complete",
    }]
    assert replay[-2:] == [{
        "type": "message", "role": "assistant", "status": "completed",
        "content": [{"type": "output_text", "text": _PARTIAL}],
    }, {
        "role": "user", "content": [{"type": "input_text", "text": "explain that"}],
    }]
    tools.execute.assert_awaited_once_with("read_file", {"path": "example.txt"})
