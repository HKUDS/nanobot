"""Tests for tool call argument normalization in _sanitize_messages.

When models (especially Dashscope/Qwen) produce malformed tool call arguments
(e.g. JSON arrays instead of objects), _sanitize_messages must normalize them
before sending to the API to prevent permanent 400 loops.
"""

import json

from nanobot.providers.litellm_provider import LiteLLMProvider


# Real poisoned data extracted from
# feishu_ou_0204b00b38f9f43f8f0177e30fc0f19b.jsonl line 25.
# The Qwen model tried to call write_file with a huge JSON template; the
# output was garbled into a JSON array instead of an object.
REAL_POISONED_ARGUMENTS = (
    '[{"path": "/root/.hiperone/workspace/脱硫系统模板.json", '
    '"content": "{\\n    \\"fileInfo\\": {\\n        \\"fileName\\": '
    '\\"脱硫吸收系统模板.gra\\"'
    '"}, '
    '"canvasHeight\\": 1080,\\n        \\"createTime\\": \\"2026-03-09 15": 30}, '
    '["n        {\\n            \\"type\\": \\"Rectangle\\"", '
    '"n            \\"name\\": \\"背景框_主区域\\""]]'
)


def _make_assistant_msg_with_tool_calls(arguments: str) -> dict:
    return {
        "role": "assistant",
        "content": "Calling tool...",
        "tool_calls": [
            {
                "id": "tc_001",
                "type": "function",
                "function": {
                    "name": "write_file",
                    "arguments": arguments,
                },
            }
        ],
    }


class TestSanitizeMessagesArgNormalization:
    """LiteLLMProvider._sanitize_messages should ensure function.arguments
    is always a valid JSON object string."""

    def test_valid_dict_args_string_unchanged(self):
        original = '{"path": "/tmp/test.txt"}'
        msg = _make_assistant_msg_with_tool_calls(original)
        result = LiteLLMProvider._sanitize_messages([msg])
        fn_args = result[0]["tool_calls"][0]["function"]["arguments"]
        assert json.loads(fn_args) == {"path": "/tmp/test.txt"}

    def test_list_args_string_normalized_to_object(self):
        original = '[{"path": "/tmp/test.txt", "content": "hello"}]'
        msg = _make_assistant_msg_with_tool_calls(original)
        result = LiteLLMProvider._sanitize_messages([msg])
        fn_args = result[0]["tool_calls"][0]["function"]["arguments"]
        parsed = json.loads(fn_args)
        assert isinstance(parsed, dict)
        assert parsed == {"path": "/tmp/test.txt", "content": "hello"}

    def test_multi_element_list_args_wrapped(self):
        original = '[{"a": 1}, {"b": 2}]'
        msg = _make_assistant_msg_with_tool_calls(original)
        result = LiteLLMProvider._sanitize_messages([msg])
        fn_args = result[0]["tool_calls"][0]["function"]["arguments"]
        parsed = json.loads(fn_args)
        assert isinstance(parsed, dict)
        assert "raw" in parsed

    def test_dict_value_as_python_dict_serialized(self):
        """If arguments is a Python dict (not JSON string), it should be serialized."""
        msg = {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "tc_001",
                "type": "function",
                "function": {
                    "name": "write_file",
                    "arguments": {"path": "/tmp/test.txt"},
                },
            }],
        }
        result = LiteLLMProvider._sanitize_messages([msg])
        fn_args = result[0]["tool_calls"][0]["function"]["arguments"]
        assert isinstance(fn_args, str)
        assert json.loads(fn_args) == {"path": "/tmp/test.txt"}

    def test_tool_result_messages_not_affected(self):
        """Tool result messages should pass through unchanged."""
        msgs = [
            {"role": "tool", "tool_call_id": "tc_001", "name": "write_file", "content": "done"},
        ]
        result = LiteLLMProvider._sanitize_messages(msgs)
        assert result[0]["content"] == "done"


class TestDashscopeSessionPoisoning:
    """Regression tests using real poisoned session data.

    The Qwen model output garbled JSON-array arguments for write_file.
    This caused:
    1. Tool execution to fail ("parameters must be an object, got list")
    2. The malformed tool_call to be saved in session history
    3. All subsequent API calls to fail with Dashscope 400 error:
       "function.arguments parameter must be in JSON format"
    """

    def test_sanitize_messages_heals_poisoned_session(self):
        """_sanitize_messages must convert the real poisoned arguments to a
        valid JSON object string so the session can recover."""
        msg = _make_assistant_msg_with_tool_calls(REAL_POISONED_ARGUMENTS)
        tool_result = {
            "role": "tool",
            "tool_call_id": "tc_001",
            "name": "write_file",
            "content": "Error: Invalid parameters for tool 'write_file': "
                       "parameters must be an object, got list",
        }
        follow_up = {"role": "user", "content": "你是谁"}

        sanitized = LiteLLMProvider._sanitize_messages([msg, tool_result, follow_up])

        fn_args_str = sanitized[0]["tool_calls"][0]["function"]["arguments"]
        assert isinstance(fn_args_str, str)
        parsed = json.loads(fn_args_str)
        assert isinstance(parsed, dict), (
            f"Dashscope requires arguments to be a JSON object, got {type(parsed).__name__}"
        )

    def test_full_round_trip_no_400_loop(self):
        """Simulate the full round-trip: poisoned history loaded from session,
        sanitized for API call — the arguments must always be a JSON object."""
        history = [
            _make_assistant_msg_with_tool_calls(REAL_POISONED_ARGUMENTS),
            {
                "role": "tool",
                "tool_call_id": "tc_001",
                "name": "write_file",
                "content": "Error: Invalid parameters for tool 'write_file': "
                           "parameters must be an object, got list",
            },
        ]
        new_user_msg = {"role": "user", "content": "你回复我"}
        messages = [{"role": "system", "content": "You are a helpful assistant."}] + history + [new_user_msg]

        sanitized = LiteLLMProvider._sanitize_messages(messages)

        for msg in sanitized:
            if msg.get("role") != "assistant" or not msg.get("tool_calls"):
                continue
            for tc in msg["tool_calls"]:
                fn_args = tc["function"]["arguments"]
                assert isinstance(fn_args, str)
                parsed = json.loads(fn_args)
                assert isinstance(parsed, dict), (
                    "All function.arguments must be JSON objects to avoid Dashscope 400 errors"
                )
