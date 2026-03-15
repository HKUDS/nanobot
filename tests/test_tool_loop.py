from __future__ import annotations

import pytest

from nanobot.agent.tool_loop import run_tool_loop
from nanobot.agent.tools.base import Tool, ToolResult
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.providers.base import LLMResponse, ToolCallRequest


class _DummyProvider:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)

    async def chat(self, **_kwargs) -> LLMResponse:
        return self._responses.pop(0)

    def get_default_model(self) -> str:
        return "openai/gpt-4.1"


class _EchoTool(Tool):
    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "echo"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {"text": {"type": "string"}}}

    async def execute(self, **kwargs):
        return ToolResult.ok(kwargs.get("text", ""))


@pytest.mark.asyncio
async def test_run_tool_loop_with_tool_call_then_final_response() -> None:
    provider = _DummyProvider(
        [
            LLMResponse(
                content="",
                tool_calls=[ToolCallRequest(id="tc1", name="echo", arguments={"text": "x"})],
            ),
            LLMResponse(content="done"),
        ]
    )
    registry = ToolRegistry()
    registry.register(_EchoTool())

    final, used, messages = await run_tool_loop(
        provider=provider,
        tools=registry,
        messages=[{"role": "user", "content": "go"}],
        model="openai/gpt-4.1",
        max_iterations=3,
    )

    assert final == "done"
    assert used == ["echo"]
    assert any(m.get("role") == "tool" for m in messages)


@pytest.mark.asyncio
async def test_run_tool_loop_exhaustion_summary_fallback_to_tool_snippets() -> None:
    class _NoSummaryProvider(_DummyProvider):
        async def chat(self, **_kwargs) -> LLMResponse:
            if not self._responses:
                raise RuntimeError("no summary")
            return self._responses.pop(0)

    provider = _NoSummaryProvider(
        [
            LLMResponse(
                content="",
                tool_calls=[ToolCallRequest(id="tc1", name="echo", arguments={"text": "A"})],
            )
        ]
    )
    registry = ToolRegistry()
    registry.register(_EchoTool())

    final, used, _messages = await run_tool_loop(
        provider=provider,
        tools=registry,
        messages=[{"role": "user", "content": "go"}],
        model="openai/gpt-4.1",
        max_iterations=1,
    )

    assert "A" in (final or "")
    assert used == ["echo"]
