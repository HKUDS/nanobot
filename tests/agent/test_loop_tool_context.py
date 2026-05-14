from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse, ToolCallRequest
from nanobot.agent.tools.context import RequestContext


class _ContextRecordingTool:
    name = "cron"
    concurrency_safe = False

    def __init__(self) -> None:
        self.contexts: list[dict] = []

    def set_context(self, ctx: RequestContext) -> None:
        self.contexts.append({
            "channel": ctx.channel,
            "chat_id": ctx.chat_id,
            "metadata": ctx.metadata,
            "session_key": ctx.session_key,
        })

    async def execute(self, **_kwargs) -> str:
        return "created"


class _Tools:
    def __init__(self, tool: _ContextRecordingTool) -> None:
        self.tool = tool

    @property
    def tool_names(self) -> list[str]:
        return ["cron"]

    def get(self, name: str):
        return self.tool if name == "cron" else None

    def get_definitions(self) -> list:
        return []

    def prepare_call(self, name: str, arguments: dict):
        return (self.tool, arguments, None) if name == "cron" else (None, arguments, None)


@pytest.mark.asyncio
async def test_loop_hook_preserves_metadata_when_resetting_tool_context(tmp_path: Path) -> None:
    provider = MagicMock()
    calls = {"n": 0}

    async def chat_with_retry(**_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return LLMResponse(
                content=None,
                tool_calls=[ToolCallRequest(id="call_1", name="cron", arguments={"action": "add"})],
            )
        return LLMResponse(content="done", tool_calls=[])

    provider.chat_with_retry = chat_with_retry
    provider.get_default_model.return_value = "test-model"

    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )
    cron = _ContextRecordingTool()
    loop.tools = _Tools(cron)

    metadata = {"slack": {"thread_ts": "111.222", "channel_type": "channel"}}
    await loop._run_agent_loop(
        [],
        channel="slack",
        chat_id="C123",
        metadata=metadata,
        session_key="slack:C123:111.222",
    )

    assert cron.contexts[-1] == {
        "channel": "slack",
        "chat_id": "C123",
        "metadata": metadata,
        "session_key": "slack:C123:111.222",
    }
