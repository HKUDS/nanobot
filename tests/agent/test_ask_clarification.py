from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


@pytest.mark.asyncio
async def test_ask_clarification_short_circuits_tool_batch():
    from loguru import logger

    from nanobot.agent.runner import AgentRunner, AgentRunSpec
    from nanobot.agent.tools.clarification import AskClarificationTool
    from nanobot.agent.tools.registry import ToolRegistry

    checkpoints = []

    async def capture_checkpoint(payload):
        checkpoints.append(payload)

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="",
        tool_calls=[
            ToolCallRequest(
                id="call_clarify",
                name="ask_clarification",
                arguments={
                    "question": "Which environment should I deploy to?",
                    "clarification_type": "approach_choice",
                    "options": ["development", "staging", "production"],
                },
            ),
            ToolCallRequest(id="call_exec", name="exec", arguments={"cmd": "deploy"}),
        ],
    ))
    tools = ToolRegistry()
    tools.register(AskClarificationTool())

    logs = []
    sink_id = logger.add(lambda message: logs.append(str(message)), format="{message}", level="INFO")
    try:
        result = await AgentRunner(provider).run(AgentRunSpec(
            initial_messages=[{"role": "user", "content": "Deploy the app"}],
            tools=tools,
            model="test-model",
            max_iterations=3,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
            checkpoint_callback=capture_checkpoint,
        ))
    finally:
        logger.remove(sink_id)

    assert result.final_content == (
        "Which environment should I deploy to?\n\n"
        "Options:\n"
        "1. development\n"
        "2. staging\n"
        "3. production"
    )
    assert result.stop_reason == "clarification"
    assert result.tools_used == ["ask_clarification"]
    assert provider.chat_with_retry.await_count == 1
    assert [msg["role"] for msg in result.messages[-3:]] == ["assistant", "tool", "assistant"]
    assistant_tool_calls = result.messages[-3]["tool_calls"]
    assert [tc["function"]["name"] for tc in assistant_tool_calls] == ["ask_clarification"]
    assert result.messages[-2]["name"] == "ask_clarification"
    assert result.messages[-1]["content"] == result.final_content
    awaiting_tools = next(payload for payload in checkpoints if payload["phase"] == "awaiting_tools")
    pending_names = [
        tc["function"]["name"] for tc in awaiting_tools["pending_tool_calls"]
    ]
    assert pending_names == ["ask_clarification"]
    assert any(
        "ask_clarification cancelled 1 same-turn tool call(s)" in entry and "exec" in entry
        for entry in logs
    )


@pytest.mark.asyncio
async def test_ask_clarification_error_continues_for_model_repair():
    from nanobot.agent.runner import AgentRunner, AgentRunSpec
    from nanobot.agent.tools.clarification import AskClarificationTool
    from nanobot.agent.tools.registry import ToolRegistry

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(side_effect=[
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="call_bad_clarify",
                    name="ask_clarification",
                    arguments={"clarification_type": "missing_info"},
                ),
            ],
        ),
        LLMResponse(content="Please tell me the span."),
    ])
    tools = ToolRegistry()
    tools.register(AskClarificationTool())

    result = await AgentRunner(provider).run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "Design a portal frame"}],
        tools=tools,
        model="test-model",
        max_iterations=3,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert result.final_content == "Please tell me the span."
    assert result.stop_reason == "completed"
    assert provider.chat_with_retry.await_count == 2
    assert result.messages[-2]["role"] == "tool"
    assert "Error: Invalid parameters" in result.messages[-2]["content"]
    assert result.messages[-1]["content"] == "Please tell me the span."


def test_snip_history_keeps_latest_clarification_pair():
    from nanobot.agent.runner import AgentRunner, AgentRunSpec

    provider = MagicMock(spec=LLMProvider)
    tools = MagicMock()
    tools.get_definitions.return_value = []
    runner = AgentRunner(provider)
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "old " + ("x" * 2000)},
        {"role": "assistant", "content": "old answer " + ("y" * 2000)},
        {"role": "user", "content": "deploy"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call_clarify",
                "type": "function",
                "function": {"name": "ask_clarification", "arguments": "{}"},
            }],
        },
        {
            "role": "tool",
            "tool_call_id": "call_clarify",
            "name": "ask_clarification",
            "content": "Deploy to production? " + ("z" * 500),
        },
        {"role": "assistant", "content": "Deploy to production? " + ("z" * 500)},
        {"role": "user", "content": "yes"},
    ]

    kept = runner._snip_history(AgentRunSpec(
        initial_messages=[],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        context_window_tokens=1200,
        context_block_limit=80,
    ), messages)

    assert kept[-5:] == messages[-5:]


@pytest.mark.asyncio
async def test_ask_clarification_tool_formats_question_options():
    from nanobot.agent.tools.clarification import AskClarificationTool

    tool = AskClarificationTool()

    assert tool.name == "ask_clarification"
    assert "Call it by itself" in tool.description
    assert tool.parameters["required"] == ["question"]
    assert tool.parameters["properties"]["clarification_type"]["enum"] == [
        "missing_info",
        "ambiguous_requirement",
        "approach_choice",
        "risk_confirmation",
        "suggestion",
    ]

    result = await tool.execute(
        question="Which environment should I deploy to?",
        clarification_type="approach_choice",
        context="Deployment target is required.",
        options=["development", "staging"],
    )
    assert result == (
        "Which environment should I deploy to?\n\n"
        "Deployment target is required.\n\n"
        "Options:\n"
        "1. development\n"
        "2. staging"
    )


@pytest.mark.asyncio
async def test_ask_clarification_tool_accepts_schema_minimum_arguments():
    from nanobot.agent.tools.clarification import AskClarificationTool

    tool = AskClarificationTool()

    result = await tool.execute(question="What span should I use?")

    assert result == "What span should I use?"
