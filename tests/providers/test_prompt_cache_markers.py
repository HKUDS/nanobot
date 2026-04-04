from __future__ import annotations

from typing import Any

from janniebot.providers.anthropic_provider import AnthropicProvider
from janniebot.providers.openai_compat_provider import OpenAICompatProvider


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
