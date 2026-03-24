"""Unit tests for ``nanobot.agent.agent_factory.build_agent``."""

from __future__ import annotations

from pathlib import Path

from nanobot.agent.agent_factory import build_agent
from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import AgentConfig, AgentRoleConfig
from nanobot.providers.base import LLMResponse
from nanobot.tools.registry import ToolRegistry
from tests.helpers import ScriptedProvider


def _config(tmp_path: Path, **overrides: object) -> AgentConfig:
    """Build a minimal AgentConfig for factory tests."""
    defaults: dict[str, object] = dict(
        workspace=str(tmp_path),
        model="test-model",
        memory_window=10,
        max_iterations=5,
        planning_enabled=False,
        verification_mode="off",
    )
    defaults.update(overrides)
    return AgentConfig(**defaults)  # type: ignore[arg-type]


def _provider() -> ScriptedProvider:
    return ScriptedProvider([LLMResponse(content="ok")])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_returns_agent_loop(tmp_path: Path) -> None:
    """``build_agent`` returns an ``AgentLoop`` instance."""
    bus = MessageBus()
    provider = _provider()
    config = _config(tmp_path)

    loop = build_agent(bus, provider, config)

    assert isinstance(loop, AgentLoop)


def test_role_manager_wired(tmp_path: Path) -> None:
    """Post-construction wiring sets role_manager."""
    bus = MessageBus()
    provider = _provider()
    config = _config(tmp_path)

    loop = build_agent(bus, provider, config)

    assert loop._role_manager is not None


def test_injected_tool_registry(tmp_path: Path) -> None:
    """When a ``tool_registry`` is provided, the loop uses it."""
    bus = MessageBus()
    provider = _provider()
    config = _config(tmp_path)
    reg = ToolRegistry()

    loop = build_agent(bus, provider, config, tool_registry=reg)

    assert loop.tools._registry is reg


def test_memory_disabled(tmp_path: Path) -> None:
    """Config with ``memory_enabled=False`` zeroes out memory token budgets."""
    bus = MessageBus()
    provider = _provider()
    config = _config(tmp_path, memory_enabled=False)

    loop = build_agent(bus, provider, config)

    assert loop.context.memory_retrieval_k == 0
    assert loop.context.memory_token_budget == 0
    assert loop.context.memory_md_token_cap == 0


def test_delegation_disabled(tmp_path: Path) -> None:
    """Config with ``delegation_enabled=False`` omits the delegate tool."""
    bus = MessageBus()
    provider = _provider()
    config = _config(tmp_path, delegation_enabled=False)

    loop = build_agent(bus, provider, config)

    tool = loop.tools.get("delegate")
    assert tool is None


def test_role_config_override(tmp_path: Path) -> None:
    """A ``role_config`` with model/temperature applies them to the loop."""
    bus = MessageBus()
    provider = _provider()
    role = AgentRoleConfig(
        name="specialist",
        model="role-model-v2",
        temperature=0.2,
    )
    config = _config(tmp_path)

    loop = build_agent(bus, provider, config, role_config=role)

    assert loop.model == "role-model-v2"
    assert loop.temperature == 0.2
