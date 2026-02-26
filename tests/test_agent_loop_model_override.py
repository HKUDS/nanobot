from pathlib import Path
from typing import Any

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider, LLMResponse


class NoopProvider(LLMProvider):
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        return LLMResponse(content="ok")

    def get_default_model(self) -> str:
        return "stub/default-model"


@pytest.mark.asyncio
async def test_process_direct_passes_model_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    loop = AgentLoop(bus=MessageBus(), provider=NoopProvider(), workspace=tmp_path)
    captured: dict[str, str | None] = {"model_override": None}

    async def _fake_process_message(
        msg: InboundMessage,
        session_key: str | None = None,
        on_progress: Any = None,
        model_override: str | None = None,
    ) -> OutboundMessage:
        captured["model_override"] = model_override
        return OutboundMessage(channel="cli", chat_id="direct", content="ok")

    monkeypatch.setattr(loop, "_process_message", _fake_process_message)

    result = await loop.process_direct(
        "run heartbeat tasks",
        session_key="heartbeat",
        channel="cli",
        chat_id="direct",
        model_override="openai/gpt-4o-mini",
    )

    assert result == "ok"
    assert captured["model_override"] == "openai/gpt-4o-mini"
