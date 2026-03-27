"""Tests for Phase C: CapabilityRegistry wiring into AgentLoop.

Verifies that CapabilityRegistry is properly constructed and wired
throughout the agent lifecycle: constructor, MCP, coordinator, and
that backward-compatible paths remain functional.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nanobot.agent.agent_factory import build_agent
from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.config.agent import AgentConfig
from nanobot.config.memory import MemoryConfig
from nanobot.config.schema import RoutingConfig
from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.tools.base import Tool, ToolResult
from nanobot.tools.capability import CapabilityRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubProvider(LLMProvider):
    """Minimal provider for constructor tests — never actually called."""

    def get_default_model(self) -> str:
        return "stub-model"

    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> LLMResponse:
        return LLMResponse(content="stub")


class _FakeTool(Tool):
    readonly = True
    name = "fake_tool"
    description = "A fake tool for testing"
    parameters: dict[str, Any] = {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult.ok("done")


class _UnavailFakeTool(Tool):
    readonly = True
    name = "unavail_fake"
    description = "Unavailable fake tool"
    parameters: dict[str, Any] = {"type": "object", "properties": {}}

    def check_available(self) -> tuple[bool, str | None]:
        return False, "missing dependency"

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult.ok("done")


def _make_loop(
    tmp_path: Path,
    routing_config: RoutingConfig | None = None,
    **config_kw: Any,
) -> AgentLoop:
    bus = MessageBus()
    defaults: dict[str, Any] = {
        "workspace": str(tmp_path),
        "model": "stub-model",
        "memory": MemoryConfig(window=10),
        "max_iterations": 3,
        "planning_enabled": False,
        "verification_mode": "off",
    }
    defaults.update(config_kw)
    config = AgentConfig(**defaults)
    return build_agent(
        bus=bus,
        provider=_StubProvider(),
        config=config,
        routing_config=routing_config,
    )


# ---------------------------------------------------------------------------
# Tests: CapabilityRegistry exists and is properly composed
# ---------------------------------------------------------------------------


class TestCapabilityRegistryWiring:
    """Verify CapabilityRegistry is created and wired in AgentLoop.__init__."""

    def test_capabilities_attribute_exists(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        assert hasattr(loop, "_capabilities")
        assert isinstance(loop._capabilities, CapabilityRegistry)

    def test_tool_registry_is_shared(self, tmp_path: Path) -> None:
        """CapabilityRegistry.tool_registry is the same instance as ToolExecutor._registry."""
        loop = _make_loop(tmp_path)
        assert loop._capabilities.tool_registry is loop.tools._registry

    def test_skills_loader_is_shared(self, tmp_path: Path) -> None:
        """CapabilityRegistry.skills_loader is the same instance as context.skills."""
        loop = _make_loop(tmp_path)
        assert loop._capabilities.skills_loader is loop.context.skills


# ---------------------------------------------------------------------------
# Tests: tools registered in ToolExecutor visible through CapabilityRegistry
# ---------------------------------------------------------------------------


class TestToolRegistrationSync:
    """Tools registered via ToolExecutor are visible through CapabilityRegistry."""

    def test_tools_registered_in_loop_visible_in_capability(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        # Default tools are registered in _register_default_tools
        # CapabilityRegistry wraps the same ToolRegistry
        tool_names = loop._capabilities.tool_registry.tool_names
        assert len(tool_names) > 0
        # At minimum, exec and filesystem tools should be present
        assert "exec" in tool_names

    def test_manual_tool_registration_visible(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        fake = _FakeTool()
        loop.tools.register(fake)
        # Should be accessible through both paths
        assert loop.tools.get("fake_tool") is fake
        assert loop._capabilities.tool_registry.get("fake_tool") is fake


# ---------------------------------------------------------------------------
# Tests: unavailable tools callback
# ---------------------------------------------------------------------------


class TestUnavailableToolsCallback:
    """Unavailable tools summary comes through CapabilityRegistry."""

    def test_unavailable_summary_wired(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        # Register an unavailable tool through CapabilityRegistry
        unavail = _UnavailFakeTool()
        loop._capabilities.register_tool(unavail)
        # The callback on context should produce output
        summary = loop._capabilities.get_unavailable_summary()
        assert "unavail_fake" in summary
        assert "missing dependency" in summary

    def test_context_callback_uses_capability_registry(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        # The context's unavailable_tools_fn should be CapabilityRegistry.get_unavailable_summary
        assert loop.context._unavailable_tools_fn is not None
        # They should produce the same output
        direct = loop._capabilities.get_unavailable_summary()
        via_context = loop.context._unavailable_tools_fn()
        assert direct == via_context


# ---------------------------------------------------------------------------
# Tests: coordinator wiring populates CapabilityRegistry roles
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Tests: backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Existing ToolExecutor API still works unchanged."""

    def test_tools_get_definitions(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        defs = loop.tools.get_definitions()
        assert isinstance(defs, list)
        assert len(defs) > 0

    def test_tools_tool_names(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        names = loop.tools.tool_names
        assert isinstance(names, list)
        assert "exec" in names

    def test_tools_register_unregister(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        fake = _FakeTool()
        loop.tools.register(fake)
        assert loop.tools.has("fake_tool")
        loop.tools.unregister("fake_tool")
        assert not loop.tools.has("fake_tool")

    def test_result_cache_set_on_capability_tool_registry(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        # result_cache should be set on the tool registry
        assert loop._capabilities.tool_registry._cache is not None
