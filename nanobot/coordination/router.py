"""Message routing: classify → threshold → resolve role.

Extracted from ``AgentLoop._classify_and_route()`` so that routing is
coordination logic owned by ``coordination/``, not orchestration logic
scattered across entry points in ``agent/``.

See also ``nanobot.coordination.coordinator`` for the LLM classifier and
``nanobot.coordination.role_switching`` for per-turn role application.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from loguru import logger

from nanobot.config.schema import AgentRoleConfig
from nanobot.coordination.coordinator import ClassificationResult


class UnknownRoleError(Exception):
    """Raised when a forced_role name does not match any registered role."""

    def __init__(self, role_name: str) -> None:
        self.role_name = role_name
        super().__init__(f"Unknown role: {role_name}")


@dataclass(slots=True)
class RoutingDecision:
    """Result of message routing — a data object, not a side effect."""

    role: AgentRoleConfig
    classification: ClassificationResult


class MessageRouter:
    """Classifies messages and resolves the target role.

    Pure coordination logic extracted from ``AgentLoop._classify_and_route()``.
    No state mutation — returns a ``RoutingDecision`` data object.
    """

    def __init__(
        self,
        *,
        coordinator: Any,
        routing_config: Any,
        dispatcher: Any,
    ) -> None:
        self._coordinator = coordinator
        self._routing_config = routing_config
        self._dispatcher = dispatcher

    async def route(
        self,
        content: str,
        channel: str,
        *,
        forced_role: str | None = None,
    ) -> RoutingDecision | None:
        """Classify a message and resolve the target role.

        Returns ``None`` when the channel is ``"system"``.

        Raises ``UnknownRoleError`` when *forced_role* is provided but not
        found in the registry.

        When *forced_role* is provided, classification is skipped.
        """
        if channel == "system":
            return None

        if forced_role:
            role = self._coordinator.route_direct(forced_role)
            if role is None:
                raise UnknownRoleError(forced_role)
            cls_result = ClassificationResult(
                role_name=forced_role,
                confidence=1.0,
                needs_orchestration=False,
                relevant_roles=[forced_role],
            )
            self._dispatcher.record_route_trace(
                "route_forced",
                role=role.name,
                confidence=1.0,
                message_excerpt=content,
            )
            return RoutingDecision(role=role, classification=cls_result)

        t0 = time.monotonic()
        cls_result = await self._coordinator.classify(content)
        role_name = cls_result.role_name
        confidence = cls_result.confidence
        latency_ms = (time.monotonic() - t0) * 1000

        threshold = self._routing_config.confidence_threshold
        if confidence < threshold:
            role_name = self._routing_config.default_role
            logger.info(
                "Low confidence ({:.2f} < {:.2f}), using default role '{}'",
                confidence,
                threshold,
                role_name,
            )

        role = (
            self._coordinator.route_direct(role_name)
            or self._coordinator.registry.get_default()
            or AgentRoleConfig(name=role_name, description="General assistant")
        )
        self._dispatcher.record_route_trace(
            "route",
            role=role.name,
            confidence=confidence,
            latency_ms=latency_ms,
            message_excerpt=content,
        )
        return RoutingDecision(role=role, classification=cls_result)


__all__ = ["MessageRouter", "RoutingDecision", "UnknownRoleError"]
