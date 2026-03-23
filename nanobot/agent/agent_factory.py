"""Agent factory: canonical entry point for constructing ``AgentLoop`` instances.

This module will eventually own all wiring logic (subsystem construction,
dependency injection, tool registration).  For now it is a thin delegation
layer that forwards every parameter to the existing ``AgentLoop.__init__``.

Migration path (see refactoring plan):
  1. (this file) ``build_agent()`` delegates to ``AgentLoop(...)``
  2. Callers are migrated from ``AgentLoop(...)`` to ``build_agent(...)``
  3. Wiring logic moves *out of* ``AgentLoop.__init__`` into ``build_agent``
  4. ``AgentLoop.__init__`` becomes a slim receiver of pre-built components
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nanobot.agent.capability import CapabilityRegistry
    from nanobot.agent.consolidation import ConsolidationOrchestrator
    from nanobot.agent.context import ContextBuilder
    from nanobot.agent.delegation import DelegationDispatcher
    from nanobot.agent.loop import AgentLoop
    from nanobot.agent.memory import MemoryStore
    from nanobot.agent.mission import MissionManager
    from nanobot.agent.role_switching import TurnRoleManager
    from nanobot.agent.streaming import StreamingLLMCaller
    from nanobot.agent.tool_executor import ToolExecutor
    from nanobot.agent.tools.cron import CronTool
    from nanobot.agent.tools.feedback import FeedbackTool
    from nanobot.agent.tools.message import MessageTool
    from nanobot.agent.tools.mission import MissionStartTool
    from nanobot.agent.tools.registry import ToolRegistry
    from nanobot.agent.tools.result_cache import ToolResultCache
    from nanobot.agent.turn_orchestrator import TurnOrchestrator
    from nanobot.agent.verifier import AnswerVerifier
    from nanobot.bus.queue import MessageBus
    from nanobot.config.schema import (
        AgentConfig,
        AgentRoleConfig,
        ChannelsConfig,
        ExecToolConfig,
        RoutingConfig,
    )
    from nanobot.cron.service import CronService
    from nanobot.providers.base import LLMProvider
    from nanobot.session.manager import SessionManager


@dataclass(slots=True)
class _AgentComponents:
    """All subsystem references needed by ``AgentLoop``.

    This is a pure data container — no logic.  ``build_agent()`` will populate
    it once the wiring logic migrates out of ``AgentLoop.__init__`` (Task 4).
    """

    # --- core refs ---
    bus: MessageBus
    provider: LLMProvider
    config: AgentConfig
    workspace: Path
    model: str
    temperature: float
    max_iterations: int

    # --- role / routing ---
    role_config: AgentRoleConfig | None
    role_name: str
    routing_config: RoutingConfig | None
    channels_config: ChannelsConfig | None

    # --- external config ---
    mcp_servers: dict
    brave_api_key: str | None
    exec_config: ExecToolConfig
    cron_service: CronService | None
    memory_rollout_overrides: dict

    # --- subsystems ---
    memory: MemoryStore
    context: ContextBuilder
    sessions: SessionManager
    tools: ToolExecutor
    tool_registry: ToolRegistry
    capabilities: CapabilityRegistry
    result_cache: ToolResultCache
    missions: MissionManager
    consolidator: ConsolidationOrchestrator
    dispatcher: DelegationDispatcher
    llm_caller: StreamingLLMCaller
    verifier: AnswerVerifier
    orchestrator: TurnOrchestrator

    # --- wired post-construction ---
    role_manager: TurnRoleManager | None = None

    # --- cached tool refs (O(1) context updates) ---
    ctx_message_tool: MessageTool | None = None
    ctx_feedback_tool: FeedbackTool | None = None
    ctx_mission_tool: MissionStartTool | None = None
    ctx_cron_tool: CronTool | None = None


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

    For now the function simply delegates to the existing ``AgentLoop.__init__``.
    Once callers are migrated, the wiring logic will move here and
    ``AgentLoop.__init__`` will accept a slim ``_AgentComponents`` instead.
    """
    from nanobot.agent.loop import AgentLoop

    return AgentLoop(
        bus=bus,
        provider=provider,
        config=config,
        brave_api_key=brave_api_key,
        exec_config=exec_config,
        cron_service=cron_service,
        session_manager=session_manager,
        mcp_servers=mcp_servers,
        channels_config=channels_config,
        role_config=role_config,
        routing_config=routing_config,
        tool_registry=tool_registry,
    )
