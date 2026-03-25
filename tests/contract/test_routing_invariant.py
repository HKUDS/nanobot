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
