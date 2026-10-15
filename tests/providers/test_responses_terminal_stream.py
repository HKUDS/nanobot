"""Responses terminal events must not depend on the transport reaching EOF."""

import asyncio
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from openai import APIConnectionError, AsyncOpenAI

from nanobot.providers.base import LLMUsage
from nanobot.providers.openai_responses import (
    ResponsesStreamCapture,
    consume_sdk_stream,
    consume_sse_with_reasoning,
)


class _ResponseBody(httpx.AsyncByteStream):
    def __init__(self, events, tail):
        self.events = events
        self.tail = tail
        self.tail_read = False
        self.closed = False

    async def __aiter__(self):
        for event in self.events:
            yield f"data: {json.dumps(event)}\n\n".encode()
        self.tail_read = True
        if self.tail == "disconnect":
            raise httpx.RemoteProtocolError("peer closed connection without sending complete message body")
        if self.tail == "open":
            await asyncio.Event().wait()

    async def aclose(self):
        self.closed = True


@asynccontextmanager
async def _consume(transport, body):
    def handle(request):
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http_client:
        if transport == "sse":
            async with http_client.stream("POST", "https://responses.test/v1/responses") as response:
                yield consume_sse_with_reasoning, response
        else:
            async with AsyncOpenAI(api_key="test", http_client=http_client) as client:
                async with await client.responses.create(model="test", input="test", stream=True) as stream:
                    yield consume_sdk_stream, stream


@pytest.mark.parametrize("transport", ["sse", "sdk"])
@pytest.mark.parametrize("status", ["completed", "incomplete"])
@pytest.mark.parametrize("tail", ["disconnect", "open", "eof"])
async def test_terminal_event_returns_without_reading_transport_tail(transport, status, tail):
    output = [
        {"type": "compaction", "id": "cmp_1", "encrypted_content": "fixture"},
        {"type": "reasoning", "id": "rs_1", "summary": [{"type": "summary_text", "text": "summary"}]},
    ]
    terminal = {
        "status": status,
        "output": output,
        "incomplete_details": {"reason": "max_output_tokens"} if status == "incomplete" else None,
        "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    }
    body = _ResponseBody([
        {"type": "response.output_text.delta", "delta": "answer"},
        {"type": f"response.{status}", "response": terminal},
    ], tail)
    capture = ResponsesStreamCapture()
    reasoning_deltas = []

    async def on_reasoning(delta):
        reasoning_deltas.append(delta)

    async with _consume(transport, body) as (consume, stream):
        result = await asyncio.wait_for(
            consume(stream, capture=capture, on_reasoning_delta=on_reasoning), timeout=1,
        )
        assert not body.tail_read

    content, tools, finish, usage, reasoning = result
    assert (content, tools, finish) == ("answer", [], "stop" if status == "completed" else "length")
    assert usage == LLMUsage.reported(input_tokens=10, output_tokens=5)
    assert reasoning == "summary"
    assert reasoning_deltas == ["summary"]
    assert capture.completed
    assert capture.output_items[0]["encrypted_content"] == "fixture"
    assert body.closed


@pytest.mark.parametrize("transport", ["sse", "sdk"])
@pytest.mark.parametrize("tail", ["disconnect", "eof"])
async def test_transport_failure_before_terminal_is_not_success(transport, tail):
    body = _ResponseBody([{"type": "response.output_text.delta", "delta": "partial"}], tail)
    capture = ResponsesStreamCapture()
    expected: tuple[type[Exception], ...] = (ConnectionError,)
    if tail == "disconnect":
        expected = (
            (APIConnectionError, httpx.RemoteProtocolError)
            if transport == "sdk"
            else (httpx.RemoteProtocolError,)
        )
    async with _consume(transport, body) as (consume, stream):
        with pytest.raises(expected):
            await consume(stream, capture=capture)
    assert not capture.completed
    assert body.closed


@pytest.mark.parametrize("transport", ["sse", "sdk"])
@pytest.mark.parametrize("id_field", ["item_id", "call_id"])
async def test_interleaved_tool_argument_events_reach_the_correct_call(transport, id_field):
    items = [
        {"type": "function_call", "id": "fc_read", "call_id": "call_read",
         "name": "read_file", "arguments": '{"path":"a.txt"}'},
        {"type": "function_call", "id": "fc_write", "call_id": "call_write",
         "name": "write_file", "arguments": '{"path":"b.txt","content":"hi"}'},
    ]
    events = [
        {"type": "response.output_item.added", "output_index": index,
         "item": {**item, "arguments": ""}}
        for index, item in enumerate(items)
    ]
    chunks = [(1, '{"path":"b.txt",'), (0, '{"path":"a.txt"}'), (1, '"content":"hi"}')]
    for index, delta in chunks:
        item = items[index]
        events.append({
            "type": "response.function_call_arguments.delta", "output_index": index,
            id_field: item["id" if id_field == "item_id" else "call_id"], "delta": delta,
        })
    for index in (1, 0):
        item = items[index]
        events.append({
            "type": "response.function_call_arguments.done", "output_index": index,
            id_field: item["id" if id_field == "item_id" else "call_id"],
            "arguments": item["arguments"],
        })
    for index, item in enumerate(items):
        events.append({"type": "response.output_item.done", "output_index": index, "item": item})
    events.append({"type": "response.completed", "response": {"status": "completed", "output": items}})
    for sequence_number, event in enumerate(events):
        event["sequence_number"] = sequence_number
    body = _ResponseBody(events, "eof")
    tool_events = []

    async def on_tool_event(event):
        tool_events.append(event)

    async with _consume(transport, body) as (consume, stream):
        _, calls, finish, _, _ = await consume(stream, on_tool_call_delta=on_tool_event)

    assert [(call.name, call.arguments) for call in calls] == [
        ("read_file", {"path": "a.txt"}),
        ("write_file", {"path": "b.txt", "content": "hi"}),
    ]
    for index, item in enumerate(items):
        call_events = [event for event in tool_events if event["call_id"] == item["call_id"]]
        assert all(event["name"] == item["name"] for event in call_events)
        assert [event["arguments_delta"] for event in call_events if "arguments_delta" in event] == [
            "", *(delta for chunk_index, delta in chunks if chunk_index == index),
        ]
        assert [event["arguments"] for event in call_events if "arguments" in event] == [item["arguments"]]
    assert [event["call_id"] for event in tool_events if "arguments" in event] == ["call_write", "call_read"]
    assert finish == "stop"
    assert body.closed


@pytest.mark.parametrize("provider_kind", ["compat", "azure"])
@pytest.mark.parametrize("tail", ["disconnect", "open"])
async def test_provider_returns_and_closes_stream_at_terminal(monkeypatch, provider_kind, tail):
    from nanobot.providers.azure_openai_provider import AzureOpenAIProvider
    from nanobot.providers.openai_compat_provider import OpenAICompatProvider
    from nanobot.providers.registry import find_by_name

    body = _ResponseBody([
        {"type": "response.output_text.delta", "delta": "answer"},
        {"type": "response.completed", "response": {
            "status": "completed",
            "output": [{"type": "compaction", "id": "cmp_1", "encrypted_content": "fixture"}],
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        }},
    ], tail)
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http_client:
        async with AsyncOpenAI(api_key="test", http_client=http_client) as client:
            module = "azure_openai_provider" if provider_kind == "azure" else "openai_compat_provider"
            monkeypatch.setattr(f"nanobot.providers.{module}.AsyncOpenAI", lambda **kwargs: client)
            if provider_kind == "azure":
                provider = AzureOpenAIProvider(api_key="test", api_base="https://azure.test", default_model="gpt-5")
            else:
                provider = OpenAICompatProvider(api_key="test", default_model="gpt-5", spec=find_by_name("openai"))
            result = await asyncio.wait_for(
                provider.chat_stream([{"role": "user", "content": "hello"}]), timeout=2,
            )
            assert result.content == "answer"
            assert result.finish_reason == "stop"
            assert result.usage == LLMUsage.reported(input_tokens=10, output_tokens=5)
            assert result.provider_compaction_state is not None
            assert body.closed
            assert not body.tail_read
            assert len(requests) == 1
            assert requests[0].url.path == "/v1/responses"
