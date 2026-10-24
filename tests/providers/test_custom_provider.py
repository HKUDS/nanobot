"""Tests for OpenAICompatProvider handling custom/direct endpoints."""

import json
from unittest.mock import patch

import httpx
import pytest
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion, ChatCompletionChunk

from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import find_by_name


@pytest.mark.parametrize("stream", [False, True], ids=["json", "sse"])
@pytest.mark.parametrize("field", ["refusal", "content"])
async def test_chat_completion_preserves_refusal_text(stream: bool, field: str) -> None:
    parts = ["I cannot help ", "with that request."] if field == "refusal" else ["Hello ", "world."]
    usage = {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12}
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/v1/chat/completions"
        assert json.loads(request.content).get("stream", False) is stream
        envelope = {"id": "chatcmpl-test", "created": 0, "model": "gpt-4o"}
        if not stream:
            return httpx.Response(200, json={
                **envelope, "object": "chat.completion", "usage": usage,
                "choices": [{"index": 0, "finish_reason": "stop", "message": {
                    "role": "assistant", "content": None, "refusal": None,
                    field: "".join(parts),
                }}],
            })
        chunks = [
            {"choices": [{"index": 0, "finish_reason": None, "delta": {field: part}}]}
            for part in parts
        ] + [
            {"choices": [{"index": 0, "finish_reason": "stop", "delta": {}}]},
            {"choices": [], "usage": usage},
        ]
        body = "".join(
            f"data: {json.dumps({**envelope, 'object': 'chat.completion.chunk', **chunk})}\n\n"
            for chunk in chunks
        ) + "data: [DONE]\n\n"
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=body)

    provider = OpenAICompatProvider(api_key="test", default_model="gpt-4o")
    provider._client = AsyncOpenAI(
        api_key="test", base_url="https://example.com/v1", max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    deltas: list[str] = []

    async def on_delta(text: str) -> None:
        deltas.append(text)

    try:
        messages = [{"role": "user", "content": "A request"}]
        if stream:
            result = await provider.chat_stream(messages, on_content_delta=on_delta)
        else:
            result = await provider.chat(messages)
    finally:
        await provider.aclose()

    assert len(requests) == 1
    assert result.content == "".join(parts)
    assert result.finish_reason == ("refusal" if field == "refusal" else "stop")
    assert not result.tool_calls
    assert not result.should_execute_tools
    assert result.usage is not None and result.usage.total_tokens == 12
    assert deltas == (parts if stream else [])


def test_custom_provider_parse_handles_empty_choices() -> None:
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()
    response = ChatCompletion(
        id="chatcmpl-empty", choices=[], created=0, model="test-model", object="chat.completion",
    )

    result = provider._parse(response)

    assert result.finish_reason == "error"
    assert "empty choices" in result.content


def test_custom_provider_parse_accepts_plain_string_response() -> None:
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    result = provider._parse("hello from backend")

    assert result.finish_reason == "stop"
    assert result.content == "hello from backend"


def test_custom_provider_parse_accepts_dict_response() -> None:
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    result = provider._parse({
        "choices": [{
            "message": {"content": "hello from dict"},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": 1,
            "completion_tokens": 2,
            "total_tokens": 3,
        },
    })

    assert result.finish_reason == "stop"
    assert result.content == "hello from dict"
    assert result.usage is not None
    assert result.usage.total_tokens == 3


def test_custom_provider_parse_normalizes_text_tool_call() -> None:
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    result = provider._parse({
        "choices": [{
            "message": {
                "content": (
                    "I'll inspect it.\n"
                    '<tool_call>{"name":"read_file","arguments":{"path":"README.md"}}'
                    "</tool_call>"
                ),
            },
            "finish_reason": "stop",
        }],
    })

    assert result.content == "I'll inspect it."
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "read_file"
    assert result.tool_calls[0].arguments == {"path": "README.md"}


def test_custom_provider_parse_keeps_structured_tool_call_over_text_markup() -> None:
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    result = provider._parse({
        "choices": [{
            "message": {
                "content": '<tool_call>{"name":"ignored","arguments":{}}</tool_call>',
                "tool_calls": [{
                    "id": "call_structured",
                    "function": {"name": "list_dir", "arguments": '{"path":"."}'},
                }],
            },
            "finish_reason": "tool_calls",
        }],
    })

    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id == "call_structured"
    assert result.tool_calls[0].name == "list_dir"


def test_custom_provider_parse_chunks_accepts_plain_text_chunks() -> None:
    result = OpenAICompatProvider._parse_chunks(["hello ", "world"])

    assert result.finish_reason == "stop"
    assert result.content == "hello world"


def test_custom_provider_parse_chunks_normalizes_split_text_tool_call() -> None:
    chunks = [
        {"choices": [{"delta": {"content": "<tool_call>"}}]},
        {"choices": [{"delta": {"content": '{"name":"list_dir",'}}]},
        {"choices": [{"delta": {"content": '"arguments":{"path":"."}}</tool_call>'}}]},
        {"choices": [{"finish_reason": "stop", "delta": {}}]},
    ]

    result = OpenAICompatProvider._parse_chunks(chunks)

    assert result.content is None
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "list_dir"
    assert result.tool_calls[0].arguments == {"path": "."}


@pytest.mark.parametrize("as_sdk", [False, True], ids=["dict", "sdk"])
def test_custom_provider_parse_chunks_deduplicates_parallel_tool_call_ids(as_sdk: bool) -> None:
    chunks = [{
        "id": "chatcmpl-parallel",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "test-model",
        "choices": [{
            "index": 0,
            "finish_reason": "tool_calls",
            "delta": {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_dup",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": '{"path":"a.txt"}'},
                    },
                    {
                        "index": 1,
                        "id": "call_dup",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": '{"path":"b.txt"}'},
                    },
                ],
            },
        }],
    }]

    if as_sdk:
        chunks = [ChatCompletionChunk.model_validate(chunk) for chunk in chunks]
    result = OpenAICompatProvider._parse_chunks(chunks)
    ids = [tool_call.id for tool_call in result.tool_calls or []]

    assert ids[0] == "call_dup"
    assert len(ids) == 2
    assert len(set(ids)) == 2
    assert [tc.arguments for tc in result.tool_calls] == [{"path": "a.txt"}, {"path": "b.txt"}]


def test_local_provider_502_error_includes_reachability_hint() -> None:
    spec = find_by_name("ollama")
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(api_base="http://localhost:11434/v1", spec=spec)

    result = provider._handle_error(
        Exception("Error code: 502"),
        spec=spec,
        api_base="http://localhost:11434/v1",
    )

    assert result.finish_reason == "error"
    assert "local model endpoint" in result.content
    assert "http://localhost:11434/v1" in result.content
    assert "proxy/tunnel" in result.content
