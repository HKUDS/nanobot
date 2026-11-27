"""Request/replay tests using the step SSE shapes from earendil-works/pi#12614."""

import json
import threading
from unittest.mock import AsyncMock

import httpx
import pytest

from nanobot import __version__
from nanobot.providers import google_ai_plan_provider as plan
from nanobot.utils.helpers import build_assistant_message

MODEL = "google-ai-plan/gemini-4-hydrogen"
PROXY = "http://proxy.invalid:8181"
TOKEN = "local-test-token"


def frame(event_type, **fields):
    return f"event: {event_type}\r\ndata: {json.dumps({'event_type': event_type, **fields})}\r\n\r\n".encode()


def step(index, kind, deltas, **fields):
    return b"".join([
        frame("step.start", index=index, step={"type": kind, **fields}),
        *(frame("step.delta", index=index, delta=d) for d in deltas),
        frame("step.stop", index=index),
    ])


def completed(status, **fields):
    return frame("interaction.completed", interaction={"status": status, **fields})


def sse(*frames):
    return httpx.Response(200, content=b"".join(frames), headers={"Content-Type": "text/event-stream"})


@pytest.fixture
def wire(monkeypatch):
    requests = []
    replies = []
    owner = threading.get_ident()
    original_client = httpx.AsyncClient

    def get_token(*, proxy):
        assert proxy == PROXY and threading.get_ident() != owner
        return TOKEN

    def handle(request):
        requests.append(request)
        return replies.pop(0)

    def client(*, proxy, trust_env, timeout):
        assert proxy == PROXY and not trust_env
        return original_client(transport=httpx.MockTransport(handle), trust_env=False, timeout=timeout)

    monkeypatch.setattr(plan, "get_google_ai_plan_token", get_token)
    monkeypatch.setattr(plan.httpx, "AsyncClient", client)
    return plan.GoogleAIPlanProvider(default_model=MODEL, proxy=PROXY), requests, replies


async def test_signed_tool_turn_replays_in_wire_order(wire):
    provider, requests, replies = wire
    thinking, content, tool_delta = AsyncMock(), AsyncMock(), AsyncMock()
    tool_step = step(2, "function_call", [
        {"type": "arguments_delta", "arguments": '{"path":'},
        {"type": "arguments_delta", "arguments": '"a.py"}'},
    ], id="call_1", name="read", arguments={})

    class ToolTurn(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield step(0, "model_output", [{"type": "text", "text": "Before."}])
            content.assert_awaited_once_with("Before.")  # Delivered before the next bytes arrive.
            yield step(1, "thought", [
                {"type": "thought_summary", "content": {"type": "text", "text": "Need file."}},
                {"type": "thought_signature", "signature": "Z24="},
            ], signature="c2l")
            yield tool_step
            yield step(3, "model_output", [{"type": "text", "text": "After."}])
            yield completed("requires_action", usage={"total_input_tokens": 114, "total_cached_tokens": 10,
                                                     "total_output_tokens": 26, "total_thought_tokens": 44,
                                                     "total_tokens": 184})

    replies.append(httpx.Response(200, stream=ToolTurn(), headers={"Content-Type": "text/event-stream"}))
    messages = [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "Read the file"}]
    schema = {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}
    tools = [{"type": "function", "function": {"name": "read", "description": "Read file", "parameters": schema}}]
    response = await provider.chat_stream(messages, tools=tools, max_tokens=256, reasoning_effort="minimal",
                                          tool_choice="required", on_content_delta=content,
                                          on_thinking_delta=thinking, on_tool_call_delta=tool_delta)
    assert response.finish_reason == "tool_calls", response.content
    assert response.should_execute_tools
    assert response.content == "Before.After." and response.reasoning_content == "Need file."
    assert response.tool_calls[0].arguments == {"path": "a.py"}
    assert response.usage == plan.LLMUsage.reported(input_tokens=114, cache_read_tokens=10,
                                                   output_tokens=70, total_tokens=184)
    thinking.assert_awaited_once_with("Need file.")
    assert [c.args[0] for c in tool_delta.await_args_list] == [
        {"index": 2, "call_id": "call_1", "name": "read", "arguments_delta": piece}
        for piece in ("", '{"path":', '"a.py"}')
    ]
    assert provider.provider_name == "google_ai_plan" and provider.get_default_model() == MODEL
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://generativelanguage.googleapis.com/v1beta/interactions:createPerUserQuota"
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert request.headers["User-Agent"] == f"nanobot/{__version__}"
    assert request.headers["Content-Type"] == "application/json" and request.headers["Accept"] == "text/event-stream"
    user = {"type": "user_input", "content": [{"type": "text", "text": "Read the file"}]}
    assert json.loads(request.content) == {
        "model": "gemini-4-hydrogen", "stream": True, "store": False, "system_instruction": "Be brief.",
        "generation_config": {"max_output_tokens": 256, "tool_choice": "any", "thinking_level": "low",
                              "thinking_summaries": "auto"},
        "tools": [{"type": "function", "name": "read", "description": "Read file", "parameters": schema}],
        "input": [user],
    }
    messages.extend([
        build_assistant_message(response.content, [c.to_openai_tool_call() for c in response.tool_calls],
                                response.reasoning_content, response.thinking_blocks),
        {"role": "tool", "tool_call_id": "call_1", "content": "file data"},
    ])
    replies.append(sse(step(0, "model_output", [{"type": "text", "text": "Done."}]), completed("completed")))
    answer = await provider.chat(messages, tools=tools)
    assert answer.finish_reason == "stop" and answer.content == "Done."
    call = {"type": "function_call", "id": "call_1", "name": "read", "arguments": {"path": "a.py"}}
    result = {"type": "function_result", "call_id": "call_1", "name": "read", "result": "file data"}
    assert json.loads(requests[1].content)["input"] == [
        user, {"type": "model_output", "content": [{"type": "text", "text": "Before."}]},
        {"type": "thought", "signature": "c2lZ24=", "summary": [{"type": "text", "text": "Need file."}]},
        call, {"type": "model_output", "content": [{"type": "text", "text": "After."}]}, result,
    ]
    # Switching models in the very same tool loop must not send a different model's signature.
    replies.append(sse(completed("completed")))
    await provider.chat(messages, model="google-ai-plan/gemini-4-carbon")
    switched = json.loads(requests[2].content)
    assert switched["model"] == "gemini-4-carbon"
    assert switched["input"] == [user, {"type": "model_output", "content": [{"type": "text", "text": "Before.After."}]},
                                 {"type": "thought", "signature": "skip_thought_signature_validator"}, call, result]


async def test_inline_user_and_tool_result_images(wire):
    provider, requests, replies = wire
    image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,YWJj"}}
    text = {"type": "text", "text": "Preview"}
    messages = [{"role": "user", "content": [text, image]}, {"role": "assistant", "tool_calls": [
        {"id": "t", "function": {"name": "draw", "arguments": "{}"}},
    ]}, {"role": "tool", "name": "draw", "tool_call_id": "t", "content": [text, image], "is_error": True}]
    replies.append(sse(step(0, "model_output", [{"type": "text", "text": "Part"}]), completed("incomplete")))
    response = await provider.chat(messages)
    assert response.finish_reason == "length" and response.content == "Part"
    parts = [text, {"type": "image", "mime_type": "image/png", "data": "YWJj"}]
    sent = json.loads(requests[0].content)["input"]
    assert sent[0] == {"type": "user_input", "content": parts}
    assert sent[-1] == {"type": "function_result", "call_id": "t", "name": "draw", "result": parts, "is_error": True}


@pytest.mark.parametrize(("reply", "status", "detail", "retry", "wait"), [
    (httpx.Response(401, json=[{"error": {"status": "UNAUTHENTICATED", "message": "Sign in again"}}]),
     401, "Sign in again", False, None),
    (httpx.Response(429, json={"error": {"message": "Too many requests"}}, headers={"Retry-After": "7"}),
     429, "Too many requests", True, 7),
    (httpx.Response(429, json={"error": {"message": "Resource exhausted", "details": [{"violations": [
        {"quotaId": "GenerateRequestsPerDayPerUserPerModel", "quotaValue": "0"}]}]}}),
     429, "Resource exhausted", False, None),
    (sse(frame("error", error={"code": "invalid_request", "message": "Missing thought signature"})),
     None, "Missing thought signature", False, None),
    (sse(step(0, "function_call", [{"type": "arguments_delta", "arguments": "{}"}], id="1", name="do"),
         b"data: [DONE]\n\n"), None, "ended before interaction.completed", True, None),
])
async def test_failed_or_truncated_turn_never_executes_tools(wire, reply, status, detail, retry, wait):
    provider, _, replies = wire
    replies.append(reply)
    response = await provider.chat([{"role": "user", "content": "Hi"}])
    assert response.finish_reason == "error" and not response.should_execute_tools
    assert detail in response.content and response.error_status_code == status
    assert provider.is_transient_response(response) is retry and response.error_retry_after_s == wait
