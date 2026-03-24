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
    from nanobot.agent.context import ContextBuilder
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.config.schema import (
        AgentConfig,
        AgentRoleConfig,
        ChannelsConfig,
        ExecToolConfig,
        RoutingConfig,
    )
    from nanobot.coordination.mission import MissionManager
    from nanobot.cron.service import CronService
    from nanobot.providers.base import LLMProvider
    from nanobot.session.manager import SessionManager
    from nanobot.tools.capability import CapabilityRegistry
    from nanobot.tools.executor import ToolExecutor
    from nanobot.tools.registry import ToolRegistry
    from nanobot.tools.result_cache import ToolResultCache


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _ToolBuildResult:
    """Named result struct for ``_build_tools()``."""

    tools: ToolExecutor
    tool_registry: ToolRegistry
    capabilities: CapabilityRegistry
    result_cache: ToolResultCache
    missions: MissionManager


def _build_rollout_overrides(config: AgentConfig) -> dict:
    """Extract memory rollout overrides from ``AgentConfig``."""
    return {
        "memory_rollout_mode": config.memory_rollout_mode,
        "memory_type_separation_enabled": config.memory_type_separation_enabled,
        "memory_router_enabled": config.memory_router_enabled,
        "memory_reflection_enabled": config.memory_reflection_enabled,
        "memory_shadow_mode": config.memory_shadow_mode,
        "memory_shadow_sample_rate": config.memory_shadow_sample_rate,
        "memory_vector_health_enabled": config.memory_vector_health_enabled,
        "memory_auto_reindex_on_empty_vector": config.memory_auto_reindex_on_empty_vector,
        "memory_history_fallback_enabled": config.memory_history_fallback_enabled,
        "conflict_auto_resolve_gap": config.memory_conflict_auto_resolve_gap,
        "memory_fallback_allowed_sources": config.memory_fallback_allowed_sources
        or ["profile", "events", "mem0_get_all"],
        "memory_fallback_max_summary_chars": config.memory_fallback_max_summary_chars,
        "rollout_gates": {
            "min_recall_at_k": config.memory_rollout_gate_min_recall_at_k,
            "min_precision_at_k": config.memory_rollout_gate_min_precision_at_k,
            "max_avg_memory_context_tokens": (
                config.memory_rollout_gate_max_avg_memory_context_tokens
            ),
            "max_history_fallback_ratio": config.memory_rollout_gate_max_history_fallback_ratio,
        },
        "graph_enabled": config.graph_enabled,
        "reranker_mode": config.reranker_mode,
        "reranker_alpha": config.reranker_alpha,
        "reranker_model": config.reranker_model,
        "mem0_user_id": config.mem0_user_id,
        "mem0_add_debug": config.mem0_add_debug,
        "mem0_verify_write": config.mem0_verify_write,
        "mem0_force_infer_true": config.mem0_force_infer_true,
    }


def _build_tools(
    *,
    tool_registry: ToolRegistry | None,
    context: ContextBuilder,
    provider: LLMProvider,
    config: AgentConfig,
    workspace: Path,
    bus: MessageBus,
    model: str,
    temperature: float,
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
    from nanobot.tools.setup import register_default_tools

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
    missions = MissionManager(
        provider=provider,
        workspace=workspace,
        bus=bus,
        model=model,
        temperature=temperature,
        max_tokens=config.max_tokens,
        max_iterations=config.mission_max_iterations,
        max_concurrent=config.mission_max_concurrent,
        result_max_chars=config.mission_result_max_chars,
        brave_api_key=brave_api_key,
        exec_config=exec_config,
        restrict_to_workspace=config.restrict_to_workspace,
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
            delegation_enabled=config.delegation_enabled,
            missions=missions,
            result_cache=result_cache,
            skills_enabled=config.skills_enabled,
            skills_loader=context.skills,
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
            if context.memory.db is not None:
                context.memory.db.append_history(text)
            else:
                # Fallback: write to HISTORY.md file directly.
                with open(context.memory.history_file, "a", encoding="utf-8") as f:
                    f.write(text)

    return ConsolidationOrchestrator(
        memory=context.memory,
        archive_fn=_archive,
        max_concurrent=3,
        memory_window=config.memory_window,
        enable_contradiction_check=config.memory_enable_contradiction_check,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


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
    routing_config: RoutingConfig | None = None,
    tool_registry: ToolRegistry | None = None,
) -> AgentLoop:
    """Construct a fully wired ``AgentLoop`` instance.

    This is the canonical entry point for creating an agent.  All CLI commands
    and test helpers should use this instead of ``AgentLoop()`` directly.
    """
    from nanobot.agent.context import ContextBuilder
    from nanobot.agent.loop import AgentLoop
    from nanobot.agent.message_processor import MessageProcessor
    from nanobot.agent.prompt_loader import prompts
    from nanobot.agent.streaming import StreamingLLMCaller
    from nanobot.agent.turn_orchestrator import TurnOrchestrator
    from nanobot.agent.verifier import AnswerVerifier
    from nanobot.config.schema import ExecToolConfig as _ExecToolConfig
    from nanobot.coordination.delegation import DelegationConfig, DelegationDispatcher
    from nanobot.coordination.delegation_advisor import DelegationAdvisor
    from nanobot.coordination.role_switching import TurnRoleManager
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

    # 2. Build rollout overrides
    memory_rollout_overrides = _build_rollout_overrides(config)

    # 3. Construct MemoryStore
    memory = MemoryStore(
        config.workspace_path,
        rollout_overrides=memory_rollout_overrides,
    )

    # 4. Construct ContextBuilder
    context = ContextBuilder(
        config.workspace_path,
        memory=memory,
        memory_retrieval_k=config.memory_retrieval_k if config.memory_enabled else 0,
        memory_token_budget=config.memory_token_budget if config.memory_enabled else 0,
        memory_md_token_cap=config.memory_md_token_cap if config.memory_enabled else 0,
        role_system_prompt=role_config.system_prompt if role_config else "",
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
        model=model,
        temperature=temperature,
        brave_api_key=brave_api_key,
        exec_config=resolved_exec_config,
        role_config=role_config,
        cron_service=cron_service,
    )

    # 7. Wire memory
    consolidator = _wire_memory(context=context, config=config)

    # 8. Construct DelegationDispatcher (tools wired at construction)
    dispatcher = DelegationDispatcher(
        config=DelegationConfig(
            workspace=config.workspace_path,
            model=model,
            temperature=temperature,
            max_tokens=config.max_tokens,
            max_iterations=max_iterations,
            restrict_to_workspace=config.restrict_to_workspace,
            brave_api_key=brave_api_key,
            exec_config=resolved_exec_config,
            role_name=role_config.name if role_config else "",
        ),
        provider=provider,
        tools=_tool_build.tools,
        max_delegation_depth=config.max_delegation_depth,
    )

    # 9. Construct DelegationAdvisor
    delegation_advisor = DelegationAdvisor()

    # 10. Construct StreamingLLMCaller
    llm_caller = StreamingLLMCaller(
        provider=provider,
        model=model,
        temperature=temperature,
        max_tokens=config.max_tokens,
    )

    # 11. Construct AnswerVerifier
    verifier = AnswerVerifier(
        provider=provider,
        model=model,
        temperature=temperature,
        max_tokens=config.max_tokens,
        verification_mode=config.verification_mode,
        memory_uncertainty_threshold=config.memory_uncertainty_threshold,
        memory_store=context.memory,
    )

    # 12. Construct TurnOrchestrator
    orchestrator = TurnOrchestrator(
        llm_caller=llm_caller,
        tool_executor=_tool_build.tools,
        verifier=verifier,
        dispatcher=dispatcher,
        delegation_advisor=delegation_advisor,
        config=config,
        prompts=prompts,
        context=context,
        provider=provider,
        model=model,
        role_name=role_config.name if role_config else "",
    )

    # 13. Construct MessageProcessor (role_manager wired post-construction
    #     via set_role_manager; span_module passed at construction time)
    processor = MessageProcessor(
        orchestrator=orchestrator,
        dispatcher=dispatcher,
        missions=_tool_build.missions,
        context=context,
        sessions=sessions,
        tools=_tool_build.tools,
        consolidator=consolidator,
        verifier=verifier,
        bus=bus,
        config=config,
        workspace=config.workspace_path,
        role_name=role_config.name if role_config else "",
        role_manager=None,
        provider=provider,
        model=model,
        span_module=sys.modules["nanobot.agent.loop"],
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
        routing_config=routing_config,
        channels_config=channels_config,
        mcp_servers=mcp_servers or {},
        brave_api_key=brave_api_key,
        exec_config=resolved_exec_config,
        cron_service=cron_service,
        memory_rollout_overrides=memory_rollout_overrides,
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
        dispatcher=dispatcher,
        delegation_advisor=delegation_advisor,
        llm_caller=llm_caller,
        verifier=verifier,
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
        role_manager=None,
    )

    # 15. Construct AgentLoop
    loop = AgentLoop(components=components)

    # 16. Post-construction wiring
    role_manager = TurnRoleManager(loop)
    loop._role_manager = role_manager
    loop._processor.set_role_manager(role_manager)  # public method

    # 17. Return loop
    return loop
