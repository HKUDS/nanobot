"""Shared tool-argument parsing policy tests."""

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
