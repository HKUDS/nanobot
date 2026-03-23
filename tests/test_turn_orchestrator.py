"""Failing tests for TurnOrchestrator (Task 5 — TDD).

These tests are written BEFORE TurnOrchestrator exists.  They will fail with
ModuleNotFoundError until Task 6 creates nanobot/agent/turn_orchestrator.py.

Covers:
- Basic run() returns TurnResult with correct fields
- No tool calls → tools_used is []
- Tool call → tools_used contains the tool name(s)
- TurnResult is frozen (FrozenInstanceError on assignment)
- Consecutive LLM errors are handled gracefully
- messages field of TurnResult reflects conversation history after the turn
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.turn_orchestrator import (
    TurnOrchestrator,
    TurnResult,
    TurnState,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_minimal_mocks() -> dict[str, Any]:
    """Return a dict of minimal mocks for TurnOrchestrator constructor.

    Async methods that the orchestrator ``await``s must be ``AsyncMock``
    instances; plain ``MagicMock`` is not awaitable and would raise
    ``TypeError`` at runtime.
    """
    # Context mock: add_assistant_message must return a list (messages)
    context = MagicMock()
    context.add_assistant_message = MagicMock(
        side_effect=lambda msgs, content, *a, **kw: (
            msgs + [{"role": "assistant", "content": content or ""}]
        )
    )
    context.add_tool_result = MagicMock(
        side_effect=lambda msgs, tid, tname, result: (
            msgs + [{"role": "tool", "tool_call_id": tid, "content": result}]
        )
    )

    # Verifier mock: verify is async and returns (content, messages)
    verifier = MagicMock()
    verifier.verify = AsyncMock(
        side_effect=lambda user_text, content, messages: (content, messages)
    )

    # Config mock: use a simple namespace with numeric defaults
    config = MagicMock()
    config.context_window_tokens = 0
    config.max_session_wall_time_seconds = 0
    config.planning_enabled = False
    config.max_iterations = 10

    # Tool executor mock
    tool_executor = MagicMock()
    tool_executor.get_definitions = MagicMock(return_value=[])

    return {
        "llm_caller": MagicMock(),
        "tool_executor": tool_executor,
        "verifier": verifier,
        "dispatcher": MagicMock(),
        "delegation_advisor": MagicMock(),
        "config": config,
        "prompts": MagicMock(),
        "context": context,
    }


def _make_turn_state(text: str = "Hello") -> TurnState:
    return TurnState(
        messages=[{"role": "user", "content": text}],
        user_text=text,
    )


# ---------------------------------------------------------------------------
# Test 1: run() returns a TurnResult with correct field types
# ---------------------------------------------------------------------------


class TestRunReturnsTurnResult:
    """TurnOrchestrator.run() must return a TurnResult instance."""

    async def test_run_returns_turn_result(self) -> None:
        """run() returns a TurnResult with content, tools_used, and messages."""
        mocks = _make_minimal_mocks()

        # Simulate a simple LLM response with no tool calls
        llm_caller = AsyncMock()
        llm_caller.call = AsyncMock(return_value=("Hello back!", []))
        mocks["llm_caller"] = llm_caller

        orchestrator = TurnOrchestrator(**mocks)
        state = _make_turn_state("Hi")

        result = await orchestrator.run(state, on_progress=None)

        assert isinstance(result, TurnResult)
        assert isinstance(result.content, str)
        assert isinstance(result.tools_used, list)
        assert isinstance(result.messages, list)


# ---------------------------------------------------------------------------
# Test 2: No tool calls → tools_used is []
# ---------------------------------------------------------------------------


class TestRunNoTools:
    """When the LLM produces no tool calls, tools_used must be empty."""

    async def test_run_no_tools_returns_empty_tools_used(self) -> None:
        mocks = _make_minimal_mocks()

        llm_caller = AsyncMock()
        llm_caller.call = AsyncMock(return_value=("Direct answer, no tools needed.", []))
        mocks["llm_caller"] = llm_caller

        orchestrator = TurnOrchestrator(**mocks)
        state = _make_turn_state("What is 2+2?")

        result = await orchestrator.run(state, on_progress=None)

        assert result.tools_used == []


# ---------------------------------------------------------------------------
# Test 3: Tool call → tools_used contains the tool name(s)
# ---------------------------------------------------------------------------


class TestRunWithToolCall:
    """When a tool is invoked, its name must appear in tools_used."""

    async def test_run_with_tool_call_returns_tool_names(self) -> None:
        mocks = _make_minimal_mocks()

        # First LLM response triggers a tool call; second returns a final answer
        tool_call = MagicMock()
        tool_call.name = "read_file"
        tool_call.id = "call_1"
        tool_call.arguments = {"path": "/tmp/test.txt"}

        call_count = 0

        async def fake_call(*args: Any, **kwargs: Any) -> tuple[str | None, list[Any]]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return (None, [tool_call])
            return ("File contents: hello", [])

        llm_caller = AsyncMock()
        llm_caller.call = fake_call
        mocks["llm_caller"] = llm_caller

        # Tool executor returns a successful result
        tool_result = MagicMock()
        tool_result.success = True
        tool_result.to_llm_string = MagicMock(return_value="hello")
        tool_executor = MagicMock()
        tool_executor.execute_batch = AsyncMock(return_value=[tool_result])
        tool_executor.get_definitions = MagicMock(return_value=[])
        mocks["tool_executor"] = tool_executor

        orchestrator = TurnOrchestrator(**mocks)
        state = _make_turn_state("Read the file")

        result = await orchestrator.run(state, on_progress=None)

        assert "read_file" in result.tools_used


# ---------------------------------------------------------------------------
# Test 4: TurnResult is frozen
# ---------------------------------------------------------------------------


class TestTurnResultIsFrozen:
    """TurnResult must be a frozen dataclass; assignment must raise FrozenInstanceError."""

    def test_turn_result_is_frozen(self) -> None:
        from dataclasses import FrozenInstanceError

        result = TurnResult(
            content="hello",
            tools_used=[],
            messages=[{"role": "assistant", "content": "hello"}],
        )

        with pytest.raises(FrozenInstanceError):
            result.content = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Test 5: Consecutive LLM errors are handled gracefully
# ---------------------------------------------------------------------------


class TestConsecutiveErrors:
    """Multiple consecutive LLM errors must not hang; should resolve or raise cleanly."""

    async def test_run_consecutive_errors_handled(self) -> None:
        from nanobot.errors import NanobotError

        mocks = _make_minimal_mocks()

        call_count = 0

        async def always_error(*args: Any, **kwargs: Any) -> tuple[str, list[Any]]:
            nonlocal call_count
            call_count += 1
            return ("LLM error occurred", [])

        # Simulate the LLM reporting errors by returning finish_reason="error"-style
        # responses.  The orchestrator must not loop forever.
        llm_caller = AsyncMock()
        llm_caller.call = always_error
        mocks["llm_caller"] = llm_caller

        orchestrator = TurnOrchestrator(**mocks)
        state = _make_turn_state("trigger errors")

        # Acceptable outcomes: returns a TurnResult OR raises a NanobotError.
        # Must NOT hang indefinitely.
        try:
            result = await orchestrator.run(state, on_progress=None)
            # If it returns, it must be a valid TurnResult
            assert isinstance(result, TurnResult)
        except NanobotError:
            pass  # graceful failure via typed exception is also acceptable


# ---------------------------------------------------------------------------
# Test 6: messages field reflects conversation history after the turn
# ---------------------------------------------------------------------------


class TestRunPassesTurnStateMessages:
    """The returned TurnResult.messages should include history after the turn."""

    async def test_run_passes_turn_state_messages(self) -> None:
        mocks = _make_minimal_mocks()

        llm_caller = AsyncMock()
        llm_caller.call = AsyncMock(return_value=("All done!", []))
        mocks["llm_caller"] = llm_caller

        orchestrator = TurnOrchestrator(**mocks)
        initial_messages = [{"role": "user", "content": "Remember this"}]
        state = TurnState(messages=initial_messages, user_text="Remember this")

        result = await orchestrator.run(state, on_progress=None)

        # The returned messages list must include at least the original user message
        assert any(
            m.get("role") == "user" and "Remember this" in m.get("content", "")
            for m in result.messages
        )
        # And must also contain the assistant's reply
        assert any(m.get("role") == "assistant" for m in result.messages)
