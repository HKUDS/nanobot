from __future__ import annotations

from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import BooleanSchema, StringSchema, tool_parameters_schema


@tool_parameters(
    tool_parameters_schema(
        should_notify=BooleanSchema(
            description=(
                "true = result contains actionable/important info the user should see; "
                "false = routine or empty, safe to suppress"
            ),
        ),
        reason=StringSchema("One-sentence reason for the decision"),
        required=["should_notify"],
    )
)
class EvaluateNotificationTool(Tool):
    @property
    def name(self) -> str:
        return "evaluate_notification"

    @property
    def description(self) -> str:
        return "Decide whether the user should be notified about this background task result."

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        raise NotImplementedError(
            "Notification evaluation is only expressed via LLM tool calls; this tool is not executed."
        )


EVALUATE_NOTIFICATION_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    EvaluateNotificationTool().to_schema()
]
