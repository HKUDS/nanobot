"""Regression tests for security-critical delegation permission paths.

Covers LAN-124:
- T-01: Web tool bypass — denied_tools must exclude web tools from delegated agents
- T-02: Disabled role routing — disabled roles must not be reachable via route_direct
- T-03: max_delegations enforcement — budget exhaustion raises _CycleError

These tests protect against regressions in the _grant() permission model, the
AgentRegistry.__contains__ enabled-flag check, and the delegation budget guard.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.config.schema import AgentRoleConfig
from nanobot.coordination.delegation import DelegationConfig, DelegationDispatcher
from nanobot.coordination.registry import AgentRegistry
from nanobot.tools.builtin.delegate import _CycleError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CONFIG_FIELDS = {f for f in DelegationConfig.__dataclass_fields__}


def _make_dispatcher(tmp_path: Path, **overrides: Any) -> DelegationDispatcher:
    exec_cfg = MagicMock()
    exec_cfg.timeout = 30
    exec_cfg.shell_mode = "denylist"
    config_defaults: dict[str, Any] = dict(
        workspace=tmp_path,
        model="test-model",
        temperature=0.7,
        max_tokens=4096,
        max_iterations=5,
        restrict_to_workspace=True,
        brave_api_key=None,
        exec_config=exec_cfg,
        role_name="main",
    )
    cfg_overrides = {k: v for k, v in overrides.items() if k in _CONFIG_FIELDS}
    wiring_overrides = {k: v for k, v in overrides.items() if k not in _CONFIG_FIELDS}
    config_defaults.update(cfg_overrides)
    config = DelegationConfig(**config_defaults)  # type: ignore[arg-type]
    return DelegationDispatcher(
        config=config,
        provider=wiring_overrides.pop("provider", None),
        **wiring_overrides,  # type: ignore[arg-type]
    )


def _role(name: str, **kwargs: Any) -> AgentRoleConfig:
    return AgentRoleConfig(name=name, description=f"{name} role", **kwargs)


# ---------------------------------------------------------------------------
# T-01: Web tool bypass via denied_tools
# ---------------------------------------------------------------------------


class TestWebToolPermissions:
    """The _grant() model must respect denied_tools for web tools in delegated agents."""

    async def test_web_search_excluded_when_denied(self, tmp_path: Path) -> None:
        """web_search must not appear in delegated tool registry when in denied_tools."""
        dispatcher = _make_dispatcher(tmp_path)
        role = _role("research", denied_tools=["web_search"])

        # Patch run_tool_loop so we can inspect the registry that was built
        captured_registry: list[Any] = []

        async def fake_tool_loop(
            provider: Any,
            tools: Any,
            messages: Any,
            **kwargs: Any,
        ) -> tuple[str, list[str], list[Any]]:
            captured_registry.append(tools)
            return "result", [], []

        import nanobot.coordination.delegation as delegation_mod

        original = delegation_mod.run_tool_loop
        delegation_mod.run_tool_loop = fake_tool_loop  # type: ignore[assignment]
        try:
            await dispatcher.execute_delegated_agent(role, "search the web", None)
        finally:
            delegation_mod.run_tool_loop = original

        assert len(captured_registry) >= 1
        registry = captured_registry[0]
        tool_names = list(registry._tools.keys())
        assert "web_search" not in tool_names, (
            "web_search must not be available when denied_tools=['web_search']"
        )

    async def test_web_fetch_excluded_when_denied(self, tmp_path: Path) -> None:
        """web_fetch must not appear in delegated tool registry when in denied_tools."""
        dispatcher = _make_dispatcher(tmp_path)
        role = _role("research", denied_tools=["web_fetch"])

        captured_registry: list[Any] = []

        async def fake_tool_loop(
            provider: Any,
            tools: Any,
            messages: Any,
            **kwargs: Any,
        ) -> tuple[str, list[str], list[Any]]:
            captured_registry.append(tools)
            return "result", [], []

        import nanobot.coordination.delegation as delegation_mod

        original = delegation_mod.run_tool_loop
        delegation_mod.run_tool_loop = fake_tool_loop  # type: ignore[assignment]
        try:
            await dispatcher.execute_delegated_agent(role, "fetch the page", None)
        finally:
            delegation_mod.run_tool_loop = original

        assert len(captured_registry) >= 1
        registry = captured_registry[0]
        tool_names = list(registry._tools.keys())
        assert "web_fetch" not in tool_names, (
            "web_fetch must not be available when denied_tools=['web_fetch']"
        )

    async def test_web_tools_present_by_default(self, tmp_path: Path) -> None:
        """web_search and web_fetch are available by default (no restrictions)."""
        dispatcher = _make_dispatcher(tmp_path, brave_api_key="test-key")
        role = _role("research")  # No allowed_tools, no denied_tools

        captured_registry: list[Any] = []

        async def fake_tool_loop(
            provider: Any,
            tools: Any,
            messages: Any,
            **kwargs: Any,
        ) -> tuple[str, list[str], list[Any]]:
            captured_registry.append(tools)
            return "result", [], []

        import nanobot.coordination.delegation as delegation_mod

        original = delegation_mod.run_tool_loop
        delegation_mod.run_tool_loop = fake_tool_loop  # type: ignore[assignment]
        try:
            await dispatcher.execute_delegated_agent(role, "search for info", None)
        finally:
            delegation_mod.run_tool_loop = original

        assert len(captured_registry) >= 1
        registry = captured_registry[0]
        tool_names = list(registry._tools.keys())
        assert "web_search" in tool_names, "web_search should be available by default"
        assert "web_fetch" in tool_names, "web_fetch should be available by default"

    async def test_exec_excluded_without_allowlist(self, tmp_path: Path) -> None:
        """exec is a privileged tool and must be excluded unless explicitly allowed."""
        dispatcher = _make_dispatcher(tmp_path)
        role = _role("research")  # No allowed_tools → privileged tools denied

        captured_registry: list[Any] = []

        async def fake_tool_loop(
            provider: Any,
            tools: Any,
            messages: Any,
            **kwargs: Any,
        ) -> tuple[str, list[str], list[Any]]:
            captured_registry.append(tools)
            return "result", [], []

        import nanobot.coordination.delegation as delegation_mod

        original = delegation_mod.run_tool_loop
        delegation_mod.run_tool_loop = fake_tool_loop  # type: ignore[assignment]
        try:
            await dispatcher.execute_delegated_agent(role, "run analysis", None)
        finally:
            delegation_mod.run_tool_loop = original

        registry = captured_registry[0]
        tool_names = list(registry._tools.keys())
        assert "exec" not in tool_names, (
            "exec is privileged and must not be available without an explicit allowlist"
        )

    async def test_exec_included_when_explicitly_allowed(self, tmp_path: Path) -> None:
        """exec must be available when explicitly listed in allowed_tools."""
        dispatcher = _make_dispatcher(tmp_path)
        role = _role("code", allowed_tools=["read_file", "list_dir", "exec"])

        captured_registry: list[Any] = []

        async def fake_tool_loop(
            provider: Any,
            tools: Any,
            messages: Any,
            **kwargs: Any,
        ) -> tuple[str, list[str], list[Any]]:
            captured_registry.append(tools)
            return "result", [], []

        import nanobot.coordination.delegation as delegation_mod

        original = delegation_mod.run_tool_loop
        delegation_mod.run_tool_loop = fake_tool_loop  # type: ignore[assignment]
        try:
            await dispatcher.execute_delegated_agent(role, "run the tests", None)
        finally:
            delegation_mod.run_tool_loop = original

        registry = captured_registry[0]
        tool_names = list(registry._tools.keys())
        assert "exec" in tool_names, "exec must be available when explicitly in allowed_tools"


# ---------------------------------------------------------------------------
# T-02: Disabled role routing
# ---------------------------------------------------------------------------


class TestDisabledRoleRouting:
    """Disabled roles must not be reachable via the AgentRegistry."""

    def test_disabled_role_not_in_registry(self) -> None:
        """A role with enabled=False must not be found via __contains__."""
        registry = AgentRegistry()
        registry.register(_role("disabled_agent", enabled=False))
        assert "disabled_agent" not in registry, (
            "Disabled roles must not be accessible via __contains__"
        )

    def test_disabled_role_not_in_list_roles(self) -> None:
        """Disabled roles must be excluded from list_roles()."""
        registry = AgentRegistry()
        registry.register(_role("active", enabled=True))
        registry.register(_role("inactive", enabled=False))
        names = [r.name for r in registry.list_roles()]
        assert "active" in names
        assert "inactive" not in names, "Disabled roles must not appear in list_roles()"

    def test_disabled_role_not_in_role_names(self) -> None:
        """Disabled roles must be excluded from role_names()."""
        registry = AgentRegistry()
        registry.register(_role("active", enabled=True))
        registry.register(_role("inactive", enabled=False))
        names = registry.role_names()
        assert "active" in names
        assert "inactive" not in names, "Disabled roles must not appear in role_names()"

    def test_enabled_role_is_in_registry(self) -> None:
        """An enabled role must be found via __contains__."""
        registry = AgentRegistry()
        registry.register(_role("research", enabled=True))
        assert "research" in registry

    def test_route_direct_returns_none_for_disabled(self) -> None:
        """Coordinator.route_direct must return None for a disabled role."""
        from nanobot.coordination.coordinator import Coordinator
        from nanobot.providers.base import LLMProvider, LLMResponse

        class StubProvider(LLMProvider):
            def get_default_model(self) -> str:
                return "stub"

            async def chat(  # type: ignore[override]
                self,
                messages: Any,
                tools: Any = None,
                model: Any = None,
                max_tokens: int = 4096,
                temperature: float = 0.7,
                metadata: Any = None,
            ) -> LLMResponse:
                return LLMResponse(content='{"role": "general"}')

        registry = AgentRegistry(default_role="general")
        registry.register(_role("general", enabled=True))
        registry.register(_role("hidden", enabled=False))

        coordinator = Coordinator(
            provider=StubProvider(), registry=registry, default_role="general"
        )
        result = coordinator.route_direct("hidden")
        assert result is None, (
            "route_direct must return None for a disabled role — "
            "it must not be routable even by explicit name"
        )

    def test_route_direct_returns_role_when_enabled(self) -> None:
        """Coordinator.route_direct must return the config for an enabled role."""
        from nanobot.coordination.coordinator import Coordinator
        from nanobot.providers.base import LLMProvider, LLMResponse

        class StubProvider(LLMProvider):
            def get_default_model(self) -> str:
                return "stub"

            async def chat(  # type: ignore[override]
                self,
                messages: Any,
                tools: Any = None,
                model: Any = None,
                max_tokens: int = 4096,
                temperature: float = 0.7,
                metadata: Any = None,
            ) -> LLMResponse:
                return LLMResponse(content='{"role": "general"}')

        registry = AgentRegistry(default_role="general")
        registry.register(_role("general", enabled=True))
        registry.register(_role("code", enabled=True))

        coordinator = Coordinator(
            provider=StubProvider(), registry=registry, default_role="general"
        )
        result = coordinator.route_direct("code")
        assert result is not None
        assert result.name == "code"


# ---------------------------------------------------------------------------
# T-03: max_delegations enforcement
# ---------------------------------------------------------------------------


class TestMaxDelegationsEnforcement:
    """Delegation budget must be enforced — exhaustion raises _CycleError."""

    async def test_budget_exhausted_raises_cycle_error(self, tmp_path: Path) -> None:
        """dispatch() must raise _CycleError when delegation_count >= max_delegations."""
        dispatcher = _make_dispatcher(tmp_path)
        dispatcher.max_delegations = 3
        dispatcher.delegation_count = 3  # Already at limit

        mock_coordinator = MagicMock()
        mock_coordinator.route_direct.return_value = None
        mock_coordinator.route = AsyncMock(return_value=_role("research", enabled=True))
        dispatcher.coordinator = mock_coordinator

        with pytest.raises(_CycleError, match="budget exhausted"):
            await dispatcher.dispatch("", "do something", None)

    async def test_budget_not_exhausted_below_limit(self, tmp_path: Path) -> None:
        """dispatch() must NOT raise when delegation_count < max_delegations."""
        dispatcher = _make_dispatcher(tmp_path)
        dispatcher.max_delegations = 3
        dispatcher.delegation_count = 2  # One slot remaining

        mock_coordinator = MagicMock()
        mock_coordinator.route_direct.return_value = None
        research_role = _role("research", enabled=True)
        mock_coordinator.route = AsyncMock(return_value=research_role)
        dispatcher.coordinator = mock_coordinator

        # Patch execute_delegated_agent so we don't need a real provider
        dispatcher.execute_delegated_agent = AsyncMock(  # type: ignore[method-assign]
            return_value=("result text", ["read_file"])
        )

        from nanobot.tools.builtin.delegate import DelegationResult

        result = await dispatcher.dispatch("", "search for info", None)
        assert isinstance(result, DelegationResult)
        assert dispatcher.delegation_count == 3  # Incremented

    async def test_budget_counts_per_session(self, tmp_path: Path) -> None:
        """Each dispatch call increments delegation_count; budget is cumulative."""
        dispatcher = _make_dispatcher(tmp_path)
        dispatcher.max_delegations = 2
        dispatcher.delegation_count = 0

        mock_coordinator = MagicMock()
        mock_coordinator.route_direct.return_value = None
        research_role = _role("research", enabled=True)
        mock_coordinator.route = AsyncMock(return_value=research_role)
        dispatcher.coordinator = mock_coordinator
        dispatcher.execute_delegated_agent = AsyncMock(  # type: ignore[method-assign]
            return_value=("result", ["read_file"])
        )

        # First dispatch — succeeds
        await dispatcher.dispatch("", "task one", None)
        assert dispatcher.delegation_count == 1

        # Second dispatch — succeeds (at limit but not over)
        await dispatcher.dispatch("", "task two", None)
        assert dispatcher.delegation_count == 2

        # Third dispatch — must fail (over budget)
        with pytest.raises(_CycleError, match="budget exhausted"):
            await dispatcher.dispatch("", "task three", None)

    async def test_default_max_delegations_is_eight(self, tmp_path: Path) -> None:
        """The default max_delegations value must be 8."""
        dispatcher = _make_dispatcher(tmp_path)
        assert dispatcher.max_delegations == 8

    async def test_budget_error_message_contains_counts(self, tmp_path: Path) -> None:
        """The _CycleError message must include current and max counts for debugging."""
        dispatcher = _make_dispatcher(tmp_path)
        dispatcher.max_delegations = 5
        dispatcher.delegation_count = 5

        mock_coordinator = MagicMock()
        mock_coordinator.route_direct.return_value = None
        mock_coordinator.route = AsyncMock(return_value=_role("research"))
        dispatcher.coordinator = mock_coordinator

        with pytest.raises(_CycleError) as exc_info:
            await dispatcher.dispatch("", "task", None)

        msg = str(exc_info.value)
        assert "5" in msg, "Error message must include current count"
        assert "5" in msg, "Error message must include max limit"
