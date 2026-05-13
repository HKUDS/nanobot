"""Tests for AgentRunner security: workspace violations, SSRF, shell guard, throttling."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMResponse, ToolCallRequest

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars

async def test_runner_does_not_abort_on_workspace_violation_anymore():
    """v2 behavior: workspace-bound rejections are *soft* tool errors.

    Previously (PR #3493) any workspace boundary error became a fatal
    RuntimeError that aborted the turn. That silently killed legitimate
    workspace commands once the heuristic guard misfired (#3599 #3605), so
    we now hand the error back to the LLM as a recoverable tool result and
    rely on ``repeated_workspace_violation_error`` to throttle bypass loops.
    """
    from nanobot.agent.runner import AgentRunSpec, AgentRunner

    provider = MagicMock()
    provider.chat_with_retry = AsyncMock(side_effect=[
        LLMResponse(
            content="trying outside",
            tool_calls=[ToolCallRequest(
                id="call_1", name="read_file", arguments={"path": "/tmp/outside.md"},
            )],
        ),
        LLMResponse(content="ok, telling the user instead", tool_calls=[]),
    ])
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(
        side_effect=PermissionError(
            "Path /tmp/outside.md is outside allowed directory /workspace"
        )
    )

    runner = AgentRunner(provider)

    result = await runner.run(AgentRunSpec(
        initial_messages=[],
        tools=tools,
        model="test-model",
        max_iterations=3,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert provider.chat_with_retry.await_count == 2, (
        "workspace violation must NOT short-circuit the loop"
    )
    assert result.stop_reason != "tool_error"
    assert result.error is None
    assert result.final_content == "ok, telling the user instead"
    assert result.tool_events and result.tool_events[0]["status"] == "error"
    # Detail still carries the workspace_violation breadcrumb for telemetry,
    # but the runner did not raise.
    assert "workspace_violation" in result.tool_events[0]["detail"]


def test_is_ssrf_violation_recognizes_private_url_blocks():
    """SSRF rejections are classified separately from workspace boundaries."""
    from nanobot.agent.runner import AgentRunner

    ssrf_msg = "Error: Command blocked by safety guard (internal/private URL detected)"
    assert AgentRunner._is_ssrf_violation(ssrf_msg) is True
    assert AgentRunner._is_ssrf_violation(
        "URL validation failed: Blocked: host resolves to private/internal address 192.168.1.2"
    ) is True

    # Workspace-bound markers are NOT classified as SSRF.
    assert AgentRunner._is_ssrf_violation(
        "Error: Command blocked by safety guard (path outside working dir)"
    ) is False
    assert AgentRunner._is_ssrf_violation(
        "Path /tmp/x is outside allowed directory /ws"
    ) is False
    # Deny / allowlist filter messages stay non-fatal too.
    assert AgentRunner._is_ssrf_violation(
        "Error: Command blocked by deny pattern filter"
    ) is False


@pytest.mark.asyncio
async def test_runner_returns_non_retryable_hint_on_ssrf_violation():
    """SSRF stays blocked, but the runtime gives the LLM a final chance to recover."""
    from nanobot.agent.runner import AgentRunSpec, AgentRunner

    provider = MagicMock()
    provider.chat_with_retry = AsyncMock(side_effect=[
        LLMResponse(
            content="curl-ing metadata",
            tool_calls=[ToolCallRequest(
                id="call_ssrf",
                name="exec",
                arguments={"command": "curl http://169.254.169.254"},
            )],
        ),
        LLMResponse(
            content="I cannot access that private URL. Please share local files.",
            tool_calls=[],
        ),
    ])
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value=(
        "Error: Command blocked by safety guard (internal/private URL detected)"
    ))

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[],
        tools=tools,
        model="test-model",
        max_iterations=3,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert provider.chat_with_retry.await_count == 2
    assert result.stop_reason == "completed"
    assert result.error is None
    assert result.final_content == "I cannot access that private URL. Please share local files."
    assert result.tool_events and result.tool_events[0]["detail"].startswith("ssrf_violation:")
    tool_messages = [m for m in result.messages if m.get("role") == "tool"]
    assert tool_messages
    assert "non-bypassable security boundary" in tool_messages[0]["content"]
    assert "Do not retry" in tool_messages[0]["content"]
    assert "tools.ssrfWhitelist" in tool_messages[0]["content"]


@pytest.mark.asyncio
async def test_runner_lets_llm_recover_from_shell_guard_path_outside():
    """Reporter scenario for #3599 / #3605 -- guard hit, agent recovers.

    The shell `_guard_command` heuristic fires on `2>/dev/null`-style
    redirects and other shell idioms. Before v2 that abort'd the whole
    turn (silent hang on Telegram per #3605); now the LLM gets the soft
    error back and can finalize on the next iteration.
    """
    from nanobot.agent.runner import AgentRunSpec, AgentRunner

    provider = MagicMock()
    captured_second_call: list[dict] = []

    async def chat_with_retry(*, messages, **kwargs):
        if provider.chat_with_retry.await_count == 1:
            return LLMResponse(
                content="trying noisy cleanup",
                tool_calls=[ToolCallRequest(
                    id="call_blocked",
                    name="exec",
                    arguments={"command": "rm scratch.txt 2>/dev/null"},
                )],
            )
        captured_second_call[:] = list(messages)
        return LLMResponse(content="recovered final answer", tool_calls=[])

    provider.chat_with_retry = AsyncMock(side_effect=chat_with_retry)
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(
        return_value="Error: Command blocked by safety guard (path outside working dir)"
    )

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[],
        tools=tools,
        model="test-model",
        max_iterations=3,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert provider.chat_with_retry.await_count == 2, (
        "guard hit must NOT short-circuit the loop -- LLM should get a second turn"
    )
    assert result.stop_reason != "tool_error"
    assert result.error is None
    assert result.final_content == "recovered final answer"
    assert result.tool_events and result.tool_events[0]["status"] == "error"
    # v2: detail keeps the breadcrumb but the runner did not raise.
    assert "workspace_violation" in result.tool_events[0]["detail"]


@pytest.mark.asyncio
async def test_runner_throttles_repeated_workspace_bypass_attempts():
    """#3493 motivation: stop the LLM bypass loop without aborting the turn.

    LLM keeps switching tools (read_file -> exec cat -> python -c open(...))
    against the same outside path. After the soft retry budget is exhausted
    the runner replaces the tool result with a hard "stop trying" message
    so the model finally gives up and surfaces the boundary to the user.
    """
    from nanobot.agent.runner import AgentRunSpec, AgentRunner

    bypass_attempts = [
        ToolCallRequest(
            id=f"a{i}", name="exec",
            arguments={"command": f"cat /Users/x/Downloads/01.md  # try {i}"},
        )
        for i in range(4)
    ]
    responses: list[LLMResponse] = [
        LLMResponse(content=f"try {i}", tool_calls=[bypass_attempts[i]])
        for i in range(4)
    ]
    responses.append(LLMResponse(content="ok telling user", tool_calls=[]))

    provider = MagicMock()
    provider.chat_with_retry = AsyncMock(side_effect=responses)
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(
        return_value="Error: Command blocked by safety guard (path outside working dir)"
    )

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[],
        tools=tools,
        model="test-model",
        max_iterations=10,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    # All 4 bypass attempts surface to the LLM (no fatal abort), and the
    # runner finally completes once the LLM stops asking.
    assert result.stop_reason != "tool_error"
    assert result.error is None
    assert result.final_content == "ok telling user"
    # The third+ attempts must have been escalated -- look at the events.
    escalated = [
        ev for ev in result.tool_events
        if ev["status"] == "error"
        and ev["detail"].startswith("workspace_violation_escalated:")
    ]
    assert escalated, (
        "expected at least one escalated workspace_violation event, got: "
        f"{result.tool_events}"
    )
