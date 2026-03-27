"""Agent components dataclass — the wiring contract between factory and loop.

``_AgentComponents`` is a pure data container populated by ``build_agent()``
in ``agent_factory.py`` and unpacked by ``AgentLoop.__init__`` in ``loop.py``.

It lives in its own module to break the import cycle between the factory
(which constructs AgentLoop) and the loop (which receives components).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from nanobot.agent.consolidation import ConsolidationOrchestrator
    from nanobot.agent.streaming import StreamingLLMCaller
    from nanobot.agent.turn_context import TurnContextManager
    from nanobot.agent.turn_types import Orchestrator, Processor
    from nanobot.bus.queue import MessageBus
    from nanobot.config.agent import AgentConfig
    from nanobot.config.schema import (
        AgentRoleConfig,
        ChannelsConfig,
        ExecToolConfig,
    )
    from nanobot.context.context import ContextBuilder
    from nanobot.coordination.delegation import DelegationDispatcher
    from nanobot.coordination.mission import MissionManager
    from nanobot.cron.service import CronService
    from nanobot.memory import MemoryStore
    from nanobot.memory.write.micro_extractor import MicroExtractor
    from nanobot.providers.base import LLMProvider
    from nanobot.session.manager import SessionManager
    from nanobot.tools.capability import CapabilityRegistry
    from nanobot.tools.executor import ToolExecutor
    from nanobot.tools.registry import ToolRegistry
    from nanobot.tools.result_cache import ToolResultCache


@dataclass(slots=True)
class _CoreConfig:
    """Model, workspace, and role identity."""

    model: str
    temperature: float
    max_iterations: int
    workspace: Path
    role_config: AgentRoleConfig | None
    role_name: str


@dataclass(slots=True)
class _InfraConfig:
    """External infrastructure: channels, MCP, exec policy."""

    channels_config: ChannelsConfig | None
    mcp_servers: dict
    brave_api_key: str | None
    exec_config: ExecToolConfig
    cron_service: CronService | None
    mcp_connector: Callable[..., Any] | None = None


@dataclass(slots=True)
class _Subsystems:
    """All constructed subsystem instances."""

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
    orchestrator: Orchestrator
    processor: Processor


@dataclass(slots=True)
class _ProcessorServices:
    """Subsystems consumed by MessageProcessor. Internal to agent/ package."""

    orchestrator: Orchestrator
    dispatcher: DelegationDispatcher
    missions: MissionManager
    context: ContextBuilder
    sessions: SessionManager
    tools: ToolExecutor
    consolidator: ConsolidationOrchestrator
    bus: MessageBus
    turn_context: TurnContextManager
    span_module: Any = None
    micro_extractor: MicroExtractor | None = None


@dataclass(slots=True)
class _AgentComponents:
    """All subsystem references needed by ``AgentLoop``.

    This is a pure data container — no logic.  ``build_agent()`` populates it
    and passes it to ``AgentLoop(components=...)``.

    Fields are grouped into nested dataclasses for clarity:
    - ``core``: model, workspace, role identity
    - ``infra``: external infrastructure config
    - ``subsystems``: all constructed subsystem instances
    """

    bus: MessageBus
    provider: LLMProvider
    config: AgentConfig
    core: _CoreConfig
    infra: _InfraConfig
    subsystems: _Subsystems
