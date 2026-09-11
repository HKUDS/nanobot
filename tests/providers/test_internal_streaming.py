"""Internal model calls consume active streams and stop when the stream goes idle."""

import asyncio
import json
from collections.abc import AsyncIterator

import httpx
import pytest
from openai import AsyncOpenAI

from nanobot.agent.hook import AgentHook
from nanobot.agent.runner import AgentRunner, AgentRunSpec
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.providers.azure_openai_provider import AzureOpenAIProvider
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import ProviderSpec
from nanobot.utils.llm_runtime import LLMRuntime


class _EventStream(httpx.AsyncByteStream):
    def __init__(self, events: list[dict], *, stall_at: int | None = None) -> None:
        self.events = events
        self.stall_at = stall_at
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for index, event in enumerate(self.events):
            if index == self.stall_at:
                await asyncio.Event().wait()
            await asyncio.sleep(0.05)
            yield f"data: {json.dumps(event)}\n\n".encode()

    async def aclose(self) -> None:
        self.closed = True


def _events(api: str, kind: str) -> list[dict]:
    if api == "chat":
        deltas = {
            "content": {"content": "a"},
            "reasoning": {"reasoning_content": "thinking"},
            "tool": {"tool_calls": [{"index": 0, "function": {"arguments": " "}}]},
            "metadata": {},
        }
        return [
            {"choices": [{"index": 0, "delta": deltas[kind], "finish_reason": None}]}
            for _ in range(8)
        ] + [{"choices": [{"index": 0, "delta": {"content": "done"}, "finish_reason": "stop"}]}]
    event_types = {
        "content": "response.output_text.delta",
        "reasoning": "response.reasoning_summary_text.delta",
        "tool": "response.function_call_arguments.delta",
        "metadata": "response.in_progress",
    }
    return [
        {"type": event_types[kind], "delta": " ", "item_id": "item", "output_index": 0}
        for _ in range(8)
    ] + [{"type": "response.output_text.delta", "delta": "done"}, {
        "type": "response.completed",
        "response": {
            "id": "response",
            "status": "completed",
            "output": [{
                "id": "message", "type": "message", "role": "assistant",
                "content": [{"type": "output_text", "text": "done"}],
            }],
            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        },
    }]


@pytest.fixture
async def make_provider(monkeypatch):
    monkeypatch.setenv("NANOBOT_STREAM_IDLE_TIMEOUT_S", "0.3")
    clients = []

    async def make(api: str, kind: str, *, stall_at: int | None = None):
        stream = _EventStream(_events(api, kind), stall_at=stall_at)

        def handler(request: httpx.Request) -> httpx.Response:
            assert json.loads(request.content)["stream"] is True
            assert request.extensions["timeout"]["read"] == 0.3
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)

        client = AsyncOpenAI(
            api_key="test", max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        clients.append(client)
        if api == "azure":
            provider = AzureOpenAIProvider(api_key="test", api_base="https://example.com")
            await provider._client.close()
        else:
            provider = OpenAICompatProvider(
                api_key="test", default_model="gpt-5.2",
                spec=ProviderSpec(name="openai", keywords=(), env_key=""),
                api_type="chat_completions" if api == "chat" else "responses",
            )
        provider._client = client
        provider._CHAT_RETRY_DELAYS = ()
        return provider, stream

    yield make
    for client in clients:
        await client.close()


@pytest.mark.parametrize("api", ["chat", "responses", "azure"])
@pytest.mark.parametrize("kind", ["content", "reasoning", "tool", "metadata"])
async def test_silent_stream_renews_idle_timeout_on_every_event(make_provider, api, kind):
    provider, stream = await make_provider(api, kind)
    response = await provider.chat_stream_with_retry([{"role": "user", "content": "work"}])
    assert response.finish_reason == "stop"
    assert response.content is not None and response.content.strip().endswith("done")
    assert stream.closed


@pytest.mark.parametrize("api", ["chat", "responses", "azure"])
@pytest.mark.parametrize("stall_at", [0, 2], ids=["first-event", "after-reasoning"])
async def test_silent_stream_times_out_without_events(make_provider, api, stall_at):
    provider, stream = await make_provider(api, "reasoning", stall_at=stall_at)
    response = await asyncio.wait_for(
        provider.chat_stream_with_retry([{"role": "user", "content": "work"}]),
        timeout=2,
    )
    assert response.finish_reason == "error"
    assert response.error_kind == "timeout"
    assert stream.closed


@pytest.mark.parametrize("show_deltas", [False, True])
async def test_runner_streams_past_old_wall_limit_with_optional_ui(
    make_provider, monkeypatch, show_deltas,
):
    monkeypatch.setenv("NANOBOT_LLM_TIMEOUT_S", "0.01")
    provider, _ = await make_provider("chat", "reasoning")
    content_deltas = []

    class Hook(AgentHook):
        def wants_streaming(self):
            return show_deltas

        async def on_stream(self, context, delta):
            content_deltas.append(delta)

    result = await AgentRunner().run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "work"}],
        tools=ToolRegistry(),
        runtime=LLMRuntime.capture(provider, "gpt-5.2", context_window_tokens=128_000),
        max_iterations=1, max_tool_result_chars=1_000, hook=Hook(),
    ))
    assert result.stop_reason == "completed"
    assert result.final_content == "done"
    assert content_deltas == (["done"] if show_deltas else [])


@pytest.mark.parametrize("finalize", [False, True], ids=["model-request", "finalization"])
async def test_chat_only_provider_still_has_a_timeout(monkeypatch, finalize):
    monkeypatch.setenv("NANOBOT_STREAM_IDLE_TIMEOUT_S", "0.05")

    class ChatOnlyProvider(LLMProvider):
        _CHAT_RETRY_DELAYS = ()

        def __init__(self):
            super().__init__(provider_name="test")
            self.calls = 0

        def get_default_model(self):
            return "test"

        async def chat(self, **kwargs):
            self.calls += 1
            if finalize and self.calls == 1:
                return LLMResponse(
                    content=None, finish_reason="tool_calls",
                    tool_calls=[ToolCallRequest(id="call", name="missing", arguments={})],
                )
            await asyncio.Event().wait()

    provider = ChatOnlyProvider()
    result = await asyncio.wait_for(AgentRunner().run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "work"}],
        tools=ToolRegistry(),
        runtime=LLMRuntime.capture(provider, "test", context_window_tokens=128_000),
        max_iterations=1, max_tool_result_chars=1_000,
        max_iterations_message="Tool budget exhausted.",
    )), timeout=1)
    assert provider.calls == (2 if finalize else 1)
    assert result.stop_reason == ("max_iterations" if finalize else "error")
    if finalize:
        assert result.final_content == "Tool budget exhausted."
