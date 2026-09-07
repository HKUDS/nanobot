"""Tests for the shared openai_responses converters and parsers."""

import json
from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from loguru import logger

from nanobot.providers.base import LLMUsage
from nanobot.providers.openai_responses.converters import (
    convert_messages,
    convert_tools,
    convert_user_message,
    split_tool_call_id,
)
from nanobot.providers.openai_responses.parsing import (
    ResponsesStreamCapture,
    consume_sdk_stream,
    consume_sse,
    consume_sse_with_reasoning,
    is_replayable_finish_reason,
    map_finish_reason,
    parse_response_output,
)
from nanobot.providers.openai_responses.state import (
    build_responses_state,
    is_compaction_compatibility_error,
    prepare_responses_input,
    resolve_compact_threshold,
    responses_state_context_tokens,
    responses_state_items,
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

    def test_preserves_deepseek_reasoning_content(self):
        _, items = convert_messages([
            {"role": "assistant", "reasoning_content": "think first", "content": "answer"},
        ], preserve_reasoning=True)

        assert items == [
            {
                "type": "reasoning",
                "content": [{"type": "output_text", "text": "think first"}],
            },
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "answer"}],
                "status": "completed",
                "id": "msg_0",
            },
        ]

    def test_reasoning_content_serialized_as_array_for_deepseek(self):
        # Regression for PR #5214: DeepSeek's Responses gateway rejects
        # reasoning items whose ``content`` is a plain string with
        # "input: invalid type: string ..., expected a sequence" (observed
        # after context consolidation cleared provider state and forced
        # full-history conversion). ``content`` must be a list of parts,
        # matching both the OpenAI Responses schema and DeepSeek's accepted
        # wire shape.
        _, items = convert_messages([
            {
                "role": "assistant",
                "reasoning_content": "Michael topped up DeepSeek with $10.",
                "content": "",
                "tool_calls": [{
                    "id": "call_1|fc_1",
                    "function": {"name": "list_dir", "arguments": "{}"},
                }],
            },
        ], preserve_reasoning=True)

        assert items[0]["type"] == "reasoning"
        assert items[0]["content"] == [
            {"type": "output_text", "text": "Michael topped up DeepSeek with $10."},
        ]
        assert items[1]["type"] == "function_call"

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
        assert items[0]["arguments"] == '{"city": "SF"}'

    def test_assistant_tool_call_history_repairs_malformed_arguments(self):
        _, items = convert_messages([{
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call_abc|fc_1",
                "function": {"name": "read_file", "arguments": '{path:"foo.txt"}'},
            }],
        }])

        assert json.loads(items[0]["arguments"]) == {"path": "foo.txt"}

    def test_duplicate_response_item_ids_are_made_unique(self):
        """Codex rejects replayed Responses input items with duplicate ids."""
        _, items = convert_messages([
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_a|rs_same",
                    "function": {"name": "first", "arguments": "{}"},
                }],
            },
            {"role": "tool", "tool_call_id": "call_a|rs_same", "content": "ok"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_b|rs_same",
                    "function": {"name": "second", "arguments": "{}"},
                }],
            },
            {"role": "tool", "tool_call_id": "call_b|rs_same", "content": "ok"},
        ])
        function_call_ids = [
            item["id"] for item in items if item.get("type") == "function_call"
        ]
        assert function_call_ids == ["rs_same", "rs_same_2"]
        assert len(function_call_ids) == len(set(function_call_ids))

    def test_fallback_response_item_ids_are_unique_with_multiple_tool_calls(self):
        _, items = convert_messages([{
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "call_a", "function": {"name": "first", "arguments": "{}"}},
                {"id": "call_b", "function": {"name": "second", "arguments": "{}"}},
            ],
        }])
        function_call_ids = [
            item["id"] for item in items if item.get("type") == "function_call"
        ]
        assert function_call_ids == ["fc_0", "fc_0_2"]
        assert len(function_call_ids) == len(set(function_call_ids))

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

    def test_tool_message_preserves_image_content(self):
        _, items = convert_messages([{
            "role": "tool",
            "tool_call_id": "call_1",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,abc"},
                    "_meta": {"path": "/private/image.png"},
                },
                {"type": "text", "text": "(Image file: image.png)"},
            ],
        }])

        assert items[0]["output"] == [
            {
                "type": "input_image",
                "image_url": "data:image/png;base64,abc",
                "detail": "auto",
            },
            {"type": "input_text", "text": "(Image file: image.png)"},
        ]
        assert "_meta" not in str(items[0])

    def test_tool_message_preserves_file_content(self):
        _, items = convert_messages([{
            "role": "tool",
            "tool_call_id": "call_1",
            "content": [{
                "type": "input_file",
                "file_id": "file_123",
                "filename": "report.pdf",
                "_meta": {"path": "/private/report.pdf"},
            }],
        }])

        assert items[0]["output"] == [{
            "type": "input_file",
            "file_id": "file_123",
            "filename": "report.pdf",
        }]
        assert "_meta" not in str(items[0])

    def test_tool_message_preserves_unknown_list_as_json(self):
        content = [
            {"type": "text", "text": "status", "code": 7},
            {"kind": "record", "value": 42},
        ]

        _, items = convert_messages([{
            "role": "tool",
            "tool_call_id": "call_1",
            "content": content,
        }])

        assert items[0]["output"] == json.dumps(content, ensure_ascii=False)

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

    @pytest.mark.parametrize("finish_reason", ["stop", "tool_calls", "function_call"])
    def test_replayable_finish_reasons(self, finish_reason):
        assert is_replayable_finish_reason(finish_reason) is True

    @pytest.mark.parametrize(
        "finish_reason",
        ["length", "refusal", "content_filter", "error"],
    )
    def test_non_replayable_finish_reasons(self, finish_reason):
        assert is_replayable_finish_reason(finish_reason) is False


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
        assert result.usage == LLMUsage.reported(input_tokens=10, output_tokens=5)
        assert result.tool_calls == []

    def test_refusal_response_surfaces_text_without_advancing_state(self):
        refusal = "I can’t help with that request."
        resp = {
            "output": [{
                "type": "message",
                "role": "assistant",
                "content": [{"type": "refusal", "refusal": refusal}],
            }],
            "status": "completed",
            "usage": {},
        }

        result = parse_response_output(
            resp,
            state_provider="openai:test",
            state_model="gpt-5.6",
            state_input_items=[{"role": "user", "content": "request"}],
        )

        assert result.content == refusal
        assert result.finish_reason == "refusal"
        assert result.provider_state is None

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
        result = parse_response_output(
            resp,
            state_provider="openai:test",
            state_model="gpt-5.6",
            state_input_items=[{"role": "user", "content": "weather?"}],
        )
        assert result.content is None
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "get_weather"
        assert result.tool_calls[0].arguments == {"city": "SF"}
        assert result.tool_calls[0].id == "call_1|fc_1"
        assert result.provider_state is not None

    def test_malformed_tool_arguments_logged(self):
        """Malformed JSON arguments should log a warning and remain non-object."""
        resp = {
            "output": [{
                "type": "function_call",
                "call_id": "c1", "id": "fc1",
                "name": "f", "arguments": "{bad json",
            }],
            "status": "completed", "usage": {},
        }
        with patch("nanobot.providers.openai_responses.parsing.logger") as mock_logger:
            result = parse_response_output(resp)
        assert result.tool_calls[0].arguments == "{bad json"
        mock_logger.warning.assert_called_once()
        assert "Failed to parse tool call arguments" in str(mock_logger.warning.call_args)

    @pytest.mark.parametrize("arguments", [[], False, 0])
    def test_falsy_non_object_tool_arguments_preserved(self, arguments):
        resp = {
            "output": [{
                "type": "function_call",
                "call_id": "c1",
                "id": "fc1",
                "name": "f",
                "arguments": arguments,
            }],
            "status": "completed",
            "usage": {},
        }

        result = parse_response_output(resp)

        assert result.tool_calls[0].arguments == arguments
        assert type(result.tool_calls[0].arguments) is type(arguments)

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

    def test_deepseek_reasoning_content_extracted(self):
        resp = {
            "output": [
                {"type": "reasoning", "content": "think first"},
                {"type": "message", "content": [
                    {"type": "output_text", "text": "answer"},
                ]},
            ],
            "status": "completed", "usage": {},
        }

        result = parse_response_output(resp)

        assert result.content == "answer"
        assert result.reasoning_content == "think first"

    def test_empty_output(self):
        resp = {"output": [], "status": "completed", "usage": {}}
        result = parse_response_output(resp)
        assert result.content is None
        assert result.tool_calls == []

    @pytest.mark.parametrize(
        ("reason", "expected_finish_reason"),
        [
            ("max_output_tokens", "length"),
            ("content_filter", "content_filter"),
        ],
    )
    def test_incomplete_status(self, reason, expected_finish_reason):
        resp = {
            "output": [],
            "status": "incomplete",
            "incomplete_details": {"reason": reason},
            "usage": {},
        }
        result = parse_response_output(
            resp,
            state_provider="openai:test",
            state_model="gpt-5.6",
            state_input_items=[{"role": "user", "content": "prompt"}],
        )
        assert result.finish_reason == expected_finish_reason
        assert result.provider_state is None

    def test_unknown_status_does_not_advance_provider_state(self):
        result = parse_response_output(
            {"output": [], "status": "future_terminal_status", "usage": {}},
            state_provider="openai:test",
            state_model="gpt-5.6",
            state_input_items=[{"role": "user", "content": "prompt"}],
        )

        assert result.finish_reason == "stop"
        assert result.provider_state is None

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
        assert result.usage is not None
        assert result.usage.input_tokens == 1

    def test_usage_maps_responses_api_keys(self):
        """Responses API uses input_tokens/output_tokens, not prompt_tokens/completion_tokens."""
        resp = {
            "output": [],
            "status": "completed",
            "usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
        }
        result = parse_response_output(resp)
        assert result.usage == LLMUsage.reported(input_tokens=100, output_tokens=50)

    def test_non_stream_preserves_provider_reported_total(self):
        result = parse_response_output({
            "output": [],
            "status": "completed",
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 999},
        })

        assert result.usage == LLMUsage.reported(
            input_tokens=10,
            output_tokens=5,
            total_tokens=999,
        )

    def test_preserves_every_output_item_as_opaque_state(self):
        input_items = [{"role": "user", "content": "inspect the repo"}]
        output = [
            {
                "id": "rs_1",
                "type": "reasoning",
                "encrypted_content": "opaque-secret",
                "summary": [],
            },
            {
                "id": "future_1",
                "type": "future_item_type",
                "provider_field": {"nested": True},
            },
            {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "done"}],
            },
        ]

        result = parse_response_output(
            {"output": output, "status": "completed", "usage": {}},
            state_provider="openai:test",
            state_model="gpt-5.6",
            state_input_items=input_items,
        )

        assert result.provider_state is not None
        assert responses_state_items(result.provider_state) == [*input_items, *output]

    def test_marks_only_a_new_response_compaction(self):
        compacted = parse_response_output(
            {
                "output": [
                    {"type": "compaction", "encrypted_content": "opaque"},
                    {"type": "message", "role": "assistant", "content": "done"},
                ],
                "status": "completed",
                "usage": {},
            },
            state_provider="openai:test",
            state_model="gpt-5.6",
            state_input_items=[{"role": "user", "content": "old"}],
        )
        replayed = parse_response_output(
            {
                "output": [
                    {"type": "message", "role": "assistant", "content": "continued"},
                ],
                "status": "completed",
                "usage": {},
            },
            state_provider="openai:test",
            state_model="gpt-5.6",
            state_input_items=[
                {"type": "compaction", "encrypted_content": "opaque"},
            ],
        )

        assert compacted.provider_compaction_applied is True
        assert compacted.provider_compaction_state is not None
        assert compacted.provider_compaction_scope == "current_request"
        assert responses_state_items(compacted.provider_compaction_state) == [
            {"type": "compaction", "encrypted_content": "opaque"},
        ]
        assert replayed.provider_compaction_applied is False
        assert replayed.provider_compaction_state is None
        assert replayed.provider_compaction_scope is None


class TestResponsesConversationState:
    def test_server_compaction_prunes_superseded_prefix(self):
        state = build_responses_state(
            provider="openai:test",
            model="gpt-5.6",
            input_items=[
                {"type": "message", "role": "user", "content": "old"},
                {"type": "reasoning", "encrypted_content": "old-reasoning"},
            ],
            output_items=[
                {"type": "compaction", "encrypted_content": "compact"},
                {"type": "message", "role": "assistant", "content": "new"},
            ],
            usage=LLMUsage.reported(
                input_tokens=90,
                output_tokens=10,
                total_tokens=175,
            ),
        )

        assert responses_state_items(state) == [
            {"type": "compaction", "encrypted_content": "compact"},
            {"type": "message", "role": "assistant", "content": "new"},
        ]
        assert responses_state_context_tokens(state) == 175

    def test_existing_compaction_keeps_canonical_retained_prefix(self):
        canonical_input = [
            {"type": "message", "role": "user", "content": "retained"},
            {"type": "compaction", "encrypted_content": "compact"},
        ]
        output = [{"type": "message", "role": "assistant", "content": "new"}]

        state = build_responses_state(
            provider="openai:test",
            model="gpt-5.6",
            input_items=canonical_input,
            output_items=output,
        )

        assert responses_state_items(state) == [*canonical_input, *output]

    @pytest.mark.parametrize(
        ("context_window", "max_output", "expected"),
        [
            (200_000, 20_000, 180_000),
            (100_000, 30_000, 70_000),
            (0, 4_096, None),
        ],
    )
    def test_compact_threshold_reserves_codex_style_headroom(
        self,
        context_window,
        max_output,
        expected,
    ):
        assert resolve_compact_threshold(context_window, max_output) == expected

    def test_compaction_compatibility_recognizes_old_sdk_signature_error(self):
        error = TypeError("create() got an unexpected keyword argument 'context_management'")
        assert is_compaction_compatibility_error(error) is True
        assert is_compaction_compatibility_error(TypeError("unrelated argument")) is False

    def test_state_observability_logs_counts_without_opaque_content(self):
        secret = "opaque-secret-that-must-not-be-logged"
        state = build_responses_state(
            provider=f"openai:https://example.test/?key={secret}",
            model=f"secret-model-{secret}",
            input_items=[{"role": "user", "content": secret}],
            output_items=[{"type": "reasoning", "encrypted_content": secret}],
        ).with_pending_messages([{"role": "user", "content": secret}])
        sink = StringIO()
        sink_id = logger.add(sink, level="DEBUG", format="{message}")
        try:
            prepare_responses_input(
                [{"role": "user", "content": secret}],
                state=state,
                provider=state.provider,
                model=state.model,
            )
            build_responses_state(
                provider=state.provider,
                model=state.model,
                input_items=[
                    {"role": "user", "content": secret},
                    {"type": "reasoning", "encrypted_content": secret},
                ],
                output_items=[
                    {"type": "compaction", "encrypted_content": secret},
                ],
            )
        finally:
            logger.remove(sink_id)

        log_text = sink.getvalue()
        assert "prior_items=2" in log_text
        assert "pending_messages=1" in log_text
        assert "dropped_items=2" in log_text
        assert secret not in log_text

    def test_replays_exact_items_then_only_pending_and_new_messages(self):
        prior_items = [
            {"role": "user", "content": "first"},
            {
                "type": "reasoning",
                "id": "rs_1",
                "encrypted_content": "opaque-secret",
            },
            {
                "type": "function_call",
                "id": "fc_1",
                "call_id": "call_1",
                "name": "read_file",
                "arguments": '{"path":"a.py"}',
            },
        ]
        state = build_responses_state(
            provider="openai:test",
            model="gpt-5.6",
            input_items=prior_items[:1],
            output_items=prior_items[1:],
        ).with_pending_messages([
            {
                "role": "tool",
                "tool_call_id": "call_1|fc_1",
                "content": "file contents",
            },
            {"role": "user", "content": "continue"},
        ])

        instructions, items, replayed = prepare_responses_input(
            [
                {"role": "system", "content": "current instructions"},
                {"role": "user", "content": "a lossy public transcript"},
            ],
            state=state,
            provider="openai:test",
            model="gpt-5.6",
        )

        assert instructions == "current instructions"
        assert replayed is True
        assert items[:3] == prior_items
        assert items[3] == {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "file contents",
        }
        assert items[4] == {
            "role": "user",
            "content": [{"type": "input_text", "text": "continue"}],
        }
        assert "lossy public transcript" not in str(items)

    def test_replayed_and_delta_reasoning_items_keep_array_content(self):
        # Regression for PR #5214: token consolidation clears
        # ``provider_state``, so the next turn converts the full history
        # (including assistant reasoning) instead of replaying server items.
        # Both paths must keep reasoning ``content`` as a list - DeepSeek's
        # Responses gateway rejects the string form with a serde error.
        prior_items = [
            {
                "type": "reasoning",
                "id": "rs_1",
                "content": [{"type": "output_text", "text": "prior reasoning"}],
            },
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "prior answer"}],
                "status": "completed",
                "id": "msg_0",
            },
        ]
        state = build_responses_state(
            provider="openai:test",
            model="deepseek-v4-flash",
            input_items=prior_items,
            output_items=[],
        ).with_pending_messages([
            {
                "role": "assistant",
                "reasoning_content": "think before acting",
                "content": "answer",
            },
            {"role": "user", "content": "audit the tools"},
        ])

        instructions, items, replayed = prepare_responses_input(
            [
                {"role": "system", "content": "You are KITT."},
                {"role": "user", "content": "audit the tools"},
            ],
            state=state,
            provider="openai:test",
            model="deepseek-v4-flash",
            preserve_reasoning=True,
        )

        assert instructions == "You are KITT."
        assert replayed is True
        reasoning_items = [item for item in items if item.get("type") == "reasoning"]
        assert len(reasoning_items) == 2  # one replayed, one converted delta
        for item in reasoning_items:
            assert isinstance(item["content"], list)
            assert item["content"][0]["type"] == "output_text"


# ======================================================================
# parsing - consume_sse
# ======================================================================


class _SseResponse:
    def __init__(self, events: list[dict]):
        self._events = events

    async def aiter_lines(self):
        for event in self._events:
            yield f"data: {json.dumps(event)}"
            yield ""


class TestConsumeSse:
    @pytest.mark.asyncio
    async def test_legacy_consume_sse_returns_three_tuple(self):
        response = _SseResponse([
            {"type": "response.output_text.delta", "delta": "hi"},
            {"type": "response.completed", "response": {"status": "completed"}},
        ])

        content, tool_calls, finish_reason = await consume_sse(response)

        assert content == "hi"
        assert tool_calls == []
        assert finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_refusal_events_reconcile_parts_and_terminal_output(self):
        refusal = "First and second sentence. Done-only. Terminal suffix."
        terminal_response = {
            "status": "completed",
            "output": [{
                "type": "message",
                "id": "msg_2",
                "role": "assistant",
                "content": [{"type": "refusal", "refusal": refusal}],
            }],
        }
        response = _SseResponse([
            {
                "type": "response.refusal.delta",
                "item_id": "msg_1",
                "content_index": 0,
                "delta": "First",
            },
            {
                "type": "response.refusal.delta",
                "item_id": "msg_1",
                "content_index": 1,
                "delta": " and second",
            },
            {
                "type": "response.refusal.done",
                "item_id": "msg_1",
                "content_index": 0,
                "refusal": "First",
            },
            {
                "type": "response.refusal.done",
                "item_id": "msg_1",
                "content_index": 1,
                "refusal": " and second sentence.",
            },
            {
                "type": "response.refusal.done",
                "item_id": "msg_2",
                "content_index": 0,
                "refusal": " Done-only.",
            },
            {
                "type": "response.refusal.delta",
                "item_id": "msg_2",
                "content_index": 1,
                "delta": " Terminal",
            },
            {"type": "response.completed", "response": terminal_response},
        ])
        capture = ResponsesStreamCapture()
        deltas: list[str] = []

        async def on_content(delta: str) -> None:
            deltas.append(delta)

        content, _, finish_reason, _, _ = await consume_sse_with_reasoning(
            response,
            on_content_delta=on_content,
            capture=capture,
        )

        assert content == refusal
        assert deltas == [
            "First",
            " and second",
            " sentence.",
            " Done-only.",
            " Terminal",
            " suffix.",
        ]
        assert finish_reason == "refusal"
        assert capture.completed is True
        assert is_replayable_finish_reason(finish_reason) is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("source", ["events", "terminal"])
    async def test_refusal_without_deltas_has_non_replayable_finish(self, source: str):
        refusal = "I can’t help with that request."
        terminal_response = {
            "status": "completed",
            "output": [{
                "type": "message",
                "id": "msg_1",
                "role": "assistant",
                "content": [{"type": "refusal", "refusal": refusal}],
            }],
        }
        events = (
            [
                {"type": "response.refusal.done", "refusal": refusal},
                {"type": "response.completed", "response": {"status": "completed"}},
            ]
            if source == "events"
            else [{"type": "response.completed", "response": terminal_response}]
        )
        response = _SseResponse(events)
        capture = ResponsesStreamCapture()
        deltas: list[str] = []

        async def on_content(delta: str) -> None:
            deltas.append(delta)

        content, _, finish_reason, _, _ = await consume_sse_with_reasoning(
            response,
            on_content_delta=on_content,
            capture=capture,
        )

        assert content == refusal
        assert deltas == [refusal]
        assert finish_reason == "refusal"
        assert capture.completed is True
        assert is_replayable_finish_reason(finish_reason) is False

    @pytest.mark.asyncio
    async def test_reasoning_summary_delta_extracted(self):
        response = _SseResponse([
            {
                "type": "response.reasoning_summary_text.delta",
                "item_id": "rs_1",
                "summary_index": 0,
                "delta": "thinking ",
            },
            {
                "type": "response.reasoning_summary_text.delta",
                "item_id": "rs_1",
                "summary_index": 0,
                "delta": "briefly",
            },
            {
                "type": "response.reasoning_summary_text.delta",
                "item_id": "rs_1",
                "summary_index": 1,
                "delta": "Checking result",
            },
            {"type": "response.output_text.delta", "delta": "answer"},
            {"type": "response.completed", "response": {"status": "completed"}},
        ])
        deltas: list[str] = []

        async def on_reasoning(delta: str) -> None:
            deltas.append(delta)

        content, tool_calls, finish_reason, usage, reasoning = await consume_sse_with_reasoning(
            response,
            on_reasoning_delta=on_reasoning,
        )

        assert content == "answer"
        assert tool_calls == []
        assert finish_reason == "stop"
        assert usage is None
        assert reasoning == "thinking briefly\nChecking result"
        assert deltas == ["thinking ", "briefly", "\nChecking result"]

    @pytest.mark.asyncio
    async def test_reasoning_summary_from_completed_response(self):
        response = _SseResponse([
            {
                "type": "response.completed",
                "response": {
                    "status": "completed",
                    "output": [
                        {"type": "reasoning", "summary": [
                            {"type": "summary_text", "text": "cached"},
                            {"type": "summary_text", "text": "summary"},
                        ]},
                    ],
                },
            },
        ])

        _, _, _, _, reasoning = await consume_sse_with_reasoning(response)

        assert reasoning == "cached\nsummary"

    @pytest.mark.asyncio
    async def test_capture_commits_exact_items_only_after_completed_event(self):
        output = [
            {
                "type": "reasoning",
                "id": "rs_1",
                "encrypted_content": "opaque-secret",
            },
            {"type": "future_item_type", "id": "future_1", "value": 7},
        ]
        capture = ResponsesStreamCapture()
        response = _SseResponse([
            {
                "type": "response.output_item.done",
                "output_index": 0,
                "item": output[0],
            },
            {
                "type": "response.output_item.done",
                "output_index": 1,
                "item": output[1],
            },
            {
                "type": "response.completed",
                "response": {"status": "completed", "output": output},
            },
        ])

        await consume_sse_with_reasoning(response, capture=capture)

        assert capture.completed is True
        assert capture.output_items == output

    @pytest.mark.asyncio
    async def test_capture_keeps_done_items_when_completed_output_is_empty(self):
        output = [
            {
                "type": "reasoning",
                "id": "rs_1",
                "encrypted_content": "opaque-secret",
                "summary": [],
            },
            {
                "type": "function_call",
                "id": "fc_1",
                "call_id": "call_1",
                "name": "read_file",
                "arguments": '{"path":"weather/SKILL.md"}',
            },
        ]
        capture = ResponsesStreamCapture()
        response = _SseResponse([
            {
                "type": "response.output_item.done",
                "output_index": index,
                "item": item,
            }
            for index, item in enumerate(output)
        ] + [{
            "type": "response.completed",
            "response": {"status": "completed", "output": []},
        }])

        await consume_sse_with_reasoning(response, capture=capture)

        assert capture.completed is True
        assert capture.output_items == output

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("reason", "expected_finish_reason"),
        [
            ("max_output_tokens", "length"),
            ("content_filter", "content_filter"),
        ],
    )
    async def test_incomplete_event_commits_capture_usage(
        self,
        reason,
        expected_finish_reason,
    ):
        output = [
            {
                "type": "message",
                "id": "msg_1",
                "status": "incomplete",
                "content": [{"type": "output_text", "text": "partial"}],
            },
        ]
        terminal_response = {
            "id": "resp_1",
            "status": "incomplete",
            "incomplete_details": {"reason": reason},
            "output": output,
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        }
        capture = ResponsesStreamCapture()
        response = _SseResponse([
            {"type": "response.output_text.delta", "delta": "partial"},
            {"type": "response.incomplete", "response": terminal_response},
        ])

        content, _, finish_reason, usage, _ = await consume_sse_with_reasoning(
            response,
            capture=capture,
        )

        assert content == "partial"
        assert finish_reason == expected_finish_reason
        assert usage == LLMUsage.reported(input_tokens=10, output_tokens=5)
        assert capture.completed is True
        assert capture.response == terminal_response
        assert capture.output_items == output

    @pytest.mark.asyncio
    async def test_capture_does_not_commit_interrupted_stream(self):
        capture = ResponsesStreamCapture()
        response = _SseResponse([
            {
                "type": "response.output_item.done",
                "output_index": 0,
                "item": {
                    "type": "reasoning",
                    "id": "rs_1",
                    "encrypted_content": "opaque-secret",
                },
            },
        ])

        await consume_sse_with_reasoning(response, capture=capture)

        assert capture.completed is False

    @pytest.mark.asyncio
    async def test_reasoning_summary_from_done_item(self):
        response = _SseResponse([
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "reasoning",
                    "summary": [{"type": "summary_text", "text": "done summary"}],
                },
            },
            {"type": "response.completed", "response": {"status": "completed", "output": []}},
        ])
        deltas: list[str] = []

        async def on_reasoning(delta: str) -> None:
            deltas.append(delta)

        _, _, _, _, reasoning = await consume_sse_with_reasoning(
            response,
            on_reasoning_delta=on_reasoning,
        )

        assert reasoning == "done summary"
        assert deltas == ["done summary"]

    @pytest.mark.asyncio
    async def test_reasoning_summary_part_done_extracted(self):
        response = _SseResponse([
            {
                "type": "response.reasoning_summary_part.done",
                "part": {"type": "summary_text", "text": "part summary"},
            },
            {"type": "response.completed", "response": {"status": "completed"}},
        ])

        _, _, _, _, reasoning = await consume_sse_with_reasoning(response)

        assert reasoning == "part summary"

    @pytest.mark.asyncio
    async def test_raw_sse_usage_extracted(self):
        response = _SseResponse([
            {
                "type": "response.completed",
                "response": {
                    "status": "completed",
                    "usage": {
                        "input_tokens": 10,
                        "input_tokens_details": {
                            "cached_tokens": 8,
                            "cache_write_tokens": 0,
                        },
                        "output_tokens": 5,
                        "total_tokens": 15,
                    },
                },
            },
        ])

        _, _, _, usage, _ = await consume_sse_with_reasoning(response)

        assert usage == LLMUsage.reported(
            input_tokens=10,
            output_tokens=5,
            cache_read_tokens=8,
            cache_write_tokens=0,
        )

    @pytest.mark.asyncio
    async def test_stream_and_non_stream_share_usage_normalization(self):
        terminal = {
            "status": "completed",
            "output": [],
            "usage": {
                "input_tokens": 15,
                "input_tokens_details": {
                    "cached_tokens": 0,
                    "cache_write_tokens": 7,
                },
                "output_tokens": 18,
                "total_tokens": 175,
            },
        }
        non_stream = parse_response_output(terminal).usage
        sse = _SseResponse([
            {"type": "response.completed", "response": terminal},
        ])
        _, _, _, streamed, _ = await consume_sse_with_reasoning(sse)

        sdk_response = SimpleNamespace(**terminal)
        sdk_response.usage = SimpleNamespace(
            input_tokens=15,
            input_tokens_details=SimpleNamespace(
                cached_tokens=0,
                cache_write_tokens=7,
            ),
            output_tokens=18,
            total_tokens=175,
        )

        async def sdk_stream():
            yield SimpleNamespace(type="response.completed", response=sdk_response)

        _, _, _, sdk_streamed, _ = await consume_sdk_stream(sdk_stream())
        expected = LLMUsage.reported(
            input_tokens=15,
            output_tokens=18,
            total_tokens=175,
            cache_read_tokens=0,
            cache_write_tokens=7,
        )
        assert non_stream == streamed == sdk_streamed == expected

    def test_missing_usage_is_not_explicit_zero_usage(self):
        missing = parse_response_output({"status": "completed", "output": []})
        explicit_zero = parse_response_output({
            "status": "completed",
            "output": [],
            "usage": {"input_tokens": 0, "output_tokens": 0},
        })

        assert missing.usage is None
        assert explicit_zero.usage == LLMUsage.reported(input_tokens=0, output_tokens=0)

    @pytest.mark.asyncio
    async def test_tool_call_done_arguments_callback(self):
        response = _SseResponse([
            {
                "type": "response.output_item.added",
                "item": {
                    "type": "function_call",
                    "call_id": "c1",
                    "id": "fc1",
                    "name": "write_file",
                    "arguments": "",
                },
            },
            {
                "type": "response.function_call_arguments.done",
                "call_id": "c1",
                "arguments": '{"path":"a.txt","content":"hello\\n"}',
            },
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "function_call",
                    "call_id": "c1",
                    "id": "fc1",
                    "name": "write_file",
                    "arguments": '{"path":"a.txt","content":"hello\\n"}',
                },
            },
            {"type": "response.completed", "response": {"status": "completed"}},
        ])
        deltas: list[dict] = []

        async def cb(delta: dict) -> None:
            deltas.append(delta)

        await consume_sse_with_reasoning(response, on_tool_call_delta=cb)

        assert deltas == [
            {"call_id": "c1", "name": "write_file", "arguments_delta": ""},
            {
                "call_id": "c1",
                "name": "write_file",
                "arguments": '{"path":"a.txt","content":"hello\\n"}',
            },
        ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("arguments", [[], False, 0])
    async def test_falsy_non_object_tool_arguments_preserved(self, arguments):
        response = _SseResponse([
            {
                "type": "response.output_item.added",
                "item": {
                    "type": "function_call",
                    "call_id": "c1",
                    "id": "fc1",
                    "name": "f",
                    "arguments": "",
                },
            },
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "function_call",
                    "call_id": "c1",
                    "id": "fc1",
                    "name": "f",
                    "arguments": arguments,
                },
            },
            {"type": "response.completed", "response": {"status": "completed"}},
        ])

        _, tool_calls, _, _, _ = await consume_sse_with_reasoning(response)

        assert tool_calls[0].arguments == arguments
        assert type(tool_calls[0].arguments) is type(arguments)


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
    async def test_hosted_web_search_lifecycle_is_streamed_as_tool_progress(self):
        search_added = SimpleNamespace(
            type="web_search_call",
            id="ws_1",
            status="in_progress",
            action=SimpleNamespace(type="search"),
        )
        search_done = SimpleNamespace(
            type="web_search_call",
            id="ws_1",
            status="completed",
            action=SimpleNamespace(
                type="search",
                queries=["nanobot DeepSeek", "nanobot latest release"],
                sources=[
                    SimpleNamespace(
                        title="DeepSeek Responses API",
                        url="https://api-docs.deepseek.com/guides/responses_api/",
                    ),
                ],
            ),
        )
        response = SimpleNamespace(status="completed", usage=None, output=[search_done])
        events = [
            SimpleNamespace(
                type="response.output_item.added",
                output_index=0,
                item=search_added,
            ),
            SimpleNamespace(
                type="response.web_search_call.searching",
                item_id="ws_1",
                output_index=0,
            ),
            SimpleNamespace(
                type="response.web_search_call.completed",
                item_id="ws_1",
                output_index=0,
            ),
            SimpleNamespace(
                type="response.output_item.done",
                output_index=0,
                item=search_done,
            ),
            SimpleNamespace(type="response.completed", response=response),
        ]
        tool_events: list[dict] = []

        async def stream():
            for event in events:
                yield event

        async def on_tool_event(event: dict) -> None:
            tool_events.append(event)

        await consume_sdk_stream(stream(), on_tool_call_delta=on_tool_event)

        assert tool_events == [
            {
                "kind": "hosted_tool",
                "phase": "start",
                "call_id": "ws_1",
                "name": "web_search",
                "arguments": {},
                "result": None,
            },
            {
                "kind": "hosted_tool",
                "phase": "end",
                "call_id": "ws_1",
                "name": "web_search",
                "arguments": {
                    "query": "nanobot DeepSeek · nanobot latest release",
                },
                "result": {
                    "status": "completed",
                    "sources": [{
                        "title": "DeepSeek Responses API",
                        "url": "https://api-docs.deepseek.com/guides/responses_api/",
                    }],
                },
            },
        ]

    @pytest.mark.asyncio
    async def test_refusal_events_reconcile_parts_and_terminal_output(self):
        refusal = "First and second sentence. Done-only. Terminal suffix."
        terminal_response = {
            "status": "completed",
            "output": [{
                "type": "message",
                "id": "msg_2",
                "role": "assistant",
                "content": [{"type": "refusal", "refusal": refusal}],
            }],
        }
        resp_obj = MagicMock(status="completed", usage=None, output=[])
        resp_obj.model_dump.return_value = terminal_response
        events = [
            MagicMock(
                type="response.refusal.delta",
                item_id="msg_1",
                content_index=0,
                delta="First",
            ),
            MagicMock(
                type="response.refusal.delta",
                item_id="msg_1",
                content_index=1,
                delta=" and second",
            ),
            MagicMock(
                type="response.refusal.done",
                item_id="msg_1",
                content_index=0,
                refusal="First",
            ),
            MagicMock(
                type="response.refusal.done",
                item_id="msg_1",
                content_index=1,
                refusal=" and second sentence.",
            ),
            MagicMock(
                type="response.refusal.done",
                item_id="msg_2",
                content_index=0,
                refusal=" Done-only.",
            ),
            MagicMock(
                type="response.refusal.delta",
                item_id="msg_2",
                content_index=1,
                delta=" Terminal",
            ),
            MagicMock(type="response.completed", response=resp_obj),
        ]
        capture = ResponsesStreamCapture()
        deltas: list[str] = []

        async def on_content(delta: str) -> None:
            deltas.append(delta)

        async def stream():
            for event in events:
                yield event

        content, _, finish_reason, _, _ = await consume_sdk_stream(
            stream(),
            on_content_delta=on_content,
            capture=capture,
        )

        assert content == refusal
        assert deltas == [
            "First",
            " and second",
            " sentence.",
            " Done-only.",
            " Terminal",
            " suffix.",
        ]
        assert finish_reason == "refusal"
        assert capture.completed is True
        assert is_replayable_finish_reason(finish_reason) is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("source", ["events", "terminal"])
    async def test_refusal_without_deltas_has_non_replayable_finish(self, source: str):
        refusal = "I can’t help with that request."
        terminal_response = {
            "status": "completed",
            "output": [{
                "type": "message",
                "id": "msg_1",
                "role": "assistant",
                "content": [{"type": "refusal", "refusal": refusal}],
            }],
        }
        resp_obj = MagicMock(status="completed", usage=None, output=[])
        resp_obj.model_dump.return_value = terminal_response
        capture = ResponsesStreamCapture()
        deltas: list[str] = []

        async def on_content(delta: str) -> None:
            deltas.append(delta)

        async def stream():
            if source == "events":
                yield MagicMock(type="response.refusal.done", refusal=refusal)
                yield MagicMock(
                    type="response.completed",
                    response={"status": "completed"},
                )
            else:
                yield MagicMock(type="response.completed", response=resp_obj)

        content, _, finish_reason, _, _ = await consume_sdk_stream(
            stream(),
            on_content_delta=on_content,
            capture=capture,
        )

        assert content == refusal
        assert deltas == [refusal]
        assert finish_reason == "refusal"
        assert capture.completed is True
        assert is_replayable_finish_reason(finish_reason) is False

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
    async def test_tool_call_argument_delta_callback(self):
        item_added = MagicMock(type="function_call", call_id="c1", id="fc1", arguments="")
        item_added.name = "write_file"
        ev1 = MagicMock(type="response.output_item.added", item=item_added)
        ev2 = MagicMock(
            type="response.function_call_arguments.delta",
            call_id="c1",
            delta='{"path":"a.txt","content":"',
        )
        ev3 = MagicMock(
            type="response.function_call_arguments.delta",
            call_id="c1",
            delta='hello\\n',
        )
        ev4 = MagicMock(
            type="response.function_call_arguments.done",
            call_id="c1",
            arguments='{"path":"a.txt","content":"hello\\n"}',
        )
        item_done = MagicMock(
            type="function_call",
            call_id="c1",
            id="fc1",
            arguments='{"path":"a.txt","content":"hello\\n"}',
        )
        item_done.name = "write_file"
        ev5 = MagicMock(type="response.output_item.done", item=item_done)
        resp_obj = MagicMock(status="completed", usage=None, output=[])
        ev6 = MagicMock(type="response.completed", response=resp_obj)
        deltas: list[dict] = []

        async def cb(delta: dict) -> None:
            deltas.append(delta)

        async def stream():
            for e in [ev1, ev2, ev3, ev4, ev5, ev6]:
                yield e

        await consume_sdk_stream(stream(), on_tool_call_delta=cb)
        assert deltas == [
            {"call_id": "c1", "name": "write_file", "arguments_delta": ""},
            {
                "call_id": "c1",
                "name": "write_file",
                "arguments_delta": '{"path":"a.txt","content":"',
            },
            {"call_id": "c1", "name": "write_file", "arguments_delta": "hello\\n"},
            {
                "call_id": "c1",
                "name": "write_file",
                "arguments": '{"path":"a.txt","content":"hello\\n"}',
            },
        ]

    @pytest.mark.asyncio
    async def test_tool_call_done_item_arguments_callback_without_delta(self):
        item_added = MagicMock(type="function_call", call_id="c1", id="fc1", arguments="")
        item_added.name = "write_file"
        ev1 = MagicMock(type="response.output_item.added", item=item_added)
        item_done = MagicMock(
            type="function_call",
            call_id="c1",
            id="fc1",
            arguments='{"path":"late.txt","content":"done\\n"}',
        )
        item_done.name = "write_file"
        ev2 = MagicMock(type="response.output_item.done", item=item_done)
        resp_obj = MagicMock(status="completed", usage=None, output=[])
        ev3 = MagicMock(type="response.completed", response=resp_obj)
        deltas: list[dict] = []

        async def cb(delta: dict) -> None:
            deltas.append(delta)

        async def stream():
            for e in [ev1, ev2, ev3]:
                yield e

        await consume_sdk_stream(stream(), on_tool_call_delta=cb)

        assert deltas == [
            {"call_id": "c1", "name": "write_file", "arguments_delta": ""},
            {
                "call_id": "c1",
                "name": "write_file",
                "arguments": '{"path":"late.txt","content":"done\\n"}',
            },
        ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("arguments", [[], False, 0])
    async def test_falsy_non_object_tool_arguments_preserved(self, arguments):
        item_added = MagicMock(type="function_call", call_id="c1", id="fc1", arguments="")
        item_added.name = "f"
        ev1 = MagicMock(type="response.output_item.added", item=item_added)
        item_done = MagicMock(type="function_call", call_id="c1", id="fc1")
        item_done.name = "f"
        item_done.arguments = arguments
        ev2 = MagicMock(type="response.output_item.done", item=item_done)
        resp_obj = MagicMock(status="completed", usage=None, output=[])
        ev3 = MagicMock(type="response.completed", response=resp_obj)

        async def stream():
            for e in [ev1, ev2, ev3]:
                yield e

        _, tool_calls, _, _, _ = await consume_sdk_stream(stream())

        assert tool_calls[0].arguments == arguments
        assert type(tool_calls[0].arguments) is type(arguments)

    @pytest.mark.asyncio
    async def test_usage_extracted(self):
        usage_obj = SimpleNamespace(
            input_tokens=10,
            input_tokens_details=SimpleNamespace(cached_tokens=8),
            output_tokens=5,
            total_tokens=15,
        )
        resp_obj = SimpleNamespace(status="completed", usage=usage_obj, output=[])
        ev = SimpleNamespace(type="response.completed", response=resp_obj)

        async def stream():
            yield ev

        _, _, _, usage, _ = await consume_sdk_stream(stream())
        assert usage == LLMUsage.reported(
            input_tokens=10,
            output_tokens=5,
            cache_read_tokens=8,
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("reason", "expected_finish_reason"),
        [
            ("max_output_tokens", "length"),
            ("content_filter", "content_filter"),
        ],
    )
    async def test_incomplete_event_commits_capture_usage(
        self,
        reason,
        expected_finish_reason,
    ):
        output = [
            {
                "type": "message",
                "id": "msg_1",
                "status": "incomplete",
                "content": [{"type": "output_text", "text": "partial"}],
            },
        ]
        usage_obj = MagicMock(input_tokens=10, output_tokens=5, total_tokens=15)
        output_item = MagicMock(type="message")
        terminal_response = {
            "id": "resp_1",
            "status": "incomplete",
            "incomplete_details": {"reason": reason},
            "output": output,
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        }
        resp_obj = MagicMock(
            status="incomplete",
            usage=usage_obj,
            output=[output_item],
        )
        resp_obj.model_dump.return_value = terminal_response
        events = [
            MagicMock(type="response.output_text.delta", delta="partial"),
            MagicMock(type="response.incomplete", response=resp_obj),
        ]
        capture = ResponsesStreamCapture()

        async def stream():
            for event in events:
                yield event

        content, _, finish_reason, usage, _ = await consume_sdk_stream(
            stream(),
            capture=capture,
        )

        assert content == "partial"
        assert finish_reason == expected_finish_reason
        assert usage == LLMUsage.reported(input_tokens=10, output_tokens=5)
        assert capture.completed is True
        assert capture.response == terminal_response
        assert capture.output_items == output

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
    async def test_deepseek_reasoning_text_streamed(self):
        events = [
            MagicMock(type="response.reasoning_text.delta", delta="step 1 "),
            MagicMock(type="response.reasoning_text.delta", delta="step 2"),
            MagicMock(type="response.reasoning_text.done", text="step 1 step 2"),
        ]
        emitted: list[str] = []

        async def stream():
            for event in events:
                yield event

        async def on_reasoning_delta(delta: str) -> None:
            emitted.append(delta)

        _, _, _, _, reasoning = await consume_sdk_stream(
            stream(),
            on_reasoning_delta=on_reasoning_delta,
        )

        assert reasoning == "step 1 step 2"
        assert emitted == ["step 1 ", "step 2"]

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
        """Malformed JSON in streaming tool args should log a warning and remain non-object."""
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

        with patch("nanobot.providers.openai_responses.parsing.logger") as mock_logger:
            _, tool_calls, _, _, _ = await consume_sdk_stream(stream())
        assert tool_calls[0].arguments == "{bad"
        mock_logger.warning.assert_called_once()
        assert "Failed to parse tool call arguments" in str(mock_logger.warning.call_args)
