"""Mission tools — launch, query, and cancel background missions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, ClassVar

from nanobot.errors import ToolExecutionError
from nanobot.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from nanobot.coordination.mission import MissionManager


class MissionStartTool(Tool):
    """Launch a background mission for tasks that benefit from asynchronous execution.

    A *mission* runs in the background using a specialist agent, structured contracts,
    and the delegation engine's task taxonomy.  The user receives the result directly
    when the mission completes — there is no need to poll.
    """

    def __init__(self, manager: MissionManager):
        self._manager = manager
        self._origin_channel = "cli"
        self._origin_chat_id = "direct"
        self.readonly = False

    def set_context(self, channel: str, chat_id: str) -> None:
        """Set the origin context so mission results reach the correct channel."""
        self._origin_channel = channel
        self._origin_chat_id = chat_id

    name = "mission_start"
    description = (
        "Launch a background mission for independent tasks that can run asynchronously. "
        "Use when: (1) the user explicitly asks you to 'do this in the background' or "
        "'work on this while I do X'; (2) you identify a large investigation, code audit, "
        "or report that would benefit from focused specialist execution without blocking the "
        "conversation. The user will receive the result directly when the mission completes. "
        "Do NOT use for quick questions or tasks that need immediate answers."
    )
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": (
                    "A clear and specific description of the task. Include enough "
                    "context for an independent agent to complete it without follow-up. "
                    "Be precise about deliverables and scope."
                ),
            },
            "label": {
                "type": "string",
                "description": (
                    "Short display label for the mission (e.g. 'security audit', "
                    "'dependency report'). Defaults to a truncation of the task."
                ),
            },
            "context": {
                "type": "string",
                "description": (
                    "Optional additional context the mission agent should know — "
                    "conversation highlights, user preferences, or constraints."
                ),
            },
        },
        "required": ["task"],
    }

    async def execute(  # type: ignore[override]
        self,
        task: str,
        label: str | None = None,
        context: str | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        """Launch the background mission and return a confirmation."""
        try:
            mission = await self._manager.start(
                task=task,
                label=label,
                context=context,
                origin_channel=self._origin_channel,
                origin_chat_id=self._origin_chat_id,
            )
        except ToolExecutionError as exc:
            return ToolResult.fail(str(exc))
        return ToolResult.ok(
            f'Mission [{mission.id}] started — "{mission.label}" (role: {mission.role}). '
            f"The result will be delivered directly when complete."
        )


class MissionStatusTool(Tool):
    """Query the status and result of a background mission by ID."""

    def __init__(self, manager: MissionManager):
        self._manager = manager
        self.readonly = True

    name = "mission_status"
    description = (
        "Check the current status of a background mission. "
        "Returns the mission's status, role, grounding info, tools used, "
        "and result (if complete)."
    )
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "mission_id": {
                "type": "string",
                "description": "The 8-character hex mission ID returned by mission_start.",
            },
        },
        "required": ["mission_id"],
    }

    async def execute(self, mission_id: str, **kwargs: Any) -> ToolResult:  # type: ignore[override]
        """Return mission details as JSON."""
        mission = self._manager.get(mission_id)
        if not mission:
            return ToolResult.fail(f"Mission [{mission_id}] not found.")

        now = datetime.now(timezone.utc)
        elapsed = (mission.completed_at or now) - mission.created_at
        result_snippet = (
            mission.result[:500] + "…"
            if mission.result and len(mission.result) > 500
            else mission.result
        )

        info = {
            "id": mission.id,
            "label": mission.label,
            "status": mission.status.value,
            "role": mission.role,
            "grounded": mission.grounded,
            "tools_used": mission.tools_used,
            "elapsed_seconds": round(elapsed.total_seconds(), 1),
            "result": result_snippet,
        }
        return ToolResult.ok(json.dumps(info, indent=2))


class MissionListTool(Tool):
    """List all background missions and their statuses."""

    def __init__(self, manager: MissionManager):
        self._manager = manager
        self.readonly = True

    name = "mission_list"
    description = (
        "List background missions. Returns all missions by default, "
        "or filter by status (active, completed, failed, cancelled)."
    )
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "status_filter": {
                "type": "string",
                "enum": ["all", "active", "completed", "failed", "cancelled"],
                "description": "Filter missions by status. Default: all.",
            },
        },
    }

    async def execute(self, status_filter: str = "all", **kwargs: Any) -> ToolResult:  # type: ignore[override]
        """Return a formatted list of missions."""
        from nanobot.coordination.mission import MissionStatus

        missions = self._manager.list_all()
        if not missions:
            return ToolResult.ok("No missions found.")

        status_map = {
            "active": {MissionStatus.PENDING, MissionStatus.RUNNING},
            "completed": {MissionStatus.COMPLETED},
            "failed": {MissionStatus.FAILED},
            "cancelled": {MissionStatus.CANCELLED},
        }
        if status_filter != "all" and status_filter in status_map:
            allowed = status_map[status_filter]
            missions = [m for m in missions if m.status in allowed]

        if not missions:
            return ToolResult.ok(f"No {status_filter} missions found.")

        lines: list[str] = []
        for m in missions:
            grounded = "✓" if m.grounded else "–"
            lines.append(
                f"[{m.id}] {m.status.value:<10} {m.label:<30} role={m.role} grounded={grounded}"
            )
        return ToolResult.ok("\n".join(lines))


class MissionCancelTool(Tool):
    """Cancel a running background mission."""

    def __init__(self, manager: MissionManager):
        self._manager = manager
        self.readonly = False

    name = "mission_cancel"
    description = (
        "Cancel a running background mission. The mission will stop and "
        "the user will be notified. Cannot cancel already-completed missions."
    )
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "mission_id": {
                "type": "string",
                "description": "The 8-character hex mission ID to cancel.",
            },
        },
        "required": ["mission_id"],
    }

    async def execute(self, mission_id: str, **kwargs: Any) -> ToolResult:  # type: ignore[override]
        """Send cancellation signal to the mission."""
        cancelled = self._manager.cancel(mission_id)
        if cancelled:
            return ToolResult.ok(f"Mission [{mission_id}] cancel signal sent.")
        return ToolResult.fail(f"Mission [{mission_id}] not found or already in a terminal state.")
