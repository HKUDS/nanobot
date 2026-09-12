"""On-demand subscription quota readout for the configured owner."""

from __future__ import annotations

from typing import Any

from nanobot.agent.tools.base import Tool, ToolResult, tool_parameters
from nanobot.agent.tools.context import ToolContext, current_request_context
from nanobot.config.paths import get_runtime_subdir
from nanobot.operations.codex_limits import CodexLimits, CodexLimitsConfig, limits_report


@tool_parameters({"type": "object", "properties": {}, "additionalProperties": False})
class CodexLimitsTool(Tool):
    config_key = "codex_limits"

    def __init__(self, monitor: CodexLimits) -> None:
        self.monitor = monitor

    @classmethod
    def config_cls(cls) -> type[CodexLimitsConfig]:
        return CodexLimitsConfig

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return ctx.config.codex_limits.enable

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        return cls(CodexLimits(ctx.config.codex_limits, get_runtime_subdir("operations") / "codex-limits.json"))

    @property
    def name(self) -> str:
        return "codex_limits"

    @property
    def description(self) -> str:
        return "Read current Codex subscription quota windows, reset times and freshness. These are account quotas, distinct from session token use."

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        request = current_request_context()
        if request is None or request.session_key != self.monitor.config.owner_session_key:
            return ToolResult.error("Codex account limits are only available to the configured owner.")
        return limits_report(await self.monitor.snapshot())
