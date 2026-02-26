from pathlib import Path
from typing import Any

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class SequenceProvider(LLMProvider):
    def __init__(self, responses: list[LLMResponse]):
        super().__init__()
        self._responses = responses
        self.calls = 0

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> LLMResponse:
        if self.calls >= len(self._responses):
            raise AssertionError("chat called more times than prepared responses")
        response = self._responses[self.calls]
        self.calls += 1
        return response

    def get_default_model(self) -> str:
        return "dummy/test-model"


@pytest.mark.asyncio
async def test_run_agent_loop_returns_stashed_content_and_stops_after_empty_reply(tmp_path: Path) -> None:
    provider = SequenceProvider(
        responses=[
            LLMResponse(
                content="stashed final answer",
                tool_calls=[ToolCallRequest(id="tc_1", name="missing_tool", arguments={})],
            ),
            LLMResponse(content="", tool_calls=[]),
        ]
    )
    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path, max_iterations=8)

    final_content, finish_reason, tool_use_log = await loop._run_agent_loop(
        initial_messages=[{"role": "user", "content": "hello"}],
        on_progress=None,
    )

    assert final_content == "stashed final answer"
    assert finish_reason == "stop"
    assert provider.calls == 2
    assert tool_use_log
    assert tool_use_log[0][0] == "missing_tool"
