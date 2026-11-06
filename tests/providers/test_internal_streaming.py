import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import textwrap
import weakref
from collections.abc import AsyncIterator, Awaitable, Callable

import httpx
import openai
import pytest
from agent.runner_helpers import failed_test_consolidator
from loguru import logger
from openai import AsyncOpenAI

from nanobot.agent.hook import AgentHook
from nanobot.agent.memory import MemoryArchiver, MemoryStore
from nanobot.agent.runner import AgentRunner, AgentRunSpec
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.providers.azure_openai_provider import AzureOpenAIProvider
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import ModelAPICapabilities, find_by_name
from nanobot.utils.llm_runtime import LLMRuntime


class _EventStream(httpx.AsyncByteStream):
    def __init__(
        self, events: list[dict], *, stall_at: int | None = None, event_delay: float = 0,
    ) -> None:
        self.events = events
        self.stall_at = stall_at
        self.event_delay = event_delay
        self.sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for index, event in enumerate(self.events):
            if index == self.stall_at:
                await asyncio.Event().wait()
            if self.event_delay:
                await self.sleep(self.event_delay)
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
    clients = []

    async def make(
        api: str, kind: str, *, stall_at: int | None = None,
        event_delay: float = 0, idle_timeout: float = 5,
    ):
        monkeypatch.setenv("NANOBOT_STREAM_IDLE_TIMEOUT_S", str(idle_timeout))
        stream = _EventStream(_events(api, kind), stall_at=stall_at, event_delay=event_delay)

        def handler(request: httpx.Request) -> httpx.Response:
            assert json.loads(request.content)["stream"] is True
            assert request.extensions["timeout"]["read"] == idle_timeout
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
                spec=find_by_name("openai"),
                model_api=ModelAPICapabilities(("chat_completions",), "chat_completions") if api == "chat" else ModelAPICapabilities(("responses",), "responses"),
            )
        provider._client = client
        provider._CHAT_RETRY_DELAYS = ()
        return provider, stream

    yield make
    for client in clients:
        await client.close()


@pytest.mark.parametrize("api", ["chat", "responses", "azure"])
@pytest.mark.parametrize("kind", ["content", "reasoning", "tool", "metadata"])
async def test_silent_stream_renews_idle_timeout_on_every_event(
    make_provider, monkeypatch, api, kind,
):
    provider, stream = await make_provider(api, kind, event_delay=0.05, idle_timeout=0.3)
    loop = asyncio.get_running_loop()
    started_at = now = loop.time()
    monkeypatch.setattr(loop, "time", lambda: now)

    async def advance_time(delay: float) -> None:
        nonlocal now
        now += delay
        await asyncio.sleep(0)

    stream.sleep = advance_time
    response = await provider.chat_stream_with_retry([{"role": "user", "content": "work"}])
    assert now - started_at > 0.3
    assert response.finish_reason == "stop"
    assert response.content is not None and response.content.strip().endswith("done")
    assert stream.closed


@pytest.mark.parametrize("api", ["chat", "responses", "azure"])
@pytest.mark.parametrize("stall_at", [0, 2], ids=["first-event", "after-reasoning"])
async def test_silent_stream_times_out_without_events(make_provider, api, stall_at):
    provider, stream = await make_provider(api, "reasoning", stall_at=stall_at, idle_timeout=0.3)
    response = await asyncio.wait_for(
        provider.chat_stream_with_retry([{"role": "user", "content": "work"}]),
        timeout=2,
    )
    assert response.finish_reason == "error"
    assert response.error_kind == "timeout"
    assert stream.closed


@pytest.mark.parametrize("api", ["chat", "responses", "azure"])
@pytest.mark.parametrize("kind", ["content", "reasoning", "tool", "metadata"])
async def test_silent_stream_rejects_eof_without_completion(make_provider, api, kind):
    provider, stream = await make_provider(api, kind)
    stream.events.pop()

    response = await provider.chat_stream_with_retry([{"role": "user", "content": "work"}])

    assert response.finish_reason == "error"
    assert response.error_kind == "connection"
    assert not response.should_execute_tools
    assert stream.closed


@pytest.mark.parametrize("api", ["chat", "responses", "azure"])
async def test_archive_preserves_raw_history_after_truncated_stream_retries(
    make_provider, tmp_path, api,
):
    provider, stream = await make_provider(api, "content")
    stream.events.pop()
    provider._CHAT_RETRY_DELAYS = (0,)
    calls = []
    provider.set_llm_call_observer(calls.append)
    store = MemoryStore(tmp_path)
    archiver = MemoryArchiver(
        store=store, build_messages=lambda **kwargs: [], get_tool_definitions=lambda: [],
    )
    messages = [{"role": "user", "content": "Mandatory constraint: PRESERVE_AUDIT_LOGS."}]

    summary = await archiver.archive(
        messages,
        runtime=LLMRuntime.capture(provider, "gpt-5.2", context_window_tokens=128_000),
        session_key="cli:archive",
        history=messages,
        request_tools=[],
    )

    assert len(calls) == 2
    assert all(call.finish_reason == "error" and call.error_kind == "connection" for call in calls)
    assert summary is not None and "[RAW]" in summary and "PRESERVE_AUDIT_LOGS" in summary
    entries = store.read_unprocessed_history(since_cursor=0)
    assert len(entries) == 1
    assert entries[0]["content"] == summary
    assert stream.closed


@pytest.mark.parametrize("show_deltas", [False, True])
async def test_runner_streams_past_old_wall_limit_with_optional_ui(
    make_provider, monkeypatch, show_deltas,
):
    monkeypatch.setenv("NANOBOT_LLM_TIMEOUT_S", "0.01")
    provider, _ = await make_provider("chat", "reasoning", event_delay=0.05)
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
        consolidate_history=failed_test_consolidator,
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
        consolidate_history=failed_test_consolidator,
        max_iterations_message="Tool budget exhausted.",
    )), timeout=1)
    assert provider.calls == (2 if finalize else 1)
    assert result.stop_reason == ("max_iterations" if finalize else "error")
    if finalize:
        assert result.final_content == "Tool budget exhausted."


def _chat_event(delta=None, *, finish=None, usage=None):
    event = {
        "id": "synthetic", "object": "chat.completion.chunk", "created": 0,
        "model": "synthetic", "choices": [],
    }
    if delta is not None:
        event["choices"] = [{"index": 0, "delta": delta, "finish_reason": finish}]
    if usage is not None:
        event["usage"] = usage
    return event


def _bad_chat_event(kind):
    if kind == "usage":
        return _chat_event(usage={"prompt_tokens": "invalid", "completion_tokens": 1, "total_tokens": 2})
    return _chat_event({"tool_calls": [{
        "index": [0], "id": "bad", "type": "function",
        "function": {"name": "bad_tool", "arguments": "{}"},
    }]})


class _ControlledChatStream(_EventStream):
    def __init__(self, events, *, disconnect=False, pause_at=None, close_error=None):
        super().__init__(events)
        self.disconnect = disconnect
        self.pause_at = pause_at
        self.close_error = close_error
        self.reached_pause = asyncio.Event()
        self.release = asyncio.Event()
        self.sent = 0
        self.close_calls = 0

    async def aclose(self):
        self.close_calls += 1
        self.closed = True
        if self.close_error is not None:
            raise self.close_error

    async def __aiter__(self):
        for index, event in enumerate(self.events):
            if index == self.pause_at:
                self.reached_pause.set()
                await self.release.wait()
            self.sent += 1
            yield f"data: {json.dumps(event)}\n\n".encode()
        if self.disconnect:
            raise ConnectionError("synthetic connection lost")
        yield b"data: [DONE]\n\n"


@pytest.fixture
async def chat_sdk():
    clients = []

    def make(streams):
        requests = []

        def handler(request):
            requests.append(request)
            assert json.loads(request.content)["stream"] is True
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"},
                stream=streams[len(requests) - 1],
            )

        client = AsyncOpenAI(
            api_key="synthetic", base_url="https://synthetic.invalid/v1", max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        clients.append(client)
        provider = OpenAICompatProvider(
            api_key="synthetic", default_model="synthetic",
            model_api=ModelAPICapabilities(("chat_completions",), "chat_completions"),
        )
        provider._client = client
        provider._CHAT_RETRY_DELAYS = (0,)
        return provider, requests

    yield make
    for client in clients:
        await client.close()


@pytest.mark.parametrize("first_bad", ["usage", "index"])
async def test_chat_parse_failure_waits_for_all_live_deltas(chat_sdk, first_bad):
    other_bad = "index" if first_bad == "usage" else "usage"
    stream = _ControlledChatStream([
        _bad_chat_event(first_bad), _bad_chat_event(other_bad),
        _chat_event({
            "content": "later", "reasoning_content": "thought",
            "tool_calls": [{"index": 1, "id": "good", "type": "function",
                            "function": {"name": "tool", "arguments": "{}"}}],
        }),
        _chat_event({}, finish="stop"),
    ], pause_at=3)
    provider, _ = chat_sdk([stream])
    callbacks = []

    async def content(value):
        callbacks.append(("content", value))

    async def thinking(value):
        callbacks.append(("thinking", value))

    async def tool(value):
        callbacks.append(("tool", value))

    task = asyncio.create_task(provider.chat_stream(
        [{"role": "user", "content": "work"}], on_content_delta=content,
        on_thinking_delta=thinking, on_tool_call_delta=tool,
    ))
    try:
        await asyncio.wait_for(stream.reached_pause.wait(), timeout=1)
        assert not task.done()
        assert callbacks == [
            ("tool", {"index": [0], "call_id": "bad", "name": "bad_tool", "arguments_delta": "{}"}),
            ("content", "later"), ("thinking", "thought"),
            ("tool", {"index": 1, "call_id": "good", "name": "tool", "arguments_delta": "{}"}),
        ]
        stream.release.set()
        result = await task
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    assert result.finish_reason == "error"
    assert ("invalid literal" if first_bad == "usage" else "unhashable type") in result.content
    assert stream.closed


@pytest.mark.parametrize("bad", ["usage", "index"])
@pytest.mark.parametrize("interruption", ["disconnect", "eof", "disconnect-after-finish"])
async def test_chat_interruption_precedes_parse_failure_and_retries(chat_sdk, bad, interruption):
    events = [_bad_chat_event(bad), _chat_event({"reasoning_content": "before retry"})]
    if interruption == "disconnect-after-finish":
        events.append(_chat_event({}, finish="stop"))
    first = _ControlledChatStream(events, disconnect=interruption != "eof")
    second = _ControlledChatStream([
        _chat_event({"content": "recovered"}), _chat_event({}, finish="stop"),
        _chat_event(usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}),
    ])
    provider, requests = chat_sdk([first, second])
    thinking, content = [], []

    async def on_thinking(value):
        thinking.append(value)

    async def on_content(value):
        content.append(value)

    result = await provider.chat_stream_with_retry(
        [{"role": "user", "content": "work"}],
        on_thinking_delta=on_thinking, on_content_delta=on_content,
    )
    assert len(requests) == 2
    assert thinking == ["before retry"]
    assert content == ["recovered"]
    assert result.finish_reason == "stop" and result.content == "recovered"
    assert result.usage is not None and result.usage.total_tokens == 15
    assert first.closed and second.closed


async def test_chat_content_after_parse_failure_preserves_retry_guard(chat_sdk):
    first = _ControlledChatStream([
        _bad_chat_event("usage"), _chat_event({"content": "already shown"}),
    ], disconnect=True)
    provider, requests = chat_sdk([first])
    content = []

    async def on_content(value):
        content.append(value)

    result = await provider.chat_stream_with_retry(
        [{"role": "user", "content": "work"}], on_content_delta=on_content,
    )
    assert len(requests) == 1 and content == ["already shown"]
    assert result.error_kind == "connection" and "synthetic connection lost" in result.content
    assert first.closed


@pytest.mark.parametrize("parse_first", [False, True])
async def test_chat_callback_error_closes_stream(chat_sdk, parse_first):
    prefix = [_bad_chat_event("usage")] if parse_first else []
    stream = _ControlledChatStream(prefix + [
        _chat_event({"content": "fail callback"}), _chat_event({}, finish="stop"),
    ])
    provider, _ = chat_sdk([stream])

    async def on_content(value):
        raise RuntimeError("callback failed")

    result = await provider.chat_stream(
        [{"role": "user", "content": "work"}], on_content_delta=on_content,
    )
    assert result.finish_reason == "error" and "callback failed" in result.content
    assert stream.sent == len(prefix) + 1 and stream.closed


@pytest.mark.parametrize("parse_first", [False, True])
@pytest.mark.parametrize("blocked", ["read", "callback"])
async def test_chat_cancel_closes_stream(chat_sdk, blocked, parse_first):
    prefix = [_bad_chat_event("usage")] if parse_first else []
    stream = _ControlledChatStream(prefix + [
        _chat_event({"content": "wait"}), _chat_event({}, finish="stop"),
    ], pause_at=len(prefix) if blocked == "read" else None)
    provider, _ = chat_sdk([stream])
    callback_started = asyncio.Event()

    async def on_content(value):
        callback_started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(provider.chat_stream(
        [{"role": "user", "content": "work"}], on_content_delta=on_content,
    ))
    try:
        started = stream.reached_pause if blocked == "read" else callback_started
        await asyncio.wait_for(started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stream.closed
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_chat_timeout_after_parse_failure_wins_and_closes(chat_sdk, monkeypatch):
    monkeypatch.setenv("NANOBOT_STREAM_IDLE_TIMEOUT_S", "0.05")
    stream = _ControlledChatStream([
        _bad_chat_event("usage"), _chat_event({}, finish="stop"),
    ], pause_at=1)
    provider, _ = chat_sdk([stream])
    result = await provider.chat_stream([{"role": "user", "content": "work"}])
    assert result.error_kind == "timeout"
    assert stream.closed


async def test_chat_sdk_error_after_parse_failure_wins_and_closes(chat_sdk):
    stream = _ControlledChatStream([
        _bad_chat_event("usage"), {"error": {"message": "provider stream error", "code": "bad_stream"}},
        _chat_event({}, finish="stop"),
    ])
    provider, _ = chat_sdk([stream])
    result = await provider.chat_stream([{"role": "user", "content": "work"}])
    assert result.finish_reason == "error" and "provider stream error" in result.content
    assert result.error_code == "bad_stream"
    assert stream.sent == 2 and stream.closed


@pytest.mark.parametrize("bad", [False, True])
async def test_chat_sdk_chunks_are_not_retained_during_stream(chat_sdk, monkeypatch, bad):
    stream = _ControlledChatStream([
        _chat_event({"content": "first"}),
        _bad_chat_event("usage") if bad else _chat_event({"content": "second"}),
        _chat_event({"content": "third"}), _chat_event({"content": "fourth"}),
        _chat_event({}, finish="stop", usage={
            "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15,
        }),
    ])
    provider, _ = chat_sdk([stream])
    references = []
    released = []
    deltas = []
    original_add = OpenAICompatProvider._ChatStreamAccumulator.add

    def track_add(accumulator, chunk):
        references.append(weakref.ref(chunk))
        original_add(accumulator, chunk)

    monkeypatch.setattr(OpenAICompatProvider._ChatStreamAccumulator, "add", track_add)

    async def on_content(value):
        deltas.append(value)
        if value == "fourth":
            released.extend(ref() is None for ref in references[:2])

    result = await provider.chat_stream(
        [{"role": "user", "content": "work"}], on_content_delta=on_content,
    )
    assert released == [True, True]
    assert deltas == (["first", "third", "fourth"] if bad else ["first", "second", "third", "fourth"])
    assert result.finish_reason == ("error" if bad else "stop")
    if not bad:
        assert result.content == "".join(deltas)
        assert result.usage is not None and result.usage.total_tokens == 15
    assert stream.closed


async def test_chat_sdk_normal_deltas_usage_and_tool_metadata(chat_sdk):
    stream = _ControlledChatStream([
        _chat_event({
            "content": "hello ", "reasoning_content": "think ",
            "tool_calls": [{
                "index": 0, "id": "call_1", "type": "function",
                "function": {"name": "write_file", "arguments": '{"path":', "vendor_fn": "f"},
                "extra_content": {"google": {"thought_signature": "signed"}},
                "vendor_call": "c",
            }],
        }),
        _chat_event({
            "content": "world", "reasoning": "more",
            "tool_calls": [{"index": 0, "function": {"arguments": '"a.txt"}'}}],
        }),
        _chat_event({"tool_calls": [{
            "index": 1, "id": "call_1", "type": "function",
            "function": {"name": "read_file", "arguments": '{"path":"b.txt"}'},
        }]}),
        _chat_event({}, finish="tool_calls"),
        _chat_event(usage={
            "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 16,
            "prompt_tokens_details": {"cached_tokens": 3},
        }),
    ])
    provider, requests = chat_sdk([stream])
    callbacks = []

    async def content(value):
        callbacks.append(("content", value))

    async def thinking(value):
        callbacks.append(("thinking", value))

    async def tool(value):
        callbacks.append(("tool", value))

    result = await provider.chat_stream(
        [{"role": "user", "content": "work"}], on_content_delta=content,
        on_thinking_delta=thinking, on_tool_call_delta=tool,
    )
    assert callbacks == [
        ("content", "hello "), ("thinking", "think "),
        ("tool", {"index": 0, "call_id": "call_1", "name": "write_file", "arguments_delta": '{"path":'}),
        ("content", "world"), ("thinking", "more"),
        ("tool", {"index": 0, "call_id": "", "name": "", "arguments_delta": '"a.txt"}'}),
        ("tool", {"index": 1, "call_id": "call_1", "name": "read_file", "arguments_delta": '{"path":"b.txt"}'}),
    ]
    assert len(requests) == 1 and stream.closed
    assert result.finish_reason == "tool_calls"
    assert result.content == "hello world" and result.reasoning_content == "think more"
    assert result.usage is not None
    assert (result.usage.input_tokens, result.usage.output_tokens, result.usage.total_tokens) == (10, 5, 16)
    assert result.usage.cache_read_tokens == 3
    first, second = result.tool_calls
    assert (first.id, first.name, first.arguments) == ("call_1", "write_file", {"path": "a.txt"})
    assert first.extra_content == {"google": {"thought_signature": "signed"}}
    assert first.provider_specific_fields == {"vendor_call": "c"}
    assert first.function_provider_specific_fields == {"vendor_fn": "f"}
    assert second.id and second.id != first.id
    assert (second.name, second.arguments) == ("read_file", {"path": "b.txt"})


async def test_chat_sdk_mistral_thinking_and_legacy_function_call(chat_sdk):
    stream = _ControlledChatStream([
        _chat_event({
            "content": [
                {"type": "thinking", "thinking": [{"type": "text", "text": "ponder"}]},
                {"type": "text", "text": "hello"},
            ],
            "function_call": {"name": "old_tool", "arguments": '{"n":'},
        }),
        _chat_event({"function_call": {"arguments": "1}"}}, finish="function_call"),
        _chat_event(usage={"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}),
    ])
    provider, _ = chat_sdk([stream])
    callbacks = []

    async def content(value):
        callbacks.append(("content", value))

    async def thinking(value):
        callbacks.append(("thinking", value))

    async def tool(value):
        callbacks.append(("tool", value))

    result = await provider.chat_stream(
        [{"role": "user", "content": "work"}], on_content_delta=content,
        on_thinking_delta=thinking, on_tool_call_delta=tool,
    )
    assert callbacks == [
        ("content", "hello"), ("thinking", "ponder"),
        ("tool", {"index": 0, "call_id": "", "name": "old_tool", "arguments_delta": '{"n":'}),
        ("tool", {"index": 0, "call_id": "", "name": "", "arguments_delta": "1}"}),
    ]
    assert result.finish_reason == "function_call" and result.content == "hello"
    assert result.reasoning_content == "ponder"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "old_tool" and result.tool_calls[0].arguments == {"n": 1}
    assert result.usage is not None and result.usage.total_tokens == 6
    assert stream.closed


@pytest.fixture
def cleanup_warnings():
    messages = []
    sink = logger.add(messages.append, format="{message}", level="WARNING")
    try:
        yield messages
    finally:
        logger.remove(sink)


def _require_minimum_sdk_for_iterator_close_failure():
    # SDK 2.24 closes inside its iterator and masks these errors before the
    # provider's cleanup runs. That pre-existing SDK behavior is outside this fix.
    if openai.__version__ != "2.8.0":
        pytest.skip("this regression targets the 2.8.0 SDK's caller-owned close")


@pytest.mark.parametrize("blocked", ["read", "callback"])
async def test_chat_cancel_wins_over_close_error_without_retry(chat_sdk, cleanup_warnings, blocked):
    if blocked == "read":
        _require_minimum_sdk_for_iterator_close_failure()
    stream = _ControlledChatStream([
        _chat_event({"content": "waiting"}), _chat_event({}, finish="stop"),
    ], pause_at=0 if blocked == "read" else None, close_error=httpx.CloseError("connection reset"))
    retry = _ControlledChatStream([_chat_event({"content": "unexpected"}, finish="stop")])
    provider, requests = chat_sdk([stream, retry])
    callback_started = asyncio.Event()

    async def on_content(value):
        if value == "waiting":
            callback_started.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(provider.chat_stream_with_retry(
        [{"role": "user", "content": "work"}], on_content_delta=on_content,
    ))
    try:
        started = stream.reached_pause if blocked == "read" else callback_started
        await asyncio.wait_for(started.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    assert len(requests) == 1 and stream.closed and stream.close_calls == 1
    assert any("connection reset" in message for message in cleanup_warnings)


@pytest.mark.parametrize("parse_first", [False, True])
async def test_chat_provider_error_wins_over_close_error_without_retry(
    chat_sdk, cleanup_warnings, parse_first,
):
    _require_minimum_sdk_for_iterator_close_failure()
    prefix = [_bad_chat_event("usage")] if parse_first else []
    stream = _ControlledChatStream(prefix + [{"error": {
        "message": "quota exhausted", "type": "insufficient_quota", "code": "insufficient_quota",
    }}], close_error=httpx.CloseError("connection reset"))
    retry = _ControlledChatStream([_chat_event({"content": "unexpected"}, finish="stop")])
    provider, requests = chat_sdk([stream, retry])

    result = await provider.chat_stream_with_retry([{"role": "user", "content": "work"}])

    assert result.finish_reason == "error"
    assert result.error_type == result.error_code == "insufficient_quota"
    assert "quota exhausted" in result.content
    assert len(requests) == 1 and stream.closed and stream.close_calls == 1
    assert any("connection reset" in message for message in cleanup_warnings)


async def test_chat_disconnect_wins_over_close_error_and_still_retries(chat_sdk, cleanup_warnings):
    _require_minimum_sdk_for_iterator_close_failure()
    first = _ControlledChatStream([
        _bad_chat_event("usage"), _chat_event({"reasoning_content": "thinking"}),
    ], disconnect=True, close_error=httpx.CloseError("connection reset"))
    second = _ControlledChatStream([_chat_event({"content": "recovered"}, finish="stop")])
    provider, requests = chat_sdk([first, second])

    result = await provider.chat_stream_with_retry([{"role": "user", "content": "work"}])

    assert result.finish_reason == "stop" and result.content == "recovered"
    assert len(requests) == 2 and first.closed and second.closed
    assert any("after ConnectionError: connection reset" in message for message in cleanup_warnings)


async def test_chat_timeout_wins_over_close_error(chat_sdk, cleanup_warnings, monkeypatch):
    _require_minimum_sdk_for_iterator_close_failure()
    monkeypatch.setenv("NANOBOT_STREAM_IDLE_TIMEOUT_S", "0.05")
    stream = _ControlledChatStream([
        _bad_chat_event("usage"), _chat_event({}, finish="stop"),
    ], pause_at=1, close_error=httpx.CloseError("connection reset"))
    provider, requests = chat_sdk([stream])

    result = await provider.chat_stream([{"role": "user", "content": "work"}])

    assert result.error_kind == "timeout" and len(requests) == 1 and stream.closed
    assert any("connection reset" in message for message in cleanup_warnings)


async def test_chat_callback_error_wins_over_close_error(chat_sdk, cleanup_warnings):
    stream = _ControlledChatStream([
        _bad_chat_event("usage"), _chat_event({"content": "fail"}),
    ], close_error=httpx.CloseError("connection reset"))
    provider, requests = chat_sdk([stream])

    async def on_content(value):
        raise RuntimeError("callback failed")

    result = await provider.chat_stream(
        [{"role": "user", "content": "work"}], on_content_delta=on_content,
    )
    assert result.finish_reason == "error" and "callback failed" in result.content
    assert len(requests) == 1 and stream.closed and stream.close_calls == 1
    assert any("connection reset" in message for message in cleanup_warnings)


@pytest.mark.parametrize("close_fails", [False, True])
@pytest.mark.parametrize("error_type", [RuntimeError, ConnectionError])
async def test_chat_callback_error_does_not_retry_without_images(chat_sdk, close_fails, error_type):
    stream = _ControlledChatStream(
        [_chat_event({"reasoning_content": "thinking"})],
        close_error=httpx.CloseError("connection reset") if close_fails else None,
    )
    retry = _ControlledChatStream([_chat_event({"content": "unexpected"}, finish="stop")])
    provider, requests = chat_sdk([stream, retry])
    messages = [{"role": "user", "content": [
        {"type": "text", "text": "work"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
    ]}]
    original = json.loads(json.dumps(messages))

    async def on_thinking(_value):
        raise error_type("callback failed")

    result = await provider.chat_stream_with_retry(messages, on_thinking_delta=on_thinking)

    assert result.finish_reason == "error" and "callback failed" in result.content
    assert len(requests) == 1
    assert messages == original
    assert stream.closed


@pytest.mark.parametrize("mode", ["success", "quota", "cancel"])
def test_langfuse_async_openai_chat_stream(mode):
    if importlib.util.find_spec("langfuse") is None:
        pytest.skip("optional Langfuse dependency is not installed")
    if mode == "quota":
        _require_minimum_sdk_for_iterator_close_failure()

    # Langfuse instruments OpenAI globally; isolate those hooks in a child.
    script = textwrap.dedent("""
        import asyncio
        import runpy
        import sys
        from pathlib import Path

        import httpx
        import langfuse.openai as langfuse_openai
        from nanobot.providers.openai_compat_provider import OpenAICompatProvider
        from nanobot.providers.registry import ModelAPICapabilities

        test_file = Path(sys.argv[2]).resolve()
        sys.path.insert(0, str(test_file.parent.parent))
        helpers = runpy.run_path(str(test_file))
        event, stream_type = helpers["_chat_event"], helpers["_ControlledChatStream"]
        mode = sys.argv[1]
        starts, ends = [], []

        class Generation:
            def update(self, **kwargs):
                return self
            def end(self):
                ends.append(True)
        class Tracer:
            def start_observation(self, **kwargs):
                starts.append(True)
                return Generation()
        langfuse_openai.get_client = lambda **kwargs: Tracer()

        events = ([{"error": {"message": "quota exhausted", "type": "insufficient_quota",
                              "code": "insufficient_quota"}}] if mode == "quota" else
                  [event({"content": "complete"}, finish="stop")])
        stream = stream_type(events, close_error=(
            httpx.CloseError("connection reset") if mode != "success" else None))
        requests = []
        def handler(request):
            requests.append(request)
            reply = stream if len(requests) == 1 else stream_type([
                event({"content": "unexpected retry"}, finish="stop")])
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=reply)

        async def main():
            client = langfuse_openai.AsyncOpenAI(
                api_key="synthetic", base_url="https://synthetic.invalid/v1", max_retries=0,
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False))
            provider = OpenAICompatProvider(
                api_key="synthetic", default_model="synthetic",
                model_api=ModelAPICapabilities(("chat_completions",), "chat_completions"))
            provider._client = client
            provider._CHAT_RETRY_DELAYS = (0,)
            try:
                if mode == "cancel":
                    started = asyncio.Event()
                    async def on_content(value):
                        started.set()
                        await asyncio.Event().wait()
                    task = asyncio.create_task(provider.chat_stream_with_retry(
                        [{"role": "user", "content": "work"}], on_content_delta=on_content))
                    await asyncio.wait_for(started.wait(), timeout=5)
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    else:
                        raise AssertionError("caller cancellation was lost")
                else:
                    result = await provider.chat_stream_with_retry(
                        [{"role": "user", "content": "work"}])
                    if mode == "success":
                        assert result.finish_reason == "stop" and result.content == "complete"
                    else:
                        assert result.finish_reason == "error"
                        assert result.error_type == result.error_code == "insufficient_quota"
                assert len(requests) == 1 and stream.closed and stream.close_calls == 1
                assert len(starts) == len(ends) == 1
            finally:
                await client.close()
        asyncio.run(main())
    """)
    env = {
        key: os.environ[key]
        for key in (
            "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE", "APPDATA",
            "LOCALAPPDATA", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "LD_LIBRARY_PATH",
        )
        if key in os.environ
    }
    result = subprocess.run(
        [sys.executable, "-B", "-c", script, mode, __file__], env=env,
        capture_output=True, text=True, timeout=30, check=False,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    assert result.returncode == 0, result.stdout + result.stderr
