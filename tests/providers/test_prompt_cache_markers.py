from __future__ import annotations

from typing import Any

from nanobot.providers.anthropic_provider import AnthropicProvider
from nanobot.providers.openai_compat_provider import OpenAICompatProvider


def _openai_tools(*names: str) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": f"{name} tool",
                "parameters": {"type": "object", "properties": {}},
            },
        }
        for name in names
    ]


def _anthropic_tools(*names: str) -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "description": f"{name} tool",
            "input_schema": {"type": "object", "properties": {}},
        }
        for name in names
    ]


def _marked_openai_tool_names(tools: list[dict[str, Any]] | None) -> list[str]:
    if not tools:
        return []
    marked: list[str] = []
    for tool in tools:
        if "cache_control" in tool:
            marked.append((tool.get("function") or {}).get("name", ""))
    return marked


def _marked_anthropic_tool_names(tools: list[dict[str, Any]] | None) -> list[str]:
    if not tools:
        return []
    return [tool.get("name", "") for tool in tools if "cache_control" in tool]


def test_openai_compat_marks_builtin_boundary_and_tail_tool() -> None:
    messages = [
        {"role": "system", "content": "system"},
        {"role": "assistant", "content": "assistant"},
        {"role": "user", "content": "user"},
    ]
    _, marked_tools = OpenAICompatProvider._apply_cache_control(
        messages,
        _openai_tools("read_file", "write_file", "mcp_fs_ls", "mcp_git_status"),
    )
    assert _marked_openai_tool_names(marked_tools) == ["write_file", "mcp_git_status"]


def test_anthropic_marks_builtin_boundary_and_tail_tool() -> None:
    messages = [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
    ]
    _, _, marked_tools = AnthropicProvider._apply_cache_control(
        "system",
        messages,
        _anthropic_tools("read_file", "write_file", "mcp_fs_ls", "mcp_git_status"),
    )
    assert _marked_anthropic_tool_names(marked_tools) == ["write_file", "mcp_git_status"]


def test_openai_compat_marks_only_tail_without_mcp() -> None:
    messages = [
        {"role": "system", "content": "system"},
        {"role": "assistant", "content": "assistant"},
        {"role": "user", "content": "user"},
    ]
    _, marked_tools = OpenAICompatProvider._apply_cache_control(
        messages,
        _openai_tools("read_file", "write_file"),
    )
    assert _marked_openai_tool_names(marked_tools) == ["write_file"]

def test_openai_compat_cache_control_with_list_content_strings() -> None:
    messages = [
        {"role": "system", "content": ["system prompt line 1", "system prompt line 2"]},
        {"role": "assistant", "content": "assistant"},
        {"role": "user", "content": ["user line 1", "user line 2"]},
    ]
    new_messages, _ = OpenAICompatProvider._apply_cache_control(messages, None)
    assert new_messages[0]["content"][-1] == {
        "type": "text",
        "text": "system prompt line 2",
        "cache_control": {"type": "ephemeral"},
    }


def test_anthropic_cache_control_with_list_content_strings() -> None:
    messages = [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": ["assistant line 1", "assistant line 2"]},
        {"role": "user", "content": "u2"},
    ]
    system, new_messages, _ = AnthropicProvider._apply_cache_control(
        ["system line 1", "system line 2"],
        messages,
        None,
    )
    assert system[-1] == {
        "type": "text",
        "text": "system line 2",
        "cache_control": {"type": "ephemeral"},
    }
    assert new_messages[-2]["content"][-1] == {
        "type": "text",
        "text": "assistant line 2",
        "cache_control": {"type": "ephemeral"},
    }
