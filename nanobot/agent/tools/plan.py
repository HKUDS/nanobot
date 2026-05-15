"""Plan tool for task decomposition and progress tracking."""
from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.context import ContextAware, RequestContext
from nanobot.agent.tools.schema import (
    ArraySchema,
    ObjectSchema,
    StringSchema,
    tool_parameters_schema,
)
from nanobot.utils.helpers import _write_text_atomic

_PLAN_PARAMETERS = tool_parameters_schema(
    action=StringSchema(
        "Action to perform",
        enum=["create", "update", "show", "done"],
    ),
    title=StringSchema(
        "Plan title (required for create). A concise name for the task.",
    ),
    goal=StringSchema(
        "Goal description (recommended for create). What you want to achieve.",
    ),
    steps=ArraySchema(
        ObjectSchema(
            properties={
                "text": StringSchema("Step description"),
                "status": StringSchema(
                    "Step status",
                    enum=["pending", "active", "done", "blocked"],
                ),
            },
            required=["text"],
        ),
        description=(
            "Step objects to add or update. Each step has 'text' (string, required) "
            "and optionally 'status' (pending|active|done|blocked). "
            "For updates, steps are matched by index."
        ),
    ),
    notes=StringSchema(
        "Notes to append — discoveries, decisions, or observations.",
    ),
    reason=StringSchema("Reason for completing or abandoning (used with done)."),
    required=["action"],
    description=(
        "Plan tool for complex multi-step tasks. Use 'create' to start a plan, "
        "'update' to mark progress or add steps/notes, 'show' to review the current plan, "
        "'done' to mark the plan complete. Per-action: create needs title; "
        "update/show/done can work with an existing plan."
    ),
)


_plan_session_key: ContextVar[str] = ContextVar("plan_session_key", default="")

_PLAN_CACHE_TTL = 5.0
_PLAN_CACHE_MAX = 256
_PLAN_MISS = object()
_plan_cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()

_VALID_STATUSES = frozenset({"pending", "active", "done", "blocked"})


def _safe_filename(key: str) -> str:
    out = []
    for ch in key:
        if ch.isalnum() or ch in ("-", "_"):
            out.append(ch)
        else:
            out.append("_")
    name = "".join(out).strip("_")[:100]
    short_hash = hashlib.sha256(key.encode()).hexdigest()[:8]
    if name:
        return f"{name}_{short_hash}"
    return f"default_{short_hash}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@tool_parameters(_PLAN_PARAMETERS)
class PlanTool(Tool, ContextAware):
    """Tool for creating and managing task plans."""

    _scopes = {"core", "subagent"}

    def __init__(self, workspace: str):
        self._workspace = workspace
        self._plans_dir = Path(workspace) / "memory" / "plans"

    @classmethod
    def create(cls, ctx: Any) -> Tool:
        return cls(workspace=ctx.workspace)

    def set_context(self, ctx: RequestContext) -> None:
        _plan_session_key.set(ctx.session_key or f"{ctx.channel}:{ctx.chat_id}")

    @property
    def name(self) -> str:
        return "plan"

    @property
    def description(self) -> str:
        return (
            "Create and manage a task plan with steps and progress tracking. "
            "Use before tackling complex, multi-step tasks. "
            "The plan persists across turns and is visible in your context. "
            "When updating steps, existing steps are merged by index (you can modify "
            "status/text or append new steps, but cannot delete or reorder existing ones)."
        )

    def runtime_context_provider(self) -> Callable[[str | None], str | None]:
        """Return a provider that injects the active plan into runtime context."""
        def _provider(session_key: str | None) -> str | None:
            if not session_key:
                return None
            plan = PlanTool.load_active_plan(self._workspace, session_key)
            if plan:
                return f"# Active Plan\n\n{plan}"
            return None
        return _provider

    # --- Storage ---

    def _plan_path(self, session_key: str | None = None) -> Path:
        key = session_key or _plan_session_key.get()
        return self._plans_dir / f"{_safe_filename(key)}.json"

    def _read_plan(self, path: Path) -> dict | None:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def _write_plan(self, path: Path, plan: dict) -> None:
        self._plans_dir.mkdir(parents=True, exist_ok=True)
        plan["updated"] = _now_iso()
        _write_text_atomic(path, json.dumps(plan, indent=2, ensure_ascii=False))
        _plan_cache.pop(path.name, None)

    def _delete_plan(self, path: Path) -> None:
        if path.exists():
            path.unlink()
        _plan_cache.pop(path.name, None)

    # --- Rendering ---

    @staticmethod
    def _render_steps(steps: list[dict[str, str]]) -> str:
        markers = {"pending": " ", "active": ">", "done": "x", "blocked": "!"}
        lines = []
        for s in steps:
            m = markers.get(s.get("status", "pending"), " ")
            lines.append(f"- [{m}] {s['text']}")
        return "\n".join(lines)

    @staticmethod
    def render_markdown(plan: dict) -> str:
        """Render a plan dict as markdown for display or context injection."""
        lines = [f"# Plan: {plan['title']}"]
        if plan.get("goal"):
            lines.append(f"\nGoal: {plan['goal']}")
        steps = plan.get("steps", [])
        if steps:
            lines.append("\n## Steps")
            lines.append(PlanTool._render_steps(steps))
        notes = plan.get("notes", [])
        if notes:
            lines.append("\n## Notes")
            for n in notes:
                lines.append(f"- [{n['ts']}] {n['text']}")
        lines.append(f"\nCreated: {plan['created']}")
        if plan.get("updated"):
            lines.append(f"Updated: {plan['updated']}")
        return "\n".join(lines)

    # --- Validation ---

    @staticmethod
    def _validate_steps(steps: list[dict]) -> list[dict]:
        """Normalize step dicts: clamp unknown status. Preserves empty text for status-only updates."""
        result = []
        for s in steps:
            text = str(s.get("text", "")).strip()
            status = s.get("status", "pending")
            if status not in _VALID_STATUSES:
                status = "pending"
            result.append({"text": text, "status": status})
        return result

    # --- Action handlers ---

    def _action_create(
        self, title: str | None, goal: str | None, steps: list[dict] | None,
    ) -> str:
        if not title or not title.strip():
            return "Error: title is required for action='create'"

        path = self._plan_path()
        existing = self._read_plan(path)
        if existing:
            md = self.render_markdown(existing)
            return (
                "A plan already exists for this session. "
                "Use action='update' to modify it, or action='done' to complete it first.\n\n"
                + md
            )

        now = _now_iso()
        plan = {
            "title": title.strip(),
            "goal": goal.strip() if goal else None,
            "steps": [s for s in self._validate_steps(steps or []) if s["text"]],
            "notes": [],
            "created": now,
            "updated": None,
        }
        self._write_plan(path, plan)
        return f"Plan created.\n\n{self.render_markdown(plan)}"

    def _action_update(
        self,
        steps: list[dict] | None,
        notes: str | None,
        goal: str | None,
    ) -> str:
        path = self._plan_path()
        plan = self._read_plan(path)
        if not plan:
            return "No active plan. Use action='create' to start one."

        if goal and goal.strip():
            plan["goal"] = goal.strip()

        if steps:
            new_steps = self._validate_steps(steps)
            existing_steps = plan.get("steps", [])
            for i, ns in enumerate(new_steps):
                if i < len(existing_steps):
                    if ns.get("status") and ns["status"] != "pending":
                        existing_steps[i]["status"] = ns["status"]
                    if ns.get("text") and ns["text"] != existing_steps[i]["text"]:
                        existing_steps[i]["text"] = ns["text"]
                else:
                    if ns["text"]:
                        existing_steps.append(ns)
            plan["steps"] = existing_steps

        if notes and notes.strip():
            plan_notes = plan.get("notes", [])
            plan_notes.append({"ts": _now_iso(), "text": notes.strip()})
            plan["notes"] = plan_notes

        self._write_plan(path, plan)
        return f"Plan updated.\n\n{self.render_markdown(plan)}"

    def _action_show(self) -> str:
        path = self._plan_path()
        plan = self._read_plan(path)
        if not plan:
            return "No active plan for this session."
        return f"Current plan:\n\n{self.render_markdown(plan)}"

    def _action_done(self, reason: str | None) -> str:
        path = self._plan_path()
        plan = self._read_plan(path)
        if not plan:
            return "No active plan to complete."

        steps = plan.get("steps", [])
        done = sum(1 for s in steps if s["status"] == "done")
        total = len(steps)
        summary = f"({done}/{total} steps completed)" if total else ""

        now = _now_iso()
        plan["completed"] = now

        archive_dir = self._plans_dir / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        _write_text_atomic(
            archive_dir / path.name,
            json.dumps(plan, indent=2, ensure_ascii=False),
        )

        self._delete_plan(path)

        md = self.render_markdown(plan)
        footer = f"\nCompleted: {now}"
        if reason:
            footer += f" — {reason.strip()}"
        if summary:
            footer += f" {summary}"
        return f"Plan completed and archived. {summary}\n\n{md}{footer}"

    async def execute(
        self,
        action: str,
        title: str | None = None,
        goal: str | None = None,
        steps: list[dict] | None = None,
        notes: str | None = None,
        reason: str | None = None,
        **kwargs: Any,
    ) -> str:
        if action == "create":
            return self._action_create(title, goal, steps)
        elif action == "update":
            return self._action_update(steps, notes, goal)
        elif action == "show":
            return self._action_show()
        elif action == "done":
            return self._action_done(reason)
        return f"Unknown action: {action}. Use create, update, show, or done."

    # --- Cache ---

    @staticmethod
    def _evict_cache(now: float) -> None:
        """Evict expired entries; if still over limit, evict oldest."""
        expired = [k for k, (ts, _) in _plan_cache.items()
                   if (now - ts) >= _PLAN_CACHE_TTL]
        for k in expired:
            del _plan_cache[k]
        while len(_plan_cache) > _PLAN_CACHE_MAX:
            _plan_cache.popitem(last=False)

    @staticmethod
    def load_active_plan(workspace: str, session_key: str) -> str | None:
        """Load the active plan for context injection. Returns rendered markdown or None."""
        plans_dir = Path(workspace) / "memory" / "plans"
        path = plans_dir / f"{_safe_filename(session_key)}.json"
        cache_key = str(path)
        now = time.monotonic()
        cached = _plan_cache.get(cache_key)
        if cached and (now - cached[0]) < _PLAN_CACHE_TTL:
            return cached[1] if cached[1] is not _PLAN_MISS else None
        PlanTool._evict_cache(now)
        if not path.exists():
            _plan_cache[cache_key] = (now, _PLAN_MISS)
            return None
        try:
            plan = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        rendered = PlanTool.render_markdown(plan)
        _plan_cache[cache_key] = (now, rendered)
        return rendered
