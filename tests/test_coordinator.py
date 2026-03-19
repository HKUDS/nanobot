"""Tests for the multi-agent Coordinator and routing.

Covers:
- Classification prompt construction
- JSON parse path
- Fallback text-scan parse path
- Error resilience (LLM failure → default role)
- Unknown role → default fallback
- route() returns AgentRoleConfig
- build_default_registry() ships all default roles
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nanobot.agent.coordinator import (
    DEFAULT_ROLES,
    Coordinator,
    build_default_registry,
)
from nanobot.agent.registry import AgentRegistry
from nanobot.config.schema import AgentConfig, AgentRoleConfig, RoutingConfig
from nanobot.providers.base import LLMProvider, LLMResponse
from tests.helpers import ScriptedProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeProvider(LLMProvider):
    """Provider that returns a single pre-set response text."""

    def __init__(self, response_text: str) -> None:
        super().__init__()
        self._text = response_text

    def get_default_model(self) -> str:
        return "fake-model"

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        metadata: dict[str, Any] | None = None,
    ) -> LLMResponse:
        return LLMResponse(content=self._text)


class FailingProvider(LLMProvider):
    """Provider that always raises an exception."""

    def get_default_model(self) -> str:
        return "fail-model"

    async def chat(self, **kwargs: Any) -> LLMResponse:
        raise RuntimeError("LLM unavailable")


def _make_registry() -> AgentRegistry:
    """Build a minimal test registry with code, research, general roles."""
    reg = AgentRegistry(default_role="general")
    reg.register(AgentRoleConfig(name="code", description="Coding tasks"))
    reg.register(AgentRoleConfig(name="research", description="Research tasks"))
    reg.register(AgentRoleConfig(name="general", description="General assistant"))
    return reg


# ---------------------------------------------------------------------------
# build_default_registry
# ---------------------------------------------------------------------------


class TestBuildDefaultRegistry:
    def test_contains_all_default_roles(self) -> None:
        reg = build_default_registry()
        for role in DEFAULT_ROLES:
            assert role.name in reg

    def test_default_role_is_general(self) -> None:
        reg = build_default_registry()
        default = reg.get_default()
        assert default is not None
        assert default.name == "general"

    def test_length_matches_defaults(self) -> None:
        reg = build_default_registry()
        assert len(reg) == len(DEFAULT_ROLES)

    def test_custom_default_role(self) -> None:
        reg = build_default_registry(default_role="code")
        default = reg.get_default()
        assert default is not None
        assert default.name == "code"


# ---------------------------------------------------------------------------
# Coordinator.classify
# ---------------------------------------------------------------------------


class TestClassify:
    async def test_json_response(self) -> None:
        provider = FakeProvider('{"role": "code"}')
        coordinator = Coordinator(provider, _make_registry())
        role_name, confidence = await coordinator.classify("Write a Python function")
        assert role_name == "code"
        assert confidence == 1.0

    async def test_json_with_whitespace(self) -> None:
        provider = FakeProvider('  { "role" : "research" }  ')
        coordinator = Coordinator(provider, _make_registry())
        role_name, confidence = await coordinator.classify("Search the web for info")
        assert role_name == "research"
        assert confidence == 1.0

    async def test_json_with_confidence(self) -> None:
        provider = FakeProvider('{"role": "code", "confidence": 0.85}')
        coordinator = Coordinator(provider, _make_registry())
        role_name, confidence = await coordinator.classify("Write a function")
        assert role_name == "code"
        assert confidence == 0.85

    async def test_fallback_text_scan(self) -> None:
        provider = FakeProvider("I think the code agent should handle this")
        coordinator = Coordinator(provider, _make_registry())
        role_name, confidence = await coordinator.classify("Fix the bug")
        assert role_name == "code"
        assert confidence == 0.5

    async def test_unknown_role_returns_default(self) -> None:
        provider = FakeProvider('{"role": "nonexistent"}')
        coordinator = Coordinator(provider, _make_registry())
        role_name, _ = await coordinator.classify("Do something")
        assert role_name == "general"

    async def test_garbage_response_returns_default(self) -> None:
        provider = FakeProvider("lolwut no json here 🤷")
        coordinator = Coordinator(provider, _make_registry())
        role_name, confidence = await coordinator.classify("Something")
        assert role_name == "general"
        assert confidence == 0.0

    async def test_provider_error_returns_default(self) -> None:
        provider = FailingProvider()
        coordinator = Coordinator(provider, _make_registry())
        role_name, confidence = await coordinator.classify("Hello")
        assert role_name == "general"
        assert confidence == 0.0

    async def test_classifier_model_override(self) -> None:
        """When classifier_model is set, it should be passed to the provider."""
        calls: list[dict] = []

        class SpyProvider(FakeProvider):
            async def chat(self, **kwargs: Any) -> LLMResponse:
                calls.append(kwargs)
                return LLMResponse(content='{"role": "general"}')

        provider = SpyProvider('{"role": "general"}')
        coordinator = Coordinator(provider, _make_registry(), classifier_model="gpt-4o-mini")
        await coordinator.classify("Hi")
        assert calls[0]["model"] == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# Coordinator.route_direct
# ---------------------------------------------------------------------------


class TestRouteDirect:
    def test_returns_role_config(self) -> None:
        coordinator = Coordinator(FakeProvider(""), _make_registry())
        role = coordinator.route_direct("code")
        assert role is not None
        assert role.name == "code"

    def test_unknown_role_returns_none(self) -> None:
        coordinator = Coordinator(FakeProvider(""), _make_registry())
        assert coordinator.route_direct("nonexistent") is None


# ---------------------------------------------------------------------------
# Coordinator.route
# ---------------------------------------------------------------------------


class TestRoute:
    async def test_route_returns_role_config(self) -> None:
        provider = FakeProvider('{"role": "research"}')
        coordinator = Coordinator(provider, _make_registry())
        role = await coordinator.route("Find papers on transformers")
        assert isinstance(role, AgentRoleConfig)
        assert role.name == "research"

    async def test_route_unknown_returns_default_config(self) -> None:
        provider = FakeProvider('{"role": "unknown"}')
        coordinator = Coordinator(provider, _make_registry())
        role = await coordinator.route("Something random")
        assert role.name == "general"

    async def test_route_on_error_returns_default(self) -> None:
        provider = FailingProvider()
        coordinator = Coordinator(provider, _make_registry())
        role = await coordinator.route("Help")
        assert role.name == "general"


# ---------------------------------------------------------------------------
# _parse_response (exercised indirectly via classify, test edge cases)
# ---------------------------------------------------------------------------


class TestParseResponse:
    def test_json_object(self) -> None:
        coordinator = Coordinator(FakeProvider(""), _make_registry())
        role, confidence, needs_orch, relevant = coordinator._parse_response('{"role": "code"}')
        assert role == "code"
        assert confidence == 1.0
        assert needs_orch is False
        assert relevant == []

    def test_json_with_confidence_field(self) -> None:
        coordinator = Coordinator(FakeProvider(""), _make_registry())
        role, confidence, _, _ = coordinator._parse_response('{"role": "code", "confidence": 0.75}')
        assert role == "code"
        assert confidence == 0.75

    def test_json_uppercase_normalised(self) -> None:
        coordinator = Coordinator(FakeProvider(""), _make_registry())
        role, _, _, _ = coordinator._parse_response('{"role": "CODE"}')
        assert role == "code"

    def test_plain_text_fallback(self) -> None:
        coordinator = Coordinator(FakeProvider(""), _make_registry())
        role, confidence, needs_orch, relevant = coordinator._parse_response(
            "Use the research agent"
        )
        assert role == "research"
        assert confidence == 0.5
        assert needs_orch is False
        assert relevant == []

    def test_no_match_returns_default(self) -> None:
        coordinator = Coordinator(FakeProvider(""), _make_registry())
        role, confidence, needs_orch, relevant = coordinator._parse_response("something random")
        assert role == "general"
        assert confidence == 0.0
        assert needs_orch is False
        assert relevant == []

    def test_confidence_clamped(self) -> None:
        coordinator = Coordinator(FakeProvider(""), _make_registry())
        _, conf, _, _ = coordinator._parse_response('{"role": "code", "confidence": 1.5}')
        assert conf == 1.0
        _, conf2, _, _ = coordinator._parse_response('{"role": "code", "confidence": -0.5}')
        assert conf2 == 0.0

    def test_needs_orchestration_parsed(self) -> None:
        coordinator = Coordinator(FakeProvider(""), _make_registry())
        role, confidence, needs_orch, relevant = coordinator._parse_response(
            '{"role": "code", "confidence": 0.9, '
            '"needs_orchestration": true, "relevant_roles": ["code", "writing"]}'
        )
        assert role == "code"
        assert confidence == 0.9
        assert needs_orch is True
        assert relevant == ["code", "writing"]

    def test_needs_orchestration_false_when_absent(self) -> None:
        coordinator = Coordinator(FakeProvider(""), _make_registry())
        _, _, needs_orch, relevant = coordinator._parse_response(
            '{"role": "code", "confidence": 0.8}'
        )
        assert needs_orch is False
        assert relevant == []

    def test_malformed_relevant_roles_ignored(self) -> None:
        coordinator = Coordinator(FakeProvider(""), _make_registry())
        _, _, _, relevant = coordinator._parse_response(
            '{"role": "code", "relevant_roles": "not-a-list"}'
        )
        assert relevant == []


class TestOrchestrationOverride:
    """Coordinator.classify() overrides to 'pm' based on LLM orchestration signal."""

    async def test_classify_overrides_to_pm_when_needs_orchestration(self) -> None:
        """When classifier says needs_orchestration=true, override to 'pm'."""
        provider = FakeProvider(
            '{"role": "code", "confidence": 0.9, '
            '"needs_orchestration": true, "relevant_roles": ["code", "writing"]}'
        )
        registry = build_default_registry("general")
        coordinator = Coordinator(provider, registry, default_role="general")
        role, _conf = await coordinator.classify(
            "Analyze code quality, investigate the subsystem architecture, "
            "and produce a comprehensive report"
        )
        assert role == "pm"

    async def test_classify_overrides_when_multiple_relevant_roles(self) -> None:
        """Even without needs_orchestration, 2+ relevant_roles triggers pm."""
        provider = FakeProvider(
            '{"role": "code", "confidence": 0.9, '
            '"needs_orchestration": false, "relevant_roles": ["code", "research"]}'
        )
        registry = build_default_registry("general")
        coordinator = Coordinator(provider, registry, default_role="general")
        role, _conf = await coordinator.classify("Do multiple things")
        assert role == "pm"

    async def test_classify_no_override_when_already_pm(self) -> None:
        """When classifier already returns 'pm', no override needed."""
        provider = FakeProvider('{"role": "pm", "confidence": 0.9, "needs_orchestration": true}')
        registry = build_default_registry("general")
        coordinator = Coordinator(provider, registry, default_role="general")
        role, _conf = await coordinator.classify(
            "Create a project report covering code and architecture"
        )
        assert role == "pm"

    async def test_classify_no_override_for_single_role(self) -> None:
        """Single-role, no orchestration needed → stays with classified role."""
        provider = FakeProvider(
            '{"role": "code", "confidence": 0.9, '
            '"needs_orchestration": false, "relevant_roles": ["code"]}'
        )
        registry = build_default_registry("general")
        coordinator = Coordinator(provider, registry, default_role="general")
        role, _conf = await coordinator.classify("Fix the bug in loop.py")
        assert role == "code"

    async def test_classify_backward_compat_old_format(self) -> None:
        """Old-format classifiers (no orchestration fields) don't trigger override."""
        provider = FakeProvider('{"role": "code", "confidence": 0.9}')
        registry = build_default_registry("general")
        coordinator = Coordinator(provider, registry, default_role="general")
        role, _conf = await coordinator.classify("Fix the bug in loop.py")
        assert role == "code"


# ---------------------------------------------------------------------------
# Integration: AgentLoop + Coordinator (full message flow)
# ---------------------------------------------------------------------------


def _make_agent_config(tmp_path: Path, **overrides: Any) -> AgentConfig:
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


class TestIntegrationRoutedFlow:
    """Integration: inbound message → coordinator routes → agent processes → response."""

    async def test_routed_message_uses_correct_role(self, tmp_path: Path) -> None:
        """Coordinator classifies as 'code', agent processes with code role settings."""
        from nanobot.agent.loop import AgentLoop
        from nanobot.bus.events import InboundMessage
        from nanobot.bus.queue import MessageBus

        # First call is the classifier (returns "code"), second is the agent response
        provider = ScriptedProvider(
            [
                LLMResponse(content='{"role": "code"}'),
                LLMResponse(content="Here is your function: def foo(): pass"),
            ]
        )
        routing = RoutingConfig(enabled=True, default_role="general")
        bus = MessageBus()
        loop = AgentLoop(
            bus,
            provider,
            _make_agent_config(tmp_path),
            routing_config=routing,
        )

        # Push a message to the bus and run one iteration
        await bus.publish_inbound(
            InboundMessage(channel="cli", chat_id="test", sender_id="user", content="Write code")
        )

        import asyncio

        loop._running = True
        # Manually trigger the coordinator lazy init
        await loop._connect_mcp()

        # Process one message directly through the coordinator path
        msg = await asyncio.wait_for(bus.consume_inbound(), timeout=1.0)
        # Manually init coordinator the same way run() does
        registry = build_default_registry(routing.default_role)
        loop._coordinator = Coordinator(
            provider=provider,
            registry=registry,
            classifier_model=routing.classifier_model,
            default_role=routing.default_role,
        )

        role = await loop._coordinator.route(msg.content)
        ctx = loop._apply_role_for_turn(role)
        assert loop.role_name == "code"
        response = await loop._process_message(msg)
        loop._reset_role_after_turn(ctx)

        assert response is not None
        assert "function" in response.content.lower() or "foo" in response.content.lower()

    async def test_routed_tool_filtering(self, tmp_path: Path) -> None:
        """When routed to 'research' role, write_file/edit_file are unavailable."""
        from nanobot.agent.loop import AgentLoop
        from nanobot.bus.queue import MessageBus

        provider = ScriptedProvider([LLMResponse(content="done")])
        bus = MessageBus()
        loop = AgentLoop(bus, provider, _make_agent_config(tmp_path))

        # Check baseline: all tools registered
        all_tool_names = loop.tools.tool_names
        assert "write_file" in all_tool_names
        assert "edit_file" in all_tool_names

        # Apply the research role (denies write_file and edit_file)
        research_role = AgentRoleConfig(
            name="research",
            description="Research",
            denied_tools=["write_file", "edit_file"],
        )
        ctx = loop._apply_role_for_turn(research_role)

        # Verify write tools are gone
        filtered_names = loop.tools.tool_names
        assert "write_file" not in filtered_names
        assert "edit_file" not in filtered_names
        assert "read_file" in filtered_names  # Still available

        # Reset and verify tools are restored
        loop._reset_role_after_turn(ctx)
        restored_names = loop.tools.tool_names
        assert "write_file" in restored_names
        assert "edit_file" in restored_names

    async def test_tool_filtering_with_allowlist(self, tmp_path: Path) -> None:
        """When a role specifies allowed_tools, only those are available."""
        from nanobot.agent.loop import AgentLoop
        from nanobot.bus.queue import MessageBus

        provider = ScriptedProvider([LLMResponse(content="done")])
        bus = MessageBus()
        loop = AgentLoop(bus, provider, _make_agent_config(tmp_path))

        role = AgentRoleConfig(
            name="minimal",
            description="Minimal",
            allowed_tools=["read_file", "list_dir"],
        )
        ctx = loop._apply_role_for_turn(role)
        names = loop.tools.tool_names
        assert set(names) == {"read_file", "list_dir"}

        loop._reset_role_after_turn(ctx)
        assert len(loop.tools.tool_names) > 2


class TestBackwardCompatibility:
    """Routing disabled (default) — behaves like single-agent."""

    async def test_routing_disabled_by_default(self, tmp_path: Path) -> None:
        """Without routing_config, coordinator is None and agent works normally."""
        from nanobot.agent.loop import AgentLoop
        from nanobot.bus.events import InboundMessage
        from nanobot.bus.queue import MessageBus

        provider = ScriptedProvider([LLMResponse(content="Hello!")])
        bus = MessageBus()
        loop = AgentLoop(bus, provider, _make_agent_config(tmp_path))

        assert loop._coordinator is None
        assert loop._routing_config is None

        msg = InboundMessage(channel="cli", chat_id="test", sender_id="user", content="Hi")
        response = await loop._process_message(msg)
        assert response is not None
        assert response.content == "Hello!"

    async def test_routing_config_disabled_flag(self, tmp_path: Path) -> None:
        """Explicit routing_config with enabled=False doesn't activate coordinator."""
        from nanobot.agent.loop import AgentLoop
        from nanobot.bus.queue import MessageBus

        routing = RoutingConfig(enabled=False)
        provider = ScriptedProvider([LLMResponse(content="Hi!")])
        bus = MessageBus()
        loop = AgentLoop(
            bus,
            provider,
            _make_agent_config(tmp_path),
            routing_config=routing,
        )

        # Coordinator should not be created even after a simulated run() start check
        assert loop._coordinator is None
        # The condition in run() checks routing_config.enabled — confirm it's False
        assert not routing.enabled

    async def test_no_role_no_tool_filtering(self, tmp_path: Path) -> None:
        """Without a role, all default tools are registered."""
        from nanobot.agent.loop import AgentLoop
        from nanobot.bus.queue import MessageBus

        provider = ScriptedProvider([LLMResponse(content="ok")])
        bus = MessageBus()
        loop = AgentLoop(bus, provider, _make_agent_config(tmp_path))

        names = loop.tools.tool_names
        # All core tools should be present
        for expected in ("read_file", "write_file", "edit_file", "list_dir", "exec"):
            assert expected in names, f"{expected} missing from tools"
