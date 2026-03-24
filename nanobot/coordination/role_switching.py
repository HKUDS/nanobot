"""Per-turn role switching for multi-agent routing.

Extracts ``TurnContext`` and ``TurnRoleManager`` from ``loop.py`` so that
role-override / restore logic is self-contained and testable in isolation.

See also ``nanobot.coordination.coordinator`` for intent classification and
``nanobot.coordination.delegation`` for cross-agent delegation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from loguru import logger

if TYPE_CHECKING:
    from nanobot.config.schema import AgentRoleConfig


class _LoopLike(Protocol):
    """Minimal interface that TurnRoleManager needs from AgentLoop.

    Using a Protocol instead of importing AgentLoop avoids a circular
    import between loop.py ↔ role_switching.py.
    """

    model: str
    temperature: float
    max_iterations: int
    role_name: str
    role_config: Any
    context: Any
    tools: Any
    _dispatcher: Any
    _capabilities: Any
    exec_config: Any


@dataclass(slots=True)
class TurnContext:
    """Snapshot of agent settings overridden for a single routed turn.

    Created by ``TurnRoleManager.apply`` and consumed by ``TurnRoleManager.reset``
    to cleanly restore the original configuration without touching shared state
    between turns.
    """

    model: str
    temperature: float
    max_iterations: int
    role_prompt: str
    tools: dict[str, Any] | None  # None → no tool filtering was applied


class TurnRoleManager:
    """Manages per-turn role switching for multi-agent routing.

    Holds a reference to the owning ``AgentLoop`` and provides ``apply`` /
    ``reset`` methods that temporarily override agent settings (model,
    temperature, max_iterations, system prompt, tools) for a single turn.
    """

    def __init__(self, loop: _LoopLike) -> None:
        self._loop = loop

    def apply(self, role: AgentRoleConfig) -> TurnContext:
        """Temporarily override agent settings for the current turn.

        Returns a ``TurnContext`` snapshot that must be passed to
        ``reset`` to restore the original configuration.
        """
        loop = self._loop

        # Only copy the tool registry when filtering will actually be applied.
        # Roles with no allowed/denied lists leave the registry unchanged, so
        # copying is wasted allocation.
        _will_filter = role.allowed_tools is not None or bool(role.denied_tools)
        ctx = TurnContext(
            model=loop.model,
            temperature=loop.temperature,
            max_iterations=loop.max_iterations,
            role_prompt=loop.context.role_system_prompt,
            tools=loop.tools.snapshot() if _will_filter else None,
        )

        if role.model:
            loop.model = role.model
        if role.temperature is not None:
            loop.temperature = role.temperature
        if role.max_iterations is not None:
            loop.max_iterations = role.max_iterations
        loop.context.role_system_prompt = role.system_prompt or ""
        loop.role_name = role.name
        loop._dispatcher.role_name = role.name  # Keep dispatcher in sync (LAN-194)

        # Apply role-specific tool filtering
        self._filter_tools(role)
        logger.debug("Applied role '{}' for turn (model={})", role.name, loop.model)
        return ctx

    def _filter_tools(self, role: AgentRoleConfig) -> None:
        """Remove tools that the role's allowed/denied lists exclude."""
        allowed = set(role.allowed_tools) if role.allowed_tools is not None else None
        denied = set(role.denied_tools) if role.denied_tools else set()
        if allowed is None and not denied:
            return
        for name in list(self._loop.tools.tool_names):
            if allowed is not None and name not in allowed:
                self._loop.tools.unregister(name)
            elif name in denied:
                self._loop.tools.unregister(name)

    def reset(self, ctx: TurnContext | None) -> None:
        """Restore original agent settings after a routed turn.

        ``ctx`` is the ``TurnContext`` returned by ``apply``.
        Passing ``None`` is a no-op (safe to call when no role was applied).
        """
        if ctx is None:
            return
        loop = self._loop
        loop.model = ctx.model
        loop.temperature = ctx.temperature
        loop.max_iterations = ctx.max_iterations
        loop.context.role_system_prompt = ctx.role_prompt
        loop.role_name = loop.role_config.name if loop.role_config else ""
        loop._dispatcher.role_name = loop.role_name  # Keep dispatcher in sync (LAN-194)
        # Restore full tool set (only non-None — None means no filtering was applied)
        if ctx.tools is not None:
            loop.tools.restore(ctx.tools)
