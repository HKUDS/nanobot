"""Layered memory hooks for the agent runner."""

from __future__ import annotations

from typing import Any

from loguru import logger

from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.agent.layered_memory.facade import LayeredMemoryFacade

class LayeredMemoryHook(AgentHook):
    """Sync tool nodes after each tool batch and refresh canvas when configured."""

    __slots__ = ("_facade", "_is_subagent", "_session_key")

    def __init__(
        self,
        facade: LayeredMemoryFacade,
        session_key: str,
        *,
        is_subagent: bool = False,
    ) -> None:
        super().__init__()
        self._facade = facade
        self._session_key = session_key
        self._is_subagent = is_subagent

    async def after_tools(self, context: AgentHookContext) -> None:
        if not self._facade.config.offload_enabled(is_subagent=self._is_subagent):
            return
        if not context.tool_calls:
            return
        try:
            self._facade.sync_tool_nodes(
                session_key=self._session_key,
                tool_calls=context.tool_calls,
                tool_results=context.tool_results,
                is_subagent=self._is_subagent,
            )
            if self._facade.config.offload.update_canvas_every_n_tools == 0:
                self._facade.refresh_canvas(
                    self._session_key,
                    is_subagent=self._is_subagent,
                )
        except Exception:
            logger.exception(
                "LayeredMemoryHook.after_tools failed for session {}",
                self._session_key,
            )
