"""Todoist tool for task and project management."""

import json
from typing import Any

import httpx

from nanobot.agent.tools.base import Tool

BASE_URL = "https://api.todoist.com/api/v1"


class TodoistTool(Tool):
    """Tool to manage Todoist tasks and projects."""

    name = "todoist"
    description = (
        "Manage Todoist tasks and projects. "
        "Actions: get_tasks, create_task, update_task, complete_task, "
        "delete_task, get_projects, create_project, get_task_comments, "
        "add_task_comment"
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "get_tasks",
                    "create_task",
                    "update_task",
                    "complete_task",
                    "delete_task",
                    "get_projects",
                    "create_project",
                    "get_task_comments",
                    "add_task_comment",
                ],
                "description": "Action to perform",
            },
            "task_id": {
                "type": "string",
                "description": "Task ID (for update, complete, delete, comments)",
            },
            "content": {
                "type": "string",
                "description": "Task/project content or name (for create/update)",
            },
            "description": {
                "type": "string",
                "description": "Task description (for create/update)",
            },
            "project_id": {
                "type": "string",
                "description": "Project ID (for filtering tasks or creating in project)",
            },
            "project_name": {
                "type": "string",
                "description": "Project name (for create_project)",
            },
            "due_string": {
                "type": "string",
                "description": "Natural language due date like 'tomorrow', 'next Monday'",
            },
            "due_date": {
                "type": "string",
                "description": "Due date in YYYY-MM-DD format",
            },
            "due_datetime": {
                "type": "string",
                "description": "Due datetime in RFC3339 format",
            },
            "priority": {
                "type": "integer",
                "description": "Task priority 1-4 (1=normal, 4=urgent)",
                "minimum": 1,
                "maximum": 4,
            },
            "labels": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of label names for the task",
            },
            "filter": {
                "type": "string",
                "description": "Filter query like 'today', 'overdue', 'p1' (for get_tasks)",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results to return",
                "minimum": 1,
                "maximum": 200,
            },
            "comment": {
                "type": "string",
                "description": "Comment text (for add_task_comment)",
            },
        },
        "required": ["action"],
    }

    def __init__(self, api_token: str | None = None):
        self.api_token = api_token or ""

    async def execute(
        self,
        action: str,
        task_id: str | None = None,
        content: str | None = None,
        description: str | None = None,
        project_id: str | None = None,
        project_name: str | None = None,
        due_string: str | None = None,
        due_date: str | None = None,
        due_datetime: str | None = None,
        priority: int | None = None,
        labels: list[str] | None = None,
        filter: str | None = None,  # noqa: A002
        limit: int | None = None,
        comment: str | None = None,
        **kwargs: Any,
    ) -> str:
        if not self.api_token:
            return "Error: Todoist API token not configured. Set it in ~/.nanobot/config.json under tools.todoist.api_token"

        try:
            if action == "get_tasks":
                return await self._get_tasks(
                    project_id=project_id, filter=filter, limit=limit
                )
            elif action == "create_task":
                return await self._create_task(
                    content=content,
                    description=description,
                    project_id=project_id,
                    due_string=due_string,
                    due_date=due_date,
                    due_datetime=due_datetime,
                    priority=priority,
                    labels=labels,
                )
            elif action == "update_task":
                return await self._update_task(
                    task_id=task_id,
                    content=content,
                    description=description,
                    due_string=due_string,
                    due_date=due_date,
                    due_datetime=due_datetime,
                    priority=priority,
                    labels=labels,
                )
            elif action == "complete_task":
                return await self._complete_task(task_id=task_id)
            elif action == "delete_task":
                return await self._delete_task(task_id=task_id)
            elif action == "get_projects":
                return await self._get_projects()
            elif action == "create_project":
                return await self._create_project(name=project_name)
            elif action == "get_task_comments":
                return await self._get_task_comments(task_id=task_id)
            elif action == "add_task_comment":
                return await self._add_task_comment(task_id=task_id, comment=comment)
            else:
                return f"Unknown action: {action}"
        except Exception as e:
            return f"Error: {e}"

    def _get_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }

    async def _get_tasks(
        self,
        project_id: str | None = None,
        filter: str | None = None,  # noqa: A002
        limit: int | None = None,
    ) -> str:
        params: dict[str, Any] = {}
        if project_id:
            params["project_id"] = project_id
        if filter:
            params["filter"] = filter
        if limit:
            params["limit"] = limit

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BASE_URL}/tasks",
                headers=self._get_headers(),
                params=params,
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()
            tasks = data.get("results", []) if isinstance(data, dict) else data

        if not tasks:
            return "No tasks found."

        lines = [f"Found {len(tasks)} task(s):\n"]
        for task in tasks:
            priority_emoji = {4: "🔴", 3: "🟠", 2: "🔵", 1: "⚪"}.get(
                task.get("priority", 1), "⚪"
            )
            due = task.get("due", {})
            due_str = f" (Due: {due.get('string', 'N/A')})" if due else ""
            lines.append(f"{priority_emoji} {task['content']}{due_str}")
            lines.append(f"   ID: {task['id']}")
            if task.get("description"):
                lines.append(f"   Description: {task['description'][:100]}")
            lines.append("")

        return "\n".join(lines)

    async def _create_task(
        self,
        content: str | None,
        description: str | None,
        project_id: str | None,
        due_string: str | None,
        due_date: str | None,
        due_datetime: str | None,
        priority: int | None,
        labels: list[str] | None,
    ) -> str:
        if not content:
            return "Error: content is required to create a task"

        data: dict[str, Any] = {"content": content}
        if description:
            data["description"] = description
        if project_id:
            data["project_id"] = project_id
        if due_string:
            data["due_string"] = due_string
        elif due_date:
            data["due_date"] = due_date
        elif due_datetime:
            data["due_datetime"] = due_datetime
        if priority:
            data["priority"] = priority
        if labels:
            data["labels"] = labels

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{BASE_URL}/tasks",
                headers=self._get_headers(),
                json=data,
                timeout=30.0,
            )
            response.raise_for_status()
            task = response.json()

        return f"Created task: '{task['content']}' (ID: {task['id']})"

    async def _update_task(
        self,
        task_id: str | None,
        content: str | None,
        description: str | None,
        due_string: str | None,
        due_date: str | None,
        due_datetime: str | None,
        priority: int | None,
        labels: list[str] | None,
    ) -> str:
        if not task_id:
            return "Error: task_id is required to update a task"

        data: dict[str, Any] = {}
        if content:
            data["content"] = content
        if description is not None:
            data["description"] = description
        if due_string:
            data["due_string"] = due_string
        elif due_date:
            data["due_date"] = due_date
        elif due_datetime:
            data["due_datetime"] = due_datetime
        if priority:
            data["priority"] = priority
        if labels:
            data["labels"] = labels

        if not data:
            return "Error: at least one field to update is required"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{BASE_URL}/tasks/{task_id}",
                headers=self._get_headers(),
                json=data,
                timeout=30.0,
            )
            response.raise_for_status()
            task = response.json()

        return f"Updated task: '{task['content']}' (ID: {task['id']})"

    async def _complete_task(self, task_id: str | None) -> str:
        if not task_id:
            return "Error: task_id is required to complete a task"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{BASE_URL}/tasks/{task_id}/close",
                headers=self._get_headers(),
                timeout=30.0,
            )
            response.raise_for_status()

        return f"Completed task (ID: {task_id})"

    async def _delete_task(self, task_id: str | None) -> str:
        if not task_id:
            return "Error: task_id is required to delete a task"

        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{BASE_URL}/tasks/{task_id}",
                headers=self._get_headers(),
                timeout=30.0,
            )
            response.raise_for_status()

        return f"Deleted task (ID: {task_id})"

    async def _get_projects(self) -> str:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BASE_URL}/projects",
                headers=self._get_headers(),
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()
            projects = data.get("results", []) if isinstance(data, dict) else data

        if not projects:
            return "No projects found."

        lines = [f"Found {len(projects)} project(s):\n"]
        for project in projects:
            lines.append(f"📁 {project['name']}")
            lines.append(f"   ID: {project['id']}")
            lines.append(f"   Tasks: {project.get('comment_count', 0)} comments")
            lines.append("")

        return "\n".join(lines)

    async def _create_project(self, name: str | None) -> str:
        if not name:
            return "Error: project_name is required to create a project"

        data = {"name": name}

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{BASE_URL}/projects",
                headers=self._get_headers(),
                json=data,
                timeout=30.0,
            )
            response.raise_for_status()
            project = response.json()

        return f"Created project: '{project['name']}' (ID: {project['id']})"

    async def _get_task_comments(self, task_id: str | None) -> str:
        if not task_id:
            return "Error: task_id is required to get comments"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BASE_URL}/comments",
                headers=self._get_headers(),
                params={"task_id": task_id},
                timeout=30.0,
            )
            response.raise_for_status()
            comments = response.json()

        if not comments:
            return "No comments found for this task."

        lines = [f"Found {len(comments)} comment(s):\n"]
        for comment in comments:
            lines.append(f"💬 {comment.get('content', 'No content')}")
            lines.append(f"   Posted: {comment.get('posted_at', 'Unknown')}")
            lines.append("")

        return "\n".join(lines)

    async def _add_task_comment(
        self, task_id: str | None, comment: str | None
    ) -> str:
        if not task_id:
            return "Error: task_id is required to add a comment"
        if not comment:
            return "Error: comment text is required"

        data = {"task_id": task_id, "content": comment}

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{BASE_URL}/comments",
                headers=self._get_headers(),
                json=data,
                timeout=30.0,
            )
            response.raise_for_status()
            result = response.json()

        return f"Added comment to task (ID: {task_id})"
