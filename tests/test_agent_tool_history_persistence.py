from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class FakeProvider(LLMProvider):
    def __init__(self) -> None:
        super().__init__(api_key="fake")
        self.calls = 0

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                content="I will inspect the file.",
                tool_calls=[
                    ToolCallRequest(
                        id="call_1",
                        name="read_file",
                        arguments={"path": "missing.txt"},
                    )
                ],
            )
        return LLMResponse(content="Done.")

    def get_default_model(self) -> str:
        return "fake/model"


@pytest.mark.asyncio
async def test_process_direct_persists_tool_messages(tmp_path: Path) -> None:
    bus = MessageBus()
    provider = FakeProvider()
    loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=tmp_path,
        max_iterations=4,
    )

    session_key = f"cli:test-tool-history-{uuid4().hex}"
    result = await loop.process_direct("check file", session_key=session_key)
    assert result == "Done."

    session = loop.sessions.get_or_create(session_key)
    roles = [m["role"] for m in session.messages]
    assert roles == ["assistant", "tool", "user", "assistant"]
    assert session.messages[0]["tool_calls"][0]["id"] == "call_1"
    assert session.messages[1]["tool_call_id"] == "call_1"
    assert session.messages[1]["name"] == "read_file"
