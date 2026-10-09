"""Exercise Responses adapters through real SDK requests to a local endpoint."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from aiohttp import web

from nanobot.providers.azure_openai_provider import AzureOpenAIProvider
from nanobot.providers.base import ProviderCallContext
from nanobot.providers.github_copilot_provider import GitHubCopilotProvider
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import ModelAPICapabilities, find_by_name


@pytest.fixture
async def responses_peer():
    requests = []
    reasoning = {
        "type": "reasoning", "id": "rs_1", "encrypted_content": "opaque-reasoning",
        "summary": [{"type": "summary_text", "text": "thinking"}],
    }
    call = {
        "type": "function_call", "id": "fc_1", "call_id": "call_1",
        "name": "read_file", "arguments": '{"path":"report.pdf"}', "status": "completed",
    }

    async def handle(request):
        body = await request.json()
        requests.append((request.path, dict(request.headers), body))
        output = [reasoning, call] if len(requests) == 1 else [{
            "type": "message", "id": "msg_2", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": "report read", "annotations": []}],
        }]
        response = {
            "id": f"resp_{len(requests)}", "object": "response", "created_at": 1,
            "status": "completed", "model": body["model"], "output": output,
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        }
        if not body["stream"]:
            return web.json_response(response)
        stream = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await stream.prepare(request)
        events = []
        if len(requests) == 1:
            events.extend([
                {"type": "response.reasoning_summary_text.delta", "item_id": "rs_1",
                 "summary_index": 0, "delta": "thinking"},
                {"type": "response.output_item.done", "output_index": 0, "item": reasoning},
                {"type": "response.output_item.added", "output_index": 1,
                 "item": {**call, "arguments": "", "status": "in_progress"}},
                {"type": "response.function_call_arguments.delta", "item_id": "fc_1",
                 "output_index": 1, "delta": call["arguments"]},
                {"type": "response.function_call_arguments.done", "item_id": "fc_1",
                 "output_index": 1, "arguments": call["arguments"]},
                {"type": "response.output_item.done", "output_index": 1, "item": call},
            ])
        else:
            events.append({"type": "response.output_text.delta", "delta": "report read"})
        events.append({"type": "response.completed", "response": response})
        for index, event in enumerate(events):
            await stream.write(f"data: {json.dumps({**event, 'sequence_number': index})}\n\n".encode())
        await stream.write_eof()
        return stream

    async def token(_request):
        return web.json_response({"token": "copilot-fixture", "expires_at": 4_000_000_000})

    app = web.Application()
    app.router.add_post("/v1/responses", handle)
    app.router.add_post("/openai/v1/responses", handle)
    app.router.add_get("/copilot_token", token)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 0).start()
    try:
        yield f"http://127.0.0.1:{runner.addresses[0][1]}", requests
    finally:
        await runner.cleanup()


@pytest.mark.parametrize("adapter", ["openai", "azure", "deepseek", "copilot"])
@pytest.mark.parametrize("streaming", [False, True])
async def test_adapters_replay_tool_results_and_reasoning(responses_peer, monkeypatch, adapter, streaming):
    url, requests = responses_peer
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    if adapter == "azure":
        provider = AzureOpenAIProvider(api_key="fixture", api_base=url, default_model="gpt-5.4")
    elif adapter == "copilot":
        monkeypatch.setenv("NANOBOT_COPILOT_BASE_URL", f"{url}/v1")
        monkeypatch.setenv("NANOBOT_COPILOT_TOKEN_URL", f"{url}/copilot_token")
        monkeypatch.setattr(
            "nanobot.providers.github_copilot_provider._load_github_token",
            lambda: SimpleNamespace(access="github-fixture"),
        )
        provider = GitHubCopilotProvider(default_model="github-copilot/gpt-5.4-mini")
    else:
        provider = OpenAICompatProvider(
            api_key="fixture", api_base=f"{url}/v1", spec=find_by_name(adapter),
            default_model="deepseek-v4-flash" if adapter == "deepseek" else "gpt-5.4",
            model_api=ModelAPICapabilities(("responses",), "responses"), extra_body={"store": True} if adapter == "openai" else None,
            provider_name=adapter,
        )
    progress = []
    thinking = []

    async def on_tool(event):
        progress.append(event)

    async def on_thinking(delta):
        thinking.append(delta)

    call = provider.chat_stream if streaming else provider.chat
    callbacks = {"on_tool_call_delta": on_tool, "on_thinking_delta": on_thinking} if streaming else {}
    messages = [{"role": "system", "content": "You are nanobot."}, {"role": "user", "content": "Read report.pdf"}]
    tools = [{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}]
    try:
        first = await call(messages, tools=tools, **callbacks)
        assert first.finish_reason == "stop"
        assert first.tool_calls[0].name == "read_file"
        assert first.tool_calls[0].arguments == {"path": "report.pdf"}
        assert first.reasoning_content == "thinking"
        assert first.usage.total_tokens == 15
        assert first.provider_state is not None
        tool_result = {"role": "tool", "tool_call_id": first.tool_calls[0].id, "content": "PDF extracted text"}
        second = await call(
            messages, tools=tools, **callbacks,
            provider_context=ProviderCallContext(
                session_id="session-a", conversation_state=first.provider_state.with_pending_messages([tool_result]),
            ),
        )
        assert second.content == "report read"
        assert second.provider_state is not None
        assert second.provider_state.provider == first.provider_state.provider
        assert len(requests) == 2
        body = requests[1][2]
        assert body["instructions"] == "You are nanobot."
        assert body["store"] is (adapter == "openai")
        assert body["input"][0]["content"][0]["text"] == "Read report.pdf"
        assert body["input"][1]["encrypted_content"] == "opaque-reasoning"
        assert body["input"][2]["call_id"] == "call_1"
        assert body["input"][3] == {"type": "function_call_output", "call_id": "call_1", "output": "PDF extracted text"}
        assert body["tools"][0]["name"] == "read_file"
        if adapter == "copilot":
            assert body["model"] == "gpt-5.4-mini"
            assert requests[0][1]["Authorization"] == "Bearer copilot-fixture"
        if streaming:
            assert thinking == ["thinking"]
            assert any(event.get("arguments_delta") == '{"path":"report.pdf"}' for event in progress)
            assert progress[-1]["call_id"] == "call_1"
    finally:
        await provider.aclose()
