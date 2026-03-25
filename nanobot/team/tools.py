from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import Tool
from . import board, mailbox

if TYPE_CHECKING:
    from nanobot.team import TeamManager


class TeamWorkerTool(Tool):
    def __init__(self, manager: "TeamManager", worker_name: str, session_key: str):
        self._manager = manager
        self._worker_name = worker_name
        self._session_key = session_key

    @property
    def name(self) -> str:
        return "team_worker"

    @property
    def description(self) -> str:
        return "Team coordination. Actions: board, claim, complete, submit_plan, mail_send, mail_read, mail_broadcast."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["board", "claim", "complete", "submit_plan", "mail_send", "mail_read", "mail_broadcast"],
                },
                "task_id": {"type": "string"},
                "result": {"type": "string"},
                "plan": {"type": "string"},
                "to": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["action"],
        }

    async def execute(self, action: str, **kwargs: Any) -> str:
        team_dir = self._manager.get_team_dir(self._session_key)
        state = self._manager.get_team_state(self._session_key)
        if not team_dir or not state:
            return "Error: no active team"

        if action == "board":
            return board.render_text(board.load(team_dir), state.members)
        if action == "claim":
            return board.claim(team_dir, kwargs.get("task_id") or "", self._worker_name)
        if action == "complete":
            return board.update_status(team_dir, kwargs.get("task_id") or "", "completed", result=kwargs.get("result"))
        if action == "submit_plan":
            return board.submit_plan(team_dir, kwargs.get("task_id") or "", kwargs.get("plan") or "")
        if action == "mail_send":
            return mailbox.send(team_dir, self._worker_name, kwargs.get("to") or "", kwargs.get("content") or "")
        if action == "mail_read":
            unread = mailbox.read_unread(team_dir, self._worker_name)
            return "\n".join(f"- [{m.from_agent}] {m.content}" for m in unread) or "No unread messages."
        if action == "mail_broadcast":
            return mailbox.broadcast(team_dir, self._worker_name, kwargs.get("content") or "")
        return f"Error: unknown action '{action}'"
