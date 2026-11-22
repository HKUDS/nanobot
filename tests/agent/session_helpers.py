from __future__ import annotations

import asyncio
import faulthandler
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypedDict, Unpack

from nanobot.agent.context import ContextBuilder
from nanobot.agent.execution_policy import ExecutionPolicy
from nanobot.agent.hook import AgentHook, AgentTurnHookFactory
from nanobot.agent.loop import AgentLoop
from nanobot.agent.model_presets import PresetCatalogLoader, PresetSnapshotLoader
from nanobot.agent.model_runtime import ModelRuntimeResolver
from nanobot.agent.subagent_status import SubagentStatus
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.turn_delivery import TurnDeliveryFactory
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.command import CommandRouter
from nanobot.config.network import NetworkConfig
from nanobot.config.schema import AgentDefaults, ModelPresetConfig, ToolsConfig
from nanobot.cron.service import CronService
from nanobot.providers.base import LLMProvider
from nanobot.providers.factory import ProviderSnapshot
from nanobot.runtime_context import (
    RUNTIME_CONTEXT_HISTORY_META,
    RUNTIME_CONTEXT_MESSAGE_META,
    public_history_message,
)
from nanobot.session.manager import SessionManager
from nanobot.session.recovery import RecoveryAdmission


class _LoopServices(TypedDict, total=False):
    builtin_assembly: Callable[[SessionManager, MessageBus, ToolRegistry, CommandRouter], ExecutionPolicy]
    cron_service: CronService
    hook_factories: list[AgentTurnHookFactory] | None
    hooks: list[AgentHook] | None
    recovery_admission: RecoveryAdmission | None
    runtime_model_publisher: Callable[[str, str | None], None]
    turn_delivery_factory: TurnDeliveryFactory


def make_agent_loop(
    *, workspace: Path, bus: MessageBus, provider: LLMProvider,
    model: str | None = None, context_window_tokens: int | None = None,
    model_presets: dict[str, ModelPresetConfig] | None = None, model_preset: str | None = None,
    provider_snapshot_loader: Callable[..., ProviderSnapshot] | None = None,
    provider_signature: tuple[object, ...] | None = None,
    preset_snapshot_loader: PresetSnapshotLoader | None = None,
    preset_catalog_loader: PresetCatalogLoader | None = None,
    max_tool_iterations: int | None = None, session_ttl_minutes: int = 0, timezone: str = "UTC",
    tools_config: ToolsConfig | None = None, tool_registry: ToolRegistry | None = None,
    context_builder: ContextBuilder | None = None, session_manager: SessionManager | None = None,
    **services: Unpack[_LoopServices],
) -> AgentLoop:
    """Compose a test loop with an isolated workspace and no background idle scan."""
    settings = AgentDefaults(
        workspace=str(workspace), timezone=timezone, session_ttl_minutes=session_ttl_minutes,
        idle_compact_check_interval_seconds=0,
    )
    if max_tool_iterations is not None:
        settings.max_tool_iterations = max_tool_iterations
    if context_window_tokens is not None:
        settings.context_window_tokens = context_window_tokens
    runtime = ModelRuntimeResolver.from_provider(
        provider, model=model, context_window_tokens=settings.context_window_tokens,
        model_presets=model_presets, model_preset=model_preset, provider_signature=provider_signature,
        provider_snapshot_loader=provider_snapshot_loader, preset_catalog_loader=preset_catalog_loader,
        preset_snapshot_loader=preset_snapshot_loader,
    )
    return AgentLoop(
        bus=bus, runtime_resolver=runtime, settings=settings,
        context_builder=context_builder if context_builder is not None else ContextBuilder(workspace, timezone=timezone),
        session_manager=session_manager if session_manager is not None else SessionManager(workspace),
        tool_registry=tool_registry if tool_registry is not None else ToolRegistry(),
        tools_config=tools_config if tools_config is not None else ToolsConfig(),
        network_config=NetworkConfig(), provider_snapshot_loader=provider_snapshot_loader, **services,
    )


def visible_message(message: dict) -> dict:
    """Project raw runner or persisted messages without model-only context."""
    marker = message.get("_meta", {}).get(RUNTIME_CONTEXT_MESSAGE_META)
    if marker is not None:
        message = {**message, RUNTIME_CONTEXT_HISTORY_META: marker}
    return public_history_message(message)


async def save_completed_subagent(loop: AgentLoop, task_id: str, owner: str) -> None:
    """Persist the child that owns a synthetic completion notification."""
    assert loop.subagents.sessions is not None
    now = time.monotonic()
    await loop.subagents.sessions.create(SubagentStatus(
        task_id=task_id, label=task_id, task_description="Background work",
        owner=owner, started_at=now, finished_at=now, completed_at=time.time(),
        state="done", phase="done",
    ))


async def run_session(loop: AgentLoop, msg: InboundMessage) -> None:
    """Submit input and wait for its session worker to finish."""
    await loop._enqueue_session_message(msg)
    await asyncio.gather(*loop._active_tasks[msg.session_key])


async def stop_loop(loop: AgentLoop, worker: asyncio.Task[None], *, timeout: float) -> None:
    """Stop an integration loop, retaining native shutdown stacks on timeout."""
    loop.stop()
    try:
        await asyncio.wait_for(worker, timeout=timeout)
    except TimeoutError:
        close_task = loop.sessions.state._close_task
        if close_task is not None:
            close_task.print_stack()
        faulthandler.dump_traceback()
        raise


def mock_session_manager(*_args, **_kwargs):
    """Model the asynchronous state boundary in scheduler-only unit tests."""
    from unittest.mock import AsyncMock, MagicMock

    from nanobot.session.manager import Session, SessionManager
    from nanobot.session.state import SessionState

    manager = MagicMock(spec=SessionManager)
    manager.get_or_create.side_effect = lambda key: Session(key=key)
    manager.state = MagicMock(spec=SessionState)
    manager.state.get = AsyncMock(side_effect=lambda key: manager.get_or_create(key))
    manager.state.read = AsyncMock(return_value=None)
    manager.state.read_metadata = AsyncMock(return_value=None)
    manager.state.list_sessions = AsyncMock(return_value=[])
    manager.state.peek.return_value = None
    return manager
