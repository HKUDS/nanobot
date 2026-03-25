"""Contract tests: routing applies uniformly across all entry points."""

from __future__ import annotations

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.config.schema import AgentRoleConfig
from nanobot.coordination.coordinator import ClassificationResult


def test_inbound_message_has_forced_role_field() -> None:
    """InboundMessage accepts forced_role with None default."""
    msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="hello")
    assert msg.forced_role is None

    msg2 = InboundMessage(
        channel="cli",
        sender_id="user",
        chat_id="direct",
        content="hello",
        forced_role="code",
    )
    assert msg2.forced_role == "code"


@pytest.mark.asyncio
async def test_router_classifies_and_resolves_role():
    """MessageRouter.route() calls coordinator.classify and returns a RoutingDecision."""
    from nanobot.coordination.router import MessageRouter, RoutingDecision

    class StubCoordinator:
        classify_called = False

        async def classify(self, message):
            self.classify_called = True
            return ClassificationResult(
                role_name="pm",
                confidence=0.9,
                needs_orchestration=True,
                relevant_roles=["research", "writing"],
            )

        def route_direct(self, name):
            return AgentRoleConfig(name=name, description="test")

        class registry:  # noqa: N801
            @staticmethod
            def get_default():
                return AgentRoleConfig(name="general", description="fallback")

    class StubRoutingConfig:
        confidence_threshold = 0.6
        default_role = "general"

    class StubDispatcher:
        traces = []

        def record_route_trace(self, event, **kwargs):
            self.traces.append((event, kwargs))

    coord = StubCoordinator()
    dispatcher = StubDispatcher()
    router = MessageRouter(
        coordinator=coord,
        routing_config=StubRoutingConfig(),
        dispatcher=dispatcher,
    )

    decision = await router.route("multi-domain task", "web")
    assert isinstance(decision, RoutingDecision)
    assert decision.role.name == "pm"
    assert decision.classification.confidence == 0.9
    assert coord.classify_called


@pytest.mark.asyncio
async def test_router_forced_role_skips_classification():
    """When forced_role is provided, classification is skipped."""
    from nanobot.coordination.router import MessageRouter

    class StubCoordinator:
        classify_called = False

        async def classify(self, message):
            self.classify_called = True
            return ClassificationResult(role_name="general", confidence=1.0)

        def route_direct(self, name):
            return AgentRoleConfig(name=name, description="test")

        class registry:  # noqa: N801
            @staticmethod
            def get_default():
                return None

    class StubRoutingConfig:
        confidence_threshold = 0.6
        default_role = "general"

    class StubDispatcher:
        def record_route_trace(self, event, **kwargs):
            pass

    coord = StubCoordinator()
    router = MessageRouter(
        coordinator=coord,
        routing_config=StubRoutingConfig(),
        dispatcher=StubDispatcher(),
    )

    decision = await router.route("hello", "cli", forced_role="code")
    assert decision is not None
    assert decision.role.name == "code"
    assert not coord.classify_called


@pytest.mark.asyncio
async def test_router_unknown_forced_role_raises():
    """Unknown forced_role raises UnknownRoleError."""
    from nanobot.coordination.router import MessageRouter, UnknownRoleError

    class StubCoordinator:
        async def classify(self, message):
            return ClassificationResult(role_name="general", confidence=1.0)

        def route_direct(self, name):
            return None

        class registry:  # noqa: N801
            @staticmethod
            def get_default():
                return None

    class StubRoutingConfig:
        confidence_threshold = 0.6
        default_role = "general"

    class StubDispatcher:
        def record_route_trace(self, event, **kwargs):
            pass

    router = MessageRouter(
        coordinator=StubCoordinator(),
        routing_config=StubRoutingConfig(),
        dispatcher=StubDispatcher(),
    )

    with pytest.raises(UnknownRoleError, match="nonexistent"):
        await router.route("hello", "cli", forced_role="nonexistent")


@pytest.mark.asyncio
async def test_router_system_channel_skips_routing():
    """System channel messages return None (no routing)."""
    from nanobot.coordination.router import MessageRouter

    class StubCoordinator:
        classify_called = False

        async def classify(self, message):
            self.classify_called = True
            return ClassificationResult(role_name="general", confidence=1.0)

        def route_direct(self, name):
            return AgentRoleConfig(name=name, description="test")

        class registry:  # noqa: N801
            @staticmethod
            def get_default():
                return None

    class StubRoutingConfig:
        confidence_threshold = 0.6
        default_role = "general"

    class StubDispatcher:
        def record_route_trace(self, event, **kwargs):
            pass

    coord = StubCoordinator()
    router = MessageRouter(
        coordinator=coord,
        routing_config=StubRoutingConfig(),
        dispatcher=StubDispatcher(),
    )

    decision = await router.route("hello", "system")
    assert decision is None
    assert not coord.classify_called


@pytest.mark.asyncio
async def test_router_low_confidence_uses_default_role():
    """When confidence is below threshold, default role is used."""
    from nanobot.coordination.router import MessageRouter

    class StubCoordinator:
        async def classify(self, message):
            return ClassificationResult(role_name="code", confidence=0.3)

        def route_direct(self, name):
            return AgentRoleConfig(name=name, description="test")

        class registry:  # noqa: N801
            @staticmethod
            def get_default():
                return AgentRoleConfig(name="general", description="fallback")

    class StubRoutingConfig:
        confidence_threshold = 0.6
        default_role = "general"

    class StubDispatcher:
        traces = []

        def record_route_trace(self, event, **kwargs):
            self.traces.append((event, kwargs))

    router = MessageRouter(
        coordinator=StubCoordinator(),
        routing_config=StubRoutingConfig(),
        dispatcher=StubDispatcher(),
    )

    decision = await router.route("hello", "web")
    assert decision is not None
    assert decision.role.name == "general"


# ---------------------------------------------------------------------------
# Integration-level: routing fires through MessageProcessor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_direct_calls_router_when_available():
    """process_direct() must trigger router.route() when a router is wired."""
    from pathlib import Path
    from unittest.mock import AsyncMock, MagicMock

    from nanobot.agent.agent_components import _ProcessorServices
    from nanobot.agent.message_processor import MessageProcessor
    from nanobot.config.schema import AgentConfig
    from nanobot.coordination.router import MessageRouter
    from nanobot.providers.base import LLMResponse
    from tests.helpers import ScriptedProvider

    # Router returns None → no role-switch, but route() must still be called.
    mock_router = MagicMock(spec=MessageRouter)
    mock_router.route = AsyncMock(return_value=None)

    provider = ScriptedProvider([LLMResponse(content="ok")])

    # Minimal session stub — needs a real list for session.messages.
    mock_session = MagicMock()
    mock_session.messages = []
    mock_session.last_consolidated = 0
    mock_session.get_history = MagicMock(return_value=[])
    mock_session.updated_at = None

    # Turn result stub — _run_orchestrator reads .content/.tools_used/.messages.
    mock_turn_result = MagicMock()
    mock_turn_result.content = "ok"
    mock_turn_result.tools_used = []
    mock_turn_result.messages = []

    mock_orchestrator = MagicMock()
    mock_orchestrator.run = AsyncMock(return_value=mock_turn_result)

    mock_bus = MagicMock()
    mock_bus.publish_outbound = AsyncMock(return_value=None)

    mock_tools = MagicMock()
    mock_tools.get = MagicMock(return_value=None)
    mock_tools.get_definitions = MagicMock(return_value=[])

    mock_context = MagicMock()
    mock_context.memory = MagicMock()  # must be non-None (asserted in processor)
    mock_context.skills = MagicMock()
    mock_context.skills.detect_relevant_skills = MagicMock(return_value=[])
    mock_context.build_messages = AsyncMock(return_value=[])
    mock_context.add_assistant_message = MagicMock(return_value=[])

    mock_sessions = MagicMock()
    mock_sessions.get_or_create = MagicMock(return_value=mock_session)
    mock_sessions.save = MagicMock()

    mock_verifier = MagicMock()
    mock_verifier.should_force_verification = MagicMock(return_value=False)
    mock_verifier.attempt_recovery = AsyncMock(return_value=None)

    mock_turn_context = MagicMock()
    mock_turn_context.set_tool_context = MagicMock()
    mock_turn_context.ensure_scratchpad = MagicMock()

    services = MagicMock(spec=_ProcessorServices)
    services.orchestrator = mock_orchestrator
    services.dispatcher = MagicMock()
    services.missions = MagicMock()
    services.context = mock_context
    services.sessions = mock_sessions
    services.tools = mock_tools
    services.consolidator = MagicMock()
    services.verifier = mock_verifier
    services.bus = mock_bus
    services.turn_context = mock_turn_context
    services.span_module = None

    config = MagicMock(spec=AgentConfig)
    config.memory_window = 10
    config.memory_enabled = False
    config.streaming_enabled = False
    config.tool_result_max_chars = 2000

    processor = MessageProcessor(
        services=services,
        config=config,
        workspace=Path("/tmp/test"),
        role_name="general",
        provider=provider,
        model="test-model",
        router=mock_router,
    )

    await processor.process_direct("test message")

    # The router must have been called with the message content and channel.
    mock_router.route.assert_called_once()
    call_args = mock_router.route.call_args
    assert call_args[0][0] == "test message"  # content positional arg
    assert call_args[0][1] == "cli"  # channel positional arg


@pytest.mark.asyncio
async def test_unknown_forced_role_returns_error_message():
    """process_direct(forced_role='bad') must return error, not silently use defaults."""
    from pathlib import Path
    from unittest.mock import AsyncMock, MagicMock

    from nanobot.agent.agent_components import _ProcessorServices
    from nanobot.agent.message_processor import MessageProcessor
    from nanobot.config.schema import AgentConfig
    from nanobot.coordination.router import MessageRouter, UnknownRoleError
    from nanobot.providers.base import LLMResponse
    from tests.helpers import ScriptedProvider

    # Router raises UnknownRoleError — processor must return the error string.
    mock_router = MagicMock(spec=MessageRouter)
    mock_router.route = AsyncMock(side_effect=UnknownRoleError("bad"))

    provider = ScriptedProvider([LLMResponse(content="ok")])

    # UnknownRoleError is caught before any services are touched,
    # so only a minimal services stub is required.
    services = MagicMock(spec=_ProcessorServices)
    services.span_module = None

    config = MagicMock(spec=AgentConfig)
    config.memory_window = 10
    config.memory_enabled = False

    processor = MessageProcessor(
        services=services,
        config=config,
        workspace=Path("/tmp/test"),
        role_name="general",
        provider=provider,
        model="test-model",
        router=mock_router,
    )

    result = await processor.process_direct("hello", forced_role="bad")

    assert "Unknown role: bad" in result
