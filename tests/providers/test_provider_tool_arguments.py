"""Shared tool-argument parsing policy tests."""

import httpx

from nanobot.providers.anthropic_provider import AnthropicProvider
from nanobot.providers.base import (
    parse_tool_arguments,
    tool_arguments_json_for_replay,
    tool_arguments_object_for_replay,
)


def test_parse_tool_arguments_preserves_malformed_executable_arguments() -> None:
    assert parse_tool_arguments('{path:"foo.txt"}') == '{path:"foo.txt"}'


def test_parse_tool_arguments_preserves_non_object_executable_arguments() -> None:
    assert parse_tool_arguments('["foo.txt"]') == ["foo.txt"]
    assert parse_tool_arguments("false") is False
    assert parse_tool_arguments("null") == "null"


def test_tool_arguments_object_for_replay_repairs_object_like_history_arguments() -> None:
    assert tool_arguments_object_for_replay('{path:"foo.txt"}') == {"path": "foo.txt"}


def test_tool_arguments_object_for_replay_keeps_history_object_shaped() -> None:
    for arguments in ['["foo.txt"]', "false", "null", "0", ["foo.txt"], False, None, 0]:
        assert tool_arguments_object_for_replay(arguments) == {}


def test_tool_arguments_json_for_replay_returns_object_string() -> None:
    assert tool_arguments_json_for_replay('{path:"foo.txt"}') == '{"path": "foo.txt"}'


def test_replay_arguments_sanitize_surrogates_after_json_decoding() -> None:
    arguments = r'{"values": ["lone \ud800", "paired \ud83e\udd16"]}'
    expected = {"values": ["lone \ufffd", "paired 🤖"]}
    assert tool_arguments_object_for_replay(arguments) == expected
    assert tool_arguments_json_for_replay(arguments).encode("utf-8")
    # Replay cleanup must not alter arguments that are about to execute.
    assert parse_tool_arguments(arguments) == {"values": ["lone \ud800", "paired 🤖"]}


def test_replay_arguments_sanitize_repaired_json_and_preserve_original_objects() -> None:
    assert tool_arguments_object_for_replay(r'{text:"\ud800"}') == {"text": "\ufffd"}
    original = {"text": "\ud800"}
    assert tool_arguments_object_for_replay(original) == {"text": "\ufffd"}
    assert original == {"text": "\ud800"}


def test_anthropic_replay_with_escaped_surrogate_is_utf8_encodable() -> None:
    messages = [
        {"role": "user", "content": "Echo this value"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {"name": "echo", "arguments": r'{"text":"hello \ud800"}'},
            }],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "done"},
    ]
    provider = AnthropicProvider(api_key="synthetic-test-key")
    kwargs = provider._build_kwargs(
        messages, None, None, 100, 0, None, None, supports_caching=False,
    )
    request = httpx.Request("POST", "https://example.invalid/messages", json=kwargs)
    assert "hello �" in request.content.decode("utf-8")
