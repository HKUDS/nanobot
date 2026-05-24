"""Integration tests for loop guard and rate limit guard in AgentRunner."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.runner import AgentRunSpec, AgentRunner
from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from nanobot.utils.runtime import RATE_LIMIT_WINDOW

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


# ═══════════════════════════════════════════════════════════════════════════
# Loop guard integration tests
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_loop_guard_blocks_tool_on_third_identical_call():
    """同一轮次内第3次相同参数调用时硬阻断，工具不执行，返回 Error"""
    provider = MagicMock(spec=LLMProvider)
    captured_messages: list[list[dict]] = []
    call_count = {"n": 0}

    async def chat_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        captured_messages.append(list(messages))
        if call_count["n"] == 1:
            # Single turn with 3 identical tool calls — the 3rd must be blocked
            return LLMResponse(
                content="searching",
                tool_calls=[
                    ToolCallRequest(id="c1", name="grep", arguments={"pattern": "TODO", "path": "."}),
                    ToolCallRequest(id="c2", name="grep", arguments={"pattern": "TODO", "path": "."}),
                    ToolCallRequest(id="c3", name="grep", arguments={"pattern": "TODO", "path": "."}),
                ],
                usage={"prompt_tokens": 10, "completion_tokens": 5},
            )
        return LLMResponse(content="done", tool_calls=[], usage={})

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="no matches found")

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "search for TODOs"}],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert result.final_content == "done"
    # 第3次被硬阻断，工具结果直接是 Error 消息
    blocked = [
        msg for msg in result.messages
        if msg.get("role") == "tool"
        and msg.get("name") == "grep"
        and "Error: loop guard blocked" in str(msg.get("content", ""))
    ]
    assert len(blocked) >= 1, (
        "第3次相同工具+参数调用应被硬阻断，工具结果包含 Error"
    )
    # 前2次的工具正常执行了
    assert tools.execute.await_count == 2, (
        f"只有前2次应执行，第3次被阻断，实际执行了{tools.execute.await_count}次"
    )


@pytest.mark.asyncio
async def test_loop_guard_does_not_block_first_two_calls():
    """同一轮次内前2次相同工具+参数调用不触发硬阻断"""
    provider = MagicMock(spec=LLMProvider)
    call_count = {"n": 0}

    async def chat_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Only 2 identical calls — within budget
            return LLMResponse(
                content="searching",
                tool_calls=[
                    ToolCallRequest(id="c1", name="grep", arguments={"pattern": "TODO", "path": "."}),
                    ToolCallRequest(id="c2", name="grep", arguments={"pattern": "TODO", "path": "."}),
                ],
                usage={"prompt_tokens": 10, "completion_tokens": 5},
            )
        return LLMResponse(content="done", tool_calls=[], usage={})

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="no matches found")

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "search for TODOs"}],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert result.final_content == "done"
    for msg in result.messages:
        if msg.get("role") == "tool":
            content = str(msg.get("content", ""))
            assert "Error: loop guard blocked" not in content, (
                f"前2次调用不应有 loop guard: {content}"
            )


@pytest.mark.asyncio
async def test_loop_guard_different_args_no_false_positive():
    """同一轮次内不同参数调用不应误触发 loop guard"""
    provider = MagicMock(spec=LLMProvider)
    call_count = {"n": 0}
    paths = ["/a.txt", "/b.txt", "/c.txt"]

    async def chat_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return LLMResponse(
                content="reading",
                tool_calls=[
                    ToolCallRequest(
                        id=f"call_{i + 1}",
                        name="read_file",
                        arguments={"path": paths[i]},
                    )
                    for i in range(3)
                ],
                usage={"prompt_tokens": 10, "completion_tokens": 5},
            )
        return LLMResponse(content="done", tool_calls=[], usage={})

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="file content")

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "read files"}],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert result.final_content == "done"
    for msg in result.messages:
        if msg.get("role") == "tool":
            content = str(msg.get("content", ""))
            assert "Error: loop guard blocked" not in content, (
                f"不同参数不应触发 loop guard: {content}"
            )


# ═══════════════════════════════════════════════════════════════════════════
# Rate limit guard integration tests
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_rate_limit_guard_blocks_on_frequent_calls():
    """同一轮次内频繁工具调用时硬阻断，返回 Error"""
    provider = MagicMock(spec=LLMProvider)
    call_count = {"n": 0}
    threshold_count, _ = RATE_LIMIT_WINDOW

    async def chat_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Single turn with threshold_count identical calls — rate limit must block
            return LLMResponse(
                content="working",
                tool_calls=[
                    ToolCallRequest(
                        id=f"call_{i + 1}",
                        name="list_dir",
                        arguments={"path": "."},
                    )
                    for i in range(threshold_count)
                ],
                usage={"prompt_tokens": 5, "completion_tokens": 2},
            )
        return LLMResponse(content="done", tool_calls=[], usage={})

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="file listing")

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "list dir a few times"}],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert result.final_content == "done"
    rate_messages = [
        msg for msg in result.messages
        if msg.get("role") == "tool"
        and "Error: rate limit exceeded" in str(msg.get("content", ""))
    ]
    assert len(rate_messages) >= 1, (
        f"第{threshold_count}次调用应触发 rate limit，但未找到"
    )


@pytest.mark.asyncio
async def test_loop_guard_preserves_normal_tool_results():
    """正常不同工具调用不应被 loop guard 影响"""
    provider = MagicMock(spec=LLMProvider)

    async def chat_with_retry(*, messages, **kwargs):
        return LLMResponse(
            content="working",
            tool_calls=[
                ToolCallRequest(id="c1", name="read_file", arguments={"path": "/a.txt"}),
                ToolCallRequest(id="c2", name="grep", arguments={"pattern": "x"}),
            ],
            usage={"prompt_tokens": 10, "completion_tokens": 5},
        )

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    async def fake_tool(name, args, **kw):
        return f"result from {name}"

    tools.execute = AsyncMock(side_effect=fake_tool)

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "do work"}],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    tool_results = [msg for msg in result.messages if msg.get("role") == "tool"]
    assert len(tool_results) == 2
    for tr in tool_results:
        content = str(tr.get("content", ""))
        assert "result from" in content
        assert "Error: loop guard blocked" not in content
        assert "Error: rate limit exceeded" not in content
