"""Provider compatibility decisions through the SDK and local HTTP endpoints."""

import json

import pytest
from aiohttp import web

from nanobot.agent.tools.exec_session import ExecSessionTool
from nanobot.providers.azure_openai_provider import AzureOpenAIProvider
from nanobot.providers.base import ProviderCallContext
from nanobot.providers.model_api import ModelAPICapabilities
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import find_by_name


@pytest.fixture
async def endpoint(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    runners = []

    async def start(handler):
        app = web.Application()
        app.router.add_post("/{path:.*}", handler)
        runner = web.AppRunner(app)
        runners.append(runner)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        return f"http://127.0.0.1:{runner.addresses[0][1]}"

    yield start
    for runner in runners:
        await runner.cleanup()


def _response(body):
    response = {
        "id": "resp_fixture", "object": "response", "status": "completed",
        "output": [{
            "id": "msg_fixture", "type": "message", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": "ok", "annotations": []}],
        }],
    }
    if not body.get("stream"):
        return web.json_response(response)
    return _sse([
        {"type": "response.output_text.delta", "delta": "ok"},
        {"type": "response.completed", "response": response},
    ])


def _sse(events):
    return web.Response(
        content_type="text/event-stream",
        text="".join(f"data: {json.dumps(event)}\n\n" for event in events),
    )


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(("content", "tool_choice"), [
    pytest.param(
        'Example only:\n```xml\n<tool_call>{"name":"read_file","arguments":{"path":"README.md"}}</tool_call>\n```',
        "none", id="quoted-json-tools-disabled",
    ),
    pytest.param(
        'Example only:\n```xml\n<tool_call>{"name":"read_file","arguments":{"path":"README.md"}}</tool_call>\n```',
        "auto", id="quoted-json-tools-enabled",
    ),
    pytest.param(
        '<tool_call><function=exec_session><parameter=session_id>fixture</parameter>'
        '<parameter=timeout_ms>{"session_id":"fixture","timeout_ms":{}}</parameter>'
        '</function></tool_call>',
        "auto", id="malformed-xml-in-content",
    ),
])
async def test_plaintext_tool_examples_remain_text(endpoint, stream, content, tool_choice):
    requests = []
    deltas = []

    async def on_content_delta(delta):
        deltas.append(delta)

    async def handler(request):
        body = await request.json()
        requests.append(body)
        if body.get("stream"):
            return _sse([
                {"choices": [{"index": 0, "delta": {"content": part}}]}
                for part in (content[:30], content[30:35], content[35:])
            ] + [{"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}])
        return web.json_response({"id": "chat_fixture", "choices": [{
            "index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop",
        }]})

    url = await endpoint(handler)
    provider = OpenAICompatProvider(api_key="fixture", api_base=f"{url}/v1", spec=find_by_name("custom"))
    invoke = provider.chat_stream if stream else provider.chat
    try:
        result = await invoke(
            [{"role": "user", "content": "Show a tool call example without executing it."}],
            tools=[{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}],
            tool_choice=tool_choice,
            **({"on_content_delta": on_content_delta} if stream else {}),
        )
        assert result.finish_reason == "stop"
        assert result.content == content
        assert result.tool_calls == []
        assert not result.should_execute_tools
        assert len(requests) == 1
        assert requests[0]["tool_choice"] == tool_choice
        if stream:
            assert "".join(deltas) == result.content
    finally:
        await provider.aclose()


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("timeout_ms", [1000, {"session_id": "fixture", "timeout_ms": {}}])
async def test_structured_calls_keep_arguments_out_of_text_and_preserve_validation(endpoint, stream, timeout_ms):
    tool = ExecSessionTool()
    arguments = {"session_id": "fixture", "timeout_ms": timeout_ms}
    encoded = json.dumps(arguments)
    text = "Checking the command output."
    deltas = []

    async def on_content_delta(delta):
        deltas.append(delta)

    async def handler(request):
        body = await request.json()
        if body.get("stream"):
            return _sse([
                {"choices": [{"index": 0, "delta": {"content": text}}]},
                {"choices": [{"index": 0, "delta": {"tool_calls": [{
                    "index": 0, "id": "call_fixture", "type": "function",
                    "function": {"name": "exec_session", "arguments": encoded[:20]},
                }]}}]},
                {"choices": [{"index": 0, "delta": {"tool_calls": [{
                    "index": 0, "function": {"arguments": encoded[20:]},
                }]}}]},
                {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
            ])
        return web.json_response({"id": "chat_fixture", "choices": [{
            "index": 0, "message": {"role": "assistant", "content": text, "tool_calls": [{
                "id": "call_fixture", "type": "function",
                "function": {"name": "exec_session", "arguments": encoded},
            }]}, "finish_reason": "tool_calls",
        }]})

    url = await endpoint(handler)
    provider = OpenAICompatProvider(api_key="fixture", api_base=f"{url}/v1", spec=find_by_name("custom"))
    invoke = provider.chat_stream if stream else provider.chat
    try:
        result = await invoke(
            [{"role": "user", "content": "Check the running command."}],
            tools=[tool.to_schema()],
            **({"on_content_delta": on_content_delta} if stream else {}),
        )
        assert result.should_execute_tools
        assert result.content == text
        assert len(result.tool_calls) == 1
        call = result.tool_calls[0]
        assert (call.id, call.name, call.arguments) == ("call_fixture", "exec_session", arguments)
        assert tool.validate_params(call.arguments) == (
            ["timeout_ms should be integer"] if isinstance(timeout_ms, dict) else []
        )
        if stream:
            assert "".join(deltas) == text
    finally:
        await provider.aclose()


@pytest.mark.parametrize("stream", [False, True])
async def test_invalid_output_limit_does_not_switch_protocol_or_trip_circuit(endpoint, stream):
    paths = []

    async def handler(request):
        paths.append(request.path)
        body = await request.json()
        if body.get("max_output_tokens", body.get("max_completion_tokens", 0)) > 64:
            return web.json_response({"error": {
                "type": "invalid_request_error", "param": "max_output_tokens",
                "message": "Invalid max_output_tokens for Responses: must be at most 64",
            }}, status=400)
        return _response(body)

    url = await endpoint(handler)
    provider = OpenAICompatProvider(
        api_key="fixture", api_base=f"{url}/v1", default_model="gpt-5", spec=find_by_name("custom"),
        model_api=ModelAPICapabilities(("responses", "chat_completions"), "responses"),
    )
    invoke = provider.chat_stream if stream else provider.chat
    try:
        for _ in range(3):
            result = await invoke([{"role": "user", "content": "hello"}], max_tokens=100)
            assert result.finish_reason == "error"
            assert result.error_status_code == 400
        result = await invoke([{"role": "user", "content": "hello"}], max_tokens=32)
        assert result.content == "ok"
        assert paths == ["/v1/responses"] * 4
    finally:
        await provider.aclose()


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("unsupported", [False, True])
async def test_server_compaction_distinguishes_unsupported_field_from_invalid_value(endpoint, stream, unsupported):
    bodies = []

    async def handler(request):
        body = await request.json()
        bodies.append(body)
        if len(bodies) == 1:
            return web.json_response({"error": {
                "type": "invalid_request_error", "param": "context_management[0].compact_threshold",
                "message": (
                    "Unknown parameter: context_management" if unsupported
                    else "Invalid context_management compact_threshold: value exceeds the context window"
                ),
            }}, status=400)
        return _response(body)

    url = await endpoint(handler)
    provider = AzureOpenAIProvider(api_key="fixture", api_base=url, default_model="gpt-5.4")
    invoke = provider.chat_stream if stream else provider.chat
    context = ProviderCallContext(context_window_tokens=200_000)
    tools = [ExecSessionTool().to_schema()]
    messages = [
        {"role": "system", "content": "Stable instructions."},
        {"role": "user", "content": "Check the running command."},
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call_fixture", "type": "function", "function": {
                "name": "exec_session", "arguments": '{"session_id":"fixture"}',
            },
        }]},
        {"role": "tool", "tool_call_id": "call_fixture", "content": "Command completed."},
    ]
    try:
        result = await invoke(messages, tools=tools, provider_context=context)
        assert result.finish_reason == ("stop" if unsupported else "error")
        assert len(bodies) == (2 if unsupported else 1)
        assert provider.supports_native_compaction() is (not unsupported)
        if unsupported:
            without_compaction = {key: value for key, value in bodies[0].items() if key != "context_management"}
            assert json.dumps(bodies[1]) == json.dumps(without_compaction)
        result = await invoke(messages, tools=tools, provider_context=context)
        assert result.content == "ok"
        assert "context_management" in bodies[0]
        assert ("context_management" in bodies[-1]) is (not unsupported)
        assert json.dumps(bodies[-1]) == json.dumps(bodies[-2] if unsupported else bodies[0])
        assert bodies[-1]["instructions"] == "Stable instructions."
        assert bodies[-1]["input"][0]["role"] == "user"
        assert [item["type"] for item in bodies[-1]["input"][1:]] == ["function_call", "function_call_output"]
        assert bodies[-1]["tools"][0]["name"] == "exec_session"
    finally:
        await provider.aclose()
