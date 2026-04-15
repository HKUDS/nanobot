"""Kosmos task API client used by tools and heartbeat automation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import aiohttp


class KosmosTasksClient:
    """Small async client for Kosmos REST endpoints."""

    def __init__(self, base_url: str = "http://localhost:18794"):
        self.base_url = base_url.rstrip("/")

    @staticmethod
    def _unwrap_list(data: Any, key: str) -> list[dict[str, Any]]:
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            nested = data.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
        return []

    async def list_tasks(self, project_id: str | None = None) -> list[dict[str, Any]]:
        params = {}
        if project_id:
            params["project_id"] = project_id
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            async with session.get(f"{self.base_url}/api/tasks", params=params) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                return self._unwrap_list(data, "tasks")

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            async with session.get(f"{self.base_url}/api/tasks/{task_id}") as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                return data if isinstance(data, dict) else None

    async def list_pending_tasks(self) -> list[dict[str, Any]]:
        tasks = await self.list_tasks()
        pending = [
            t
            for t in tasks
            if str(t.get("status") or "").strip().lower()
            in {"todo", "progress", "in_progress", "qa", "release"}
        ]
        pending.sort(key=lambda t: str(t.get("created_at", "")))
        return pending

    async def update_task(self, task_id: str, **updates: Any) -> dict[str, Any] | None:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            async with session.patch(
                f"{self.base_url}/api/tasks/{task_id}",
                json=updates,
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                return data if isinstance(data, dict) else None

    async def transition_task(
        self,
        task_id: str,
        to_status: str,
        comment_text: str,
        *,
        agent_id: str | None = None,
        agent_name: str | None = None,
        assigned_to: str | None = None,
    ) -> dict[str, Any] | None:
        payload: dict[str, Any] = {
            "to_status": to_status,
            "comment_text": comment_text,
        }
        if agent_id:
            payload["agent_id"] = agent_id
        if agent_name:
            payload["agent_name"] = agent_name
        if assigned_to is not None:
            payload["assigned_to"] = assigned_to
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            async with session.post(
                f"{self.base_url}/api/tasks/{task_id}/transition",
                json=payload,
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                return data if isinstance(data, dict) else None

    async def approve_release(
        self,
        task_id: str,
        *,
        approved_by: str,
        branch: str,
        push: bool,
        comment_text: str | None = None,
    ) -> dict[str, Any] | None:
        payload: dict[str, Any] = {
            "approved_by": approved_by,
            "branch": branch,
            "push": push,
        }
        if comment_text:
            payload["comment_text"] = comment_text
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            async with session.post(
                f"{self.base_url}/api/tasks/{task_id}/approve_release",
                json=payload,
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                return data if isinstance(data, dict) else None

    async def create_task(
        self,
        project_id: str,
        title: str,
        description: str = "",
        priority: str = "medium",
    ) -> dict[str, Any] | None:
        payload = {
            "project_id": project_id,
            "title": title,
            "description": description,
            "priority": priority,
            "status": "todo",
        }
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            async with session.post(f"{self.base_url}/api/tasks", json=payload) as resp:
                if resp.status not in {200, 201}:
                    return None
                data = await resp.json()
                return data if isinstance(data, dict) else None

    async def delete_task(self, task_id: str) -> bool:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            async with session.delete(f"{self.base_url}/api/tasks/{task_id}") as resp:
                return resp.status == 200

    async def list_projects(self, include_hidden: bool = True) -> list[dict[str, Any]]:
        params = {"include_hidden": "true"} if include_hidden else {}
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            async with session.get(f"{self.base_url}/api/projects", params=params) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                return self._unwrap_list(data, "projects")

    async def list_agents(self) -> list[dict[str, Any]]:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            async with session.get(f"{self.base_url}/api/agents") as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                return self._unwrap_list(data, "agents")

    async def resolve_agent_id_by_name(self, agent_name: str) -> str | None:
        target = (agent_name or "").strip().lower()
        if not target:
            return None
        agents = await self.list_agents()
        for agent in agents:
            name = str(agent.get("name") or "").strip().lower()
            if name == target:
                return str(agent.get("id") or "") or None
        return None

    async def list_task_comments(self, task_id: str) -> list[dict[str, Any]]:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            async with session.get(f"{self.base_url}/api/tasks/{task_id}/comments") as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                return self._unwrap_list(data, "comments")

    async def create_task_comment(
        self,
        task_id: str,
        agent_id: str,
        comment: str,
    ) -> dict[str, Any] | None:
        payload = {
            "agent_id": agent_id,
            "comment_text": comment,
        }
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            async with session.post(
                f"{self.base_url}/api/tasks/{task_id}/comments",
                json=payload,
            ) as resp:
                if resp.status not in {200, 201}:
                    return None
                data = await resp.json()
                return data if isinstance(data, dict) else None

    async def upsert_agent_identity(
        self,
        agent_id: str,
        agent_name: str,
        project_id: str = "",
        status: str = "working",
        mood: str = "focused",
        current_task: str = "",
    ) -> dict[str, Any] | None:
        payload = {
            "id": agent_id,
            "name": agent_name,
            "status": status,
            "mood": mood,
            "currentTask": current_task,
            "projectId": project_id,
            "lastActivity": "",
        }
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            async with session.post(f"{self.base_url}/api/agents", json=payload) as resp:
                if resp.status not in {200, 201}:
                    return None
                data = await resp.json()
                return data if isinstance(data, dict) else None

    async def publish_activity(self, activity: dict[str, Any]) -> bool:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            async with session.post(
                f"{self.base_url}/api/events/activity",
                json=activity,
            ) as resp:
                return resp.status in {200, 201, 202}

    async def upload_artifact(
        self,
        task_id: str,
        file_path: str,
        filename: str,
        mime_type: str = "image/png",
        created_by: str | None = None,
    ) -> dict[str, Any] | None:
        boundary = aiohttp.helpers.gen_boundary()
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
            async with session.post(
                f"{self.base_url}/api/tasks/{task_id}/artifacts",
                data=self._multipart_file(file_path, filename, boundary, created_by),
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            ) as resp:
                if resp.status not in {200, 201}:
                    return None
                data = await resp.json()
                return data if isinstance(data, dict) else None

    @staticmethod
    def _multipart_file(
        file_path: str, filename: str, boundary: str, created_by: str | None
    ) -> bytes:
        import mimetypes

        content = Path(file_path).read_bytes()
        mime_type = mimetypes.guess_type(filename)[0] or "image/png"

        crlf = b"\r\n"
        body = crlf.join(
            [
                b"--" + boundary.encode(),
                b'Content-Disposition: form-data; name="file"; filename="'
                + filename.encode()
                + b'"',
                b"Content-Type: " + mime_type.encode(),
                b"",
                content,
                b"--" + boundary.encode() + b"--",
                b"",
            ]
        )
        return body

    async def list_artifacts(self, task_id: str) -> list[dict[str, Any]]:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            async with session.get(f"{self.base_url}/api/tasks/{task_id}/artifacts") as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                return data if isinstance(data, list) else []


# Backward compatibility alias (legacy NanoCats naming).
NanoCatsTasksClient = KosmosTasksClient
