"""Tests for Anthropic <-> LiteLLM format conversion."""

import json

from nanobot.api.anthropic_format import (
    anthropic_request_to_litellm,
    litellm_response_to_anthropic,
    _convert_tool,
    _map_stop_reason,
    _sse_line,
)


# ---------------------------------------------------------------------------
# Request conversion tests
# ---------------------------------------------------------------------------


def test_simple_text_request():
    body = {
        "model": "claude-opus-4-6",
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": "Hello"}],
    }
    result = anthropic_request_to_litellm(body)
    assert result["model"] == "claude-opus-4-6"
    assert result["messages"] == [{"role": "user", "content": "Hello"}]
    assert result["max_tokens"] == 1024
    assert result["stream"] is False


def test_system_prompt_string():
    body = {
        "model": "test",
        "max_tokens": 100,
        "system": "You are helpful.",
        "messages": [{"role": "user", "content": "Hi"}],
    }
    result = anthropic_request_to_litellm(body)
    assert result["messages"][0] == {"role": "system", "content": "You are helpful."}
    assert result["messages"][1] == {"role": "user", "content": "Hi"}


def test_system_prompt_array():
    body = {
        "model": "test",
        "max_tokens": 100,
        "system": [
            {"type": "text", "text": "Line one."},
            {"type": "text", "text": "Line two."},
        ],
        "messages": [{"role": "user", "content": "Hi"}],
    }
    result = anthropic_request_to_litellm(body)
    assert result["messages"][0]["content"] == "Line one.\nLine two."


def test_stream_flag():
    body = {
        "model": "test",
        "max_tokens": 100,
        "stream": True,
        "messages": [{"role": "user", "content": "Hi"}],
    }
    result = anthropic_request_to_litellm(body)
    assert result["stream"] is True


def test_optional_params():
    body = {
        "model": "test",
        "max_tokens": 100,
        "temperature": 0.5,
        "top_p": 0.9,
        "stop_sequences": ["\n\n"],
        "messages": [{"role": "user", "content": "Hi"}],
    }
    result = anthropic_request_to_litellm(body)
    assert result["temperature"] == 0.5
    assert result["top_p"] == 0.9
    assert result["stop"] == ["\n\n"]


# ---------------------------------------------------------------------------
# Tool conversion tests
# ---------------------------------------------------------------------------


def test_tool_definition_conversion():
    tool = {
        "name": "get_weather",
        "description": "Get weather for a location",
        "input_schema": {
            "type": "object",
            "properties": {"location": {"type": "string"}},
            "required": ["location"],
        },
    }
    result = _convert_tool(tool)
    assert result["type"] == "function"
    assert result["function"]["name"] == "get_weather"
    assert result["function"]["description"] == "Get weather for a location"
    assert result["function"]["parameters"] == tool["input_schema"]


def test_tools_in_request():
    body = {
        "model": "test",
        "max_tokens": 100,
        "messages": [{"role": "user", "content": "Weather?"}],
        "tools": [
            {
                "name": "get_weather",
                "description": "Get weather",
                "input_schema": {"type": "object", "properties": {}},
            }
        ],
    }
    result = anthropic_request_to_litellm(body)
    assert len(result["tools"]) == 1
    assert result["tools"][0]["function"]["name"] == "get_weather"
    assert result["tool_choice"] == "auto"


# ---------------------------------------------------------------------------
# Message content block conversion tests
# ---------------------------------------------------------------------------


def test_assistant_tool_use_blocks():
    body = {
        "model": "test",
        "max_tokens": 100,
        "messages": [
            {"role": "user", "content": "What's the weather?"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Let me check."},
                    {
                        "type": "tool_use",
                        "id": "toolu_123",
                        "name": "get_weather",
                        "input": {"location": "SF"},
                    },
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_123",
                        "content": "72F sunny",
                    }
                ],
            },
        ],
    }
    result = anthropic_request_to_litellm(body)

    # Assistant message has tool_calls
    assistant = result["messages"][1]
    assert assistant["role"] == "assistant"
    assert assistant["content"] == "Let me check."
    assert len(assistant["tool_calls"]) == 1
    assert assistant["tool_calls"][0]["id"] == "toolu_123"
    assert assistant["tool_calls"][0]["function"]["name"] == "get_weather"
    args = json.loads(assistant["tool_calls"][0]["function"]["arguments"])
    assert args == {"location": "SF"}

    # Tool result becomes a tool message
    tool_msg = result["messages"][2]
    assert tool_msg["role"] == "tool"
    assert tool_msg["tool_call_id"] == "toolu_123"
    assert tool_msg["content"] == "72F sunny"


def test_user_image_block():
    body = {
        "model": "test",
        "max_tokens": 100,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": "abc123",
                        },
                    },
                    {"type": "text", "text": "What is this?"},
                ],
            }
        ],
    }
    result = anthropic_request_to_litellm(body)
    user_msg = result["messages"][0]
    assert user_msg["role"] == "user"
    assert len(user_msg["content"]) == 2
    assert user_msg["content"][0]["type"] == "image_url"
    assert "data:image/png;base64,abc123" in user_msg["content"][0]["image_url"]["url"]
    assert user_msg["content"][1]["type"] == "text"


def test_tool_result_with_content_blocks():
    body = {
        "model": "test",
        "max_tokens": 100,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_456",
                        "content": [
                            {"type": "text", "text": "Result line 1"},
                            {"type": "text", "text": "Result line 2"},
                        ],
                    }
                ],
            }
        ],
    }
    result = anthropic_request_to_litellm(body)
    tool_msg = result["messages"][0]
    assert tool_msg["role"] == "tool"
    assert tool_msg["content"] == "Result line 1\nResult line 2"


# ---------------------------------------------------------------------------
# Response conversion tests
# ---------------------------------------------------------------------------


class MockUsage:
    def __init__(self, prompt=10, completion=20, total=30):
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.total_tokens = total


class MockFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class MockToolCall:
    def __init__(self, id, name, arguments):
        self.id = id
        self.function = MockFunction(name, arguments)


class MockMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class MockChoice:
    def __init__(self, content=None, tool_calls=None, finish_reason="stop"):
        self.message = MockMessage(content, tool_calls)
        self.finish_reason = finish_reason


class MockResponse:
    def __init__(self, content=None, tool_calls=None, finish_reason="stop"):
        self.choices = [MockChoice(content, tool_calls, finish_reason)]
        self.usage = MockUsage()


def test_text_response_conversion():
    response = MockResponse(content="Hello!")
    result = litellm_response_to_anthropic(response, "claude-opus-4-6")
    assert result["type"] == "message"
    assert result["role"] == "assistant"
    assert result["model"] == "claude-opus-4-6"
    assert result["stop_reason"] == "end_turn"
    assert len(result["content"]) == 1
    assert result["content"][0] == {"type": "text", "text": "Hello!"}
    assert result["usage"]["input_tokens"] == 10
    assert result["usage"]["output_tokens"] == 20
    assert result["id"].startswith("msg_")


def test_tool_call_response_conversion():
    tc = MockToolCall("toolu_abc", "get_weather", '{"location": "NYC"}')
    response = MockResponse(content="Let me check.", tool_calls=[tc], finish_reason="tool_calls")
    result = litellm_response_to_anthropic(response, "claude-opus-4-6")
    assert result["stop_reason"] == "tool_use"
    assert len(result["content"]) == 2
    assert result["content"][0] == {"type": "text", "text": "Let me check."}
    assert result["content"][1]["type"] == "tool_use"
    assert result["content"][1]["id"] == "toolu_abc"
    assert result["content"][1]["name"] == "get_weather"
    assert result["content"][1]["input"] == {"location": "NYC"}


# ---------------------------------------------------------------------------
# Stop reason mapping
# ---------------------------------------------------------------------------


def test_stop_reason_mapping():
    assert _map_stop_reason("stop") == "end_turn"
    assert _map_stop_reason("length") == "max_tokens"
    assert _map_stop_reason("tool_calls") == "tool_use"
    assert _map_stop_reason("content_filter") == "end_turn"
    assert _map_stop_reason(None) == "end_turn"
    assert _map_stop_reason("unknown") == "end_turn"


# ---------------------------------------------------------------------------
# SSE formatting
# ---------------------------------------------------------------------------


def test_sse_line_format():
    line = _sse_line("message_stop", {"type": "message_stop"})
    assert line.startswith("event: message_stop\n")
    assert "data: " in line
    assert line.endswith("\n\n")
    parsed = json.loads(line.split("data: ")[1].strip())
    assert parsed["type"] == "message_stop"
