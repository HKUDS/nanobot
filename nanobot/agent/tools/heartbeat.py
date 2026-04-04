from __future__ import annotations

from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema


@tool_parameters(
    tool_parameters_schema(
        action=StringSchema(
            "skip = nothing to do, run = has active tasks",
            enum=("skip", "run"),
        ),
        tasks=StringSchema(
            "Natural-language summary of active tasks (required for run)",
        ),
        required=["action"],
    )
)
class HeartbeatDecisionTool(Tool):
    @property
    def name(self) -> str:
        return "heartbeat"

    @property
    def description(self) -> str:
        return "Report heartbeat decision after reviewing tasks."

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        raise NotImplementedError(
            "Heartbeat decision is only expressed via LLM tool calls; this tool is not executed."
        )


HEARTBEAT_DECISION_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    HeartbeatDecisionTool().to_schema()
]
