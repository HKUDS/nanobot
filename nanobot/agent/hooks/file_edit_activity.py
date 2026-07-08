"""Agent hook that observes file-editing tools and emits file-edit activity."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from nanobot.agent.hook import AgentHook, AgentHookContext, AgentTurnHookContext
from nanobot.providers.base import ToolCallRequest
from nanobot.utils.file_edit_events import (
    FileEditTracker,
    build_file_edit_end_event,
    build_file_edit_error_event,
    build_file_edit_start_event,
    prepare_file_edit_trackers,
)
from nanobot.utils.progress_events import (
    invoke_file_edit_progress,
    on_progress_accepts_file_edit_events,
)


class FileEditActivityHook(AgentHook):
    """Translate file-editing tool lifecycle events into WebUI progress events."""

    def __init__(
        self,
        *,
        on_progress: Callable[..., Awaitable[None]] | None,
        workspace: Path | None,
    ) -> None:
        super().__init__()
        self._on_progress = (
            on_progress
            if on_progress is not None and on_progress_accepts_file_edit_events(on_progress)
            else None
        )
        self._workspace = workspace
        self._trackers_by_call: dict[str, list[FileEditTracker]] = {}

    async def before_iteration(self, context: AgentHookContext) -> None:
        self._trackers_by_call.clear()

    async def before_execute_tool(
        self,
        context: AgentHookContext,
        tool_call: ToolCallRequest,
        tool: Any,
        params: Any,
    ) -> None:
        if self._on_progress is None or not isinstance(params, dict):
            return
        trackers = prepare_file_edit_trackers(
            call_id=tool_call.id,
            tool_name=tool_call.name,
            tool=tool,
            workspace=self._workspace,
            params=params,
        )
        if not trackers:
            return
        self._trackers_by_call[self._tool_call_key(tool_call)] = trackers
        await self._emit([build_file_edit_start_event(tracker, params) for tracker in trackers])

    async def after_execute_tool(
        self,
        context: AgentHookContext,
        tool_call: ToolCallRequest,
        tool: Any,
        params: Any,
        result: Any,
    ) -> None:
        trackers = self._trackers_by_call.pop(self._tool_call_key(tool_call), [])
        if trackers:
            await self._emit([build_file_edit_end_event(tracker) for tracker in trackers])

    async def on_execute_tool_error(
        self,
        context: AgentHookContext,
        tool_call: ToolCallRequest,
        tool: Any,
        params: Any,
        error: Any,
    ) -> None:
        trackers = self._trackers_by_call.pop(self._tool_call_key(tool_call), [])
        if trackers:
            await self._emit([
                build_file_edit_error_event(tracker, str(error)) for tracker in trackers
            ])

    async def _emit(self, events: list[dict[str, Any]]) -> None:
        if self._on_progress is not None:
            await invoke_file_edit_progress(self._on_progress, events)

    @staticmethod
    def _tool_call_key(tool_call: ToolCallRequest) -> str:
        call_id = getattr(tool_call, "id", "") or ""
        return f"{call_id}|{tool_call.name}" if call_id else f"{id(tool_call)}|{tool_call.name}"


def create_file_edit_activity_hook(context: AgentTurnHookContext) -> AgentHook | None:
    """Create the default file-edit observer for one agent turn."""
    if context.on_progress is None:
        return None
    return FileEditActivityHook(
        on_progress=context.on_progress,
        workspace=context.workspace,
    )
