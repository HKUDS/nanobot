from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import AgentConfig
from nanobot.config.schema import AgentRoleConfig
from nanobot.providers.base import LLMProvider, LLMResponse


class _ScriptedProvider(LLMProvider):
    def __init__(self, responses: list[LLMResponse]):
        super().__init__()
        self._responses = list(responses)
        self._idx = 0

    def get_default_model(self) -> str:
        return "test-model"

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        if self._idx >= len(self._responses):
            return LLMResponse(content="{}")
        out = self._responses[self._idx]
        self._idx += 1
        return out


def _make_loop(tmp_path: Path, provider: LLMProvider, verification_mode: str) -> AgentLoop:
    cfg = AgentConfig(
        workspace=str(tmp_path),
        model="test-model",
        memory_window=10,
        max_iterations=4,
        planning_enabled=False,
        verification_mode=verification_mode,
    )
    return AgentLoop(MessageBus(), provider, cfg)


@pytest.mark.asyncio
async def test_verify_answer_revise_and_parse_fallback(tmp_path: Path) -> None:
    provider = _ScriptedProvider(
        [
            LLMResponse(content='{"confidence": 2, "issues": ["unsupported claim"]}'),
            LLMResponse(content="revised answer"),
            LLMResponse(content="not-json"),
        ]
    )
    loop = _make_loop(tmp_path, provider, verification_mode="always")

    revised, msgs = await loop._verify_answer(
        "what changed?",
        "candidate",
        [{"role": "assistant", "content": "candidate"}],
    )
    assert revised == "revised answer"
    assert any(m.get("role") == "system" for m in msgs)

    kept, _ = await loop._verify_answer(
        "what changed?",
        "candidate",
        [{"role": "assistant", "content": "candidate"}],
    )
    assert kept == "candidate"


@pytest.mark.asyncio
async def test_verify_answer_on_uncertainty_skip(tmp_path: Path) -> None:
    provider = _ScriptedProvider([LLMResponse(content='{"confidence": 5, "issues": []}')])
    loop = _make_loop(tmp_path, provider, verification_mode="on_uncertainty")
    loop._should_force_verification = lambda _text: False  # type: ignore[method-assign]
    out, _ = await loop._verify_answer("hi", "candidate", [])
    assert out == "candidate"


@pytest.mark.asyncio
async def test_run_timeout_and_none_response_paths(tmp_path: Path) -> None:
    provider = _ScriptedProvider([])
    bus = MessageBus()
    cfg = AgentConfig(
        workspace=str(tmp_path),
        model="test-model",
        memory_window=10,
        max_iterations=2,
        planning_enabled=False,
        verification_mode="off",
        message_timeout=1,
    )
    loop = AgentLoop(bus, provider, cfg)
    loop._connect_mcp = lambda: asyncio.sleep(0)  # type: ignore[method-assign]

    async def _slow(_msg):
        await asyncio.sleep(1.2)
        return None

    loop._process_message = _slow  # type: ignore[method-assign]

    task = asyncio.create_task(loop.run())
    await bus.publish_inbound(
        InboundMessage(channel="cli", chat_id="c1", sender_id="u1", content="hello")
    )
    outbound = await asyncio.wait_for(bus.consume_outbound(), timeout=1.5)
    assert "ran out of time" in outbound.content.lower()

    loop.stop()
    await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_run_exception_path_publishes_user_friendly_error(tmp_path: Path) -> None:
    provider = _ScriptedProvider([])
    bus = MessageBus()
    cfg = AgentConfig(
        workspace=str(tmp_path),
        model="test-model",
        memory_window=10,
        max_iterations=2,
        planning_enabled=False,
        verification_mode="off",
    )
    loop = AgentLoop(bus, provider, cfg)
    loop._connect_mcp = lambda: asyncio.sleep(0)  # type: ignore[method-assign]

    async def _explode(_msg):
        raise RuntimeError("boom")

    loop._process_message = _explode  # type: ignore[method-assign]
    task = asyncio.create_task(loop.run())
    await bus.publish_inbound(
        InboundMessage(channel="cli", chat_id="c2", sender_id="u2", content="hello")
    )
    outbound = await asyncio.wait_for(bus.consume_outbound(), timeout=1.5)
    assert "error" in outbound.content.lower() or "sorry" in outbound.content.lower()

    loop.stop()
    await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_run_with_routing_low_confidence_and_none_response(tmp_path: Path) -> None:
    provider = _ScriptedProvider([])
    bus = MessageBus()
    cfg = AgentConfig(
        workspace=str(tmp_path),
        model="test-model",
        memory_window=10,
        max_iterations=2,
        planning_enabled=False,
        verification_mode="off",
    )
    loop = AgentLoop(bus, provider, cfg)
    loop._connect_mcp = lambda: asyncio.sleep(0)  # type: ignore[method-assign]

    default_role = AgentRoleConfig(name="general", description="general")
    loop._coordinator = type(
        "_Coord",
        (),
        {
            "classify": staticmethod(lambda _text: asyncio.sleep(0, result=("code", 0.1))),
            "route_direct": staticmethod(lambda _name: None),
            "registry": type("_Reg", (), {"get_default": staticmethod(lambda: default_role)})(),
        },
    )()
    loop._routing_config = type(
        "_Routing",
        (),
        {"confidence_threshold": 0.9, "default_role": "general", "enabled": True},
    )()

    role_calls = {"applied": 0, "reset": 0}
    loop._record_route_trace = lambda *a, **k: None  # type: ignore[method-assign]
    loop._apply_role_for_turn = lambda _r: role_calls.__setitem__("applied", role_calls["applied"] + 1)  # type: ignore[method-assign]
    loop._reset_role_after_turn = lambda: role_calls.__setitem__("reset", role_calls["reset"] + 1)  # type: ignore[method-assign]

    async def _none_response(_msg):
        return None

    loop._process_message = _none_response  # type: ignore[method-assign]

    task = asyncio.create_task(loop.run())
    await bus.publish_inbound(
        InboundMessage(channel="cli", chat_id="c3", sender_id="u3", content="route me")
    )
    out = await asyncio.wait_for(bus.consume_outbound(), timeout=1.5)
    assert out.content == ""
    assert role_calls["applied"] == 1
    assert role_calls["reset"] == 1

    loop.stop()
    await asyncio.wait_for(task, timeout=2.0)