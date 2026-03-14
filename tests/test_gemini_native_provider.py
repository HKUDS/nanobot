"""Tests for GeminiNativeProvider message and tool conversion."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_convert_messages_extracts_system_instruction():
    """System messages should be extracted and concatenated."""
    from nanobot.providers.gemini_native_provider import GeminiNativeProvider

    provider = GeminiNativeProvider(
        api_key="test-key",
        api_base="http://localhost:8045",
        default_model="gemini-3-flash",
    )
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "system", "content": "Be concise."},
        {"role": "user", "content": "Hello"},
    ]
    system_instruction, contents = provider._convert_messages(messages)
    assert system_instruction == "You are helpful.\nBe concise."
    assert len(contents) == 1
    assert contents[0]["role"] == "user"
    assert contents[0]["parts"][0]["text"] == "Hello"


def test_convert_messages_user_and_assistant():
    """User and assistant messages map to user/model roles."""
    from nanobot.providers.gemini_native_provider import GeminiNativeProvider

    provider = GeminiNativeProvider(
        api_key="test-key",
        api_base="http://localhost:8045",
        default_model="gemini-3-flash",
    )
    messages = [
        {"role": "user", "content": "What is 2+2?"},
        {"role": "assistant", "content": "4"},
        {"role": "user", "content": "Thanks"},
    ]
    system_instruction, contents = provider._convert_messages(messages)
    assert system_instruction is None
    assert len(contents) == 3
    assert contents[0]["role"] == "user"
    assert contents[1]["role"] == "model"
    assert contents[2]["role"] == "user"


def test_convert_messages_assistant_with_tool_calls():
    """Assistant messages with tool_calls become model content with function_call parts."""
    from nanobot.providers.gemini_native_provider import GeminiNativeProvider

    provider = GeminiNativeProvider(
        api_key="test-key",
        api_base="http://localhost:8045",
        default_model="gemini-3-flash",
    )
    messages = [
        {"role": "user", "content": "What's the weather?"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_abc",
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "arguments": '{"city": "Tokyo"}',
                    },
                }
            ],
        },
    ]
    system_instruction, contents = provider._convert_messages(messages)
    assert len(contents) == 2
    model_content = contents[1]
    assert model_content["role"] == "model"
    fc = model_content["parts"][0]["function_call"]
    assert fc["name"] == "get_weather"
    assert fc["args"] == {"city": "Tokyo"}


def test_convert_messages_tool_result():
    """Tool result messages become user content with function_response parts."""
    from nanobot.providers.gemini_native_provider import GeminiNativeProvider

    provider = GeminiNativeProvider(
        api_key="test-key",
        api_base="http://localhost:8045",
        default_model="gemini-3-flash",
    )
    # Build the tool_call_id -> name mapping the provider maintains
    provider._tool_call_name_map = {"call_abc": "get_weather"}
    messages = [
        {
            "role": "tool",
            "tool_call_id": "call_abc",
            "content": '{"temp": 20}',
        },
    ]
    _, contents = provider._convert_messages(messages)
    assert len(contents) == 1
    assert contents[0]["role"] == "user"
    fr = contents[0]["parts"][0]["function_response"]
    assert fr["name"] == "get_weather"
    assert fr["response"] == {"temp": 20}


def test_convert_messages_tool_result_plain_text():
    """Tool results with plain text content are wrapped in a dict."""
    from nanobot.providers.gemini_native_provider import GeminiNativeProvider

    provider = GeminiNativeProvider(
        api_key="test-key",
        api_base="http://localhost:8045",
        default_model="gemini-3-flash",
    )
    provider._tool_call_name_map = {"call_xyz": "search"}
    messages = [
        {"role": "tool", "tool_call_id": "call_xyz", "content": "no results found"},
    ]
    _, contents = provider._convert_messages(messages)
    fr = contents[0]["parts"][0]["function_response"]
    assert fr["name"] == "search"
    assert fr["response"] == {"result": "no results found"}


def test_convert_messages_round_trip_tool_call_name_map():
    """Full round-trip: assistant with tool_calls populates name map, tool results use it."""
    from nanobot.providers.gemini_native_provider import GeminiNativeProvider

    provider = GeminiNativeProvider(
        api_key="test-key",
        api_base="http://localhost:8045",
        default_model="gemini-3-flash",
    )
    # Do NOT pre-set _tool_call_name_map — it should be populated by _convert_messages
    messages = [
        {"role": "user", "content": "What's the weather in Tokyo and Paris?"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "get_weather", "arguments": '{"city": "Tokyo"}'}},
                {"id": "call_2", "type": "function", "function": {"name": "get_weather", "arguments": '{"city": "Paris"}'}},
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": '{"temp": 20}'},
        {"role": "tool", "tool_call_id": "call_2", "content": '{"temp": 15}'},
    ]
    _, contents = provider._convert_messages(messages)
    # Verify tool results resolved names correctly (not "unknown")
    tool_content = contents[2]  # user content with function_responses
    assert tool_content["role"] == "user"
    assert tool_content["parts"][0]["function_response"]["name"] == "get_weather"
    assert tool_content["parts"][1]["function_response"]["name"] == "get_weather"
    assert tool_content["parts"][0]["function_response"]["response"] == {"temp": 20}
    assert tool_content["parts"][1]["function_response"]["response"] == {"temp": 15}


def test_convert_messages_consecutive_tool_results_merged():
    """Multiple consecutive tool results should be merged into one user content."""
    from nanobot.providers.gemini_native_provider import GeminiNativeProvider

    provider = GeminiNativeProvider(
        api_key="test-key",
        api_base="http://localhost:8045",
        default_model="gemini-3-flash",
    )
    provider._tool_call_name_map = {"call_1": "func_a", "call_2": "func_b"}
    messages = [
        {"role": "tool", "tool_call_id": "call_1", "content": '{"a": 1}'},
        {"role": "tool", "tool_call_id": "call_2", "content": '{"b": 2}'},
    ]
    _, contents = provider._convert_messages(messages)
    # Gemini expects all function responses for one turn in a single Content
    assert len(contents) == 1
    assert contents[0]["role"] == "user"
    assert len(contents[0]["parts"]) == 2
