"""Phase E tests: health tracking with transition detection + heartbeat integration."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.capability import (
    CapabilityRegistry,
    HealthChange,
    HealthRefreshResult,
)
from nanobot.agent.tools.base import Tool, ToolResult
from nanobot.heartbeat.service import HeartbeatService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _ToggleTool(Tool):
    """A tool whose availability can be toggled at test time."""

    readonly = True
    name = "toggle"
    description = "Toggleable tool"
    parameters: dict[str, Any] = {"type": "object", "properties": {}}
    _available: bool = True
    _reason: str | None = "turned off"

    def check_available(self) -> tuple[bool, str | None]:
        if self._available:
            return True, None
        return False, self._reason

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult.ok("ok")


class _AlwaysAvailTool(Tool):
    readonly = True
    name = "always"
    description = "Always available"
    parameters: dict[str, Any] = {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult.ok("ok")


# ---------------------------------------------------------------------------
# HealthRefreshResult dataclass
# ---------------------------------------------------------------------------


class TestHealthRefreshResult:
    def test_has_changes_empty(self) -> None:
        result = HealthRefreshResult(health={"a": "healthy"})
        assert not result.has_changes

    def test_has_changes_with_changes(self) -> None:
        change = HealthChange(name="t", kind="tool", old_health="healthy", new_health="unavailable")
        result = HealthRefreshResult(health={"t": "unavailable"}, changes=[change])
        assert result.has_changes


# ---------------------------------------------------------------------------
# Transition detection
# ---------------------------------------------------------------------------


class TestTransitionDetection:
    def test_healthy_to_unavailable(self) -> None:
        """Transition healthy→unavailable is detected and returned."""
        reg = CapabilityRegistry()
        tool = _ToggleTool()
        reg.register_tool(tool)

        tool._available = False
        result = reg.refresh_health()

        assert result.has_changes
        assert len(result.changes) == 1
        c = result.changes[0]
        assert c.name == "toggle"
        assert c.kind == "tool"
        assert c.old_health == "healthy"
        assert c.new_health == "unavailable"
        assert c.reason == "turned off"

    def test_unavailable_to_healthy(self) -> None:
        """Transition unavailable→healthy (recovery) is detected."""
        reg = CapabilityRegistry()
        tool = _ToggleTool()
        tool._available = False
        reg.register_tool(tool)

        tool._available = True
        result = reg.refresh_health()

        assert result.has_changes
        assert len(result.changes) == 1
        c = result.changes[0]
        assert c.old_health == "unavailable"
        assert c.new_health == "healthy"
        assert c.reason is None  # recovered → no reason

    def test_no_change_when_stable(self) -> None:
        """If nothing changed, changes list is empty."""
        reg = CapabilityRegistry()
        tool = _ToggleTool()
        reg.register_tool(tool)

        result = reg.refresh_health()
        assert not result.has_changes
        assert result.health["toggle"] == "healthy"

    def test_no_change_when_stable_unavailable(self) -> None:
        """Tool stays unavailable → no change reported."""
        reg = CapabilityRegistry()
        tool = _ToggleTool()
        tool._available = False
        reg.register_tool(tool)

        result = reg.refresh_health()
        assert not result.has_changes
        assert result.health["toggle"] == "unavailable"

    def test_multiple_tools_mixed_transitions(self) -> None:
        """Multiple tools changing simultaneously are all reported."""
        reg = CapabilityRegistry()
        t1 = _ToggleTool()
        t1.name = "t1"  # type: ignore[misc]
        t2 = _ToggleTool()
        t2.name = "t2"  # type: ignore[misc]
        t2._available = False
        always = _AlwaysAvailTool()

        reg.register_tool(t1)
        reg.register_tool(t2)
        reg.register_tool(always)

        # t1: healthy→unavailable, t2: unavailable→healthy, always: stable
        t1._available = False
        t2._available = True

        result = reg.refresh_health()
        assert len(result.changes) == 2

        names = {c.name for c in result.changes}
        assert names == {"t1", "t2"}

    def test_skill_and_role_unchanged(self) -> None:
        """Skills and roles don't have check_available — their health is stable."""
        reg = CapabilityRegistry()
        reg.register_skill("my_skill", description="A skill")
        result = reg.refresh_health()
        assert not result.has_changes
        assert result.health["my_skill"] == "healthy"

    def test_successive_refreshes_only_report_new_changes(self) -> None:
        """After a transition is reported, next refresh is stable (no re-report)."""
        reg = CapabilityRegistry()
        tool = _ToggleTool()
        reg.register_tool(tool)

        tool._available = False
        r1 = reg.refresh_health()
        assert r1.has_changes

        r2 = reg.refresh_health()
        assert not r2.has_changes  # already unavailable, no new transition


# ---------------------------------------------------------------------------
# Transition logging
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("propagate_loguru_to_caplog")
class TestTransitionLogging:
    def test_logs_warning_on_unavailable(self, caplog: pytest.LogCaptureFixture) -> None:
        reg = CapabilityRegistry()
        tool = _ToggleTool()
        reg.register_tool(tool)

        tool._available = False
        with caplog.at_level(logging.WARNING, logger="nanobot.agent.capability"):
            reg.refresh_health()

        assert any("unavailable" in r.message and "toggle" in r.message for r in caplog.records)

    def test_logs_info_on_recovery(self, caplog: pytest.LogCaptureFixture) -> None:
        reg = CapabilityRegistry()
        tool = _ToggleTool()
        tool._available = False
        reg.register_tool(tool)

        tool._available = True
        with caplog.at_level(logging.INFO, logger="nanobot.agent.capability"):
            reg.refresh_health()

        assert any("recovered" in r.message and "toggle" in r.message for r in caplog.records)

    def test_no_log_when_stable(self, caplog: pytest.LogCaptureFixture) -> None:
        reg = CapabilityRegistry()
        tool = _ToggleTool()
        reg.register_tool(tool)

        with caplog.at_level(logging.DEBUG, logger="nanobot.agent.capability"):
            reg.refresh_health()

        cap_records = [r for r in caplog.records if r.name == "nanobot.agent.capability"]
        assert len(cap_records) == 0


# ---------------------------------------------------------------------------
# Heartbeat integration
# ---------------------------------------------------------------------------


class TestHeartbeatHealthRefresh:
    def _make_service(self, tmp_path, **overrides):
        provider = overrides.pop("provider", MagicMock())
        model = overrides.pop("model", "test-model")
        defaults = dict(
            workspace=tmp_path,
            provider=provider,
            model=model,
            interval_s=9999,
            enabled=True,
        )
        defaults.update(overrides)
        return HeartbeatService(**defaults)

    async def test_tick_calls_health_refresh(self, tmp_path) -> None:
        """Health refresh callback is called during heartbeat tick."""
        refresh_mock = MagicMock(return_value=HealthRefreshResult(health={}))
        service = self._make_service(tmp_path, on_health_refresh=refresh_mock)

        await service._tick()
        refresh_mock.assert_called_once()

    async def test_tick_without_health_refresh(self, tmp_path) -> None:
        """Tick works fine when no health refresh callback is set."""
        service = self._make_service(tmp_path)
        # Should not raise
        await service._tick()

    async def test_tick_survives_health_refresh_error(self, tmp_path) -> None:
        """If health refresh raises, tick continues with heartbeat logic."""
        from nanobot.providers.base import LLMResponse, ToolCallRequest

        hb_file = tmp_path / "HEARTBEAT.md"
        hb_file.write_text("# Heartbeat\n- Deploy v2.1", encoding="utf-8")

        provider = AsyncMock()
        provider.chat = AsyncMock(
            return_value=LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="hb_1",
                        name="heartbeat",
                        arguments={"action": "run", "tasks": "Deploy v2.1"},
                    )
                ],
            )
        )

        def _exploding_refresh():
            raise RuntimeError("kaboom")

        on_execute = AsyncMock(return_value="done")
        on_notify = AsyncMock()

        service = self._make_service(
            tmp_path,
            provider=provider,
            on_health_refresh=_exploding_refresh,
            on_execute=on_execute,
            on_notify=on_notify,
        )

        await service._tick()  # Should not raise
        on_execute.assert_awaited_once()  # Heartbeat still ran

    async def test_health_refresh_called_before_heartbeat_file(self, tmp_path) -> None:
        """Health refresh runs even when HEARTBEAT.md doesn't exist."""
        refresh_mock = MagicMock(return_value=HealthRefreshResult(health={}))
        service = self._make_service(tmp_path, on_health_refresh=refresh_mock)

        await service._tick()
        refresh_mock.assert_called_once()

    async def test_end_to_end_with_capability_registry(self, tmp_path) -> None:
        """Integration: real CapabilityRegistry.refresh_health wired into heartbeat."""
        reg = CapabilityRegistry()
        tool = _ToggleTool()
        reg.register_tool(tool)

        service = self._make_service(
            tmp_path,
            on_health_refresh=reg.refresh_health,
        )

        # Tool becomes unavailable
        tool._available = False
        await service._tick()

        cap = reg.get("toggle")
        assert cap is not None
        assert cap.health == "unavailable"

        # Tool recovers
        tool._available = True
        await service._tick()
        assert reg.get("toggle").health == "healthy"  # type: ignore[union-attr]
