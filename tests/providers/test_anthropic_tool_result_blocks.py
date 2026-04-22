"""Anthropic provider tool_result block normalization tests."""

from __future__ import annotations

from unittest.mock import patch

from nanobot.providers.anthropic_provider import AnthropicProvider


def _make_provider() -> AnthropicProvider:
    with patch("anthropic.AsyncAnthropic"):
        return AnthropicProvider(api_key="sk-test", default_model="claude-sonnet-4-6")


def test_tool_result_block_normalizes_untyped_dict_items() -> None:
    provider = _make_provider()

    block = provider._tool_result_block({
        "tool_call_id": "call_1",
        "content": [{"phase": "done", "ok": True}],
    })

    assert block["type"] == "tool_result"
    assert block["tool_use_id"] == "call_1"
    assert block["content"] == [
        {"type": "text", "text": '{"phase": "done", "ok": true}'},
    ]


def test_tool_result_block_normalizes_openai_text_variants() -> None:
    provider = _make_provider()

    block = provider._tool_result_block({
        "tool_call_id": "call_2",
        "content": [
            {"type": "output_text", "text": "done"},
            {"type": "input_text", "text": "next"},
        ],
    })

    assert block["content"] == [
        {"type": "text", "text": "done"},
        {"type": "text", "text": "next"},
    ]


def test_convert_messages_keeps_tool_result_content_anthropic_safe() -> None:
    provider = _make_provider()

    _, messages = provider._convert_messages([
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call_1",
                "function": {"name": "demo_tool", "arguments": "{}"},
            }],
        },
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "name": "demo_tool",
            "content": [{"status": "ok"}],
        },
    ])

    assert messages[0]["role"] == "assistant"
    assert messages[1]["role"] == "user"
    tool_result = messages[1]["content"][0]
    assert tool_result["type"] == "tool_result"
    assert tool_result["content"] == [{"type": "text", "text": '{"status": "ok"}'}]
