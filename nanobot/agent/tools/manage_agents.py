"""Manage agents tool for runtime agent creation/removal."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot.agent.registry import AgentRegistry


class ManageAgentsTool(Tool):
    """Create, remove, list, or update named agents at runtime."""

    def __init__(self, registry: "AgentRegistry"):
        self._registry = registry

    @property
    def name(self) -> str:
        return "manage_agents"

    @property
    def description(self) -> str:
        return (
            "Manage named agents at runtime. Actions: "
            "create (add a new agent), remove (delete an agent), "
            "list (show all agents), update (modify an existing agent's config)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "remove", "list", "update"],
                    "description": "The action to perform",
                },
                "agent_name": {
                    "type": "string",
                    "description": "Name of the agent (required for create/remove/update)",
                },
                "identity": {
                    "type": "string",
                    "description": "Agent's identity/system prompt (for create/update)",
                },
                "aliases": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Alternative names for @mention routing (for create/update)",
                },
                "model": {
                    "type": ["string", "null"],
                    "description": "Override model for this agent; null = inherit main agent's model (for create/update)",
                },
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str,
        agent_name: str | None = None,
        identity: str | None = None,
        aliases: list[str] | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> str:
        if action == "list":
            return self._do_list()
        if action == "create":
            return self._do_create(agent_name, identity, aliases, model)
        if action == "remove":
            return self._do_remove(agent_name)
        if action == "update":
            return self._do_update(agent_name, identity, aliases, model)
        return f"Unknown action: {action}"

    def _do_list(self) -> str:
        agents = self._registry.list_agents()
        if not agents:
            return "No named agents registered."
        lines = ["Registered agents:"]
        for agent in agents:
            aliases = f" (aliases: {', '.join(agent.config.aliases)})" if agent.config.aliases else ""
            model = agent.config.model or "(inherited)"
            lines.append(f"  - {agent.name}{aliases} [model: {model}]")
        return "\n".join(lines)

    def _do_create(
        self,
        agent_name: str | None,
        identity: str | None,
        aliases: list[str] | None,
        model: str | None,
    ) -> str:
        if not agent_name:
            return "agent_name is required for create."
        from nanobot.config.schema import NamedAgentConfig

        config = NamedAgentConfig(
            aliases=aliases or [],
            identity=identity or "",
            model=model,
        )
        self._registry.register(agent_name, config)
        return f"Agent '{agent_name}' created successfully."

    def _do_remove(self, agent_name: str | None) -> str:
        if not agent_name:
            return "agent_name is required for remove."
        if self._registry.unregister(agent_name):
            return f"Agent '{agent_name}' removed."
        return f"Agent '{agent_name}' not found."

    def _do_update(
        self,
        agent_name: str | None,
        identity: str | None,
        aliases: list[str] | None,
        model: str | None,
    ) -> str:
        if not agent_name:
            return "agent_name is required for update."
        agent = self._registry.get(agent_name)
        if not agent:
            return f"Agent '{agent_name}' not found."

        # Merge updates into existing config
        cfg = agent.config
        if identity is not None:
            cfg.identity = identity
        if aliases is not None:
            cfg.aliases = aliases
        if model is not None:
            cfg.model = model

        # Re-register to rebuild context/tools and update index
        self._registry.register(agent_name, cfg)
        return f"Agent '{agent_name}' updated."
