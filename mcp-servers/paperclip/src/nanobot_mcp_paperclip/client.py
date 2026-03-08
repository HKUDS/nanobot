"""HTTP client for the Paperclip REST API."""

from __future__ import annotations

from typing import Any

import httpx


class PaperclipClient:
    """Thin wrapper around Paperclip's REST API.

    All methods return raw dicts (parsed JSON) so the MCP tool layer
    can format responses for the agent.
    """

    def __init__(self, base_url: str, api_token: str, company_id: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._company_id = company_id
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {api_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=30.0,
        )

    async def close(self) -> None:
        await self._http.aclose()

    # ── helpers ──────────────────────────────────────────────────────

    def _co(self, path: str) -> str:
        """Prefix a path with the company scope."""
        return f"/api/companies/{self._company_id}{path}"

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        r = await self._http.get(path, params=params)
        r.raise_for_status()
        return r.json()

    async def _post(self, path: str, json: dict[str, Any] | None = None) -> Any:
        r = await self._http.post(path, json=json)
        r.raise_for_status()
        return r.json()

    async def _patch(self, path: str, json: dict[str, Any] | None = None) -> Any:
        r = await self._http.patch(path, json=json)
        r.raise_for_status()
        return r.json()

    # ── health ───────────────────────────────────────────────────────

    async def health(self) -> dict[str, Any]:
        return await self._get("/health")

    # ── agents ───────────────────────────────────────────────────────

    async def list_agents(self) -> list[dict[str, Any]]:
        return await self._get(self._co("/agents"))

    async def get_agent(self, agent_id: str) -> dict[str, Any]:
        return await self._get(f"/api/agents/{agent_id}")

    async def wake_agent(
        self,
        agent_id: str,
        *,
        reason: str | None = None,
        source: str = "on_demand",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"source": source}
        if reason:
            body["reason"] = reason
        if payload:
            body["payload"] = payload
        return await self._post(f"/api/agents/{agent_id}/wake", json=body)

    # ── issues ───────────────────────────────────────────────────────

    async def list_issues(
        self,
        *,
        status: str | None = None,
        priority: str | None = None,
        assignee_agent_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status
        if priority:
            params["priority"] = priority
        if assignee_agent_id:
            params["assigneeAgentId"] = assignee_agent_id
        return await self._get(self._co("/issues"), params=params)

    async def create_issue(
        self,
        *,
        title: str,
        description: str = "",
        priority: str = "medium",
        labels: list[str] | None = None,
        project_id: str | None = None,
        assignee_agent_id: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "title": title,
            "description": description,
            "priority": priority,
        }
        if labels:
            body["labels"] = labels
        if project_id:
            body["projectId"] = project_id
        if assignee_agent_id:
            body["assigneeAgentId"] = assignee_agent_id
        return await self._post(self._co("/issues"), json=body)

    async def get_issue(self, issue_id: str) -> dict[str, Any]:
        return await self._get(f"/api/issues/{issue_id}")

    async def update_issue(self, issue_id: str, **fields: Any) -> dict[str, Any]:
        return await self._patch(f"/api/issues/{issue_id}", json=fields)

    async def add_comment(self, issue_id: str, text: str) -> dict[str, Any]:
        return await self._post(f"/api/issues/{issue_id}/comments", json={"text": text})

    # ── costs ────────────────────────────────────────────────────────

    async def report_cost(
        self,
        *,
        agent_id: str,
        model: str,
        provider: str,
        input_tokens: int,
        output_tokens: int,
        cost_cents: int,
        issue_id: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "agentId": agent_id,
            "model": model,
            "provider": provider,
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "costCents": cost_cents,
        }
        if issue_id:
            body["issueId"] = issue_id
        if project_id:
            body["projectId"] = project_id
        return await self._post(self._co("/cost-events"), json=body)

    async def cost_summary(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if start_date:
            params["startDate"] = start_date
        if end_date:
            params["endDate"] = end_date
        return await self._get(self._co("/costs/summary"), params=params)

    async def cost_by_agent(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if start_date:
            params["startDate"] = start_date
        if end_date:
            params["endDate"] = end_date
        return await self._get(self._co("/costs/by-agent"), params=params)

    # ── projects ─────────────────────────────────────────────────────

    async def list_projects(self) -> list[dict[str, Any]]:
        return await self._get(self._co("/projects"))

    # ── goals ────────────────────────────────────────────────────────

    async def list_goals(self) -> list[dict[str, Any]]:
        return await self._get(self._co("/goals"))

    async def create_goal(
        self, *, title: str, description: str = "", priority: str = "medium"
    ) -> dict[str, Any]:
        return await self._post(
            self._co("/goals"),
            json={"title": title, "description": description, "priority": priority},
        )

    # ── approvals ────────────────────────────────────────────────────

    async def list_approvals(self) -> list[dict[str, Any]]:
        return await self._get(self._co("/approvals"))

    async def create_approval(self, *, type_: str, **fields: Any) -> dict[str, Any]:
        body = {"type": type_, **fields}
        return await self._post(self._co("/approvals"), json=body)

    # ── activity ─────────────────────────────────────────────────────

    async def activity(self, *, limit: int = 20) -> list[dict[str, Any]]:
        return await self._get(self._co("/activity"), params={"limit": limit})
