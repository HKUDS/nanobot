"""Tests for OpenAICompatProvider handling custom/direct endpoints."""

from types import SimpleNamespace
from unittest.mock import patch

from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import find_by_name


def test_custom_provider_parse_handles_empty_choices() -> None:
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()
    response = SimpleNamespace(choices=[])

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
    assert result.usage["total_tokens"] == 3


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


def test_custom_provider_parse_chunks_deduplicates_parallel_tool_call_ids() -> None:
    chunks = [{
        "choices": [{
            "finish_reason": "tool_calls",
            "delta": {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_dup",
                        "function": {"name": "read_file", "arguments": '{"path":"a.txt"}'},
                    },
                    {
                        "index": 1,
                        "id": "call_dup",
                        "function": {"name": "read_file", "arguments": '{"path":"b.txt"}'},
                    },
                ],
            },
        }],
    }]

    result = OpenAICompatProvider._parse_chunks(chunks)
    ids = [tool_call.id for tool_call in result.tool_calls or []]

    assert ids[0] == "call_dup"
    assert len(ids) == 2
    assert len(set(ids)) == 2


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
