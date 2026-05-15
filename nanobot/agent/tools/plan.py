"""Plan tool for task decomposition and progress tracking."""
from __future__ import annotations

import hashlib
import json
import re
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.context import ContextAware, RequestContext
from nanobot.agent.tools.schema import (
    StringSchema,
    tool_parameters_schema,
)

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
    steps=StringSchema(
        "JSON array of step objects. Each step has 'text' (string) and "
        "optionally 'status' ('pending'|'active'|'done'|'blocked'). "
        "Example: [{\"text\": \"Read config\", \"status\": \"done\"}, "
        "{\"text\": \"Implement feature\", \"status\": \"active\"}]",
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

    def _plan_path(self, session_key: str | None = None) -> Path:
        key = session_key or _plan_session_key.get()
        return self._plans_dir / f"{_safe_filename(key)}.md"

    def _read_plan(self, path: Path) -> str | None:
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def _write_plan(self, path: Path, content: str) -> None:
        self._plans_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)

    def _delete_plan(self, path: Path) -> None:
        if path.exists():
            path.unlink()

    # --- Parsing ---

    @staticmethod
    def _parse_steps(plan_text: str) -> list[dict[str, str]]:
        steps = []
        for m in re.finditer(
            r"^- \[([ x>!])\] (.+)$", plan_text, re.MULTILINE
        ):
            marker = m.group(1)
            text = m.group(2).strip()
            if marker == "x":
                status = "done"
            elif marker == ">":
                status = "active"
            elif marker == "!":
                status = "blocked"
            else:
                status = "pending"
            steps.append({"text": text, "status": status})
        return steps

    @staticmethod
    def _render_steps(steps: list[dict[str, str]]) -> str:
        markers = {"pending": " ", "active": ">", "done": "x", "blocked": "!"}
        lines = []
        for s in steps:
            m = markers.get(s.get("status", "pending"), " ")
            lines.append(f"- [{m}] {s['text']}")
        return "\n".join(lines)

    @staticmethod
    def _parse_title(plan_text: str) -> str:
        m = re.search(r"^# Plan: (.+)$", plan_text, re.MULTILINE)
        return m.group(1).strip() if m else ""

    @staticmethod
    def _parse_goal(plan_text: str) -> str:
        m = re.search(r"^Goal: (.+)$", plan_text, re.MULTILINE)
        return m.group(1).strip() if m else ""

    # --- Action handlers ---

    def _action_create(self, title: str | None, goal: str | None, steps_raw: str | None) -> str:
        if not title or not title.strip():
            return "Error: title is required for action='create'"

        path = self._plan_path()
        existing = self._read_plan(path)
        if existing:
            return (
                "A plan already exists for this session. "
                "Use action='update' to modify it, or action='done' to complete it first.\n\n"
                + existing
            )

        steps = self._parse_steps_input(steps_raw)
        lines = [f"# Plan: {title.strip()}"]
        if goal:
            lines.append(f"\nGoal: {goal.strip()}")
        if steps:
            lines.append("\n## Steps")
            lines.append(self._render_steps(steps))
        lines.append(f"\nCreated: {_now_iso()}")

        content = "\n".join(lines)
        self._write_plan(path, content)
        return f"Plan created.\n\n{content}"

    def _action_update(
        self,
        steps_raw: str | None,
        notes: str | None,
        goal: str | None,
    ) -> str:
        path = self._plan_path()
        plan = self._read_plan(path)
        if not plan:
            return (
                "No active plan. Use action='create' to start one."
            )

        lines = plan.split("\n")

        # Update goal
        if goal and goal.strip():
            new_goal_line = f"Goal: {goal.strip()}"
            goal_idx = next(
                (i for i, ln in enumerate(lines) if ln.startswith("Goal: ")), None
            )
            if goal_idx is not None:
                lines[goal_idx] = new_goal_line
            else:
                # Insert after title
                title_idx = next(
                    (i for i, ln in enumerate(lines) if ln.startswith("# Plan: ")), 0
                )
                lines.insert(title_idx + 1, "")
                lines.insert(title_idx + 1, new_goal_line)

        # Update steps
        if steps_raw:
            new_steps = self._parse_steps_input(steps_raw)
            existing_steps = self._parse_steps(plan)

            # Merge: update existing by index, append new ones
            for i, ns in enumerate(new_steps):
                if i < len(existing_steps):
                    if ns.get("status") and ns["status"] != "pending":
                        existing_steps[i]["status"] = ns["status"]
                    if ns.get("text") and ns["text"] != existing_steps[i]["text"]:
                        existing_steps[i]["text"] = ns["text"]
                else:
                    existing_steps.append(ns)

            rendered = self._render_steps(existing_steps)
            # Replace the steps section
            steps_start = next(
                (i for i, ln in enumerate(lines) if ln.strip() == "## Steps"), None
            )
            if steps_start is not None:
                # Find where steps end (next ## or end)
                steps_end = steps_start + 1
                while steps_end < len(lines) and lines[steps_end].startswith("- ["):
                    steps_end += 1
                lines[steps_start:steps_end] = ["## Steps", rendered]
            else:
                lines.extend(["", "## Steps", rendered])

        # Append notes
        if notes and notes.strip():
            notes_heading = "\n## Notes"
            if notes_heading not in lines:
                lines.append(notes_heading)
            lines.append(f"- [{_now_iso()}] {notes.strip()}")

        content = "\n".join(lines)
        self._write_plan(path, content)
        return f"Plan updated.\n\n{content}"

    def _action_show(self) -> str:
        path = self._plan_path()
        plan = self._read_plan(path)
        if not plan:
            return "No active plan for this session."
        return f"Current plan:\n\n{plan}"

    def _action_done(self, reason: str | None) -> str:
        path = self._plan_path()
        plan = self._read_plan(path)
        if not plan:
            return "No active plan to complete."

        # Count completed vs total steps
        steps = self._parse_steps(plan)
        done = sum(1 for s in steps if s["status"] == "done")
        total = len(steps)
        summary = f"({done}/{total} steps completed)" if total else ""

        # Mark completion, append timestamp, and remove active plan
        archive_line = f"\nCompleted: {_now_iso()}"
        if reason:
            archive_line += f" — {reason.strip()}"
        if summary:
            archive_line += f" {summary}"

        content = plan + archive_line
        self._delete_plan(path)
        return f"Plan completed and removed. {summary}\n\n{content}"

    @staticmethod
    def _parse_steps_input(steps_raw: str | None) -> list[dict[str, str]]:
        if not steps_raw:
            return []

        try:
            items = json.loads(steps_raw)
        except (json.JSONDecodeError, TypeError):
            # Treat as plain text lines
            items = []
            for line in str(steps_raw).split("\n"):
                line = line.strip().lstrip("- ").strip()
                if line:
                    items.append({"text": line})

        if not isinstance(items, list):
            return []
        result = []
        for item in items:
            if isinstance(item, str):
                result.append({"text": item, "status": "pending"})
            elif isinstance(item, dict):
                result.append({
                    "text": str(item.get("text", "")),
                    "status": item.get("status", "pending"),
                })
        return result

    async def execute(
        self,
        action: str,
        title: str | None = None,
        goal: str | None = None,
        steps: str | None = None,
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

    @staticmethod
    def load_active_plan(workspace: str, session_key: str) -> str | None:
        """Load the active plan for context injection. Returns None if no plan exists."""
        plans_dir = Path(workspace) / "memory" / "plans"
        path = plans_dir / f"{_safe_filename(session_key)}.md"
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")
