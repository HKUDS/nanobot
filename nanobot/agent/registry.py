"""Named agent registry for long-lived peer agents."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.agent.context import ContextBuilder
from nanobot.agent.skills import BUILTIN_SKILLS_DIR
from nanobot.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.web import WebFetchTool, WebSearchTool
from nanobot.utils.helpers import ensure_dir

if TYPE_CHECKING:
    from nanobot.config.schema import ExecToolConfig, NamedAgentConfig, WebSearchConfig


@dataclass
class NamedAgent:
    """Runtime state for a named agent."""

    name: str
    config: "NamedAgentConfig"
    workspace: Path  # agent-specific workspace: {main_workspace}/agents/{name}/
    context: ContextBuilder
    tools: ToolRegistry


class AgentRegistry:
    """Manages named long-lived agents."""

    _REGISTRY_FILE = "registry.json"
    _MENTION_PATTERN = re.compile(r"^@(\S+)\s+([\s\S]*)", re.DOTALL)
    _RESERVED_NAMES = {"main", "nanobot"}  # used to switch back to main agent

    def __init__(
        self,
        workspace: Path,
        named_configs: dict[str, "NamedAgentConfig"] | None = None,
        *,
        main_model: str,
        web_search_config: "WebSearchConfig | None" = None,
        web_proxy: str | None = None,
        exec_config: "ExecToolConfig | None" = None,
        restrict_to_workspace: bool = False,
    ):
        from nanobot.config.schema import ExecToolConfig, WebSearchConfig

        self.workspace = workspace
        self.agents_dir = ensure_dir(workspace / "agents")
        self.main_model = main_model
        self.web_search_config = web_search_config or WebSearchConfig()
        self.web_proxy = web_proxy
        self.exec_config = exec_config or ExecToolConfig()
        self.restrict_to_workspace = restrict_to_workspace

        self._agents: dict[str, NamedAgent] = {}
        # name/alias → agent name mapping for fast lookup
        self._name_index: dict[str, str] = {}

        # Load from config
        for name, cfg in (named_configs or {}).items():
            self._init_agent(name, cfg)

        # Load runtime-registered agents from registry.json
        self._load_runtime_registry()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, name: str) -> NamedAgent | None:
        """Get a named agent by name or alias."""
        key = self._name_index.get(name)
        return self._agents.get(key) if key else None

    def list_agents(self) -> list[NamedAgent]:
        """List all registered named agents."""
        return list(self._agents.values())

    def match_mention(self, text: str) -> tuple[str, str] | None:
        """Match @agent_name prefix. Returns (agent_name, stripped_message) or None.

        Also matches reserved names (main, nanobot) for switching back.
        """
        m = self._MENTION_PATTERN.match(text.strip())
        if not m:
            return None
        mention = m.group(1)
        # Reserved names for switching back to main agent
        if mention.lower() in self._RESERVED_NAMES:
            return mention.lower(), m.group(2).strip()
        key = self._name_index.get(mention)
        if key is None:
            return None
        return key, m.group(2).strip()

    def register(self, name: str, config: "NamedAgentConfig") -> NamedAgent:
        """Register a new named agent at runtime."""
        if name.lower() in self._RESERVED_NAMES:
            raise ValueError(f"'{name}' is a reserved name and cannot be used for an agent.")
        if name in self._agents:
            # Update existing
            self.unregister(name)
        agent = self._init_agent(name, config)
        self._save_runtime_registry()
        logger.info("Registered named agent: {}", name)
        return agent

    def unregister(self, name: str) -> bool:
        """Unregister a named agent (keeps workspace data)."""
        if name not in self._agents:
            return False
        agent = self._agents.pop(name)
        # Remove from index
        to_remove = [k for k, v in self._name_index.items() if v == name]
        for k in to_remove:
            del self._name_index[k]
        self._save_runtime_registry()
        logger.info("Unregistered named agent: {}", name)
        return True

    def get_model(self, agent: NamedAgent) -> str:
        """Get the effective model for a named agent."""
        return agent.config.model or self.main_model

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _init_agent(self, name: str, config: "NamedAgentConfig") -> NamedAgent:
        """Initialize a named agent with its own workspace and tools."""
        agent_workspace = ensure_dir(self.agents_dir / name)
        ensure_dir(agent_workspace / "memory")

        context = ContextBuilder(
            agent_workspace,
            agent_name=name,
            custom_identity=config.identity or None,
            main_workspace=self.workspace,
        )
        tools = self._build_tools(agent_workspace)

        agent = NamedAgent(
            name=name,
            config=config,
            workspace=agent_workspace,
            context=context,
            tools=tools,
        )
        self._agents[name] = agent

        # Build name index
        self._name_index[name] = name
        for alias in config.aliases:
            self._name_index[alias] = name

        return agent

    def _build_tools(self, agent_workspace: Path) -> ToolRegistry:
        """Build the tool set for a named agent (no spawn/delegate/discuss/manage)."""
        tools = ToolRegistry()
        allowed_dir = self.workspace if self.restrict_to_workspace else None
        extra_read = [BUILTIN_SKILLS_DIR] if allowed_dir else None

        tools.register(ReadFileTool(workspace=agent_workspace, allowed_dir=allowed_dir, extra_allowed_dirs=extra_read))
        for cls in (WriteFileTool, EditFileTool, ListDirTool):
            tools.register(cls(workspace=agent_workspace, allowed_dir=allowed_dir))
        tools.register(ExecTool(
            working_dir=str(self.workspace),
            timeout=self.exec_config.timeout,
            restrict_to_workspace=self.restrict_to_workspace,
            path_append=self.exec_config.path_append,
        ))
        tools.register(WebSearchTool(config=self.web_search_config, proxy=self.web_proxy))
        tools.register(WebFetchTool(proxy=self.web_proxy))
        return tools

    def _load_runtime_registry(self) -> None:
        """Load runtime-registered agents from registry.json."""
        from nanobot.config.schema import NamedAgentConfig

        path = self.agents_dir / self._REGISTRY_FILE
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for name, cfg_dict in data.items():
                if name not in self._agents:
                    config = NamedAgentConfig(**cfg_dict)
                    self._init_agent(name, config)
            logger.info("Loaded {} runtime agents from registry", len(data))
        except Exception:
            logger.exception("Failed to load runtime agent registry")

    def _save_runtime_registry(self) -> None:
        """Save runtime-registered agents to registry.json."""
        path = self.agents_dir / self._REGISTRY_FILE
        data = {}
        for name, agent in self._agents.items():
            data[name] = {
                "aliases": agent.config.aliases,
                "identity": agent.config.identity,
                "model": agent.config.model,
                "max_iterations": agent.config.max_iterations,
                "tools": agent.config.tools,
            }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def build_agents_summary(self) -> str:
        """Build a summary of available agents for the main agent's system prompt."""
        if not self._agents:
            return ""
        lines = ["## Available Agents", "",
                 "You can delegate tasks to the following named agents using the `delegate` tool.",
                 "Users can also directly mention an agent with @name to route messages to them.", ""]
        for agent in self._agents.values():
            aliases = f" (aliases: {', '.join(agent.config.aliases)})" if agent.config.aliases else ""
            identity = agent.config.identity[:80] if agent.config.identity else "General assistant"
            model = agent.config.model or "(inherited)"
            lines.append(f"- **{agent.name}**{aliases}: {identity} [model: {model}]")
        return "\n".join(lines)
