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


def test_convert_tools_basic():
    """OpenAI tool defs convert to Gemini FunctionDeclaration dicts."""
    from nanobot.providers.gemini_native_provider import GeminiNativeProvider

    provider = GeminiNativeProvider(
        api_key="k", api_base="http://localhost:8045", default_model="gemini-3-flash"
    )
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather for a city",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            },
        }
    ]
    result = provider._convert_tools(tools)
    assert result is not None
    assert len(result) == 1
    decls = result[0]["function_declarations"]
    assert len(decls) == 1
    assert decls[0]["name"] == "get_weather"
    assert decls[0]["description"] == "Get weather for a city"
    assert decls[0]["parameters_json_schema"]["type"] == "object"


def test_convert_tools_none():
    """None tools input returns None."""
    from nanobot.providers.gemini_native_provider import GeminiNativeProvider

    provider = GeminiNativeProvider(
        api_key="k", api_base="http://localhost:8045", default_model="gemini-3-flash"
    )
    assert provider._convert_tools(None) is None
    assert provider._convert_tools([]) is None


def test_convert_tool_choice_auto():
    from nanobot.providers.gemini_native_provider import GeminiNativeProvider

    provider = GeminiNativeProvider(
        api_key="k", api_base="http://localhost:8045", default_model="gemini-3-flash"
    )
    result = provider._convert_tool_choice("auto")
    assert result["function_calling_config"]["mode"] == "AUTO"


def test_convert_tool_choice_required():
    from nanobot.providers.gemini_native_provider import GeminiNativeProvider

    provider = GeminiNativeProvider(
        api_key="k", api_base="http://localhost:8045", default_model="gemini-3-flash"
    )
    result = provider._convert_tool_choice("required")
    assert result["function_calling_config"]["mode"] == "ANY"


def test_convert_tool_choice_specific_function():
    from nanobot.providers.gemini_native_provider import GeminiNativeProvider

    provider = GeminiNativeProvider(
        api_key="k", api_base="http://localhost:8045", default_model="gemini-3-flash"
    )
    result = provider._convert_tool_choice(
        {"type": "function", "function": {"name": "get_weather"}}
    )
    assert result["function_calling_config"]["mode"] == "ANY"
    assert result["function_calling_config"]["allowed_function_names"] == ["get_weather"]


def test_convert_tool_choice_none_string():
    from nanobot.providers.gemini_native_provider import GeminiNativeProvider

    provider = GeminiNativeProvider(
        api_key="k", api_base="http://localhost:8045", default_model="gemini-3-flash"
    )
    result = provider._convert_tool_choice("none")
    assert result["function_calling_config"]["mode"] == "NONE"


def test_parse_response_text_only():
    """Parse a simple text response."""
    from nanobot.providers.gemini_native_provider import GeminiNativeProvider

    provider = GeminiNativeProvider(
        api_key="k", api_base="http://localhost:8045", default_model="gemini-3-flash"
    )

    # Mock response structure
    mock_part = MagicMock()
    mock_part.text = "Hello world"
    mock_part.function_call = None

    mock_content = MagicMock()
    mock_content.parts = [mock_part]

    mock_candidate = MagicMock()
    mock_candidate.content = mock_content

    mock_usage = MagicMock()
    mock_usage.prompt_token_count = 10
    mock_usage.candidates_token_count = 5
    mock_usage.total_token_count = 15

    mock_response = MagicMock()
    mock_response.candidates = [mock_candidate]
    mock_response.usage_metadata = mock_usage

    result = provider._parse_response(mock_response)
    assert result.content == "Hello world"
    assert result.finish_reason == "stop"
    assert len(result.tool_calls) == 0
    assert result.usage["prompt_tokens"] == 10
    assert result.usage["completion_tokens"] == 5
    assert result.usage["total_tokens"] == 15


def test_parse_response_with_function_call():
    """Parse a response with function calls."""
    from nanobot.providers.gemini_native_provider import GeminiNativeProvider

    provider = GeminiNativeProvider(
        api_key="k", api_base="http://localhost:8045", default_model="gemini-3-flash"
    )

    mock_fc = MagicMock()
    mock_fc.name = "get_weather"
    mock_fc.args = {"city": "Tokyo"}

    mock_part = MagicMock()
    mock_part.text = None
    mock_part.function_call = mock_fc

    mock_content = MagicMock()
    mock_content.parts = [mock_part]

    mock_candidate = MagicMock()
    mock_candidate.content = mock_content

    mock_response = MagicMock()
    mock_response.candidates = [mock_candidate]
    mock_response.usage_metadata = None

    result = provider._parse_response(mock_response)
    assert result.content is None
    assert result.finish_reason == "tool_calls"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "get_weather"
    assert result.tool_calls[0].arguments == {"city": "Tokyo"}
    assert len(result.tool_calls[0].id) == 9
    # Verify the name map was populated
    tc_id = result.tool_calls[0].id
    assert provider._tool_call_name_map[tc_id] == "get_weather"


def test_parse_response_no_candidates():
    """Parse response with no candidates returns text attr."""
    from nanobot.providers.gemini_native_provider import GeminiNativeProvider

    provider = GeminiNativeProvider(
        api_key="k", api_base="http://localhost:8045", default_model="gemini-3-flash"
    )

    mock_response = MagicMock()
    mock_response.candidates = []
    mock_response.text = "fallback text"

    result = provider._parse_response(mock_response)
    assert result.content == "fallback text"
    assert result.finish_reason == "stop"


def test_parse_response_no_usage():
    """Parse response with missing usage_metadata returns empty usage dict."""
    from nanobot.providers.gemini_native_provider import GeminiNativeProvider

    provider = GeminiNativeProvider(
        api_key="k", api_base="http://localhost:8045", default_model="gemini-3-flash"
    )

    mock_part = MagicMock()
    mock_part.text = "hi"
    mock_part.function_call = None

    mock_content = MagicMock()
    mock_content.parts = [mock_part]

    mock_candidate = MagicMock()
    mock_candidate.content = mock_content

    mock_response = MagicMock()
    mock_response.candidates = [mock_candidate]
    mock_response.usage_metadata = None

    result = provider._parse_response(mock_response)
    assert result.usage == {}
