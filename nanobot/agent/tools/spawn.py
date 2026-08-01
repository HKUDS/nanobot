"""Spawn tool for creating background subagents."""

# pyright: reportIncompatibleMethodOverride=false

from __future__ import annotations

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
    from nanobot.agent.model_runtime import ModelRuntimeResolver
    from nanobot.agent.subagent import SubagentManager
    from nanobot.agent.tools.context import ToolContext
    from nanobot.utils.llm_runtime import LLMRuntime


@tool_parameters(
    tool_parameters_schema(
        task=StringSchema("The task for the subagent to complete"),
        label=StringSchema("Optional short label for the task (for display)"),
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
        preset=StringSchema(
            description=(
                "Optional named model preset whose runtime (model + temperature) the "
                "subagent should use. When set, the subagent runs with that preset's "
                "generation settings regardless of the calling session's preset. "
                "Overrides the session runtime; mutually exclusive with temperature."
            ),
        ),
        required=["task"],
    )
)
class SpawnTool(Tool):
    """Tool to spawn a subagent for background task execution."""

    def __init__(
        self,
        manager: "SubagentManager",
        resolver: "ModelRuntimeResolver | None" = None,
    ):
        self._manager = manager
        self._resolver = resolver

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        manager = ctx.subagent_manager
        if manager is None:
            raise RuntimeError("SpawnTool requires an initialized subagent manager")
        return cls(manager=manager, resolver=ctx.runtime_resolver)

    @property
    def name(self) -> str:
        return "spawn"

    @property
    def description(self) -> str:
        return (
            "Spawn a subagent to handle a task in the background. "
            "Use this for complex or time-consuming tasks that can run independently. "
            "Set wait=true for a consultation whose result must inform the current turn. "
            "The subagent will complete the task and report back when done. "
            "For deliverables or existing projects, inspect the workspace first "
            "and use a dedicated subdirectory when helpful."
        )

    async def execute(
        self,
        task: str,
        label: str | None = None,
        temperature: float | None = None,
        wait: bool = False,
        preset: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Spawn a subagent to execute the given task."""
        running = self._manager.get_running_count()
        limit = self._manager.max_concurrent_subagents
        if running >= limit:
            return (
                f"Cannot spawn subagent: concurrency limit reached "
                f"({running}/{limit} running). Wait for a running subagent "
                f"to complete before spawning a new one."
            )
        request_ctx = current_request_context()
        if request_ctx is None or request_ctx.runtime is None:
            return ToolResult.error("Error: spawn requires an active model runtime")
        if preset is not None and temperature is not None:
            return ToolResult.error(
                "Error: 'preset' and 'temperature' are mutually exclusive; "
                "use one or the other."
            )
        if preset is not None:
            if self._resolver is None:
                return ToolResult.error(
                    "Error: preset resolution unavailable (no runtime resolver)."
                )
            try:
                runtime: "LLMRuntime" = self._resolver.resolve_preset(preset)
            except Exception as e:  # noqa: BLE001
                return ToolResult.error(f"Error: cannot resolve preset {preset!r}: {e}")
        else:
            runtime = request_ctx.runtime
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
