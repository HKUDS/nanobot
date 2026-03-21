"""Tests for process_direct with the forced_role parameter (LAN-192)."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any
from unittest.mock import patch

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import AgentConfig, AgentRoleConfig
from nanobot.providers.base import LLMResponse
from tests.helpers import ScriptedProvider


def _make_config(tmp_path: Path, **overrides: Any) -> AgentConfig:
    defaults: dict[str, Any] = dict(
        workspace=str(tmp_path),
        model="test-model",
        memory_window=10,
        max_iterations=5,
        planning_enabled=False,
        verification_mode="off",
    )
    defaults.update(overrides)
    return AgentConfig(**defaults)


def _make_loop(tmp_path: Path, provider: ScriptedProvider, **overrides: Any) -> AgentLoop:
    bus = MessageBus()
    config = _make_config(tmp_path, **overrides)
    return AgentLoop(bus, provider, config)


class TestProcessDirectForcedRole:
    """process_direct applies forced_role via TurnRoleManager.apply."""

    async def test_forced_role_applies_role_and_resets(self, tmp_path: Path) -> None:
        """When forced_role is given, the named role should be applied for the turn."""
        provider = ScriptedProvider(
            [
                LLMResponse(
                    content="role response", usage={"prompt_tokens": 5, "completion_tokens": 2}
                )
            ]
        )
        loop = _make_loop(tmp_path, provider)

        test_role = AgentRoleConfig(
            name="research", description="Research role", model="test-model"
        )

        # Patch _ensure_coordinator and route_direct to return our test role
        loop._coordinator = type(
            "FakeCoordinator",
            (),
            {  # type: ignore[assignment]
                "route_direct": lambda self, name: test_role if name == "research" else None,
            },
        )()

        # Track role application
        applied_roles: list[str] = []
        original_apply = loop._role_manager.apply

        def tracking_apply(role: AgentRoleConfig) -> Any:
            applied_roles.append(role.name)
            return original_apply(role)

        loop._role_manager.apply = tracking_apply  # type: ignore[assignment]

        # Suppress trace_request context manager
        @contextlib.asynccontextmanager
        async def fake_trace_request(**kwargs: Any):
            yield None

        with patch("nanobot.agent.loop.trace_request", side_effect=fake_trace_request):
            result = await loop.process_direct("test query", forced_role="research")

        assert result == "role response"
        assert applied_roles == ["research"]

    async def test_forced_role_unknown_returns_error(self, tmp_path: Path) -> None:
        """When forced_role names an unknown role, return an error string."""
        provider = ScriptedProvider(
            [
                LLMResponse(
                    content="should not run", usage={"prompt_tokens": 1, "completion_tokens": 1}
                )
            ]
        )
        loop = _make_loop(tmp_path, provider)

        # Coordinator that never finds a role
        loop._coordinator = type(
            "FakeCoordinator",
            (),
            {  # type: ignore[assignment]
                "route_direct": lambda self, name: None,
            },
        )()

        result = await loop.process_direct("test", forced_role="nonexistent")
        assert "Unknown role" in result
        assert "nonexistent" in result
