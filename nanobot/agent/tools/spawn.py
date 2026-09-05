"""Spawn tool for creating background subagents."""

# pyright: reportIncompatibleMethodOverride=false

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import Tool, ToolResult, tool_parameters
from nanobot.agent.tools.context import current_request_context
from nanobot.agent.tools.schema import (
    BooleanSchema,
    NumberSchema,
    StringSchema,
    tool_parameters_schema,
)
from nanobot.security.workspace_access import current_workspace_scope

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager
    from nanobot.agent.tools.context import ToolContext
    from nanobot.utils.llm_runtime import LLMRuntime


@tool_parameters(
    tool_parameters_schema(
        task=StringSchema("The task for the subagent to complete"),
        label=StringSchema("Optional short label for the task (for display)"),
        preset=StringSchema(
            "Model preset for the subagent; only allowlisted presets are accepted"
        ),
        temperature=NumberSchema(
            description=(
                "Optional sampling temperature for the subagent "
                "(0.0 = deterministic, higher = more creative). "
                "Defaults to the provider's configured temperature."
            ),
            minimum=0.0,
            maximum=2.0,
        ),
        wait=BooleanSchema(
            description=(
                "Wait for the subagent and return its result directly. Use this for a "
                "blocking consultation that must inform the current turn. Defaults to "
                "false for background execution."
            ),
            default=False,
        ),
        required=["task"],
    )
)
class SpawnTool(Tool):
    """Tool to spawn a subagent for background task execution."""

    def __init__(
        self,
        manager: "SubagentManager",
        spawn_presets_loader: Callable[[], list[str]] | None = None,
        preset_runtime_resolver: Callable[[str], LLMRuntime] | None = None,
    ):
        self._manager = manager
        self._spawn_presets_loader: Callable[[], list[str]] = (
            spawn_presets_loader or (lambda: [])
        )
        self._preset_runtime_resolver = preset_runtime_resolver

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        manager = ctx.subagent_manager
        if manager is None:
            raise RuntimeError("SpawnTool requires an initialized subagent manager")
        return cls(
            manager=manager,
            spawn_presets_loader=ctx.spawn_presets_loader,
            preset_runtime_resolver=ctx.preset_runtime_resolver,
        )

    @property
    def name(self) -> str:
        return "spawn"

    @property
    def description(self) -> str:
        available = ", ".join(sorted(self._spawn_presets_loader())) or "(none)"
        return (
            "Spawn a subagent to handle a task in the background. "
            "Use this for complex or time-consuming tasks that can run independently. "
            "Set wait=true for a consultation whose result must inform the current turn. "
            "The subagent will complete the task and report back when done. "
            "For deliverables or existing projects, inspect the workspace first "
            "and use a dedicated subdirectory when helpful. "
            f"Available model presets: {available}."
        )

    @property
    def concurrency_safe(self) -> bool:
        """Each call owns its task state; the manager serializes capacity admission."""
        return True

    async def execute(
        self,
        task: str,
        label: str | None = None,
        preset: str | None = None,
        temperature: float | None = None,
        wait: bool = False,
        **kwargs: Any,
    ) -> str:
        """Spawn a subagent to execute the given task."""
        request_ctx = current_request_context()
        if request_ctx is None or request_ctx.runtime is None:
            return ToolResult.error("Error: spawn requires an active model runtime")
        runtime = request_ctx.runtime
        if preset is not None:
            spawn_presets = self._spawn_presets_loader()
            if preset not in spawn_presets:
                available = ", ".join(sorted(spawn_presets)) or "(none)"
                return ToolResult.error(
                    f"Error: spawn preset {preset!r} is not allowlisted. "
                    f"Available: {available}"
                )
            if self._preset_runtime_resolver is None:
                return ToolResult.error("Error: spawn preset resolution is unavailable")
            try:
                runtime = self._preset_runtime_resolver(preset)
            except (KeyError, ValueError) as exc:
                return ToolResult.error(
                    f"Error: failed to resolve spawn preset {preset!r}: {exc}"
                )
        origin_channel = request_ctx.channel
        origin_chat_id = request_ctx.chat_id
        session_key = request_ctx.session_key or f"{origin_channel}:{origin_chat_id}"
        method = self._manager.run_inline if wait else self._manager.spawn
        return await method(
            task=task,
            runtime=runtime,
            label=label,
            origin_channel=origin_channel,
            origin_chat_id=origin_chat_id,
            session_key=session_key,
            origin_message_id=request_ctx.message_id,
            temperature=temperature,
            workspace_scope=current_workspace_scope(),
        )
