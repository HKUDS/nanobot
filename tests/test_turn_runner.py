"""Contract tests for TurnRunner — the simplified tool-use loop.

Verifies behavioral guarantees: loop termination, working memory logging,
guardrail integration, and self-check gating.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from nanobot.agent.turn_guardrails import Intervention
from nanobot.agent.turn_runner import TurnRunner
from nanobot.agent.turn_types import TurnState
from nanobot.providers.base import LLMResponse, ToolCallRequest
from nanobot.tools.base import ToolResult

# ---------------------------------------------------------------------------
# Test fixtures / helpers
# ---------------------------------------------------------------------------


def _make_tool_call(name: str = "exec", args: dict[str, Any] | None = None) -> ToolCallRequest:
    return ToolCallRequest(id=f"call_{name}_1", name=name, arguments=args or {"cmd": "ls"})


def _text_response(content: str) -> LLMResponse:
    return LLMResponse(content=content, tool_calls=[], finish_reason="stop", usage={})


def _tool_response(tool_calls: list[ToolCallRequest], content: str | None = None) -> LLMResponse:
    return LLMResponse(content=content, tool_calls=tool_calls, finish_reason="stop", usage={})


class ScriptedCaller:
    """Async callable that returns predetermined LLMResponse objects."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = iter(responses)
        self.model = "test-model"
        self.max_tokens = 4096
        self.call_count = 0

    async def call(
        self,
        messages: list[dict],
        tools: list[dict[str, Any]] | None,
        on_progress: Any,
        **kwargs: Any,
    ) -> LLMResponse:
        self.call_count += 1
        return next(self._responses)


class FakeExecutor:
    """Minimal ToolExecutor stand-in that always returns success."""

    def __init__(self, results: list[ToolResult] | None = None) -> None:
        self._results = results

    async def execute_batch(self, tool_calls: list[ToolCallRequest]) -> list[ToolResult]:
        if self._results is not None:
            return self._results[: len(tool_calls)]
        return [ToolResult.ok("result data") for _ in tool_calls]

    def get_definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "exec",
                    "description": "Run a command",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]


class FakeGuardrails:
    """GuardrailChain stand-in with optional fixed Intervention."""

    def __init__(self, intervention: Intervention | None = None) -> None:
        self._intervention = intervention

    def check(
        self,
        all_attempts: list[Any],
        latest_results: list[Any],
        *,
        iteration: int = 0,
    ) -> Intervention | None:
        return self._intervention


class FakeContext:
    """Minimal ContextBuilder stand-in."""

    def add_assistant_message(
        self,
        messages: list[dict[str, Any]],
        content: str | None,
        tool_calls: list[dict[str, Any]] | None = None,
        reasoning_content: str | None = None,
    ) -> list[dict[str, Any]]:
        msg: dict[str, Any] = {"role": "assistant", "content": content}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        return messages + [msg]

    def add_tool_result(
        self,
        messages: list[dict[str, Any]],
        tool_call_id: str,
        tool_name: str,
        result: str,
    ) -> list[dict[str, Any]]:
        return messages + [{"role": "tool", "tool_call_id": tool_call_id, "content": result}]


def _make_config(
    max_iterations: int = 10,
    context_window_tokens: int = 0,
    max_session_wall_time_seconds: int = 0,
    verification_mode: str = "off",
) -> SimpleNamespace:
    return SimpleNamespace(
        max_iterations=max_iterations,
        context_window_tokens=context_window_tokens,
        max_session_wall_time_seconds=max_session_wall_time_seconds,
        verification_mode=verification_mode,
        summary_model=None,
        tool_result_context_tokens=2000,
    )


def _make_state(messages: list[dict[str, Any]] | None = None) -> TurnState:
    return TurnState(
        messages=messages or [{"role": "user", "content": "hello"}],
        user_text="hello",
    )


def _build_runner(
    caller: ScriptedCaller,
    executor: FakeExecutor | None = None,
    guardrails: FakeGuardrails | None = None,
    config: SimpleNamespace | None = None,
    provider: Any = None,
) -> TurnRunner:
    return TurnRunner(
        llm_caller=caller,  # type: ignore[arg-type]
        tool_executor=executor or FakeExecutor(),  # type: ignore[arg-type]
        guardrails=guardrails or FakeGuardrails(),  # type: ignore[arg-type]
        context=FakeContext(),  # type: ignore[arg-type]
        config=config or _make_config(),  # type: ignore[arg-type]
        provider=provider,
    )


# ---------------------------------------------------------------------------
# TestTurnRunnerLoop
# ---------------------------------------------------------------------------


class TestTurnRunnerLoop:
    """Core loop termination and iteration behavior."""

    @pytest.mark.asyncio
    async def test_text_response_breaks_loop(self) -> None:
        """LLM returns text (no tool calls) => loop exits with that content."""
        caller = ScriptedCaller([_text_response("Final answer")])
        runner = _build_runner(caller)
        state = _make_state()

        result = await runner.run(state, on_progress=None)

        assert result.content == "Final answer"
        assert result.tools_used == []
        assert caller.call_count == 1

    @pytest.mark.asyncio
    async def test_tool_calls_continue_loop(self) -> None:
        """LLM returns tool calls first, then text => both iterations run."""
        tc = _make_tool_call("exec")
        caller = ScriptedCaller(
            [
                _tool_response([tc]),
                _text_response("Done after tools"),
            ]
        )
        runner = _build_runner(caller)
        state = _make_state()

        result = await runner.run(state, on_progress=None)

        assert result.content == "Done after tools"
        assert "exec" in result.tools_used
        assert caller.call_count == 2

    @pytest.mark.asyncio
    async def test_max_iterations_terminates(self) -> None:
        """LLM always returns tool calls => loop stops at max_iterations."""
        tc = _make_tool_call("exec")
        # Provide more responses than max_iterations to avoid StopIteration
        responses = [_tool_response([tc]) for _ in range(5)]
        caller = ScriptedCaller(responses)
        config = _make_config(max_iterations=3)
        runner = _build_runner(caller, config=config)
        state = _make_state()

        result = await runner.run(state, on_progress=None)

        assert "maximum number of tool call iterations" in result.content
        assert caller.call_count == 3

    @pytest.mark.asyncio
    async def test_empty_response_triggers_final_nudge(self) -> None:
        """LLM returns tool calls, then empty response => nudge injected, loop continues."""
        tc = _make_tool_call("exec")
        caller = ScriptedCaller(
            [
                _tool_response([tc]),  # iteration 1: tool call
                _text_response(None),  # iteration 2: empty => nudge
                _text_response("Here it is"),  # iteration 3: final answer
            ]
        )
        runner = _build_runner(caller)
        state = _make_state()

        result = await runner.run(state, on_progress=None)

        assert result.content == "Here it is"
        assert caller.call_count == 3
        # Verify the nudge message was injected
        nudge_msgs = [
            m
            for m in state.messages
            if m.get("role") == "system" and "final answer" in m.get("content", "").lower()
        ]
        assert len(nudge_msgs) >= 1


# ---------------------------------------------------------------------------
# TestWorkingMemory
# ---------------------------------------------------------------------------


class TestWorkingMemory:
    """ToolAttempt working memory logging."""

    @pytest.mark.asyncio
    async def test_tool_attempts_logged(self) -> None:
        """One tool call => one ToolAttempt in state.tool_results_log."""
        tc = _make_tool_call("exec", {"cmd": "pwd"})
        caller = ScriptedCaller(
            [
                _tool_response([tc]),
                _text_response("done"),
            ]
        )
        runner = _build_runner(caller)
        state = _make_state()

        await runner.run(state, on_progress=None)

        assert len(state.tool_results_log) == 1
        attempt = state.tool_results_log[0]
        assert attempt.tool_name == "exec"
        assert attempt.success is True
        assert attempt.arguments == {"cmd": "pwd"}
        assert attempt.iteration == 1

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_all_logged(self) -> None:
        """3 tool calls in one batch => 3 ToolAttempts logged."""
        tc1 = ToolCallRequest(id="c1", name="exec", arguments={"cmd": "ls"})
        tc2 = ToolCallRequest(id="c2", name="exec", arguments={"cmd": "pwd"})
        tc3 = ToolCallRequest(id="c3", name="exec", arguments={"cmd": "date"})
        caller = ScriptedCaller(
            [
                _tool_response([tc1, tc2, tc3]),
                _text_response("all done"),
            ]
        )
        executor = FakeExecutor(
            results=[
                ToolResult.ok("out1"),
                ToolResult.ok("out2"),
                ToolResult.ok("out3"),
            ]
        )
        runner = _build_runner(caller, executor=executor)
        state = _make_state()

        await runner.run(state, on_progress=None)

        assert len(state.tool_results_log) == 3
        names = [a.tool_name for a in state.tool_results_log]
        assert names == ["exec", "exec", "exec"]


# ---------------------------------------------------------------------------
# TestGuardrailIntegration
# ---------------------------------------------------------------------------


class TestGuardrailIntegration:
    """Guardrail checkpoint behavior after tool execution."""

    @pytest.mark.asyncio
    async def test_guardrail_intervention_injected(self) -> None:
        """GuardrailChain returns Intervention => system message injected."""
        intervention = Intervention(
            source="test_guard",
            message="Stop repeating yourself.",
            severity="directive",
        )
        tc = _make_tool_call("exec")
        caller = ScriptedCaller(
            [
                _tool_response([tc]),
                _text_response("ok"),
            ]
        )
        guardrails = FakeGuardrails(intervention=intervention)
        runner = _build_runner(caller, guardrails=guardrails)
        state = _make_state()

        await runner.run(state, on_progress=None)

        system_msgs = [
            m
            for m in state.messages
            if m.get("role") == "system" and m.get("content") == "Stop repeating yourself."
        ]
        assert len(system_msgs) >= 1

    @pytest.mark.asyncio
    async def test_guardrail_activation_recorded(self) -> None:
        """GuardrailChain returns Intervention => entry in guardrail_activations."""
        intervention = Intervention(
            source="test_guard",
            message="Change strategy.",
            severity="override",
        )
        tc = _make_tool_call("exec")
        caller = ScriptedCaller(
            [
                _tool_response([tc]),
                _text_response("ok"),
            ]
        )
        guardrails = FakeGuardrails(intervention=intervention)
        runner = _build_runner(caller, guardrails=guardrails)
        state = _make_state()

        await runner.run(state, on_progress=None)

        assert len(state.guardrail_activations) >= 1
        activation = state.guardrail_activations[0]
        assert activation["source"] == "test_guard"
        assert activation["severity"] == "override"
        assert activation["message"] == "Change strategy."

    @pytest.mark.asyncio
    async def test_no_guardrail_no_injection(self) -> None:
        """GuardrailChain returns None => no extra system messages from guardrails."""
        tc = _make_tool_call("exec")
        caller = ScriptedCaller(
            [
                _tool_response([tc]),
                _text_response("done"),
            ]
        )
        guardrails = FakeGuardrails(intervention=None)
        runner = _build_runner(caller, guardrails=guardrails)
        state = _make_state()

        await runner.run(state, on_progress=None)

        assert len(state.guardrail_activations) == 0


# ---------------------------------------------------------------------------
# TestSelfCheck
# ---------------------------------------------------------------------------


class TestSelfCheck:
    """Structured self-check gating behavior."""

    @pytest.mark.asyncio
    async def test_structured_self_check_enabled(self) -> None:
        """verification_mode='structured' => extra LLM call for self-check."""
        caller = ScriptedCaller([_text_response("My answer")])
        provider = AsyncMock()
        provider.chat = AsyncMock(return_value=LLMResponse(content="Revised answer", usage={}))
        config = _make_config(verification_mode="structured")
        runner = _build_runner(caller, config=config, provider=provider)
        state = _make_state()

        with patch("nanobot.context.prompt_loader.prompts") as mock_prompts:
            mock_prompts.get.return_value = "Check your answer carefully."
            result = await runner.run(state, on_progress=None)

        assert result.content == "Revised answer"
        assert provider.chat.call_count == 1
        assert result.llm_calls == 2  # 1 main + 1 self-check

    @pytest.mark.asyncio
    async def test_self_check_disabled_by_default(self) -> None:
        """Default config (verification_mode='off') => no self-check call."""
        caller = ScriptedCaller([_text_response("My answer")])
        provider = AsyncMock()
        config = _make_config(verification_mode="off")
        runner = _build_runner(caller, config=config, provider=provider)
        state = _make_state()

        result = await runner.run(state, on_progress=None)

        assert result.content == "My answer"
        assert provider.chat.call_count == 0
        assert result.llm_calls == 1
