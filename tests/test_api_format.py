"""Tests for Anthropic <-> LiteLLM format conversion."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nanobot.api.anthropic_format import (
    anthropic_request_to_litellm,
    litellm_response_to_anthropic,
)


# ── Request conversion ──────────────────────────────────────────────


class TestAnthropicRequestToLitellm:
    def test_basic_user_message(self):
        body = {
            "model": "claude-sonnet-4-5-20250929",
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": "Hello"}],
        }
        result = anthropic_request_to_litellm(body)

        assert result["model"] == "claude-sonnet-4-5-20250929"
        assert result["max_tokens"] == 1024
        assert len(result["messages"]) == 1
        assert result["messages"][0] == {"role": "user", "content": "Hello"}

    def test_system_string(self):
        body = {
            "model": "claude-sonnet-4-5-20250929",
            "max_tokens": 1024,
            "system": "You are helpful.",
            "messages": [{"role": "user", "content": "Hi"}],
        }
        result = anthropic_request_to_litellm(body)

        assert result["messages"][0] == {"role": "system", "content": "You are helpful."}
        assert result["messages"][1] == {"role": "user", "content": "Hi"}

    def test_system_array(self):
        body = {
            "model": "claude-sonnet-4-5-20250929",
            "max_tokens": 1024,
            "system": [
                {"type": "text", "text": "Part 1"},
                {"type": "text", "text": "Part 2"},
            ],
            "messages": [{"role": "user", "content": "Hi"}],
        }
        result = anthropic_request_to_litellm(body)

        assert result["messages"][0]["role"] == "system"
        assert "Part 1" in result["messages"][0]["content"]
        assert "Part 2" in result["messages"][0]["content"]

    def test_assistant_with_tool_use(self):
        body = {
            "model": "claude-sonnet-4-5-20250929",
            "max_tokens": 1024,
            "messages": [
                {"role": "user", "content": "Read the file"},
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "I'll read that."},
                        {
                            "type": "tool_use",
                            "id": "call_123",
                            "name": "read_file",
                            "input": {"path": "/tmp/test.txt"},
                        },
                    ],
                },
            ],
        }
        result = anthropic_request_to_litellm(body)

        assistant_msg = result["messages"][1]
        assert assistant_msg["role"] == "assistant"
        assert assistant_msg["content"] == "I'll read that."
        assert len(assistant_msg["tool_calls"]) == 1
        tc = assistant_msg["tool_calls"][0]
        assert tc["id"] == "call_123"
        assert tc["type"] == "function"
        assert tc["function"]["name"] == "read_file"
        assert json.loads(tc["function"]["arguments"]) == {"path": "/tmp/test.txt"}

    def test_tool_result(self):
        body = {
            "model": "claude-sonnet-4-5-20250929",
            "max_tokens": 1024,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "call_123",
                            "content": "file contents here",
                        },
                    ],
                },
            ],
        }
        result = anthropic_request_to_litellm(body)

        tool_msg = result["messages"][0]
        assert tool_msg["role"] == "tool"
        assert tool_msg["tool_call_id"] == "call_123"
        assert tool_msg["content"] == "file contents here"

    def test_tool_definitions(self):
        body = {
            "model": "claude-sonnet-4-5-20250929",
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": "Hi"}],
            "tools": [
                {
                    "name": "get_weather",
                    "description": "Get weather data",
                    "input_schema": {
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                    },
                },
            ],
        }
        result = anthropic_request_to_litellm(body)

        assert len(result["tools"]) == 1
        tool = result["tools"][0]
        assert tool["type"] == "function"
        assert tool["function"]["name"] == "get_weather"
        assert tool["function"]["description"] == "Get weather data"
        assert tool["function"]["parameters"]["properties"]["city"]["type"] == "string"

    def test_stop_sequences(self):
        body = {
            "model": "claude-sonnet-4-5-20250929",
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": "Hi"}],
            "stop_sequences": ["\n\nHuman:"],
        }
        result = anthropic_request_to_litellm(body)
        assert result["stop"] == ["\n\nHuman:"]

    def test_image_content(self):
        body = {
            "model": "claude-sonnet-4-5-20250929",
            "max_tokens": 1024,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "What is this?"},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": "iVBOR...",
                            },
                        },
                    ],
                },
            ],
        }
        result = anthropic_request_to_litellm(body)

        user_msg = result["messages"][0]
        assert user_msg["role"] == "user"
        assert isinstance(user_msg["content"], list)
        assert user_msg["content"][0] == {"type": "text", "text": "What is this?"}
        img = user_msg["content"][1]
        assert img["type"] == "image_url"
        assert img["image_url"]["url"].startswith("data:image/png;base64,")

    def test_stream_passthrough(self):
        body = {
            "model": "claude-sonnet-4-5-20250929",
            "max_tokens": 1024,
            "stream": True,
            "messages": [{"role": "user", "content": "Hi"}],
        }
        result = anthropic_request_to_litellm(body)
        assert result["stream"] is True

    def test_temperature_passthrough(self):
        body = {
            "model": "claude-sonnet-4-5-20250929",
            "max_tokens": 1024,
            "temperature": 0.5,
            "messages": [{"role": "user", "content": "Hi"}],
        }
        result = anthropic_request_to_litellm(body)
        assert result["temperature"] == 0.5


# ── Response conversion ─────────────────────────────────────────────


def _make_response(content=None, tool_calls=None, finish_reason="stop", model="claude-test"):
    """Helper to build a mock LiteLLM response."""
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=20, total_tokens=30)
    return SimpleNamespace(id="chatcmpl-test", choices=[choice], usage=usage, model=model)


class TestLitellmResponseToAnthropic:
    def test_text_response(self):
        resp = _make_response(content="Hello there!")
        result = litellm_response_to_anthropic(resp, model="claude-sonnet-4-5-20250929")

        assert result["type"] == "message"
        assert result["role"] == "assistant"
        assert result["model"] == "claude-sonnet-4-5-20250929"
        assert len(result["content"]) == 1
        assert result["content"][0] == {"type": "text", "text": "Hello there!"}
        assert result["stop_reason"] == "end_turn"
        assert result["usage"]["input_tokens"] == 10
        assert result["usage"]["output_tokens"] == 20

    def test_tool_call_response(self):
        tc = SimpleNamespace(
            id="call_abc",
            function=SimpleNamespace(name="get_weather", arguments='{"city": "London"}'),
        )
        resp = _make_response(content=None, tool_calls=[tc], finish_reason="tool_calls")
        result = litellm_response_to_anthropic(resp)

        assert len(result["content"]) == 1
        block = result["content"][0]
        assert block["type"] == "tool_use"
        assert block["id"] == "call_abc"
        assert block["name"] == "get_weather"
        assert block["input"] == {"city": "London"}
        assert result["stop_reason"] == "tool_use"

    def test_text_and_tool_response(self):
        tc = SimpleNamespace(
            id="call_xyz",
            function=SimpleNamespace(name="search", arguments='{"q": "test"}'),
        )
        resp = _make_response(content="Let me search.", tool_calls=[tc], finish_reason="tool_calls")
        result = litellm_response_to_anthropic(resp)

        assert len(result["content"]) == 2
        assert result["content"][0]["type"] == "text"
        assert result["content"][1]["type"] == "tool_use"

    def test_stop_reason_mapping(self):
        for oai_reason, anthropic_reason in [
            ("stop", "end_turn"),
            ("length", "max_tokens"),
            ("tool_calls", "tool_use"),
            ("content_filter", "end_turn"),
        ]:
            resp = _make_response(content="x", finish_reason=oai_reason)
            result = litellm_response_to_anthropic(resp)
            assert result["stop_reason"] == anthropic_reason, f"Failed for {oai_reason}"

    def test_no_usage(self):
        message = SimpleNamespace(content="hi", tool_calls=None)
        choice = SimpleNamespace(message=message, finish_reason="stop")
        resp = SimpleNamespace(id="test", choices=[choice], usage=None, model="test")
        result = litellm_response_to_anthropic(resp)

        assert result["usage"]["input_tokens"] == 0
        assert result["usage"]["output_tokens"] == 0
