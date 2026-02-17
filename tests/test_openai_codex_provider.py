"""Tests for the OpenAI Codex provider helpers and SSE parsing."""

from __future__ import annotations

import pytest

from nanobot.providers import openai_codex_provider as provider


def test_strip_model_prefix_removes_openai_codex_prefix() -> None:
    """It strips the openai-codex model prefix when present."""
    assert provider._strip_model_prefix("openai-codex/gpt-5.1-codex") == "gpt-5.1-codex"
    assert provider._strip_model_prefix("gpt-5.1-codex") == "gpt-5.1-codex"


def test_build_headers_sets_required_codex_headers() -> None:
    """It builds expected auth and streaming headers for Codex responses."""
    headers = provider._build_headers("acct_123", "tok_456")

    assert headers["Authorization"] == "Bearer tok_456"
    assert headers["chatgpt-account-id"] == "acct_123"
    assert headers["OpenAI-Beta"] == "responses=experimental"
    assert headers["originator"] == provider.DEFAULT_ORIGINATOR
    assert headers["accept"] == "text/event-stream"
    assert headers["content-type"] == "application/json"


def test_convert_tools_flattens_function_schema_and_skips_invalid() -> None:
    """It converts function-call tool shape into Codex flat tool schema."""
    tools = [
        {
            "type": "function",
            "function": {
                "name": "weather",
                "description": "Get weather",
                "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
            },
        },
        {"name": "already_flat", "description": "Flat tool", "parameters": {"type": "object"}},
        {"type": "function", "function": {"description": "missing name"}},
    ]

    converted = provider._convert_tools(tools)

    assert converted == [
        {
            "type": "function",
            "name": "weather",
            "description": "Get weather",
            "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
        },
        {
            "type": "function",
            "name": "already_flat",
            "description": "Flat tool",
            "parameters": {"type": "object"},
        },
    ]


def test_convert_messages_handles_system_user_assistant_and_tool() -> None:
    """It converts mixed chat messages into Codex instructions and input items."""
    messages = [
        {"role": "system", "content": "be brief"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe this"},
                {"type": "image_url", "image_url": {"url": "https://example.com/cat.png"}},
            ],
        },
        {
            "role": "assistant",
            "content": "I will call a tool",
            "tool_calls": [
                {
                    "id": "call_9|fc_9",
                    "function": {"name": "weather", "arguments": '{"city":"sf"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_9|fc_9", "content": {"temp": 72}},
    ]

    system_prompt, input_items = provider._convert_messages(messages)

    assert system_prompt == "be brief"
    assert input_items[0] == {
        "role": "user",
        "content": [
            {"type": "input_text", "text": "Describe this"},
            {"type": "input_image", "image_url": "https://example.com/cat.png", "detail": "auto"},
        ],
    }
    assert input_items[1]["type"] == "message"
    assert input_items[1]["role"] == "assistant"
    assert input_items[1]["content"] == [{"type": "output_text", "text": "I will call a tool"}]
    assert input_items[2] == {
        "type": "function_call",
        "id": "fc_9",
        "call_id": "call_9",
        "name": "weather",
        "arguments": '{"city":"sf"}',
    }
    assert input_items[3] == {
        "type": "function_call_output",
        "call_id": "call_9",
        "output": '{"temp": 72}',
    }


def test_split_tool_call_id_handles_pipe_plain_and_fallback() -> None:
    """It splits tool call id into call id and item id with defaults."""
    assert provider._split_tool_call_id("call_a|fc_b") == ("call_a", "fc_b")
    assert provider._split_tool_call_id("call_only") == ("call_only", None)
    assert provider._split_tool_call_id(None) == ("call_0", None)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("completed", "stop"),
        ("incomplete", "length"),
        ("failed", "error"),
        ("cancelled", "error"),
        (None, "stop"),
        ("unknown", "stop"),
    ],
)
def test_map_finish_reason_translates_response_status(status: str | None, expected: str) -> None:
    """It maps Codex response statuses onto nanobot finish reasons."""
    assert provider._map_finish_reason(status) == expected


def test_friendly_error_formats_429_and_generic_http_errors() -> None:
    """It returns a user-friendly rate-limit string and generic HTTP fallback."""
    assert "quota exceeded" in provider._friendly_error(429, "whatever")
    assert provider._friendly_error(500, "boom") == "HTTP 500: boom"


@pytest.mark.asyncio
async def test_consume_sse_assembles_content_tool_calls_and_finish_reason(monkeypatch) -> None:
    """It assembles text deltas and function-call argument deltas into final output."""

    async def fake_iter_sse(_response):
        events = [
            {
                "type": "response.output_item.added",
                "item": {"type": "function_call", "call_id": "call_1", "id": "fc_1", "name": "weather", "arguments": "{"},
            },
            {"type": "response.output_text.delta", "delta": "Hello "},
            {"type": "response.output_text.delta", "delta": "world"},
            {"type": "response.function_call_arguments.delta", "call_id": "call_1", "delta": '"city":"SF"}'},
            {
                "type": "response.output_item.done",
                "item": {"type": "function_call", "call_id": "call_1", "id": "fc_1", "name": "weather"},
            },
            {"type": "response.completed", "response": {"status": "completed"}},
        ]
        for event in events:
            yield event

    monkeypatch.setattr(provider, "_iter_sse", fake_iter_sse)

    content, tool_calls, finish_reason = await provider._consume_sse(object())

    assert content == "Hello world"
    assert finish_reason == "stop"
    assert len(tool_calls) == 1
    assert tool_calls[0].id == "call_1|fc_1"
    assert tool_calls[0].name == "weather"
    assert tool_calls[0].arguments == {"city": "SF"}


@pytest.mark.asyncio
async def test_consume_sse_raises_on_error_event(monkeypatch) -> None:
    """It raises when Codex emits an error event in the SSE stream."""

    async def fake_iter_sse(_response):
        yield {"type": "error"}

    monkeypatch.setattr(provider, "_iter_sse", fake_iter_sse)

    with pytest.raises(RuntimeError, match="Codex response failed"):
        await provider._consume_sse(object())
