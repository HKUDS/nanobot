"""Tests for the shared openai_responses converters and parsers."""

from unittest.mock import MagicMock, patch

import pytest

from janniebot.providers.openai_responses.converters import (
    convert_messages,
    convert_tools,
    convert_user_message,
    split_tool_call_id,
)
from janniebot.providers.openai_responses.parsing import (
    consume_sdk_stream,
    map_finish_reason,
    parse_response_output,
)

# ======================================================================
# converters - split_tool_call_id
# ======================================================================


class TestSplitToolCallId:
    def test_plain_id(self):
        assert split_tool_call_id("call_abc") == ("call_abc", None)

    def test_compound_id(self):
        assert split_tool_call_id("call_abc|fc_1") == ("call_abc", "fc_1")

    def test_compound_empty_item_id(self):
        assert split_tool_call_id("call_abc|") == ("call_abc", None)

    def test_none(self):
        assert split_tool_call_id(None) == ("call_0", None)

    def test_empty_string(self):
        assert split_tool_call_id("") == ("call_0", None)

    def test_non_string(self):
        assert split_tool_call_id(42) == ("call_0", None)


# ======================================================================
# converters - convert_user_message
# ======================================================================


class TestConvertUserMessage:
    def test_string_content(self):
        result = convert_user_message("hello")
        assert result == {"role": "user", "content": [{"type": "input_text", "text": "hello"}]}

    def test_text_block(self):
        result = convert_user_message([{"type": "text", "text": "hi"}])
        assert result["content"] == [{"type": "input_text", "text": "hi"}]

    def test_image_url_block(self):
        result = convert_user_message([
            {"type": "image_url", "image_url": {"url": "https://img.example/a.png"}},
        ])
        assert result["content"] == [
            {"type": "input_image", "image_url": "https://img.example/a.png", "detail": "auto"},
        ]

    def test_mixed_text_and_image(self):
        result = convert_user_message([
            {"type": "text", "text": "what's this?"},
            {"type": "image_url", "image_url": {"url": "https://img.example/b.png"}},
        ])
        assert len(result["content"]) == 2
        assert result["content"][0]["type"] == "input_text"
        assert result["content"][1]["type"] == "input_image"

    def test_empty_list_falls_back(self):
        result = convert_user_message([])
        assert result["content"] == [{"type": "input_text", "text": ""}]

    def test_none_falls_back(self):
        result = convert_user_message(None)
        assert result["content"] == [{"type": "input_text", "text": ""}]

    def test_image_without_url_skipped(self):
        result = convert_user_message([{"type": "image_url", "image_url": {}}])
        assert result["content"] == [{"type": "input_text", "text": ""}]

    def test_meta_fields_not_leaked(self):
        """_meta on content blocks must never appear in converted output."""
        result = convert_user_message([
            {"type": "text", "text": "hi", "_meta": {"path": "/tmp/x"}},
        ])
        assert "_meta" not in result["content"][0]

    def test_non_dict_items_skipped(self):
        result = convert_user_message(["just a string", 42])
        assert result["content"] == [{"type": "input_text", "text": ""}]


# ======================================================================
# converters - convert_messages
# ======================================================================


class TestConvertMessages:
    def test_system_extracted_as_instructions(self):
        msgs = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi"},
        ]
        instructions, items = convert_messages(msgs)
        assert instructions == "You are helpful."
        assert len(items) == 1
        assert items[0]["role"] == "user"

    def test_multiple_system_messages_last_wins(self):
        msgs = [
            {"role": "system", "content": "first"},
            {"role": "system", "content": "second"},
            {"role": "user", "content": "x"},
        ]
        instructions, _ = convert_messages(msgs)
        assert instructions == "second"

    def test_user_message_converted(self):
        _, items = convert_messages([{"role": "user", "content": "hello"}])
        assert items[0]["role"] == "user"
        assert items[0]["content"][0]["type"] == "input_text"

    def test_assistant_text_message(self):
        _, items = convert_messages([
            {"role": "assistant", "content": "I'll help"},
        ])
        assert items[0]["type"] == "message"
        assert items[0]["role"] == "assistant"
        assert items[0]["content"][0]["type"] == "output_text"
        assert items[0]["content"][0]["text"] == "I'll help"

    def test_assistant_empty_content_skipped(self):
        _, items = convert_messages([{"role": "assistant", "content": ""}])
        assert len(items) == 0

    def test_assistant_with_tool_calls(self):
        _, items = convert_messages([{
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call_abc|fc_1",
                "function": {"name": "get_weather", "arguments": '{"city":"SF"}'},
            }],
        }])
        assert items[0]["type"] == "function_call"
        assert items[0]["call_id"] == "call_abc"
        assert items[0]["id"] == "fc_1"
        assert items[0]["name"] == "get_weather"

    def test_assistant_with_tool_calls_no_id(self):
        """Fallback IDs when tool_call.id is missing."""
        _, items = convert_messages([{
            "role": "assistant",
            "content": None,
            "tool_calls": [{"function": {"name": "f1", "arguments": "{}"}}],
        }])
        assert items[0]["call_id"] == "call_0"
        assert items[0]["id"].startswith("fc_")

    def test_tool_message(self):
        _, items = convert_messages([{
            "role": "tool",
            "tool_call_id": "call_abc",
            "content": "result text",
        }])
        assert items[0]["type"] == "function_call_output"
        assert items[0]["call_id"] == "call_abc"
        assert items[0]["output"] == "result text"

    def test_tool_message_dict_content(self):
        _, items = convert_messages([{
            "role": "tool",
            "tool_call_id": "call_1",
            "content": {"key": "value"},
        }])
        assert items[0]["output"] == '{"key": "value"}'

    def test_non_standard_keys_not_leaked(self):
        """Extra keys on messages must not appear in converted items."""
        _, items = convert_messages([{
            "role": "user",
            "content": "hi",
            "extra_field": "should vanish",
            "_meta": {"path": "/tmp"},
        }])
        item = items[0]
        assert "extra_field" not in str(item)
        assert "_meta" not in str(item)

    def test_full_conversation_roundtrip(self):
        """System + user + assistant(tool_call) + tool -> correct structure."""
        msgs = [
            {"role": "system", "content": "Be concise."},
            {"role": "user", "content": "Weather in SF?"},
            {
                "role": "assistant", "content": None,
                "tool_calls": [{
                    "id": "c1|fc1",
                    "function": {"name": "get_weather", "arguments": '{"city":"SF"}'},
                }],
            },
            {"role": "tool", "tool_call_id": "c1", "content": '{"temp":72}'},
        ]
        instructions, items = convert_messages(msgs)
        assert instructions == "Be concise."
        assert len(items) == 3  # user, function_call, function_call_output
        assert items[0]["role"] == "user"
        assert items[1]["type"] == "function_call"
        assert items[2]["type"] == "function_call_output"


# ======================================================================
# converters - convert_tools
# ======================================================================


class TestConvertTools:
    def test_standard_function_tool(self):
        tools = [{"type": "function", "function": {
            "name": "get_weather",
            "description": "Get weather",
            "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
        }}]
        result = convert_tools(tools)
        assert len(result) == 1
        assert result[0]["type"] == "function"
        assert result[0]["name"] == "get_weather"
        assert result[0]["description"] == "Get weather"
        assert "properties" in result[0]["parameters"]

    def test_tool_without_name_skipped(self):
        tools = [{"type": "function", "function": {"parameters": {}}}]
        assert convert_tools(tools) == []

    def test_tool_without_function_wrapper(self):
        """Direct dict without type=function wrapper."""
        tools = [{"name": "f1", "description": "d", "parameters": {}}]
        result = convert_tools(tools)
        assert result[0]["name"] == "f1"

    def test_missing_optional_fields_default(self):
        tools = [{"type": "function", "function": {"name": "f"}}]
        result = convert_tools(tools)
        assert result[0]["description"] == ""
        assert result[0]["parameters"] == {}

    def test_multiple_tools(self):
        tools = [
            {"type": "function", "function": {"name": "a", "parameters": {}}},
            {"type": "function", "function": {"name": "b", "parameters": {}}},
        ]
        assert len(convert_tools(tools)) == 2


# ======================================================================
# parsing - map_finish_reason
# ======================================================================


class TestMapFinishReason:
    def test_completed(self):
        assert map_finish_reason("completed") == "stop"

    def test_incomplete(self):
        assert map_finish_reason("incomplete") == "length"

    def test_failed(self):
        assert map_finish_reason("failed") == "error"

    def test_cancelled(self):
        assert map_finish_reason("cancelled") == "error"

    def test_none_defaults_to_stop(self):
        assert map_finish_reason(None) == "stop"

    def test_unknown_defaults_to_stop(self):
        assert map_finish_reason("some_new_status") == "stop"


# ======================================================================
# parsing - parse_response_output
# ======================================================================


class TestParseResponseOutput:
    def test_text_response(self):
        resp = {
            "output": [{"type": "message", "role": "assistant",
                         "content": [{"type": "output_text", "text": "Hello!"}]}],
            "status": "completed",
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        }
        result = parse_response_output(resp)
        assert result.content == "Hello!"
        assert result.finish_reason == "stop"
        assert result.usage == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        assert result.tool_calls == []

    def test_tool_call_response(self):
        resp = {
            "output": [{
                "type": "function_call",
                "call_id": "call_1", "id": "fc_1",
                "name": "get_weather",
                "arguments": '{"city": "SF"}',
            }],
            "status": "completed",
            "usage": {},
        }
        result = parse_response_output(resp)
        assert result.content is None
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "get_weather"
        assert result.tool_calls[0].arguments == {"city": "SF"}
        assert result.tool_calls[0].id == "call_1|fc_1"

    def test_malformed_tool_arguments_logged(self):
        """Malformed JSON arguments should log a warning and fallback."""
        resp = {
            "output": [{
                "type": "function_call",
                "call_id": "c1", "id": "fc1",
                "name": "f", "arguments": "{bad json",
            }],
            "status": "completed", "usage": {},
        }
        with patch("janniebot.providers.openai_responses.parsing.logger") as mock_logger:
            result = parse_response_output(resp)
        assert result.tool_calls[0].arguments == {"raw": "{bad json"}
        mock_logger.warning.assert_called_once()
        assert "Failed to parse tool call arguments" in str(mock_logger.warning.call_args)

    def test_reasoning_content_extracted(self):
        resp = {
            "output": [
                {"type": "reasoning", "summary": [
                    {"type": "summary_text", "text": "I think "},
                    {"type": "summary_text", "text": "therefore I am."},
                ]},
                {"type": "message", "role": "assistant",
                 "content": [{"type": "output_text", "text": "42"}]},
            ],
            "status": "completed", "usage": {},
        }
        result = parse_response_output(resp)
        assert result.content == "42"
        assert result.reasoning_content == "I think therefore I am."

    def test_empty_output(self):
        resp = {"output": [], "status": "completed", "usage": {}}
        result = parse_response_output(resp)
        assert result.content is None
        assert result.tool_calls == []

    def test_incomplete_status(self):
        resp = {"output": [], "status": "incomplete", "usage": {}}
        result = parse_response_output(resp)
        assert result.finish_reason == "length"

    def test_sdk_model_object(self):
        """parse_response_output should handle SDK objects with model_dump()."""
        mock = MagicMock()
        mock.model_dump.return_value = {
            "output": [{"type": "message", "role": "assistant",
                         "content": [{"type": "output_text", "text": "sdk"}]}],
            "status": "completed",
            "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
        }
        result = parse_response_output(mock)
        assert result.content == "sdk"
        assert result.usage["prompt_tokens"] == 1

    def test_usage_maps_responses_api_keys(self):
        """Responses API uses input_tokens/output_tokens, not prompt_tokens/completion_tokens."""
        resp = {
            "output": [],
            "status": "completed",
            "usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
        }
        result = parse_response_output(resp)
        assert result.usage["prompt_tokens"] == 100
        assert result.usage["completion_tokens"] == 50
        assert result.usage["total_tokens"] == 150


# ======================================================================
# parsing - consume_sdk_stream
# ======================================================================


class TestConsumeSdkStream:
    @pytest.mark.asyncio
    async def test_text_stream(self):
        ev1 = MagicMock(type="response.output_text.delta", delta="Hello")
        ev2 = MagicMock(type="response.output_text.delta", delta=" world")
        resp_obj = MagicMock(status="completed", usage=None, output=[])
        ev3 = MagicMock(type="response.completed", response=resp_obj)

        async def stream():
            for e in [ev1, ev2, ev3]:
                yield e

        content, tool_calls, finish_reason, usage, reasoning = await consume_sdk_stream(stream())
        assert content == "Hello world"
        assert tool_calls == []
        assert finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_on_content_delta_called(self):
        ev1 = MagicMock(type="response.output_text.delta", delta="hi")
        resp_obj = MagicMock(status="completed", usage=None, output=[])
        ev2 = MagicMock(type="response.completed", response=resp_obj)
        deltas = []

        async def cb(text):
            deltas.append(text)

        async def stream():
            for e in [ev1, ev2]:
                yield e

        await consume_sdk_stream(stream(), on_content_delta=cb)
        assert deltas == ["hi"]

    @pytest.mark.asyncio
    async def test_tool_call_stream(self):
        item_added = MagicMock(type="function_call", call_id="c1", id="fc1", arguments="")
        item_added.name = "get_weather"
        ev1 = MagicMock(type="response.output_item.added", item=item_added)
        ev2 = MagicMock(type="response.function_call_arguments.delta", call_id="c1", delta='{"ci')
        ev3 = MagicMock(type="response.function_call_arguments.done", call_id="c1", arguments='{"city":"SF"}')
        item_done = MagicMock(type="function_call", call_id="c1", id="fc1", arguments='{"city":"SF"}')
        item_done.name = "get_weather"
        ev4 = MagicMock(type="response.output_item.done", item=item_done)
        resp_obj = MagicMock(status="completed", usage=None, output=[])
        ev5 = MagicMock(type="response.completed", response=resp_obj)

        async def stream():
            for e in [ev1, ev2, ev3, ev4, ev5]:
                yield e

        content, tool_calls, finish_reason, usage, reasoning = await consume_sdk_stream(stream())
        assert content == ""
        assert len(tool_calls) == 1
        assert tool_calls[0].name == "get_weather"
        assert tool_calls[0].arguments == {"city": "SF"}

    @pytest.mark.asyncio
    async def test_usage_extracted(self):
        usage_obj = MagicMock(input_tokens=10, output_tokens=5, total_tokens=15)
        resp_obj = MagicMock(status="completed", usage=usage_obj, output=[])
        ev = MagicMock(type="response.completed", response=resp_obj)

        async def stream():
            yield ev

        _, _, _, usage, _ = await consume_sdk_stream(stream())
        assert usage == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}

    @pytest.mark.asyncio
    async def test_reasoning_extracted(self):
        summary_item = MagicMock(type="summary_text", text="thinking...")
        reasoning_item = MagicMock(type="reasoning", summary=[summary_item])
        resp_obj = MagicMock(status="completed", usage=None, output=[reasoning_item])
        ev = MagicMock(type="response.completed", response=resp_obj)

        async def stream():
            yield ev

        _, _, _, _, reasoning = await consume_sdk_stream(stream())
        assert reasoning == "thinking..."

    @pytest.mark.asyncio
    async def test_error_event_raises(self):
        ev = MagicMock(type="error", error="rate_limit_exceeded")

        async def stream():
            yield ev

        with pytest.raises(RuntimeError, match="Response failed.*rate_limit_exceeded"):
            await consume_sdk_stream(stream())

    @pytest.mark.asyncio
    async def test_failed_event_raises(self):
        ev = MagicMock(type="response.failed", error="server_error")

        async def stream():
            yield ev

        with pytest.raises(RuntimeError, match="Response failed.*server_error"):
            await consume_sdk_stream(stream())

    @pytest.mark.asyncio
    async def test_malformed_tool_args_logged(self):
        """Malformed JSON in streaming tool args should log a warning."""
        item_added = MagicMock(type="function_call", call_id="c1", id="fc1", arguments="")
        item_added.name = "f"
        ev1 = MagicMock(type="response.output_item.added", item=item_added)
        ev2 = MagicMock(type="response.function_call_arguments.done", call_id="c1", arguments="{bad")
        item_done = MagicMock(type="function_call", call_id="c1", id="fc1", arguments="{bad")
        item_done.name = "f"
        ev3 = MagicMock(type="response.output_item.done", item=item_done)
        resp_obj = MagicMock(status="completed", usage=None, output=[])
        ev4 = MagicMock(type="response.completed", response=resp_obj)

        async def stream():
            for e in [ev1, ev2, ev3, ev4]:
                yield e

        with patch("janniebot.providers.openai_responses.parsing.logger") as mock_logger:
            _, tool_calls, _, _, _ = await consume_sdk_stream(stream())
        assert tool_calls[0].arguments == {"raw": "{bad"}
        mock_logger.warning.assert_called_once()
        assert "Failed to parse tool call arguments" in str(mock_logger.warning.call_args)
