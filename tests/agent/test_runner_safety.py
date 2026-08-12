"""Tests for AgentRunner security: workspace violations, SSRF, shell guard, throttling."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.runner_helpers import make_run_spec
from nanobot.agent.runner import AgentRunner
from nanobot.agent.tools import ToolResult
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

    runner = AgentRunner()

    result = await runner.run(make_run_spec(provider,
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
    tools.execute = AsyncMock(return_value=ToolResult.error(
        "Error: Command blocked by safety guard (internal/private URL detected)"
    ))

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
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
        return_value=ToolResult.error(
            "Error: Command blocked by safety guard (path outside working dir)"
        )
    )

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
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
        return_value=ToolResult.error(
            "Error: Command blocked by safety guard (path outside working dir)"
        )
    )

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
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


@pytest.mark.asyncio
async def test_runner_warns_on_repeated_identical_tool_call():
    """Loop guard: 3 identical (name + args) tool-call rounds in a row inject
    a system warning into the conversation. The warning informs, it does not
    block -- all four iterations must still run, and the warning must fire
    exactly once, not once per repeat.
    """
    repeated_call = ToolCallRequest(
        id="call_x", name="read_file", arguments={"path": "/workspace/a.md"},
    )
    provider = MagicMock()
    provider.chat_with_retry = AsyncMock(side_effect=[
        LLMResponse(content="", tool_calls=[repeated_call]),
        LLMResponse(content="", tool_calls=[repeated_call]),
        LLMResponse(content="", tool_calls=[repeated_call]),
        LLMResponse(content="giving up on that path", tool_calls=[]),
    ])
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value=ToolResult("not found", is_error=False))

    runner = AgentRunner()
    result = await runner.run(make_run_spec(
        provider,
        initial_messages=[],
        tools=tools,
        model="test-model",
        max_iterations=6,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert provider.chat_with_retry.await_count == 4, (
        "the loop guard must not short-circuit execution -- all four "
        "iterations (three repeats plus the final differing response) "
        "should still run"
    )
    warnings = [
        m for m in result.messages
        if m.get("role") == "system" and "same tool call" in m.get("content", "")
    ]
    assert len(warnings) == 1, (
        f"expected exactly one loop warning, got {len(warnings)}: {warnings}"
    )


@pytest.mark.asyncio
async def test_runner_does_not_warn_on_two_repeats_or_varied_calls():
    """Two identical calls in a row is not (yet) a loop; varying the
    arguments between calls must never trigger a false-positive warning.
    """
    provider = MagicMock()
    provider.chat_with_retry = AsyncMock(side_effect=[
        LLMResponse(content="", tool_calls=[ToolCallRequest(
            id="c1", name="read_file", arguments={"path": "/workspace/a.md"},
        )]),
        LLMResponse(content="", tool_calls=[ToolCallRequest(
            id="c2", name="read_file", arguments={"path": "/workspace/a.md"},
        )]),
        LLMResponse(content="", tool_calls=[ToolCallRequest(
            id="c3", name="read_file", arguments={"path": "/workspace/b.md"},
        )]),
        LLMResponse(content="done", tool_calls=[]),
    ])
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value=ToolResult("ok", is_error=False))

    runner = AgentRunner()
    result = await runner.run(make_run_spec(
        provider,
        initial_messages=[],
        tools=tools,
        model="test-model",
        max_iterations=6,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    warnings = [
        m for m in result.messages
        if m.get("role") == "system" and "same tool call" in m.get("content", "")
    ]
    assert warnings == [], f"expected no loop warning, got: {warnings}"


@pytest.mark.asyncio
async def test_runner_warns_on_batched_identical_tool_calls_in_one_round():
    """Loop guard, batched variant: 3 identical (name + args) tool calls
    issued together in a single round must warn immediately, on that first
    round -- not just when the same round repeats across iterations. This is
    the gap _detect_tool_call_loop's one-signature-per-round approach can't
    see (three parallel calls in one round produce a distinct joined
    signature exactly once, so it would never look like a repeat).
    """
    batched_calls = [
        ToolCallRequest(id="c1", name="read_file", arguments={"path": "/workspace/a.md"}),
        ToolCallRequest(id="c2", name="read_file", arguments={"path": "/workspace/a.md"}),
        ToolCallRequest(id="c3", name="read_file", arguments={"path": "/workspace/a.md"}),
    ]
    provider = MagicMock()
    provider.chat_with_retry = AsyncMock(side_effect=[
        LLMResponse(content="", tool_calls=batched_calls),
        LLMResponse(content="done", tool_calls=[]),
    ])
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value=ToolResult("not found", is_error=False))

    runner = AgentRunner()
    result = await runner.run(make_run_spec(
        provider,
        initial_messages=[],
        tools=tools,
        model="test-model",
        max_iterations=6,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    warnings = [
        m for m in result.messages
        if m.get("role") == "system" and "same tool call" in m.get("content", "")
    ]
    assert len(warnings) == 1, (
        f"expected exactly one loop warning on the first (batched) round, got {len(warnings)}: {warnings}"
    )


@pytest.mark.asyncio
async def test_runner_does_not_warn_on_two_batched_identical_or_varied_calls():
    """Two identical calls batched in one round is not (yet) a loop; a
    third, differently-argued call in the same round must not tip it over
    into a false-positive warning.
    """
    provider = MagicMock()
    provider.chat_with_retry = AsyncMock(side_effect=[
        LLMResponse(content="", tool_calls=[
            ToolCallRequest(id="c1", name="read_file", arguments={"path": "/workspace/a.md"}),
            ToolCallRequest(id="c2", name="read_file", arguments={"path": "/workspace/a.md"}),
            ToolCallRequest(id="c3", name="read_file", arguments={"path": "/workspace/b.md"}),
        ]),
        LLMResponse(content="done", tool_calls=[]),
    ])
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value=ToolResult("ok", is_error=False))

    runner = AgentRunner()
    result = await runner.run(make_run_spec(
        provider,
        initial_messages=[],
        tools=tools,
        model="test-model",
        max_iterations=6,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    warnings = [
        m for m in result.messages
        if m.get("role") == "system" and "same tool call" in m.get("content", "")
    ]
    assert warnings == [], f"expected no loop warning, got: {warnings}"


@pytest.mark.asyncio
async def test_runner_rejects_leaked_tool_call_markup_after_max_iterations():
    """Reporter scenario 2026-08-11: a model asked to finalize with no tools
    offered (has_tool_calls is therefore always False) can still emit
    tool-call-shaped text instead of a real answer. That text must never
    become the final response the user sees -- it should fall back to the
    safe max-iterations template instead.
    """
    tool_call = ToolCallRequest(
        id="c1", name="read_file", arguments={"path": "/workspace/a.md"},
    )
    provider = MagicMock()
    provider.chat_with_retry = AsyncMock(side_effect=[
        # Both real iterations keep calling tools, so max_iterations is hit.
        LLMResponse(content="", tool_calls=[tool_call]),
        LLMResponse(content="", tool_calls=[tool_call]),
        # The finalize-with-no-tools retry: no structured tool_calls (none
        # were offered), but the content is leaked tool-call markup anyway.
        LLMResponse(
            content=(
                "<tool_call>\n<function=exec>\n<parameter=command>\n"
                'Remove-Item "C:\\temp\\file.vtt" -Force\n</parameter>\n'
                "</function>\n</tool_call>"
            ),
            tool_calls=[],
        ),
    ])
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value=ToolResult("ok", is_error=False))

    runner = AgentRunner()
    result = await runner.run(make_run_spec(
        provider,
        initial_messages=[],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert result.stop_reason == "max_iterations"
    assert result.final_content is not None
    assert "<tool_call" not in result.final_content, (
        f"leaked tool-call markup reached final_content: {result.final_content!r}"
    )
    assert "maximum number of tool call iterations" in result.final_content


@pytest.mark.asyncio
async def test_runner_still_uses_a_clean_finalize_response_after_max_iterations():
    """Companion to the leak-rejection test above: a genuinely clean
    finalize response (no tool calls, no leaked markup) must still be used
    as-is -- the new check should not reject legitimate answers.
    """
    tool_call = ToolCallRequest(
        id="c1", name="read_file", arguments={"path": "/workspace/a.md"},
    )
    provider = MagicMock()
    provider.chat_with_retry = AsyncMock(side_effect=[
        LLMResponse(content="", tool_calls=[tool_call]),
        LLMResponse(content="", tool_calls=[tool_call]),
        LLMResponse(content="Here's a summary of what I found so far.", tool_calls=[]),
    ])
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value=ToolResult("ok", is_error=False))

    runner = AgentRunner()
    result = await runner.run(make_run_spec(
        provider,
        initial_messages=[],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert result.stop_reason == "max_iterations"
    assert result.final_content == "Here's a summary of what I found so far."


@pytest.mark.asyncio
async def test_runner_rejects_leaked_tool_call_markup_on_normal_turn():
    """Dominant-path companion to the max-iterations leak tests above: most
    turns end via the normal single-response finalize path (no tool calls
    ever offered/made), not the max-iterations retry -- that path needs its
    own guard rather than relying on the retry-path check alone.
    """
    provider = MagicMock()
    provider.chat_with_retry = AsyncMock(side_effect=[
        LLMResponse(
            content=(
                "<tool_call>\n<function=exec>\n<parameter=command>\n"
                'Remove-Item "C:\\temp\\file.vtt" -Force\n</parameter>\n'
                "</function>\n</tool_call>"
            ),
            tool_calls=[],
        ),
    ])
    tools = MagicMock()
    tools.get_definitions.return_value = []

    runner = AgentRunner()
    result = await runner.run(make_run_spec(
        provider,
        initial_messages=[],
        tools=tools,
        model="test-model",
        max_iterations=5,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert result.stop_reason == "leaked_tool_call_markup"
    assert result.final_content is not None
    assert "<tool_call" not in result.final_content, (
        f"leaked tool-call markup reached final_content: {result.final_content!r}"
    )


@pytest.mark.asyncio
async def test_runner_still_uses_a_clean_response_on_normal_turn():
    """Companion negative case: a genuinely clean single-turn response (no
    tool calls, no leaked markup) must still be used as-is.
    """
    provider = MagicMock()
    provider.chat_with_retry = AsyncMock(side_effect=[
        LLMResponse(content="Here's the answer you asked for.", tool_calls=[]),
    ])
    tools = MagicMock()
    tools.get_definitions.return_value = []

    runner = AgentRunner()
    result = await runner.run(make_run_spec(
        provider,
        initial_messages=[],
        tools=tools,
        model="test-model",
        max_iterations=5,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert result.final_content == "Here's the answer you asked for."
