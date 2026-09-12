"""Owner-scoped access to the durable development project."""

from __future__ import annotations

import json
from typing import Any, Literal

from filelock import Timeout
from pydantic import BaseModel, ConfigDict, Field

from nanobot.agent.tools.base import Tool, ToolResult, tool_parameters
from nanobot.agent.tools.context import RequestContext, ToolContext, current_request_context
from nanobot.development.config import DevelopmentConfig
from nanobot.development.service import DevelopmentService
from nanobot.runtime_context import (
    RuntimeContextBlock,
    RuntimeContextProvider,
    wrap_runtime_context_lines,
)


class DevelopmentAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["status", "project", "job", "propose", "note", "continue", "pause", "start", "cancel"]
    job_id: str | None = None
    title: str = ""
    objective: str = ""
    evidence: list[str] = Field(default_factory=list)
    acceptance: list[str] = Field(default_factory=list)
    requirement_ids: list[str] = Field(default_factory=list)
    note: str = ""


@tool_parameters(DevelopmentAction.model_json_schema())
class DevelopmentTool(Tool):
    config_key = "development"

    def __init__(self, service: DevelopmentService) -> None:
        self.service = service

    @classmethod
    def config_cls(cls) -> type[DevelopmentConfig]:
        return DevelopmentConfig

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return ctx.config.development.enable

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        return cls(DevelopmentService(ctx.config.development, ctx.workspace))

    @property
    def name(self) -> str:
        return "development"

    @property
    def description(self) -> str:
        return (
            "Manage the owner's durable agent development project: read its full requirements, "
            "status, job evidence and checkpoints; propose a bounded change with evidence and fixed "
            "acceptance; continue, pause, start or cancel. Use this project across sessions. "
            "Start runs a separate isolated builder with frozen baseline checks, bounded budget and "
            "independent review. Notes never count as verification or deployment. Preserve the full "
            "project scope. Do not edit the running gateway to bypass this development pipeline."
        )

    def runtime_context_provider(self) -> RuntimeContextProvider:
        return self._context

    async def _context(self, request: RequestContext) -> RuntimeContextBlock | None:
        if request.session_key != self.service.config.owner_session_key:
            return None
        project = self.service.store.read()
        if not project.objective:
            return None
        data = {
            "development_project_available": True, "paused": project.paused,
            "requirement_count": len(project.requirements), "job_count": len(project.jobs),
            "active": [{"id": job.id, "title": job.title, "stage": job.stage}
                       for job in project.jobs if job.stage not in {"deployed", "cancelled"}][:12],
        }
        encoded = json.dumps(data, ensure_ascii=False).replace("[", "\\u005b").replace("]", "\\u005d")
        return RuntimeContextBlock(source="development", persist=False,
                                   content=wrap_runtime_context_lines([encoded]))

    async def execute(self, **kwargs: Any) -> str:
        try:
            request = current_request_context()
            self.service.authorize(request.session_key if request else None)
            action = DevelopmentAction.model_validate(kwargs)
            if action.action == "project":
                return self.service.store.read().model_dump_json(indent=2)
            if action.action == "job":
                return self.service.store.find(self.service.store.read(), action.job_id or "").model_dump_json(indent=2)
            if action.action == "propose":
                return self.service.store.propose(title=action.title, objective=action.objective,
                                                 evidence=action.evidence, acceptance=action.acceptance,
                                                 requirement_ids=action.requirement_ids).model_dump_json(indent=2)
            if action.action == "note":
                return self.service.store.note(action.job_id or "", action.note).model_dump_json(indent=2)
            return self.service.control(action.action, action.job_id)
        except (ValueError, OSError, Timeout) as exc:
            return ToolResult.error(str(exc))
