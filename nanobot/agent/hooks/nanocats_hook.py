"""
NanoCats Agent Hook
Sends real-time agent events to the NanoCats WebSocket server.
Supports both main agent and subagent activity tracking.
"""

import contextvars
import json
from datetime import datetime
from pathlib import Path

from nanobot.agent.hook import AgentHook, AgentHookContext

_PROJECTS_PATH = Path.home() / "proyectos"


# Thread-safe context for current NanoCats task context
# Set by NanoCatsTaskTool.execute when claiming a task
# Read by NanoCatsSubagentHook to include projectId in events
_current_task_context: contextvars.ContextVar[dict] = contextvars.ContextVar(
    "nanocats_task_context", default={"project_id": None, "task_id": None}
)


def set_nanocats_task_context(project_id: str | None, task_id: str | None) -> None:
    """Set the current NanoCats task context (called by NanoCatsTaskTool)."""
    _current_task_context.set({"project_id": project_id, "task_id": task_id})


def get_nanocats_task_context() -> dict:
    """Get the current NanoCats task context."""
    return _current_task_context.get()


class NanoCatsAgentHook(AgentHook):
    """Hook that sends agent events to NanoCats WebSocket server for monitoring."""

    def __init__(
        self,
        agent_id: str = "main",
        agent_name: str = "Kosmos",
        workspace: Path | None = None,
        task_id: str | None = None,
    ):
        super().__init__()
        self.agent_id = agent_id
        self.agent_name = agent_name
        self.task_id = task_id
        self._workspace = workspace
        self._current_project_id: str | None = None
        if workspace:
            self._current_project_id = self._get_project_id_from_workspace(workspace)

    def _get_task_id(self) -> str | None:
        """Get task_id from context var, falling back to hook state."""
        ctx = get_nanocats_task_context()
        return ctx.get("task_id") or self.task_id

    def _get_project_id_from_workspace(self, workspace: Path | str | None) -> str | None:
        """Detect which project folder the agent is working in."""
        if workspace is None:
            return None
        workspace_str = str(workspace)
        if workspace_str.startswith(str(_PROJECTS_PATH)):
            parts = workspace_str[len(str(_PROJECTS_PATH)) :].strip("/").split("/")
            if parts:
                return parts[0]
        return None

    def _get_status_for_tool(self, tool_name: str) -> str:
        """Map tool name to activity status."""
        tool_lower = tool_name.lower()
        if any(t in tool_lower for t in ["read", "file", "glob", "grep", "cat", "list_dir"]):
            return "reading"
        elif any(t in tool_lower for t in ["write", "edit", "create", "delete", "move"]):
            return "writing"
        elif any(t in tool_lower for t in ["exec", "bash", "shell", "run", "spawn"]):
            return "executing"
        elif any(t in tool_lower for t in ["search", "web", "fetch", "http"]):
            return "consulting"
        elif any(t in tool_lower for t in ["spawn", "agent", "subagent"]):
            return "thinking"
        return "executing"

    def _detect_project_from_context(self, context: AgentHookContext) -> str | None:
        """Detect project from tool call arguments (file paths being read/written)."""
        if not context.tool_calls:
            return self._current_project_id

        for tc in context.tool_calls:
            args = tc.arguments
            # Check common path arguments
            for key in [
                "path",
                "file",
                "target",
                "source",
                "destination",
                "file_path",
                "target_path",
            ]:
                if key in args and isinstance(args[key], str):
                    project = self._get_project_id_from_workspace(args[key])
                    if project:
                        return project
        return self._current_project_id

    async def _send_event(self, event: dict):
        """Send event via WebSocket broadcast."""
        try:
            from nanobot.services.nanocats import get_nanocats

            nanocats = get_nanocats()
            if nanocats and nanocats._running:
                await nanocats.send_agent_update(event)
        except Exception:
            pass

    async def _send_activity(self, activity_data: dict):
        """Send activity event (tool executions, status changes, etc)."""
        try:
            from nanobot.services.nanocats import get_nanocats

            nanocats = get_nanocats()
            if nanocats and nanocats._running:
                await nanocats.send_activity(activity_data)
        except Exception:
            pass

    async def before_iteration(self, context: AgentHookContext) -> None:
        """Send thinking status when agent starts an iteration."""
        project_id = self._detect_project_from_context(context)

        await self._send_event(
            {
                "id": self.agent_id,
                "name": self.agent_name,
                "type": "agent",
                "status": "thinking",
                "mood": "focused",
                "currentTask": f"Thinking - Iteration {context.iteration + 1}",
                "projectId": project_id or "",
                "lastActivity": datetime.now().isoformat(),
            }
        )

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        """Send tool execution status and activity log."""
        if not context.tool_calls:
            return

        project_id = self._detect_project_from_context(context)
        task_id = self._get_task_id()

        for i, tool_call in enumerate(context.tool_calls):
            status = self._get_status_for_tool(tool_call.name)
            args_str = json.dumps(tool_call.arguments, ensure_ascii=False)[:80]

            await self._send_activity(
                {
                    "id": f"{datetime.now().timestamp()}-{i}",
                    "agentId": self.agent_id,
                    "agentName": self.agent_name,
                    "type": status,
                    "status": status,
                    "mood": "busy",
                    "currentTask": f"{tool_call.name}",
                    "message": f"{tool_call.name}: {args_str}",
                    "projectId": project_id or "",
                    "taskId": task_id,
                    "timestamp": datetime.now().isoformat(),
                }
            )

        tool_names = [tc.name for tc in context.tool_calls]
        primary_status = self._get_status_for_tool(tool_names[0])

        await self._send_event(
            {
                "id": self.agent_id,
                "name": self.agent_name,
                "type": "agent",
                "status": primary_status,
                "mood": "busy",
                "currentTask": f"{', '.join(tool_names[:2])}",
                "projectId": project_id or "",
                "taskId": task_id,
                "lastActivity": datetime.now().isoformat(),
            }
        )

    async def after_iteration(self, context: AgentHookContext) -> None:
        """Send iteration completion status."""
        project_id = self._detect_project_from_context(context)
        task_id = self._get_task_id()

        if context.error:
            status = "error"
            mood = "tired"
            task = context.error[:80] if context.error else "Error"
        elif context.tool_results:
            status = "coding"
            mood = "satisfied"
            task = (
                context.final_content[:80].replace("\n", " ")
                if context.final_content
                else "Completed"
            )
        else:
            status = "thinking"
            mood = "happy"
            task = (
                context.final_content[:80].replace("\n", " ") if context.final_content else "Ready"
            )

        await self._send_event(
            {
                "id": self.agent_id,
                "name": self.agent_name,
                "type": "agent",
                "status": status,
                "mood": mood,
                "currentTask": task or "Ready",
                "projectId": project_id or "",
                "taskId": task_id,
                "lastActivity": datetime.now().isoformat(),
            }
        )

        if context.final_content:
            await self._send_activity(
                {
                    "id": f"{datetime.now().timestamp()}",
                    "agentId": self.agent_id,
                    "agentName": self.agent_name,
                    "type": "status",
                    "status": status,
                    "mood": mood,
                    "currentTask": task or "Task completed",
                    "message": context.final_content[:100].replace("\n", " ")
                    if context.final_content
                    else "Task completed",
                    "projectId": project_id or "",
                    "taskId": task_id,
                    "timestamp": datetime.now().isoformat(),
                }
            )


class NanoCatsSubagentHook(AgentHook):
    """Hook for subagent activity tracking."""

    def __init__(
        self,
        task_id: str,
        task_label: str = "",
        workspace: Path | None = None,
        project_id: str | None = None,
    ):
        super().__init__()
        self.task_id = task_id
        self.task_label = task_label
        self.agent_id = f"subagent-{task_id}"
        self.agent_name = task_label or f"Subagent {task_id[:8]}"
        self._workspace = workspace
        # project_id takes precedence over workspace detection
        self._current_project_id = project_id
        if not project_id and workspace:
            self._current_project_id = self._get_project_id_from_workspace(workspace)

    def set_project_id(self, project_id: str | None) -> None:
        """Update project_id (e.g., after claiming a NanoCats task)."""
        if project_id:
            self._current_project_id = project_id

    def _get_project_id_from_workspace(self, workspace: Path | str | None) -> str | None:
        """Detect which project folder the agent is working in."""
        if workspace is None:
            return None
        workspace_str = str(workspace)
        if workspace_str.startswith(str(_PROJECTS_PATH)):
            parts = workspace_str[len(str(_PROJECTS_PATH)) :].strip("/").split("/")
            if parts:
                return parts[0]
        return None

    def _get_status_for_tool(self, tool_name: str) -> str:
        """Map tool name to activity status."""
        tool_lower = tool_name.lower()
        if any(t in tool_lower for t in ["read", "file", "glob", "grep", "cat", "list_dir"]):
            return "reading"
        elif any(t in tool_lower for t in ["write", "edit", "create", "delete", "move"]):
            return "writing"
        elif any(t in tool_lower for t in ["exec", "bash", "shell", "run"]):
            return "executing"
        elif any(t in tool_lower for t in ["search", "web", "fetch", "http"]):
            return "consulting"
        return "executing"

    def _get_task_context_project(self) -> str | None:
        """Get project_id and task_id from current NanoCats task context."""
        ctx = get_nanocats_task_context()
        return ctx.get("project_id"), ctx.get("task_id")

    def _detect_project_from_context(self, context: AgentHookContext) -> str | None:
        """Detect project from tool call arguments and current NanoCats task context."""
        # First check context var (set by NanoCatsTaskTool when claiming a task)
        ctx = get_nanocats_task_context()
        if ctx.get("project_id"):
            return ctx["project_id"]

        if not context.tool_calls:
            return self._current_project_id

        for tc in context.tool_calls:
            args = tc.arguments
            for key in [
                "path",
                "file",
                "target",
                "source",
                "destination",
                "file_path",
                "target_path",
            ]:
                if key in args and isinstance(args[key], str):
                    project = self._get_project_id_from_workspace(args[key])
                    if project:
                        return project
        return self._current_project_id

    async def _send_event(self, event: dict):
        """Send event via WebSocket."""
        try:
            from nanobot.services.nanocats import get_nanocats

            nanocats = get_nanocats()
            if nanocats and nanocats._running:
                await nanocats.send_agent_update(event)
        except Exception:
            pass

    async def _send_activity(self, activity_data: dict):
        """Send subagent activity event."""
        try:
            from nanobot.services.nanocats import get_nanocats

            nanocats = get_nanocats()
            if nanocats and nanocats._running:
                await nanocats.send_activity(activity_data)
        except Exception:
            pass

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        """Send subagent tool execution activity."""
        if not context.tool_calls:
            return

        project_id = self._detect_project_from_context(context)

        for i, tool_call in enumerate(context.tool_calls):
            status = self._get_status_for_tool(tool_call.name)
            args_str = json.dumps(tool_call.arguments, ensure_ascii=False)[:80]

            await self._send_activity(
                {
                    "id": f"{datetime.now().timestamp()}-{i}",
                    "agentId": self.agent_id,
                    "agentName": self.agent_name,
                    "type": status,
                    "status": status,
                    "mood": "busy",
                    "currentTask": f"{tool_call.name}",
                    "message": f"{tool_call.name}: {args_str}",
                    "projectId": project_id or "",
                    "taskId": self.task_id,
                    "timestamp": datetime.now().isoformat(),
                }
            )

        tool_names = [tc.name for tc in context.tool_calls]
        primary_status = self._get_status_for_tool(tool_names[0])

        await self._send_event(
            {
                "id": self.agent_id,
                "name": self.agent_name,
                "type": "subagent",
                "status": primary_status,
                "mood": "busy",
                "currentTask": f"{', '.join(tool_names[:2])}",
                "projectId": project_id or "",
                "taskId": self.task_id,
                "lastActivity": datetime.now().isoformat(),
            }
        )

    async def after_iteration(self, context: AgentHookContext) -> None:
        """Send subagent iteration completion."""
        project_id = self._detect_project_from_context(context)

        if context.error:
            status = "error"
            mood = "tired"
        elif context.tool_results:
            status = "completed"
            mood = "satisfied"
        else:
            status = "idle"
            mood = "relaxed"

        await self._send_event(
            {
                "id": self.agent_id,
                "name": self.agent_name,
                "type": "subagent",
                "status": status,
                "mood": mood,
                "currentTask": context.final_content[:50].replace("\n", " ")
                if context.final_content
                else "Completed",
                "projectId": project_id or "",
                "taskId": self.task_id,
                "lastActivity": datetime.now().isoformat(),
            }
        )


def create_nanocats_hook(
    agent_id: str = "main",
    agent_name: str = "Kosmos",
    workspace: Path | None = None,
    task_id: str | None = None,
) -> NanoCatsAgentHook:
    """Factory to create the NanoCats agent hook."""
    return NanoCatsAgentHook(agent_id, agent_name, workspace, task_id)


def create_subagent_hook(
    task_id: str,
    task_label: str = "",
    workspace: Path | None = None,
    project_id: str | None = None,
) -> NanoCatsSubagentHook:
    """Factory to create a hook for subagent tracking."""
    return NanoCatsSubagentHook(task_id, task_label, workspace, project_id)
