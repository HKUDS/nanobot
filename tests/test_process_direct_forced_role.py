"""Tests for process_direct with the forced_role parameter (LAN-192).

Routing is now owned by ``MessageProcessor`` via ``MessageRouter``.  These tests
verify the end-to-end path through ``AgentLoop.process_direct()`` which delegates
to the processor.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any
from unittest.mock import patch

from nanobot.agent.agent_factory import build_agent
from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.config.agent import AgentConfig
from nanobot.config.memory import MemoryConfig
from nanobot.config.schema import AgentRoleConfig
from nanobot.coordination.router import RoutingDecision, UnknownRoleError
from nanobot.providers.base import LLMResponse
from tests.helpers import ScriptedProvider


def _make_config(tmp_path: Path, **overrides: Any) -> AgentConfig:
    defaults: dict[str, Any] = dict(
        workspace=str(tmp_path),
        model="test-model",
        memory=MemoryConfig(window=10),
        max_iterations=5,
        planning_enabled=False,
        verification_mode="off",
    )
    defaults.update(overrides)
    return AgentConfig(**defaults)


def _make_loop(tmp_path: Path, provider: ScriptedProvider, **overrides: Any) -> AgentLoop:
    bus = MessageBus()
    config = _make_config(tmp_path, **overrides)
    return build_agent(bus=bus, provider=provider, config=config)


class TestProcessDirectForcedRole:
    """process_direct applies forced_role via the processor's MessageRouter."""

    async def test_forced_role_applies_role_and_resets(self, tmp_path: Path) -> None:
        """When forced_role is given, the processor routes to the named role."""
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

        # Track role application through the processor's role manager
        applied_roles: list[str] = []
        original_apply = loop._role_manager.apply

        def tracking_apply(role: AgentRoleConfig) -> Any:
            applied_roles.append(role.name)
            return original_apply(role)

        loop._role_manager.apply = tracking_apply  # type: ignore[assignment]

        # Wire a fake router into the processor that resolves forced_role
        from nanobot.coordination.coordinator import ClassificationResult

        async def fake_route(
            _self: Any,
            content: str,
            channel: str,
            forced_role: str | None = None,
        ) -> RoutingDecision | None:
            if forced_role == "research":
                return RoutingDecision(
                    role=test_role,
                    classification=ClassificationResult(role_name="research", confidence=1.0),
                )
            return None

        loop._processor._router = type(  # type: ignore[assignment]
            "FakeRouter", (), {"route": fake_route}
        )()

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
                    content="should not run",
                    usage={"prompt_tokens": 1, "completion_tokens": 1},
                )
            ]
        )
        loop = _make_loop(tmp_path, provider)

        # Wire a router that raises UnknownRoleError for unknown roles
        async def fake_route(
            _self: Any,
            content: str,
            channel: str,
            forced_role: str | None = None,
        ) -> RoutingDecision | None:
            if forced_role:
                raise UnknownRoleError(forced_role)
            return None

        loop._processor._router = type(  # type: ignore[assignment]
            "FakeRouter", (), {"route": fake_route}
        )()

        result = await loop.process_direct("test", forced_role="nonexistent")
        assert "Unknown role" in result
        assert "nonexistent" in result
