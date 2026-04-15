"""Tooling to manage Kosmos Kanban tasks from the agent."""

from __future__ import annotations

from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema
from nanobot.services.kosmos_tasks import KosmosTasksClient

ALLOWED_KOSMOS_ACTORS = {"Kosmos", "Vicks", "Wedge", "Rydia"}


def _truncate(text: str, limit: int = 120) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _canonical_actor(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    for actor in ALLOWED_KOSMOS_ACTORS:
        if raw.lower() == actor.lower():
            return actor
    return None


@tool_parameters(
    tool_parameters_schema(
        action=StringSchema(
            "Action to perform",
            enum=[
                "list_pending",
                "list_project",
                "claim",
                "qa",
                "release",
                "done",
                "block",
                "unblock",
                "approve_release",
                "create",
                "delete",
                "list_comments",
                "comment",
            ],
        ),
        task_id=StringSchema("Task ID for claim/done/delete"),
        project_id=StringSchema("Project ID for list_project/create"),
        title=StringSchema("Task title for create"),
        task_description=StringSchema("Task description for create"),
        assignee=StringSchema("Assignee name for claim"),
        branch=StringSchema("Branch name for release approval"),
        push=StringSchema("Push decision for release approval (yes/no)"),
        agent_id=StringSchema("Agent identity for comments (must match assigned_to by name)"),
        comment_text=StringSchema("Comment body for task comments"),
        required=["action"],
    )
)
class NanoCatsTaskTool(Tool):
    """Manage Kosmos tasks in the kanban board API."""

    def __init__(self, base_url: str = "http://localhost:18794"):
        self._client = KosmosTasksClient(base_url=base_url)

    @property
    def name(self) -> str:
        return "nanocats_tasks"

    @property
    def description(self) -> str:
        return (
            "Manage Kosmos kanban tasks by project. "
            "Use list_pending to get tasks waiting to be done, claim to move task to progress, "
            "qa/release/done for workflow transitions, block/unblock for blockers, "
            "create/delete for task maintenance, "
            "and list_comments/comment for task discussion."
        )

    async def execute(
        self,
        action: str,
        task_id: str | None = None,
        project_id: str | None = None,
        title: str | None = None,
        task_description: str | None = None,
        assignee: str | None = None,
        branch: str | None = None,
        push: str | None = None,
        agent_id: str | None = None,
        comment_text: str | None = None,
        **kwargs: Any,
    ) -> str:
        if action == "list_pending":
            tasks = await self._client.list_pending_tasks()
            if not tasks:
                return "No pending tasks."
            lines = [
                f"- {t.get('id')} | {t.get('project_id')} | {t.get('status')} | {_truncate(str(t.get('title') or ''))}"
                for t in tasks
            ]
            return "Pending tasks:\n" + "\n".join(lines)

        if action == "list_project":
            if not project_id:
                return "Error: project_id is required"
            tasks = await self._client.list_tasks(project_id=project_id)
            if not tasks:
                return f"No tasks for project {project_id}."
            lines = [
                f"- {t.get('id')} | {t.get('status')} | {_truncate(str(t.get('title') or ''))}"
                for t in tasks
            ]
            return f"Tasks for {project_id}:\n" + "\n".join(lines)

        if action == "claim":
            if not task_id:
                return "Error: task_id is required"
            requested_assignee = _canonical_actor(assignee) or _canonical_actor(agent_id)
            task = await self._client.get_task(task_id)
            if not task:
                return f"Error: task {task_id} not found"

            if not requested_assignee:
                requested_assignee = _canonical_actor(str(task.get("assigned_to") or ""))
            if not requested_assignee:
                return (
                    "Error: claim requires a valid assignee. "
                    "Allowed actors: Kosmos, Vicks, Wedge, Rydia."
                )

            current_status = str(task.get("status") or "").strip().lower()
            current_owner = str(task.get("assigned_to") or "").strip()

            if current_status in {"progress", "in_progress"}:
                if not current_owner or current_owner.lower() == requested_assignee.lower():
                    return (
                        f"Task {task_id} is already in progress"
                        + (f" (owner: {current_owner})" if current_owner else "")
                        + ". Claim skipped."
                    )

            if current_status in {"qa", "release", "done"}:
                return (
                    f"Task {task_id} is already in status '{current_status}'"
                    + (f" (owner: {current_owner})" if current_owner else "")
                    + ". Claim skipped."
                )

            transition_comment = comment_text or str(kwargs.get("transition_comment") or "").strip()
            if not transition_comment:
                transition_comment = "Task claimed for implementation"
            updated = await self._client.transition_task(
                task_id,
                to_status="progress",
                comment_text=transition_comment,
                agent_id=requested_assignee,
                agent_name=requested_assignee,
                assigned_to=requested_assignee,
            )
            if not updated:
                latest = await self._client.get_task(task_id)
                latest_status = str((latest or {}).get("status") or "").strip().lower()
                latest_owner = str((latest or {}).get("assigned_to") or "").strip()
                if latest_status in {"progress", "qa", "release", "done"}:
                    return (
                        f"Task {task_id} is now in status '{latest_status}'"
                        + (f" (owner: {latest_owner})" if latest_owner else "")
                        + ". Claim skipped."
                    )
                return f"Error: failed to claim task {task_id}"
            project_info = updated.get("project_id", "")
            return f"Task {task_id} claimed and moved to progress." + (
                f" (project: {project_info})" if project_info else ""
            )

        if action == "done":
            if not task_id:
                return "Error: task_id is required"
            actor = _canonical_actor(agent_id) or _canonical_actor(assignee)
            if not actor:
                return "Error: done requires actor in {Kosmos, Vicks, Wedge, Rydia}"
            transition_comment = comment_text or str(kwargs.get("transition_comment") or "").strip()
            if not transition_comment:
                transition_comment = "Task completed and ready to close"
            updated = await self._client.transition_task(
                task_id,
                to_status="done",
                comment_text=transition_comment,
                agent_id=actor,
                agent_name=actor,
                assigned_to=assignee,
            )
            if not updated:
                return f"Error: failed to complete task {task_id}"
            return f"Task {task_id} marked as done."

        if action == "qa":
            if not task_id:
                return "Error: task_id is required"
            actor = _canonical_actor(agent_id) or _canonical_actor(assignee)
            if not actor:
                return "Error: qa requires actor in {Kosmos, Vicks, Wedge, Rydia}"
            transition_comment = comment_text or str(kwargs.get("transition_comment") or "").strip()
            if not transition_comment:
                transition_comment = "Implementation finished and handed off to QA"
            updated = await self._client.transition_task(
                task_id,
                to_status="qa",
                comment_text=transition_comment,
                agent_id=actor,
                agent_name=actor,
                assigned_to=assignee,
            )
            if not updated:
                return f"Error: failed to move task {task_id} to QA"
            return f"Task {task_id} moved to QA."

        if action == "release":
            if not task_id:
                return "Error: task_id is required"
            actor = _canonical_actor(agent_id) or _canonical_actor(assignee)
            if not actor:
                return "Error: release requires actor in {Kosmos, Vicks, Wedge, Rydia}"
            transition_comment = comment_text or str(kwargs.get("transition_comment") or "").strip()
            if not transition_comment:
                transition_comment = "QA passed and handed off to Release"
            updated = await self._client.transition_task(
                task_id,
                to_status="release",
                comment_text=transition_comment,
                agent_id=actor,
                agent_name=actor,
                assigned_to=assignee,
            )
            if not updated:
                return f"Error: failed to move task {task_id} to release"
            return f"Task {task_id} moved to release."

        if action == "block":
            if not task_id:
                return "Error: task_id is required"
            reason = comment_text or task_description or str(kwargs.get("reason") or "").strip()
            if not reason:
                return "Error: block reason is required"
            updated = await self._client.update_task(
                task_id,
                is_blocked=True,
                block_reason=reason,
                blocked_by=agent_id or assignee or "Kosmos",
            )
            if not updated:
                return f"Error: failed to block task {task_id}"
            return f"Task {task_id} marked as blocked."

        if action == "unblock":
            if not task_id:
                return "Error: task_id is required"
            updated = await self._client.update_task(
                task_id,
                is_blocked=False,
                block_reason="",
                blocked_by=agent_id or assignee or "Kosmos",
            )
            if not updated:
                return f"Error: failed to unblock task {task_id}"
            return f"Task {task_id} unblocked."

        if action == "approve_release":
            if not task_id:
                return "Error: task_id is required"
            target_branch = (branch or str(kwargs.get("branch") or "")).strip()
            if not target_branch:
                return "Error: branch is required"
            push_value = (push or str(kwargs.get("push") or "no")).strip().lower()
            do_push = push_value in {"1", "true", "yes", "y", "si"}
            approver = agent_id or assignee or str(kwargs.get("approved_by") or "Kosmos")
            updated = await self._client.approve_release(
                task_id,
                approved_by=approver,
                branch=target_branch,
                push=do_push,
                comment_text=comment_text
                or str(kwargs.get("approval_comment") or "").strip()
                or None,
            )
            if not updated:
                return f"Error: failed to approve release for task {task_id}"
            return (
                f"Release approved for task {task_id} by {approver} "
                f"(branch={target_branch}, push={'yes' if do_push else 'no'})."
            )

        if action == "create":
            if not project_id or not title:
                return "Error: project_id and title are required"
            description = task_description or str(kwargs.get("description") or "")
            created = await self._client.create_task(
                project_id=project_id,
                title=title,
                description=description,
            )
            if not created:
                return "Error: failed to create task"
            return f"Created task {created.get('id')} in {project_id}."

        if action == "list_comments":
            if not task_id:
                return "Error: task_id is required"
            comments = await self._client.list_task_comments(task_id)
            if not comments:
                return f"No comments for task {task_id}."
            lines = [
                f"- {c.get('agent_name') or c.get('agent_id')}: {_truncate(str(c.get('comment') or ''), 240)}"
                for c in comments
            ]
            return f"Comments for {task_id}:\n" + "\n".join(lines)

        if action == "comment":
            if not task_id:
                return "Error: task_id is required"
            comment = comment_text or task_description or str(kwargs.get("comment") or "")
            if not comment.strip():
                return "Error: comment text is required"
            actor = (
                _canonical_actor(agent_id)
                or _canonical_actor(assignee)
                or _canonical_actor(str(kwargs.get("agent_id") or ""))
            )
            if not actor:
                return "Error: comment requires actor in {Kosmos, Vicks, Wedge, Rydia}"

            created = await self._client.create_task_comment(
                task_id=task_id,
                agent_id=actor,
                comment=comment.strip(),
            )
            if not created:
                return (
                    f"Error: failed to create comment for task {task_id}. "
                    "Ensure agent_id exists and matches task assigned_to by agent name."
                )
            return f"Comment added to task {task_id} by {actor}."

        if action == "delete":
            if not task_id:
                return "Error: task_id is required"
            ok = await self._client.delete_task(task_id)
            return f"Task {task_id} deleted." if ok else f"Error: failed to delete task {task_id}"

        return f"Unknown action: {action}"


KosmosTaskTool = NanoCatsTaskTool
