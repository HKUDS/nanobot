"""Agent factory: canonical entry point for constructing ``AgentLoop`` instances.

This module owns all wiring logic — subsystem construction, dependency
injection, tool registration.  ``AgentLoop.__init__`` is a slim receiver
that unpacks the ``_AgentComponents`` dataclass populated here.

See also ``nanobot/agent/tool_setup.py`` for the default tool registration
helper invoked by ``_build_tools()``.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nanobot.agent.agent_components import (
    _AgentComponents,
    _CoreConfig,
    _InfraConfig,
    _Subsystems,
)

if TYPE_CHECKING:
    from nanobot.agent.consolidation import ConsolidationOrchestrator
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.config.agent import AgentConfig
    from nanobot.config.schema import (
        AgentRoleConfig,
        ChannelsConfig,
        ExecToolConfig,
        RoutingConfig,
    )
    from nanobot.config.sub_agent import SubAgentConfig
    from nanobot.context.context import ContextBuilder
    from nanobot.coordination.mission import MissionManager
    from nanobot.cron.service import CronService
    from nanobot.providers.base import LLMProvider
    from nanobot.session.manager import SessionManager
    from nanobot.tools.capability import CapabilityRegistry
    from nanobot.tools.executor import ToolExecutor
    from nanobot.tools.registry import ToolRegistry
    from nanobot.tools.result_cache import ToolResultCache


@dataclass(slots=True)
class _ToolBuildResult:
    """Named result struct for ``_build_tools()``."""

    tools: ToolExecutor
    tool_registry: ToolRegistry
    capabilities: CapabilityRegistry
    result_cache: ToolResultCache
    missions: MissionManager


def _mcp_connector_fn() -> Any:
    """Return the ``connect_mcp_servers`` function, or *None* if MCP is unavailable."""
    try:
        from nanobot.tools.builtin.mcp import connect_mcp_servers

        return connect_mcp_servers
    except ImportError:
        return None


def _build_tools(
    *,
    tool_registry: ToolRegistry | None,
    context: ContextBuilder,
    provider: LLMProvider,
    config: AgentConfig,
    workspace: Path,
    bus: MessageBus,
    sub_agent_config: SubAgentConfig,
    brave_api_key: str | None,
    exec_config: ExecToolConfig,
    role_config: AgentRoleConfig | None,
    cron_service: CronService | None,
) -> _ToolBuildResult:
    """Construct and wire the tool / capability layer.

    Returns a ``_ToolBuildResult`` with the constructed subsystems.
    """
    from nanobot.coordination.mission import MissionManager
    from nanobot.tools.capability import CapabilityRegistry
    from nanobot.tools.executor import ToolExecutor
    from nanobot.tools.registry import ToolRegistry as _ToolRegistry
    from nanobot.tools.result_cache import ToolResultCache
    from nanobot.tools.setup import build_mission_tools, register_default_tools

    if tool_registry is not None:
        _tool_registry = tool_registry
    else:
        _tool_registry = _ToolRegistry()

    capabilities = CapabilityRegistry(
        tool_registry=_tool_registry,
        skills_loader=context.skills,
    )
    tools = ToolExecutor(_tool_registry)
    result_cache = ToolResultCache(workspace=workspace)
    capabilities.tool_registry.set_cache(
        result_cache,
        provider=provider,
        summary_model=config.tool_summary_model or None,
    )
    context.set_unavailable_tools_fn(capabilities.get_unavailable_summary)
    _mission_tools = build_mission_tools(
        workspace=workspace,
        restrict_to_workspace=config.restrict_to_workspace,
        exec_config=exec_config,
        brave_api_key=brave_api_key,
    )
    missions = MissionManager(
        sub_agent_config=sub_agent_config,
        provider=provider,
        bus=bus,
        max_iterations=config.mission.max_iterations,
        max_concurrent=config.mission.max_concurrent,
        result_max_chars=config.mission.result_max_chars,
        base_tools=_mission_tools,
    )
    if tool_registry is None:
        register_default_tools(
            capabilities=capabilities,
            role_config=role_config,
            workspace=workspace,
            restrict_to_workspace=config.restrict_to_workspace,
            shell_mode=config.shell_mode,
            vision_model=config.vision_model,
            exec_config=exec_config,
            brave_api_key=brave_api_key,
            publish_outbound=bus.publish_outbound,
            cron_service=cron_service,
            missions=missions,
            result_cache=result_cache,
            skills_enabled=config.skills_enabled,
            skills_loader=context.skills,
            feedback_db=context.memory.db if context.memory else None,
        )

    return _ToolBuildResult(
        tools=tools,
        tool_registry=capabilities.tool_registry,
        capabilities=capabilities,
        result_cache=result_cache,
        missions=missions,
    )


def _wire_memory(
    context: ContextBuilder,
    config: AgentConfig,
) -> ConsolidationOrchestrator:
    """Set up the memory consolidation subsystem.

    Returns a ``ConsolidationOrchestrator`` wired to the memory store
    inside *context*.
    """
    from nanobot.agent.consolidation import ConsolidationOrchestrator

    def _archive(messages: list[dict[str, Any]]) -> None:
        lines: list[str] = []
        for m in messages:
            content = m.get("content")
            if not content:
                continue
            tools_str = f" [tools: {', '.join(m['tools_used'])}]" if m.get("tools_used") else ""
            timestamp = str(m.get("timestamp", "?"))[:16]
            role = str(m.get("role", "unknown")).upper()
            lines.append(f"[{timestamp}] {role}{tools_str}: {content}")
        if lines:
            header = (
                f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}] "
                f"Fallback archive ({len(lines)} messages)"
            )
            text = header + "\n" + "\n".join(lines) + "\n\n"
            assert context.memory is not None  # always injected by build_agent
            context.memory.db.append_history(text)

    assert context.memory is not None  # always injected by build_agent
    return ConsolidationOrchestrator(
        memory=context.memory,
        archive_fn=_archive,
        max_concurrent=3,
        memory_window=config.memory.window,
        enable_contradiction_check=config.memory.enable_contradiction_check,
    )


def build_agent(
    bus: MessageBus,
    provider: LLMProvider,
    config: AgentConfig,
    *,
    brave_api_key: str | None = None,
    exec_config: ExecToolConfig | None = None,
    cron_service: CronService | None = None,
    session_manager: SessionManager | None = None,
    mcp_servers: dict | None = None,
    channels_config: ChannelsConfig | None = None,
    role_config: AgentRoleConfig | None = None,
    routing_config: RoutingConfig | None = None,  # accepted but unused; routing removed
    tool_registry: ToolRegistry | None = None,
) -> AgentLoop:
    """Construct a fully wired ``AgentLoop`` instance.

    This is the canonical entry point for creating an agent.  All CLI commands
    and test helpers should use this instead of ``AgentLoop()`` directly.
    """
    from nanobot.agent.loop import AgentLoop
    from nanobot.agent.message_processor import MessageProcessor
    from nanobot.agent.streaming import StreamingLLMCaller
    from nanobot.agent.turn_guardrails import (
        EmptyResultRecovery,
        FailureEscalation,
        GuardrailChain,
        NoProgressBudget,
        RepeatedStrategyDetection,
        SkillTunnelVision,
    )
    from nanobot.agent.turn_runner import TurnRunner
    from nanobot.config.schema import ExecToolConfig as _ExecToolConfig
    from nanobot.context.context import ContextBuilder
    from nanobot.memory import MemoryStore
    from nanobot.session.manager import SessionManager as _SessionManager

    # 1. Resolve model / temperature / max_iterations
    model = (
        (role_config.model if role_config and role_config.model else None)
        or config.model
        or provider.get_default_model()
    )
    max_iterations = (
        role_config.max_iterations
        if role_config and role_config.max_iterations is not None
        else config.max_iterations
    )
    temperature = (
        role_config.temperature
        if role_config and role_config.temperature is not None
        else config.temperature
    )
    resolved_exec_config = exec_config or _ExecToolConfig()

    from nanobot.config.sub_agent import SubAgentConfig

    sub_agent_config = SubAgentConfig(
        workspace=config.workspace_path,
        model=model,
        temperature=temperature,
        max_tokens=config.max_tokens,
    )

    # 2. Construct MemoryStore
    memory = MemoryStore(
        config.workspace_path,
        memory_config=config.memory,
    )

    # 3.5 Construct StrategyAccess for procedural memory (shares MemoryDatabase connection)
    from nanobot.memory.strategy import StrategyAccess

    strategy_store = StrategyAccess(memory.db.connection)

    # 4. Construct ContextBuilder
    context = ContextBuilder(
        config.workspace_path,
        memory=memory,
        memory_config=config.memory if config.memory_enabled else None,
        strategy_store=strategy_store,
    )

    # 5. Construct SessionManager
    sessions = session_manager or _SessionManager(config.workspace_path)

    # 6. Build tools
    _tool_build = _build_tools(
        tool_registry=tool_registry,
        context=context,
        provider=provider,
        config=config,
        workspace=config.workspace_path,
        bus=bus,
        sub_agent_config=sub_agent_config,
        brave_api_key=brave_api_key,
        exec_config=resolved_exec_config,
        role_config=role_config,
        cron_service=cron_service,
    )

    # 7. Wire memory
    consolidator = _wire_memory(context=context, config=config)

    # 9. Construct StreamingLLMCaller
    llm_caller = StreamingLLMCaller(
        provider=provider,
        model=model,
        temperature=temperature,
        max_tokens=config.max_tokens,
    )

    # 11. Construct TurnRunner with guardrails
    guardrails = GuardrailChain(
        [
            FailureEscalation(),
            NoProgressBudget(),
            RepeatedStrategyDetection(),
            EmptyResultRecovery(),
            SkillTunnelVision(),
        ]
    )
    orchestrator = TurnRunner(
        llm_caller=llm_caller,
        tool_executor=_tool_build.tools,
        guardrails=guardrails,
        context=context,
        config=config,
        provider=provider,
    )

    # 12.5 Construct TurnContextManager
    from nanobot.agent.turn_context import TurnContextManager
    from nanobot.coordination.scratchpad import Scratchpad

    turn_context = TurnContextManager(
        tools=_tool_build.tools,
        missions=_tool_build.missions,
        context=context,
        scratchpad_factory=Scratchpad,
    )

    # 13. Construct MicroExtractor (per-turn memory extraction)
    from nanobot.memory.write.micro_extractor import MicroExtractor as _MicroExtractor

    _micro_extractor: _MicroExtractor | None = None
    if config.memory.micro_extraction_enabled:
        _micro_extractor = _MicroExtractor(
            provider=provider,
            ingester=memory.ingester,
            model=config.memory.micro_extraction_model or "gpt-4o-mini",
            enabled=True,
        )

    # 13.2 Construct StrategyExtractor (procedural memory)
    from nanobot.memory.strategy_extractor import StrategyExtractor as _StrategyExtractor

    _strategy_extractor = _StrategyExtractor(
        store=strategy_store,
        provider=provider,
        model=model,
    )

    # 13.5. Construct _ProcessorServices and MessageProcessor
    from nanobot.agent.agent_components import _ProcessorServices

    services = _ProcessorServices(
        orchestrator=orchestrator,
        missions=_tool_build.missions,
        context=context,
        sessions=sessions,
        tools=_tool_build.tools,
        consolidator=consolidator,
        bus=bus,
        turn_context=turn_context,
        span_module=sys.modules["nanobot.agent.loop"],
        micro_extractor=_micro_extractor,
        strategy_extractor=_strategy_extractor,
    )
    processor = MessageProcessor(
        services=services,
        config=config,
        workspace=config.workspace_path,
        role_name=role_config.name if role_config else "",
        provider=provider,
        model=model,
    )

    # 14. Pack _AgentComponents (nested groups)
    _core = _CoreConfig(
        model=model,
        temperature=temperature,
        max_iterations=max_iterations,
        workspace=config.workspace_path,
        role_config=role_config,
        role_name=role_config.name if role_config else "",
    )
    _infra = _InfraConfig(
        channels_config=channels_config,
        mcp_servers=mcp_servers or {},
        brave_api_key=brave_api_key,
        exec_config=resolved_exec_config,
        cron_service=cron_service,
        mcp_connector=_mcp_connector_fn(),
    )
    _subs = _Subsystems(
        memory=memory,
        context=context,
        sessions=sessions,
        tools=_tool_build.tools,
        tool_registry=_tool_build.tool_registry,
        capabilities=_tool_build.capabilities,
        result_cache=_tool_build.result_cache,
        missions=_tool_build.missions,
        consolidator=consolidator,
        llm_caller=llm_caller,
        orchestrator=orchestrator,
        processor=processor,
    )
    components = _AgentComponents(
        bus=bus,
        provider=provider,
        config=config,
        core=_core,
        infra=_infra,
        subsystems=_subs,
    )

    # 15. Construct AgentLoop
    loop = AgentLoop(components=components)

    # 16. Return loop
    return loop
