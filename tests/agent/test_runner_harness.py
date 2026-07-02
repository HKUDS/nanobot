"""Tests that exercise the reusable scripted agent harness."""

from __future__ import annotations

import pytest

from agent.harness import (
    ScriptedProvider,
    ScriptedTools,
    assert_tool_results_are_paired,
    tool_call,
)
from nanobot.agent.runner import AgentRunner, AgentRunSpec
from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMResponse

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


@pytest.mark.asyncio
async def test_scripted_provider_drives_tool_loop_transcript() -> None:
    provider = ScriptedProvider([
        LLMResponse(
            content="I will inspect the file.",
            tool_calls=[tool_call("read_file", {"path": "README.md"}, id="read_1")],
            reasoning_content="Need to inspect first.",
            usage={"prompt_tokens": 7, "completion_tokens": 3},
        ),
        LLMResponse(
            content="README says hello.",
            usage={"prompt_tokens": 11, "completion_tokens": 5},
        ),
    ])
    tools = ScriptedTools(
        ["hello from README"],
        definitions=[{"type": "function", "function": {"name": "read_file"}}],
    )

    result = await AgentRunner(provider).run(
        AgentRunSpec(
            initial_messages=[{"role": "user", "content": "Summarize README.md"}],
            tools=tools,
            model="test-model",
            max_iterations=3,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        ),
    )

    assert result.final_content == "README says hello."
    assert result.tools_used == ["read_file"]
    assert result.usage == {
        "prompt_tokens": 18,
        "completion_tokens": 8,
        "total_tokens": 26,
        "provider_tokens": 26,
    }
    assert tools.calls[0].name == "read_file"
    assert tools.calls[0].arguments == {"path": "README.md"}
    assert len(provider.requests) == 2

    second_request = provider.requests[1]
    assert_tool_results_are_paired(second_request.messages)
    assert second_request.messages == [
        {"role": "user", "content": "Summarize README.md"},
        {
            "role": "assistant",
            "content": "I will inspect the file.",
            "tool_calls": [
                {
                    "id": "read_1",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": '{"path": "README.md"}',
                    },
                },
            ],
            "reasoning_content": "Need to inspect first.",
        },
        {
            "role": "tool",
            "tool_call_id": "read_1",
            "name": "read_file",
            "content": "hello from README",
        },
    ]


@pytest.mark.asyncio
async def test_scripted_harness_covers_multi_tool_transcript_pairing() -> None:
    provider = ScriptedProvider([
        LLMResponse(
            content="I need both files.",
            tool_calls=[
                tool_call("read_file", {"path": "pyproject.toml"}, id="read_pyproject"),
                tool_call("read_file", {"path": "README.md"}, id="read_readme"),
            ],
        ),
        LLMResponse(content="Both files were inspected."),
    ])
    tools = ScriptedTools(["pyproject content", "readme content"])

    result = await AgentRunner(provider).run(
        AgentRunSpec(
            initial_messages=[{"role": "user", "content": "Inspect project files"}],
            tools=tools,
            model="test-model",
            max_iterations=3,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        ),
    )

    assert result.final_content == "Both files were inspected."
    assert [call.arguments["path"] for call in tools.calls] == [
        "pyproject.toml",
        "README.md",
    ]
    assert_tool_results_are_paired(result.messages)
    assert provider.requests[1].messages[-2:] == [
        {
            "role": "tool",
            "tool_call_id": "read_pyproject",
            "name": "read_file",
            "content": "pyproject content",
        },
        {
            "role": "tool",
            "tool_call_id": "read_readme",
            "name": "read_file",
            "content": "readme content",
        },
    ]
