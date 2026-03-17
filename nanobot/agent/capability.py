"""Unified capability registry (ADR-009).

``CapabilityRegistry`` composes the existing ``ToolRegistry``,
``SkillsLoader``, and ``AgentRegistry`` behind a single facade that
tracks availability, health, and metadata for every capability the
agent can use.

Phase B: core dataclass + registry with register/query/execute API.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from nanobot.agent.tools.base import Tool, ToolResult
from nanobot.agent.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from nanobot.agent.registry import AgentRegistry
    from nanobot.agent.skills import SkillsLoader
    from nanobot.config.schema import AgentRoleConfig

logger = logging.getLogger(__name__)

CapabilityKind = Literal["tool", "skill", "delegate_role"]
CapabilityHealth = Literal["healthy", "degraded", "unavailable"]


@dataclass(slots=True)
class Capability:
    """A single capability the agent can use."""

    name: str
    kind: CapabilityKind
    description: str
    intents: list[str] = field(default_factory=list)
    health: CapabilityHealth = "healthy"
    unavailability_reason: str | None = None
    fallback_priority: int = 0

    # Back-references (exactly one is set per kind)
    tool: Tool | None = None
    skill_path: str | None = None
    role_config: AgentRoleConfig | None = None


class CapabilityRegistry:
    """Unified registry that composes ToolRegistry, SkillsLoader, and AgentRegistry.

    This is the single source of truth for "what can the agent do right now".
    Internally it delegates tool execution to ``ToolRegistry`` and delegates
    skill/role resolution to their respective subsystems.
    """

    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        skills_loader: SkillsLoader | None = None,
        agent_registry: AgentRegistry | None = None,
    ) -> None:
        self._tools = tool_registry if tool_registry is not None else ToolRegistry()
        self._skills = skills_loader
        self._agents = agent_registry
        self._capabilities: dict[str, Capability] = {}

    # ------------------------------------------------------------------
    # Properties — expose composed registries for backward compatibility
    # ------------------------------------------------------------------

    @property
    def tool_registry(self) -> ToolRegistry:
        return self._tools

    @property
    def skills_loader(self) -> SkillsLoader | None:
        return self._skills

    @property
    def agent_registry(self) -> AgentRegistry | None:
        return self._agents

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_tool(
        self,
        tool: Tool,
        *,
        intents: list[str] | None = None,
        fallback_priority: int = 0,
    ) -> None:
        """Register a tool and create a Capability entry for it."""
        self._tools.register(tool)
        available, reason = tool.check_available()
        health: CapabilityHealth = "healthy" if available else "unavailable"
        self._capabilities[tool.name] = Capability(
            name=tool.name,
            kind="tool",
            description=tool.description,
            intents=intents or [],
            health=health,
            unavailability_reason=reason,
            fallback_priority=fallback_priority,
            tool=tool,
        )

    def register_skill(
        self,
        name: str,
        *,
        description: str = "",
        path: str = "",
        intents: list[str] | None = None,
        available: bool = True,
        unavailability_reason: str | None = None,
    ) -> None:
        """Register a skill as a capability."""
        health: CapabilityHealth = "healthy" if available else "unavailable"
        self._capabilities[name] = Capability(
            name=name,
            kind="skill",
            description=description,
            intents=intents or [],
            health=health,
            unavailability_reason=unavailability_reason,
            skill_path=path,
        )

    def register_role(
        self,
        role: AgentRoleConfig,
        *,
        intents: list[str] | None = None,
    ) -> None:
        """Register a delegation role as a capability."""
        if self._agents is not None:
            self._agents.register(role)
        health: CapabilityHealth = "healthy" if role.enabled else "unavailable"
        self._capabilities[role.name] = Capability(
            name=role.name,
            kind="delegate_role",
            description=role.description,
            intents=intents or [],
            health=health,
            unavailability_reason=None if role.enabled else "role disabled",
            role_config=role,
        )

    def unregister(self, name: str) -> None:
        """Remove a capability (and its underlying tool if applicable)."""
        cap = self._capabilities.pop(name, None)
        if cap is not None and cap.kind == "tool":
            self._tools.unregister(name)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get(self, name: str) -> Capability | None:
        """Look up a capability by name."""
        return self._capabilities.get(name)

    def get_available(
        self,
        kind: CapabilityKind | None = None,
        intent: str | None = None,
    ) -> list[Capability]:
        """Return capabilities filtered by health, kind, and/or intent."""
        caps = [c for c in self._capabilities.values() if c.health != "unavailable"]
        if kind is not None:
            caps = [c for c in caps if c.kind == kind]
        if intent is not None:
            caps = [c for c in caps if intent in c.intents]
        caps.sort(key=lambda c: c.fallback_priority)
        return caps

    def get_unavailable(self) -> list[Capability]:
        """Return all unavailable capabilities."""
        return [c for c in self._capabilities.values() if c.health == "unavailable"]

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return OpenAI-format tool schemas for available tools only.

        Delegates to ``ToolRegistry.get_definitions()`` which already filters
        by ``check_available()``.
        """
        return self._tools.get_definitions()

    def get_unavailable_summary(self) -> str:
        """Human-readable summary of all unavailable capabilities.

        Includes both capabilities tracked in the registry *and* tools
        registered directly in the underlying ``ToolRegistry`` that report
        themselves unavailable via ``check_available()``.
        """
        lines: list[str] = []
        seen: set[str] = set()
        # 1. Check Capability entries (roles, skills, and any tools registered
        #    through register_tool())
        for cap in self._capabilities.values():
            if cap.health == "unavailable":
                lines.append(
                    f"- {cap.name} ({cap.kind}): {cap.unavailability_reason or 'unavailable'}"
                )
                seen.add(cap.name)
        # 2. Check ToolRegistry for tools registered directly (bypassing
        #    CapabilityRegistry.register_tool), e.g. via ToolExecutor.register()
        tool_summary = self._tools.get_unavailable_summary()
        if tool_summary:
            for line in tool_summary.splitlines():
                # Extract tool name from "- tool_name: reason" format
                name = line.lstrip("- ").split(":")[0].strip()
                if name and name not in seen:
                    lines.append(line)
        return "\n".join(lines)

    def role_names(self) -> list[str]:
        """Return names of all healthy delegation roles."""
        return [
            c.name
            for c in self._capabilities.values()
            if c.kind == "delegate_role" and c.health != "unavailable"
        ]

    # ------------------------------------------------------------------
    # Tool execution (delegates to ToolRegistry)
    # ------------------------------------------------------------------

    def get_tool(self, name: str) -> Tool | None:
        """Look up a tool by name."""
        return self._tools.get(name)

    async def execute_tool(self, name: str, params: dict[str, Any]) -> ToolResult:
        """Execute a tool by name."""
        return await self._tools.execute(name, params)

    # ------------------------------------------------------------------
    # Health refresh
    # ------------------------------------------------------------------

    def refresh_health(self) -> dict[str, CapabilityHealth]:
        """Re-check availability of all capabilities and return updated health map."""
        result: dict[str, CapabilityHealth] = {}
        for cap in self._capabilities.values():
            if cap.kind == "tool" and cap.tool is not None:
                available, reason = cap.tool.check_available()
                cap.health = "healthy" if available else "unavailable"
                cap.unavailability_reason = reason
            result[cap.name] = cap.health
        return result

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def all_capabilities(self) -> list[Capability]:
        """All registered capabilities regardless of health."""
        return list(self._capabilities.values())

    def __len__(self) -> int:
        return len(self._capabilities)

    def __contains__(self, name: str) -> bool:
        return name in self._capabilities
