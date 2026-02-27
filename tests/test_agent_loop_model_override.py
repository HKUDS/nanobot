from pathlib import Path
from typing import Any

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.session.manager import Session


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


class ConsolidationCaptureProvider(LLMProvider):
    def __init__(self) -> None:
        super().__init__()
        self.called_models: list[str | None] = []

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        self.called_models.append(model)
        return LLMResponse(
            content='{"history_entry":"[2026-02-26 10:00] summary","memory_update":"# Memory\\n- test"}'
        )

    def get_default_model(self) -> str:
        return "stub/default-model"


class MainProviderNoUse(LLMProvider):
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        raise AssertionError("Main provider should not be used for consolidation")

    def get_default_model(self) -> str:
        return "stub/default-model"


class OverrideProvider(LLMProvider):
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> LLMResponse:
        return LLMResponse(content="override-ok")

    def get_default_model(self) -> str:
        return "stub/default-model"


@pytest.mark.asyncio
async def test_process_direct_passes_model_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    loop = AgentLoop(bus=MessageBus(), provider=NoopProvider(), workspace=tmp_path)
    captured: dict[str, Any] = {"model_override": None, "provider_override": None}

    async def _fake_process_message(
        msg: InboundMessage,
        session_key: str | None = None,
        on_progress: Any = None,
        model_override: str | None = None,
        provider_override: LLMProvider | None = None,
    ) -> OutboundMessage:
        captured["model_override"] = model_override
        captured["provider_override"] = provider_override
        return OutboundMessage(channel="cli", chat_id="direct", content="ok")

    monkeypatch.setattr(loop, "_process_message", _fake_process_message)
    provider_override = OverrideProvider()

    result = await loop.process_direct(
        "run heartbeat tasks",
        session_key="heartbeat",
        channel="cli",
        chat_id="direct",
        model_override="openai/gpt-4o-mini",
        provider_override=provider_override,
    )

    assert result == "ok"
    assert captured["model_override"] == "openai/gpt-4o-mini"
    assert captured["provider_override"] is provider_override


@pytest.mark.asyncio
async def test_run_agent_loop_uses_provider_override(tmp_path: Path) -> None:
    loop = AgentLoop(
        bus=MessageBus(),
        provider=MainProviderNoUse(),
        workspace=tmp_path,
        model="main/model",
    )
    loop.tools.get_definitions = lambda: []  # type: ignore[method-assign]

    final_content, _, _ = await loop._run_agent_loop(
        [{"role": "user", "content": "ping"}],
        provider_override=OverrideProvider(),
        model_override="override/model",
    )

    assert final_content == "override-ok"


@pytest.mark.asyncio
async def test_consolidation_uses_dedicated_model_when_configured(tmp_path: Path) -> None:
    provider = ConsolidationCaptureProvider()
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="main/model",
        memory_window=4,
        memory_consolidation_model="summary/model",
    )
    session = Session(key="test:dedicated-model")
    for i in range(6):
        session.add_message("user", f"msg {i}")

    await loop._consolidate_memory(session)

    assert provider.called_models[-1] == "summary/model"


@pytest.mark.asyncio
async def test_consolidation_falls_back_to_main_model(tmp_path: Path) -> None:
    provider = ConsolidationCaptureProvider()
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="main/model",
        memory_window=4,
        memory_consolidation_model="",
    )
    session = Session(key="test:fallback-model")
    for i in range(6):
        session.add_message("user", f"msg {i}")

    await loop._consolidate_memory(session)

    assert provider.called_models[-1] == "main/model"


@pytest.mark.asyncio
async def test_consolidation_uses_dedicated_provider_when_given(tmp_path: Path) -> None:
    consolidation_provider = ConsolidationCaptureProvider()
    loop = AgentLoop(
        bus=MessageBus(),
        provider=MainProviderNoUse(),
        memory_consolidation_provider=consolidation_provider,
        workspace=tmp_path,
        model="main/model",
        memory_window=4,
        memory_consolidation_model="summary/model",
    )
    session = Session(key="test:dedicated-provider")
    for i in range(6):
        session.add_message("user", f"msg {i}")

    await loop._consolidate_memory(session)

    assert consolidation_provider.called_models[-1] == "summary/model"
