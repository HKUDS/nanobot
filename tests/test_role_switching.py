"""Unit tests for TurnRoleManager (extracted from AgentLoop, LAN-214)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from nanobot.agent.role_switching import TurnRoleManager
from nanobot.config.schema import AgentRoleConfig

# -- Fakes satisfying _LoopLike Protocol ----------------------------------


@dataclass
class FakeContext:
    role_system_prompt: str = ""


@dataclass
class FakeDispatcher:
    role_name: str = ""


@dataclass
class FakeTools:
    """Dict-backed stub for ToolExecutor's snapshot/restore/unregister."""

    _tools: dict[str, str] = field(default_factory=dict)

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())

    def snapshot(self) -> dict[str, str]:
        return dict(self._tools)

    def restore(self, snap: dict[str, str]) -> None:
        self._tools = snap

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)


@dataclass
class FakeRoleConfig:
    name: str = "general"


@dataclass
class FakeLoop:
    model: str = "default-model"
    temperature: float = 0.7
    max_iterations: int = 10
    role_name: str = "general"
    role_config: Any = field(default_factory=FakeRoleConfig)
    context: Any = field(default_factory=FakeContext)
    tools: Any = field(default_factory=FakeTools)
    _dispatcher: Any = field(default_factory=FakeDispatcher)
    _capabilities: Any = None
    exec_config: Any = None


@pytest.fixture
def loop() -> FakeLoop:
    return FakeLoop(
        tools=FakeTools(_tools={"read_file": "r", "exec": "e", "web_search": "w"}),
    )


@pytest.fixture
def manager(loop: FakeLoop) -> TurnRoleManager:
    return TurnRoleManager(loop)


class TestApply:
    def test_captures_snapshot(self, manager: TurnRoleManager, loop: FakeLoop) -> None:
        role = AgentRoleConfig(name="code", description="Coder", model="gpt-4")
        ctx = manager.apply(role)
        assert ctx.model == "default-model"
        assert ctx.temperature == 0.7
        assert ctx.max_iterations == 10
        assert ctx.role_prompt == ""

    def test_overrides_model(self, manager: TurnRoleManager, loop: FakeLoop) -> None:
        role = AgentRoleConfig(name="code", description="", model="gpt-4")
        manager.apply(role)
        assert loop.model == "gpt-4"

    def test_overrides_temperature(self, manager: TurnRoleManager, loop: FakeLoop) -> None:
        role = AgentRoleConfig(name="code", description="", temperature=0.2)
        manager.apply(role)
        assert loop.temperature == 0.2

    def test_overrides_max_iterations(self, manager: TurnRoleManager, loop: FakeLoop) -> None:
        role = AgentRoleConfig(name="code", description="", max_iterations=3)
        manager.apply(role)
        assert loop.max_iterations == 3

    def test_sets_role_system_prompt(self, manager: TurnRoleManager, loop: FakeLoop) -> None:
        role = AgentRoleConfig(name="code", description="", system_prompt="You are a coder.")
        manager.apply(role)
        assert loop.context.role_system_prompt == "You are a coder."

    def test_syncs_dispatcher_role_name(self, manager: TurnRoleManager, loop: FakeLoop) -> None:
        role = AgentRoleConfig(name="research", description="")
        manager.apply(role)
        assert loop._dispatcher.role_name == "research"
        assert loop.role_name == "research"

    def test_no_model_override_preserves_default(
        self, manager: TurnRoleManager, loop: FakeLoop
    ) -> None:
        role = AgentRoleConfig(name="code", description="", model=None)
        manager.apply(role)
        assert loop.model == "default-model"


class TestReset:
    def test_restores_all_values(self, manager: TurnRoleManager, loop: FakeLoop) -> None:
        role = AgentRoleConfig(
            name="code",
            description="",
            model="gpt-4",
            temperature=0.1,
            max_iterations=2,
            system_prompt="override",
            allowed_tools=["exec"],
        )
        ctx = manager.apply(role)
        assert loop.model == "gpt-4"
        assert loop.temperature == 0.1

        manager.reset(ctx)
        assert loop.model == "default-model"
        assert loop.temperature == 0.7
        assert loop.max_iterations == 10
        assert loop.context.role_system_prompt == ""
        assert loop.role_name == "general"

    def test_reset_none_is_noop(self, manager: TurnRoleManager, loop: FakeLoop) -> None:
        original_model = loop.model
        manager.reset(None)
        assert loop.model == original_model

    def test_reset_skips_tool_restore_when_no_filtering(
        self, manager: TurnRoleManager, loop: FakeLoop
    ) -> None:
        role = AgentRoleConfig(name="code", description="")
        ctx = manager.apply(role)
        assert ctx.tools is None
        original_tools = dict(loop.tools._tools)
        manager.reset(ctx)
        assert loop.tools._tools == original_tools
