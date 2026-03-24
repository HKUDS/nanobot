from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nanobot.utils.filelock import filelock
from nanobot.team.state import Task, Teammate
from nanobot.utils.helpers import ensure_dir


def _path(team_dir: Path) -> Path:
    return ensure_dir(team_dir) / "tasks.json"


def load(team_dir: Path) -> list[Task]:
    path = _path(team_dir)
    if not path.exists():
        return []
    return [Task.from_dict(item) for item in json.loads(path.read_text(encoding="utf-8") or "[]")]


def save(team_dir: Path, tasks: list[Task]) -> None:
    _path(team_dir).write_text(
        json.dumps([t.__dict__ for t in tasks], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _locked_update(team_dir: Path, update) -> Any:
    path = _path(team_dir)
    with open(path, "a+", encoding="utf-8") as f, filelock(f):
        f.seek(0)
        raw = f.read().strip()
        tasks = [Task.from_dict(item) for item in json.loads(raw or "[]")]
        result = update(tasks)
        f.seek(0)
        f.truncate()
        f.write(json.dumps([t.__dict__ for t in tasks], ensure_ascii=False, indent=2))
        f.flush()
    return result


def _deps_met(task: Task, tasks: list[Task]) -> bool:
    done = {t.id for t in tasks if t.status == "completed"}
    return all(dep in done for dep in task.depends_on)


def claim(team_dir: Path, task_id: str, worker: str) -> str:
    def _update(tasks: list[Task]) -> str:
        for task in tasks:
            if task.id != task_id:
                continue
            if task.owner and task.owner != worker:
                return f"Error: task {task_id} is already owned by {task.owner}"
            if task.status not in {"pending", "planning"}:
                return f"Error: task {task_id} is not claimable (status: {task.status})"
            if not _deps_met(task, tasks):
                return f"Error: task {task_id} is blocked by dependencies"
            task.owner = worker
            task.status = "planning" if task.requires_approval else "in_progress"
            return f"Claimed task {task_id}"
        return f"Error: task {task_id} not found"

    return _locked_update(team_dir, _update)


def update_status(team_dir: Path, task_id: str, status: str, **fields: Any) -> str:
    def _update(tasks: list[Task]) -> str:
        for task in tasks:
            if task.id == task_id:
                task.status = status
                for key, value in fields.items():
                    if hasattr(task, key):
                        setattr(task, key, value)
                return f"Updated task {task_id} to {status}"
        return f"Error: task {task_id} not found"

    return _locked_update(team_dir, _update)


def submit_plan(team_dir: Path, task_id: str, plan_text: str) -> str:
    return update_status(team_dir, task_id, "awaiting_approval", plan=plan_text)


def approve(team_dir: Path, task_id: str) -> str:
    return update_status(team_dir, task_id, "in_progress")


def reject(team_dir: Path, task_id: str, reason: str) -> str:
    return update_status(team_dir, task_id, "planning", result=reason)


def get_claimable(team_dir: Path, worker: str) -> list[Task]:
    tasks = load(team_dir)
    return [t for t in tasks if not t.owner and t.status == "pending" and _deps_met(t, tasks)]


def get_current(team_dir: Path, worker: str) -> Task | None:
    for task in load(team_dir):
        if task.owner == worker and task.status in {"planning", "awaiting_approval", "in_progress"}:
            return task
    return None


def add_task(team_dir: Path, task: Task) -> str:
    return _locked_update(team_dir, lambda tasks: (tasks.append(task), f"Added task {task.id}")[1])


def task_rows(tasks: list[Task]) -> list[dict[str, str]]:
    return [{
        "id": t.id,
        "title": t.title,
        "owner": t.owner or "—",
        "status": t.status,
        "depends": ", ".join(t.depends_on) or "—",
    } for t in tasks]


def member_rows(tasks: list[Task], members: list[Teammate]) -> list[dict[str, str]]:
    current_by_owner = {t.owner: t for t in tasks if t.owner and t.status in {"planning", "awaiting_approval", "in_progress"}}
    rows = []
    for m in members:
        current = current_by_owner.get(m.name)
        rows.append({
            "name": m.name,
            "role": m.role,
            "status": m.status,
            "task": f"{current.id}: {current.title}" if current else "—",
        })
    return rows


def approval_rows(tasks: list[Task]) -> list[dict[str, str]]:
    return [{
        "id": t.id,
        "title": t.title,
        "owner": t.owner or "—",
        "plan": (t.plan or "").strip() or "No plan submitted.",
    } for t in tasks if t.status == "awaiting_approval"]


def render_text(tasks: list[Task], members: list[Teammate]) -> str:
    if not tasks:
        return "No team tasks."
    member_text = "\n".join(
        f"- {row['name']}: {row['role']} ({row['status']}) [{row['task']}]"
        for row in member_rows(tasks, members)
    ) or "- none"
    task_text = "\n".join(
        f"| {row['id']} | {row['title']} | {row['owner']} | {row['status']} | {row['depends']} |"
        for row in task_rows(tasks)
    )
    return (
        "## Members\n"
        f"{member_text}\n\n"
        "## Tasks\n"
        "| ID | Title | Owner | Status | Depends |\n"
        "| --- | --- | --- | --- | --- |\n"
        f"{task_text}"
    )
