"""Tests for SuspendTurn: a tool ending the turn for an async/human-in-the-loop
continuation, without re-invoking the model or publishing a response."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nanobot.agent.runner import AgentRunner, AgentRunSpec
from nanobot.agent.tools.base import SuspendTurn, Tool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMResponse, ToolCallRequest

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


class _SuspendingTool(Tool):
    def __init__(self, name: str = "needs_approval", content: str = "Approval requested; awaiting user."):
        self._name = name
        self._content = content
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._name

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **kwargs) -> SuspendTurn:
        self.calls += 1
        return SuspendTurn(self._content)


class _EchoTool(Tool):
    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "echo"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **kwargs) -> str:
        return "ok"


def _tool_message(result, tool_call_id: str) -> dict:
    return [
        msg for msg in result.messages
        if msg.get("role") == "tool" and msg.get("tool_call_id") == tool_call_id
    ][0]


def _spec(tools: ToolRegistry, *, user: str = "go") -> AgentRunSpec:
    return AgentRunSpec(
        initial_messages=[{"role": "user", "content": user}],
        tools=tools,
        model="test-model",
        max_iterations=5,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    )


@pytest.mark.asyncio
async def test_suspend_ends_turn_without_a_second_model_call():
    """The defining behavior: after a tool suspends, the model is never called
    again, so it cannot emit a stray narration; the turn ends with no response."""
    provider = MagicMock()
    calls = {"n": 0}

    async def chat_with_retry(*, messages, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return LLMResponse(
                content="",
                tool_calls=[ToolCallRequest(id="call_1", name="needs_approval", arguments={})],
                finish_reason="tool_calls",
                usage={},
            )
        # A second model call is exactly the "I've requested approval, waiting…"
        # narration this feature exists to prevent.
        raise AssertionError("model must not be re-invoked after a suspended turn")

    provider.chat_with_retry = chat_with_retry
    tools = ToolRegistry()
    tool = _SuspendingTool()
    tools.register(tool)

    result = await AgentRunner(provider).run(_spec(tools, user="send an email"))

    assert calls["n"] == 1
    assert tool.calls == 1
    assert result.stop_reason == "suspended"
    # Nothing to publish to the user.
    assert result.final_content is None
    # The tool_call stays answered in history, so the resuming turn is valid.
    assert _tool_message(result, "call_1")["content"] == "Approval requested; awaiting user."
    # No synthesized final assistant message was appended.
    assert not [
        m for m in result.messages
        if m.get("role") == "assistant" and not m.get("tool_calls")
    ]


@pytest.mark.asyncio
async def test_all_suspended_batch_records_every_result_and_ends_turn():
    """When EVERY tool in a fanned-out batch suspends (e.g. one grouped approval
    covering multiple services), all results are recorded and the turn ends."""
    provider = MagicMock()
    calls = {"n": 0}

    async def chat_with_retry(*, messages, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(id="a", name="needs_approval", arguments={}),
                    ToolCallRequest(id="b", name="needs_approval_2", arguments={}),
                ],
                finish_reason="tool_calls",
                usage={},
            )
        raise AssertionError("model must not be re-invoked when the whole batch suspended")

    provider.chat_with_retry = chat_with_retry
    tools = ToolRegistry()
    tools.register(_SuspendingTool("needs_approval", "Approval A pending."))
    tools.register(_SuspendingTool("needs_approval_2", "Approval B pending."))

    result = await AgentRunner(provider).run(_spec(tools))

    assert calls["n"] == 1
    assert result.stop_reason == "suspended"
    assert result.final_content is None
    assert _tool_message(result, "a")["content"] == "Approval A pending."
    assert _tool_message(result, "b")["content"] == "Approval B pending."


@pytest.mark.asyncio
async def test_mixed_batch_continues_and_responds_about_completed_tools():
    """A MIXED batch (one normal result + one SuspendTurn) does NOT end the turn:
    the model is called again to respond using the completed result, while the
    suspended tool's placeholder is recorded and it defers/resumes later."""
    provider = MagicMock()
    calls = {"n": 0}

    async def chat_with_retry(*, messages, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(id="A", name="echo", arguments={}),            # normal
                    ToolCallRequest(id="B", name="needs_approval", arguments={}),   # suspends
                ],
                finish_reason="tool_calls",
                usage={},
            )
        return LLMResponse(content="Here is the calendar.", tool_calls=[], usage={})

    provider.chat_with_retry = chat_with_retry
    tools = ToolRegistry()
    tools.register(_EchoTool())
    tools.register(_SuspendingTool("needs_approval", "Approval requested; handled separately."))

    result = await AgentRunner(provider).run(_spec(tools))

    assert calls["n"] == 2                     # turn CONTINUED: model was re-invoked
    assert result.stop_reason == "completed"   # not "suspended"
    assert result.final_content == "Here is the calendar."
    # Both results are in history: the completed one and the suspended placeholder.
    assert _tool_message(result, "A")["content"] == "ok"
    assert _tool_message(result, "B")["content"] == "Approval requested; handled separately."


@pytest.mark.asyncio
async def test_normal_tool_result_still_continues_the_turn():
    """Regression: a non-SuspendTurn result must keep the loop going to a final
    model response (the suspend check must not short-circuit normal tool use)."""
    provider = MagicMock()
    calls = {"n": 0}

    async def chat_with_retry(*, messages, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return LLMResponse(
                content="",
                tool_calls=[ToolCallRequest(id="call_1", name="echo", arguments={})],
                finish_reason="tool_calls",
                usage={},
            )
        return LLMResponse(content="done", tool_calls=[], usage={})

    provider.chat_with_retry = chat_with_retry
    tools = ToolRegistry()
    tools.register(_EchoTool())

    result = await AgentRunner(provider).run(_spec(tools))

    assert calls["n"] == 2
    assert result.stop_reason == "completed"
    assert result.final_content == "done"


def test_normalize_tool_result_records_suspend_placeholder():
    runner = AgentRunner(MagicMock())
    spec = AgentRunSpec(
        initial_messages=[],
        tools=ToolRegistry(),
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    )
    out = runner._normalize_tool_result(
        spec, "call_1", "needs_approval", SuspendTurn("Approval requested; awaiting user."),
    )
    assert out == "Approval requested; awaiting user."
