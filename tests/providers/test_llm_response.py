"""Regression tests for ``LLMResponse.should_execute_tools`` (#3220).

The agent used to execute tool calls whenever ``has_tool_calls`` was true, regardless
of ``finish_reason``. Non-compliant API gateways that inject empty / bogus tool calls
under ``refusal`` / ``content_filter`` / ``error`` pushed the agent into a tight loop
until ``max_iterations`` fired. ``should_execute_tools`` is the single guard that
every tool-execution site now funnels through.
"""

from __future__ import annotations

import pytest

from nanobot.providers.base import LLMResponse, ToolCallRequest


def _response(finish_reason: str, *, with_tool_call: bool = True) -> LLMResponse:
    tool_calls = (
        [ToolCallRequest(id="call_1", name="list_dir", arguments={"path": "."})]
        if with_tool_call
        else []
    )
    return LLMResponse(content=None, tool_calls=tool_calls, finish_reason=finish_reason)


class TestShouldExecuteTools:
    def test_no_tool_calls_never_executes(self) -> None:
        # No tool calls present -> guard must reject regardless of finish_reason.
        for reason in ("tool_calls", "stop", "length", "error", "refusal", "content_filter"):
            resp = _response(reason, with_tool_call=False)
            assert resp.should_execute_tools is False, f"rejected for finish_reason={reason!r}"

    def test_tool_calls_with_tool_calls_reason_executes(self) -> None:
        # The canonical case: provider explicitly signals tool intent.
        resp = _response("tool_calls")
        assert resp.has_tool_calls is True
        assert resp.should_execute_tools is True

    def test_tool_calls_with_stop_reason_executes(self) -> None:
        # Some compliant providers emit "stop" together with tool_calls; the
        # guard must accept this to avoid breaking real tool-calling flows.
        # See openai_compat_provider.py:~633,678 where ("tool_calls", "stop")
        # are both treated as terminal tool-call states.
        resp = _response("stop")
        assert resp.should_execute_tools is True

    @pytest.mark.parametrize(
        "anomalous_reason",
        ["refusal", "content_filter", "error", "length", "function_call", ""],
    )
    def test_tool_calls_under_anomalous_reason_blocked(self, anomalous_reason: str) -> None:
        # This is the #3220 bug: gateways injecting tool_calls under any of these
        # finish_reasons must not cause execution. Blocking here is what prevents
        # the infinite empty tool-call loop.
        resp = _response(anomalous_reason)
        assert resp.has_tool_calls is True
        assert resp.should_execute_tools is False
