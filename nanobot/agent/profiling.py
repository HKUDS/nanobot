"""Lightweight profiling hook and timing infrastructure for the agent loop."""

from __future__ import annotations

import os
import time
from typing import Any

from loguru import logger

from nanobot.agent.hook import AgentHook, AgentHookContext


def is_profiling_enabled(agent_defaults: Any = None) -> bool:
    """Check if profiling is enabled via env var or config."""
    if os.environ.get("NANOBOT_PROFILING", "").strip() in ("1", "true", "yes"):
        return True
    if isinstance(agent_defaults, dict):
        return bool(agent_defaults.get("profiling", False))
    return bool(getattr(agent_defaults, "profiling", False))


class ProfilingHook(AgentHook):
    """Records wall-clock timing between AgentHook lifecycle events."""

    def __init__(self) -> None:
        super().__init__()
        self._iter_start: float = 0.0
        self._tools_start: float = 0.0
        self.last_iteration_ms: float = 0.0
        self.last_tool_batch_ms: float = 0.0
        self.total_iterations: int = 0

    async def before_iteration(self, context: AgentHookContext) -> None:
        self._iter_start = time.perf_counter()
        self._tools_start = 0.0

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        self._tools_start = time.perf_counter()

    async def after_iteration(self, context: AgentHookContext) -> None:
        now = time.perf_counter()
        if self._iter_start:
            self.last_iteration_ms = (now - self._iter_start) * 1000
        if self._tools_start:
            self.last_tool_batch_ms = (now - self._tools_start) * 1000
            self._tools_start = 0.0
        else:
            self.last_tool_batch_ms = 0.0

        self.total_iterations += 1
        logger.debug(
            "[profiling] iter {}: {:.0f}ms total, {:.0f}ms tools",
            context.iteration,
            self.last_iteration_ms,
            self.last_tool_batch_ms,
        )
