"""Agent pool for managing multiple agents."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable

from loguru import logger

from nanobot.agent.loop import AgentLoop
from nanobot.session.manager import SessionManager

if TYPE_CHECKING:
    from nanobot.bus.queue import MessageBus
    from nanobot.config.schema import Config
    from nanobot.providers.base import LLMProvider


class AgentPool:
    """Manages multiple AgentLoop instances and routes messages to them."""

    def __init__(
        self,
        config: Config,
        bus: MessageBus,
        provider_factory: Callable[[str, str | None], LLMProvider],
    ):
        self.config = config
        self.bus = bus
        self.provider_factory = provider_factory
        self._agents: dict[str, AgentLoop] = {}
        self._bindings: dict[tuple[str, str], str] = {}

        self._init_agents()
        self._init_bindings()

    def _init_agents(self) -> None:
        """Create AgentLoop instances from config."""
        if not self.config.agents.list:
            # Backward compatibility: create default agent
            defaults = self.config.agents.defaults
            workspace = Path(defaults.workspace).expanduser()
            model = defaults.model
            provider_name = defaults.provider if defaults.provider != "auto" else None
            provider = self.provider_factory(model, provider_name)

            agent = self._create_agent(
                agent_id="default",
                model=model,
                provider=provider,
                workspace=workspace,
                temperature=defaults.temperature,
                max_tokens=defaults.max_tokens,
                max_iterations=defaults.max_tool_iterations,
                memory_window=defaults.memory_window,
                reasoning_effort=defaults.reasoning_effort,
            )
            self._agents["default"] = agent
            logger.info("Created default agent")
        else:
            # Create agents from list
            for agent_config in self.config.agents.list:
                defaults = self.config.agents.defaults
                model = agent_config.model or defaults.model
                provider_name = agent_config.provider or defaults.provider
                if provider_name == "auto":
                    provider_name = None
                provider = self.provider_factory(model, provider_name)

                workspace_str = agent_config.workspace or defaults.workspace
                workspace = Path(workspace_str).expanduser() / agent_config.id

                agent = self._create_agent(
                    agent_id=agent_config.id,
                    model=model,
                    provider=provider,
                    workspace=workspace,
                    temperature=agent_config.temperature or defaults.temperature,
                    max_tokens=agent_config.max_tokens or defaults.max_tokens,
                    max_iterations=agent_config.max_tool_iterations or defaults.max_tool_iterations,
                    memory_window=agent_config.memory_window or defaults.memory_window,
                    reasoning_effort=agent_config.reasoning_effort or defaults.reasoning_effort,
                )
                self._agents[agent_config.id] = agent
                logger.info("Created agent: {}", agent_config.id)

    def _create_agent(
        self,
        agent_id: str,
        model: str,
        provider: LLMProvider,
        workspace: Path,
        temperature: float,
        max_tokens: int,
        max_iterations: int,
        memory_window: int,
        reasoning_effort: str | None,
    ) -> AgentLoop:
        """Create a single AgentLoop instance."""
        workspace.mkdir(parents=True, exist_ok=True)

        return AgentLoop(
            bus=self.bus,
            provider=provider,
            workspace=workspace,
            model=model,
            max_iterations=max_iterations,
            temperature=temperature,
            max_tokens=max_tokens,
            memory_window=memory_window,
            reasoning_effort=reasoning_effort,
            brave_api_key=self.config.tools.web.search.api_key,
            web_proxy=self.config.tools.web.proxy,
            exec_config=self.config.tools.exec,
            restrict_to_workspace=self.config.tools.restrict_to_workspace,
            session_manager=SessionManager(workspace),
            mcp_servers=self.config.tools.mcp_servers,
            channels_config=self.config.channels,
            openviking_config=self.config.tools.openviking,
        )

    def _init_bindings(self) -> None:
        """Build (channel, accountId) -> agentId map."""
        for binding in self.config.bindings:
            channel = binding.match.get("channel")
            account_id = binding.match.get("accountId")
            if channel and account_id:
                self._bindings[(channel, account_id)] = binding.agent_id

    def get_agent(self, channel: str, account_id: str) -> AgentLoop | None:
        """Get agent for the given channel and account_id."""
        agent_id = self._bindings.get((channel, account_id))
        if agent_id:
            return self._agents.get(agent_id)
        return None

    def get_default_agent(self) -> AgentLoop | None:
        """Get default agent for backward compatibility."""
        return self._agents.get("default")
