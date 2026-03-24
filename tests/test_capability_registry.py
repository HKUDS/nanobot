"""Tests for Phase B: CapabilityRegistry core."""

from __future__ import annotations

from typing import Any

import pytest

from nanobot.coordination.registry import AgentRegistry
from nanobot.tools.base import Tool, ToolResult
from nanobot.tools.capability import CapabilityRegistry
from nanobot.tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class _AvailableTool(Tool):
    readonly = True
    name = "avail_tool"
    description = "An available tool"
    parameters: dict[str, Any] = {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult.ok("ok")


class _UnavailableTool(Tool):
    readonly = True
    name = "unavail_tool"
    description = "Tool missing deps"
    parameters: dict[str, Any] = {"type": "object", "properties": {}}

    def check_available(self) -> tuple[bool, str | None]:
        return False, "missing dep"

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult.ok("ok")


class _SearchTool(Tool):
    readonly = True
    name = "search"
    description = "Search tool"
    parameters: dict[str, Any] = {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult.ok("results")


def _make_role(
    name: str = "test_role",
    description: str = "A test role",
    enabled: bool = True,
) -> Any:
    """Create a minimal AgentRoleConfig-like object for testing."""
    from nanobot.config.schema import AgentRoleConfig

    return AgentRoleConfig(name=name, description=description, enabled=enabled)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_register_tool_creates_capability(self) -> None:
        reg = CapabilityRegistry(agent_registry=AgentRegistry())
        tool = _AvailableTool()
        reg.register_tool(tool, intents=["do_stuff"])

        cap = reg.get("avail_tool")
        assert cap is not None
        assert cap.kind == "tool"
        assert cap.health == "healthy"
        assert cap.intents == ["do_stuff"]
        assert cap.tool is tool

    def test_register_unavailable_tool(self) -> None:
        reg = CapabilityRegistry(agent_registry=AgentRegistry())
        reg.register_tool(_UnavailableTool())

        cap = reg.get("unavail_tool")
        assert cap is not None
        assert cap.health == "unavailable"
        assert cap.unavailability_reason == "missing dep"

    def test_register_tool_also_registers_in_tool_registry(self) -> None:
        tr = ToolRegistry()
        reg = CapabilityRegistry(tool_registry=tr)
        reg.register_tool(_AvailableTool())

        assert tr.has("avail_tool")

    def test_register_skill(self) -> None:
        reg = CapabilityRegistry(agent_registry=AgentRegistry())
        reg.register_skill(
            "weather",
            description="Check weather",
            path="/skills/weather/SKILL.md",
            intents=["weather"],
        )

        cap = reg.get("weather")
        assert cap is not None
        assert cap.kind == "skill"
        assert cap.health == "healthy"
        assert cap.skill_path == "/skills/weather/SKILL.md"

    def test_register_unavailable_skill(self) -> None:
        reg = CapabilityRegistry(agent_registry=AgentRegistry())
        reg.register_skill(
            "playwright",
            description="Browser automation",
            available=False,
            unavailability_reason="playwright-cli not installed",
        )

        cap = reg.get("playwright")
        assert cap is not None
        assert cap.health == "unavailable"
        assert "not installed" in (cap.unavailability_reason or "")

    def test_register_role(self) -> None:
        reg = CapabilityRegistry(agent_registry=AgentRegistry())
        role = _make_role("research", "Research specialist")
        reg.register_role(role, intents=["research", "investigate"])

        cap = reg.get("research")
        assert cap is not None
        assert cap.kind == "delegate_role"
        assert cap.health == "healthy"
        assert "investigate" in cap.intents

    def test_register_disabled_role(self) -> None:
        reg = CapabilityRegistry(agent_registry=AgentRegistry())
        role = _make_role("legacy", "Old role", enabled=False)
        reg.register_role(role)

        cap = reg.get("legacy")
        assert cap is not None
        assert cap.health == "unavailable"

    def test_unregister_tool(self) -> None:
        tr = ToolRegistry()
        reg = CapabilityRegistry(tool_registry=tr)
        reg.register_tool(_AvailableTool())

        reg.unregister("avail_tool")
        assert reg.get("avail_tool") is None
        assert not tr.has("avail_tool")

    def test_unregister_skill(self) -> None:
        reg = CapabilityRegistry(agent_registry=AgentRegistry())
        reg.register_skill("weather", description="Check weather")
        reg.unregister("weather")
        assert reg.get("weather") is None

    def test_unregister_nonexistent_is_noop(self) -> None:
        reg = CapabilityRegistry(agent_registry=AgentRegistry())
        reg.unregister("nonexistent")  # should not raise

    def test_capability_is_immutable(self) -> None:
        """Capability dataclass is frozen — direct mutation raises FrozenInstanceError."""
        from dataclasses import FrozenInstanceError

        reg = CapabilityRegistry(agent_registry=AgentRegistry())
        reg.register_tool(_AvailableTool())
        cap = reg.get("avail_tool")
        assert cap is not None
        with pytest.raises(FrozenInstanceError):
            cap.health = "unavailable"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


class TestQueries:
    def test_get_available_excludes_unavailable(self) -> None:
        reg = CapabilityRegistry(agent_registry=AgentRegistry())
        reg.register_tool(_AvailableTool())
        reg.register_tool(_UnavailableTool())

        avail = reg.get_available()
        names = [c.name for c in avail]
        assert "avail_tool" in names
        assert "unavail_tool" not in names

    def test_get_available_filter_by_kind(self) -> None:
        reg = CapabilityRegistry(agent_registry=AgentRegistry())
        reg.register_tool(_AvailableTool())
        reg.register_skill("weather", description="Weather")
        role = _make_role("research")
        reg.register_role(role)

        tools = reg.get_available(kind="tool")
        assert all(c.kind == "tool" for c in tools)

        skills = reg.get_available(kind="skill")
        assert all(c.kind == "skill" for c in skills)

        roles = reg.get_available(kind="delegate_role")
        assert all(c.kind == "delegate_role" for c in roles)

    def test_get_available_filter_by_intent(self) -> None:
        reg = CapabilityRegistry(agent_registry=AgentRegistry())
        reg.register_tool(_AvailableTool(), intents=["do_stuff"])
        reg.register_tool(_SearchTool(), intents=["search_web"])

        results = reg.get_available(intent="search_web")
        assert len(results) == 1
        assert results[0].name == "search"

    def test_get_available_sorted_by_priority(self) -> None:
        reg = CapabilityRegistry(agent_registry=AgentRegistry())
        reg.register_tool(_SearchTool(), intents=["search"], fallback_priority=10)
        reg.register_tool(_AvailableTool(), intents=["search"], fallback_priority=1)

        results = reg.get_available(intent="search")
        assert results[0].name == "avail_tool"
        assert results[1].name == "search"

    def test_get_unavailable(self) -> None:
        reg = CapabilityRegistry(agent_registry=AgentRegistry())
        reg.register_tool(_AvailableTool())
        reg.register_tool(_UnavailableTool())

        unavail = reg.get_unavailable()
        assert len(unavail) == 1
        assert unavail[0].name == "unavail_tool"

    def test_get_tool_definitions_delegates(self) -> None:
        tr = ToolRegistry()
        reg = CapabilityRegistry(tool_registry=tr)
        reg.register_tool(_AvailableTool())
        reg.register_tool(_UnavailableTool())

        defs = reg.get_tool_definitions()
        names = [d["function"]["name"] for d in defs]
        assert "avail_tool" in names
        assert "unavail_tool" not in names

    def test_get_unavailable_summary(self) -> None:
        reg = CapabilityRegistry(agent_registry=AgentRegistry())
        reg.register_tool(_AvailableTool())
        reg.register_tool(_UnavailableTool())
        reg.register_skill(
            "broken", description="Broken", available=False, unavailability_reason="no bin"
        )

        summary = reg.get_unavailable_summary()
        assert "unavail_tool" in summary
        assert "missing dep" in summary
        assert "broken" in summary
        # "avail_tool" should not appear as its own entry
        lines = summary.splitlines()
        assert not any(line.startswith("- avail_tool") for line in lines)

    def test_get_unavailable_summary_empty(self) -> None:
        reg = CapabilityRegistry(agent_registry=AgentRegistry())
        reg.register_tool(_AvailableTool())
        assert reg.get_unavailable_summary() == ""

    def test_role_names(self) -> None:
        reg = CapabilityRegistry(agent_registry=AgentRegistry())
        reg.register_role(_make_role("research"))
        reg.register_role(_make_role("code"))
        reg.register_role(_make_role("disabled", enabled=False))

        names = reg.role_names()
        assert "research" in names
        assert "code" in names
        assert "disabled" not in names


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------


class TestToolExecution:
    def test_get_tool(self) -> None:
        reg = CapabilityRegistry(agent_registry=AgentRegistry())
        tool = _AvailableTool()
        reg.register_tool(tool)

        assert reg.get_tool("avail_tool") is tool
        assert reg.get_tool("nonexistent") is None

    async def test_execute_tool(self) -> None:
        reg = CapabilityRegistry(agent_registry=AgentRegistry())
        reg.register_tool(_AvailableTool())

        result = await reg.execute_tool("avail_tool", {})
        assert result.success
        assert result.output == "ok"

    async def test_execute_nonexistent_tool(self) -> None:
        reg = CapabilityRegistry(agent_registry=AgentRegistry())
        result = await reg.execute_tool("nonexistent", {})
        assert not result.success


# ---------------------------------------------------------------------------
# Health refresh
# ---------------------------------------------------------------------------


class _ToggleTool(Tool):
    """A tool whose availability can be toggled at test time."""

    readonly = True
    name = "toggle"
    description = "Toggleable"
    parameters: dict[str, Any] = {"type": "object", "properties": {}}
    _available: bool = True

    def check_available(self) -> tuple[bool, str | None]:
        if self._available:
            return True, None
        return False, "turned off"

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult.ok("ok")


class TestHealthRefresh:
    def test_refresh_updates_health(self) -> None:
        reg = CapabilityRegistry(agent_registry=AgentRegistry())
        tool = _ToggleTool()
        reg.register_tool(tool)

        assert reg.get("toggle") is not None
        assert reg.get("toggle").health == "healthy"  # type: ignore[union-attr]

        tool._available = False
        result = reg.refresh_health()
        assert result.health["toggle"] == "unavailable"
        assert reg.get("toggle").health == "unavailable"  # type: ignore[union-attr]

    def test_refresh_recovers_health(self) -> None:
        reg = CapabilityRegistry(agent_registry=AgentRegistry())
        tool = _ToggleTool()
        tool._available = False
        reg.register_tool(tool)

        assert reg.get("toggle").health == "unavailable"  # type: ignore[union-attr]

        tool._available = True
        result = reg.refresh_health()
        assert result.health["toggle"] == "healthy"  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Introspection
# ---------------------------------------------------------------------------


class TestIntrospection:
    def test_len(self) -> None:
        reg = CapabilityRegistry(agent_registry=AgentRegistry())
        assert len(reg) == 0
        reg.register_tool(_AvailableTool())
        assert len(reg) == 1
        reg.register_skill("weather", description="Weather")
        assert len(reg) == 2

    def test_contains(self) -> None:
        reg = CapabilityRegistry(agent_registry=AgentRegistry())
        reg.register_tool(_AvailableTool())
        assert "avail_tool" in reg
        assert "nonexistent" not in reg

    def test_all_capabilities(self) -> None:
        reg = CapabilityRegistry(agent_registry=AgentRegistry())
        reg.register_tool(_AvailableTool())
        reg.register_tool(_UnavailableTool())
        reg.register_skill("weather", description="Weather")

        all_caps = reg.all_capabilities
        assert len(all_caps) == 3

    def test_property_accessors(self) -> None:
        tr = ToolRegistry()
        ar = AgentRegistry()
        reg = CapabilityRegistry(tool_registry=tr, agent_registry=ar)

        assert reg.tool_registry is tr
        assert reg.skills_loader is None
        assert reg.agent_registry is ar

    def test_register_role_always_propagates_to_agent_registry(self) -> None:
        """register_role writes to both _capabilities and agent_registry."""
        reg = CapabilityRegistry(agent_registry=AgentRegistry())
        role = _make_role("research", "Research specialist")
        reg.register_role(role, intents=["research"])

        # Capability side
        cap = reg.get("research")
        assert cap is not None
        assert cap.kind == "delegate_role"
        assert cap.health == "healthy"

        # AgentRegistry side
        ar_role = reg.agent_registry.get("research")
        assert ar_role is not None
        assert ar_role.name == "research"
        assert ar_role.description == "Research specialist"

    def test_merge_register_role_updates_both_registries(self) -> None:
        """merge_register_role updates both _capabilities and agent_registry."""
        from nanobot.config.schema import AgentRoleConfig

        reg = CapabilityRegistry(agent_registry=AgentRegistry())
        # Register a base role
        reg.register_role(_make_role("code", "Code generation"))
        # Merge an override with a new description
        override = AgentRoleConfig(name="code", description="Advanced code generation")
        reg.merge_register_role(override, intents=["coding"])

        cap = reg.get("code")
        assert cap is not None
        assert cap.description == "Advanced code generation"
        assert cap.intents == ["coding"]

        ar_role = reg.agent_registry.get("code")
        assert ar_role is not None
        assert ar_role.description == "Advanced code generation"

    def test_register_role_then_merge_preserves_override(self) -> None:
        """Register default, merge user override, verify merged config wins."""
        from nanobot.config.schema import AgentRoleConfig

        reg = CapabilityRegistry(agent_registry=AgentRegistry())
        # Register default
        default_role = _make_role("research", "Default research")
        reg.register_role(default_role, intents=["research"])

        # Merge user override (only description set explicitly)
        user_override = AgentRoleConfig(name="research", description="Custom research")
        reg.merge_register_role(user_override)

        cap = reg.get("research")
        assert cap is not None
        assert cap.description == "Custom research"
        # Intents should be preserved from existing capability (no new intents passed)
        assert cap.intents == ["research"]

        ar_role = reg.agent_registry.get("research")
        assert ar_role is not None
        assert ar_role.description == "Custom research"
