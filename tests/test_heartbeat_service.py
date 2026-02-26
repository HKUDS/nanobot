import asyncio
from pathlib import Path
from typing import Any

import pytest

from nanobot.heartbeat.service import HeartbeatService
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class StubProvider(LLMProvider):
    def __init__(self, response: LLMResponse):
        super().__init__()
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        self.calls.append({"messages": messages, "tools": tools, "model": model})
        return self.response

    def get_default_model(self) -> str:
        return "stub/default-model"


@pytest.mark.asyncio
async def test_decide_uses_configured_model(tmp_path: Path) -> None:
    provider = StubProvider(
        LLMResponse(
            content=None,
            tool_calls=[ToolCallRequest(id="tc_1", name="heartbeat", arguments={"action": "run", "tasks": "sync"})],
        )
    )
    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="anthropic/claude-3-5-haiku",
    )

    action, tasks = await service._decide("## Periodic Tasks\n\n- [ ] sync")

    assert action == "run"
    assert tasks == "sync"
    assert provider.calls[0]["model"] == "anthropic/claude-3-5-haiku"


@pytest.mark.asyncio
async def test_start_is_idempotent(tmp_path: Path) -> None:
    provider = StubProvider(LLMResponse(content=None))
    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="stub/heartbeat",
        interval_s=9999,
        enabled=True,
    )

    await service.start()
    first_task = service._task
    await service.start()

    assert service._task is first_task

    service.stop()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_trigger_now_executes_tasks_from_tool_call(tmp_path: Path) -> None:
    provider = StubProvider(
        LLMResponse(
            content=None,
            tool_calls=[ToolCallRequest(id="tc_1", name="heartbeat", arguments={"action": "run", "tasks": "report"})],
        )
    )
    (tmp_path / "HEARTBEAT.md").write_text("## Periodic Tasks\n\n- [ ] report", encoding="utf-8")

    captured: dict[str, str] = {}

    async def _on_execute(tasks: str) -> str:
        captured["tasks"] = tasks
        return "ok"

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="stub/heartbeat",
        on_execute=_on_execute,
        enabled=True,
    )

    result = await service.trigger_now()

    assert result == "ok"
    assert captured["tasks"] == "report"
