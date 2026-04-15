"""SQLite database operations for Kosmos project/task management."""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Generator, Optional

import aiosqlite
from loguru import logger

DATABASE_PATH = Path.home() / ".nanobot" / "kosmos.db"

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    color TEXT DEFAULT '#6b7280',
    is_hidden INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT DEFAULT 'todo',
    assigned_to TEXT,
    release_approved INTEGER DEFAULT 0,
    approved_by TEXT,
    approved_branch TEXT,
    approved_push INTEGER DEFAULT 0,
    approved_at TEXT,
    workspace_path TEXT,
    work_branch TEXT,
    base_branch TEXT,
    release_note TEXT,
    jira_ready INTEGER DEFAULT 0,
    retry_count INTEGER DEFAULT 0,
    last_failure_reason TEXT,
    priority TEXT DEFAULT 'medium',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_comments (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    comment TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS task_artifacts (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'screenshot',
    filename TEXT NOT NULL,
    path TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes INTEGER DEFAULT 0,
    created_by TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_task_artifacts_task_id ON task_artifacts(task_id);
CREATE INDEX IF NOT EXISTS idx_task_artifacts_created_at ON task_artifacts(created_at);
"""

TASKS_EXTRA_COLUMNS: list[tuple[str, str]] = [
    ("release_approved", "INTEGER DEFAULT 0"),
    ("approved_by", "TEXT"),
    ("approved_branch", "TEXT"),
    ("approved_push", "INTEGER DEFAULT 0"),
    ("approved_at", "TEXT"),
    ("workspace_path", "TEXT"),
    ("work_branch", "TEXT"),
    ("base_branch", "TEXT"),
    ("release_note", "TEXT"),
    ("jira_ready", "INTEGER DEFAULT 0"),
    ("retry_count", "INTEGER DEFAULT 0"),
    ("last_failure_reason", "TEXT"),
]

ARTIFACTS_EXTRA_COLUMNS: list[tuple[str, str]] = [
    ("size_bytes", "INTEGER DEFAULT 0"),
    ("created_by", "TEXT"),
]


async def _ensure_artifacts_columns(db: aiosqlite.Connection) -> None:
    """Apply idempotent schema upgrades for artifacts table."""
    async with db.execute("PRAGMA table_info(task_artifacts)") as cursor:
        rows = await cursor.fetchall()
    existing = {str(row[1]) for row in rows}
    for column, definition in ARTIFACTS_EXTRA_COLUMNS:
        if column in existing:
            continue
        await db.execute(f"ALTER TABLE task_artifacts ADD COLUMN {column} {definition}")


async def _ensure_tasks_columns(db: aiosqlite.Connection) -> None:
    """Apply idempotent schema upgrades for task release workflow fields."""
    async with db.execute("PRAGMA table_info(tasks)") as cursor:
        rows = await cursor.fetchall()
    existing = {str(row[1]) for row in rows}
    for column, definition in TASKS_EXTRA_COLUMNS:
        if column in existing:
            continue
        await db.execute(f"ALTER TABLE tasks ADD COLUMN {column} {definition}")


# ---------------------------------------------------------------------------
# Database initialization
# ---------------------------------------------------------------------------


async def init_db(db_path: Path = DATABASE_PATH) -> aiosqlite.Connection:
    """Initialize database connection and create schema if needed."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(str(db_path))
    db.row_factory = aiosqlite.Row
    await db.executescript(SCHEMA)
    await _ensure_tasks_columns(db)
    await _ensure_artifacts_columns(db)
    await db.commit()
    logger.info("Kosmos database initialized at {}", db_path)
    return db


@contextmanager
def sync_init_db(db_path: Path = DATABASE_PATH) -> Generator[aiosqlite.Connection, None, None]:
    """Synchronous context manager for database initialization."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = aiosqlite.connect(str(db_path))
    db.row_factory = aiosqlite.Row
    db.executescript(SCHEMA)
    db.commit()
    logger.info("Kosmos database initialized at {}", db_path)
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Projects CRUD
# ---------------------------------------------------------------------------


async def create_project(
    db: aiosqlite.Connection,
    name: str,
    path: str,
    color: str = "#6b7280",
    is_hidden: bool = False,
    project_id: Optional[str] = None,
) -> dict[str, Any]:
    """Create a new project."""
    pid = project_id or str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    await db.execute(
        """INSERT INTO projects (id, name, path, color, is_hidden, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (pid, name, path, color, int(is_hidden), now),
    )
    await db.commit()

    logger.info("Created project: {} ({})", name, pid)
    return {
        "id": pid,
        "name": name,
        "path": path,
        "color": color,
        "is_hidden": bool(is_hidden),
        "created_at": now,
    }


async def get_project(db: aiosqlite.Connection, project_id: str) -> Optional[dict[str, Any]]:
    """Get a single project by ID."""
    async with db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)) as cursor:
        row = await cursor.fetchone()
        if row:
            return dict(row)
        return None


async def get_projects(
    db: aiosqlite.Connection,
    include_hidden: bool = False,
) -> list[dict[str, Any]]:
    """Get all projects, optionally including hidden ones."""
    query = "SELECT * FROM projects"
    if not include_hidden:
        query += " WHERE is_hidden = 0"
    query += " ORDER BY created_at DESC"

    async with db.execute(query) as cursor:
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_projects_with_task_count(
    db: aiosqlite.Connection,
    include_hidden: bool = False,
) -> list[dict[str, Any]]:
    """Get all projects with task count."""
    query = """
        SELECT p.*, COUNT(t.id) as task_count
        FROM projects p
        LEFT JOIN tasks t ON t.project_id = p.id
    """
    if not include_hidden:
        query += " WHERE p.is_hidden = 0"
    query += " GROUP BY p.id ORDER BY p.created_at DESC"

    async with db.execute(query) as cursor:
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def update_project(
    db: aiosqlite.Connection,
    project_id: str,
    **fields,
) -> Optional[dict[str, Any]]:
    """Update project fields. Returns updated project or None if not found."""
    allowed = {"name", "path", "color", "is_hidden"}
    updates = {k: v for k, v in fields.items() if k in allowed}

    if not updates:
        return await get_project(db, project_id)

    # Handle boolean conversion for is_hidden
    if "is_hidden" in updates:
        updates["is_hidden"] = int(bool(updates["is_hidden"]))

    set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
    values = list(updates.values()) + [project_id]

    await db.execute(f"UPDATE projects SET {set_clause} WHERE id = ?", values)
    await db.commit()

    logger.info("Updated project {}: {}", project_id, updates)
    return await get_project(db, project_id)


async def delete_project(db: aiosqlite.Connection, project_id: str) -> bool:
    """Delete a project and its tasks. Returns True if deleted."""
    # Tasks are deleted via CASCADE, but let's do it explicitly
    await db.execute("DELETE FROM tasks WHERE project_id = ?", (project_id,))
    cursor = await db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    await db.commit()

    deleted = cursor.rowcount > 0
    if deleted:
        logger.info("Deleted project: {}", project_id)
    return deleted


# ---------------------------------------------------------------------------
# Tasks CRUD
# ---------------------------------------------------------------------------


async def create_task(
    db: aiosqlite.Connection,
    project_id: str,
    title: str,
    description: Optional[str] = None,
    status: str = "todo",
    assigned_to: Optional[str] = None,
    priority: str = "medium",
    task_id: Optional[str] = None,
) -> dict[str, Any]:
    """Create a new task."""
    tid = task_id or str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    await db.execute(
        """INSERT INTO tasks (id, project_id, title, description, status, assigned_to, priority, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (tid, project_id, title, description, status, assigned_to, priority, now, now),
    )
    await db.commit()

    logger.info("Created task: {} ({})", title, tid)
    return {
        "id": tid,
        "project_id": project_id,
        "title": title,
        "description": description,
        "status": status,
        "assigned_to": assigned_to,
        "release_approved": False,
        "approved_by": None,
        "approved_branch": None,
        "approved_push": False,
        "approved_at": None,
        "workspace_path": None,
        "work_branch": None,
        "base_branch": None,
        "release_note": None,
        "jira_ready": False,
        "retry_count": 0,
        "last_failure_reason": None,
        "priority": priority,
        "created_at": now,
        "updated_at": now,
    }


async def get_task(db: aiosqlite.Connection, task_id: str) -> Optional[dict[str, Any]]:
    """Get a single task by ID."""
    async with db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)) as cursor:
        row = await cursor.fetchone()
        if row:
            return dict(row)
        return None


async def get_tasks(
    db: aiosqlite.Connection,
    project_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Get all tasks, optionally filtered by project_id."""
    if project_id:
        async with db.execute(
            "SELECT * FROM tasks WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,),
        ) as cursor:
            rows = await cursor.fetchall()
    else:
        async with db.execute("SELECT * FROM tasks ORDER BY created_at DESC") as cursor:
            rows = await cursor.fetchall()

    return [dict(row) for row in rows]


async def update_task(
    db: aiosqlite.Connection,
    task_id: str,
    **fields,
) -> Optional[dict[str, Any]]:
    """Update task fields. Returns updated task or None if not found."""
    allowed = {
        "project_id",
        "title",
        "description",
        "status",
        "assigned_to",
        "priority",
        "release_approved",
        "approved_by",
        "approved_branch",
        "approved_push",
        "approved_at",
        "workspace_path",
        "work_branch",
        "base_branch",
        "release_note",
        "jira_ready",
        "retry_count",
        "last_failure_reason",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}

    if not updates:
        return await get_task(db, task_id)

    if "release_approved" in updates:
        updates["release_approved"] = int(bool(updates["release_approved"]))
    if "approved_push" in updates:
        updates["approved_push"] = int(bool(updates["approved_push"]))
    if "jira_ready" in updates:
        updates["jira_ready"] = int(bool(updates["jira_ready"]))
    if "retry_count" in updates:
        try:
            updates["retry_count"] = max(0, int(updates["retry_count"]))
        except Exception:
            updates["retry_count"] = 0

    updates["updated_at"] = datetime.utcnow().isoformat()

    set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
    values = list(updates.values()) + [task_id]

    await db.execute(f"UPDATE tasks SET {set_clause} WHERE id = ?", values)
    await db.commit()

    logger.info("Updated task {}: {}", task_id, updates)
    return await get_task(db, task_id)


async def delete_task(db: aiosqlite.Connection, task_id: str) -> bool:
    """Delete a task. Returns True if deleted."""
    cursor = await db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    await db.commit()

    deleted = cursor.rowcount > 0
    if deleted:
        logger.info("Deleted task: {}", task_id)
    return deleted


# ---------------------------------------------------------------------------
# Settings CRUD
# ---------------------------------------------------------------------------


async def get_settings(db: aiosqlite.Connection) -> dict[str, Any]:
    """Get all settings as a key-value dict."""
    async with db.execute("SELECT key, value FROM settings") as cursor:
        rows = await cursor.fetchall()
        return {
            row["key"]: json.loads(row["value"]) if row["value"].startswith("{") else row["value"]
            for row in rows
        }


async def get_setting(db: aiosqlite.Connection, key: str) -> Optional[Any]:
    """Get a single setting value."""
    async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cursor:
        row = await cursor.fetchone()
        if row:
            try:
                return json.loads(row["value"])
            except json.JSONDecodeError:
                return row["value"]
        return None


async def update_setting(
    db: aiosqlite.Connection,
    key: str,
    value: Any,
) -> dict[str, Any]:
    """Create or update a setting."""
    json_value = json.dumps(value) if not isinstance(value, str) else value
    await db.execute(
        """INSERT INTO settings (key, value) VALUES (?, ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
        (key, json_value),
    )
    await db.commit()

    logger.info("Updated setting: {} = {}", key, value)
    return {"key": key, "value": value}


async def delete_setting(db: aiosqlite.Connection, key: str) -> bool:
    """Delete a setting. Returns True if deleted."""
    cursor = await db.execute("DELETE FROM settings WHERE key = ?", (key,))
    await db.commit()
    return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Task Comments CRUD
# ---------------------------------------------------------------------------


async def get_task_comments(db: aiosqlite.Connection, task_id: str) -> list[dict[str, Any]]:
    """Get all comments for a task."""
    async with db.execute(
        "SELECT * FROM task_comments WHERE task_id = ? ORDER BY created_at ASC", (task_id,)
    ) as cursor:
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_task_comment_count(db: aiosqlite.Connection, task_id: str) -> int:
    """Get the number of comments for a task."""
    async with db.execute(
        "SELECT COUNT(*) as count FROM task_comments WHERE task_id = ?", (task_id,)
    ) as cursor:
        row = await cursor.fetchone()
        return row["count"] if row else 0


async def get_tasks_with_comment_count(
    db: aiosqlite.Connection, project_id: Optional[str] = None
) -> list[dict[str, Any]]:
    """Get all tasks with comment count."""
    if project_id:
        async with db.execute(
            """SELECT t.*, p.name as project_name, p.path as project_path, COUNT(c.id) as comment_count
               FROM tasks t
               LEFT JOIN projects p ON t.project_id = p.id
               LEFT JOIN task_comments c ON t.id = c.task_id
               WHERE t.project_id = ?
               GROUP BY t.id
               ORDER BY t.created_at DESC""",
            (project_id,),
        ) as cursor:
            rows = await cursor.fetchall()
    else:
        async with db.execute(
            """SELECT t.*, p.name as project_name, p.path as project_path, COUNT(c.id) as comment_count
               FROM tasks t
               LEFT JOIN projects p ON t.project_id = p.id
               LEFT JOIN task_comments c ON t.id = c.task_id
               GROUP BY t.id
               ORDER BY t.created_at DESC"""
        ) as cursor:
            rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def create_task_comment(
    db: aiosqlite.Connection,
    task_id: str,
    agent_id: str,
    agent_name: str,
    comment: str,
) -> dict[str, Any]:
    """Create a new comment for a task."""
    import uuid

    comment_id = str(uuid.uuid4())
    created_at = datetime.utcnow().isoformat()

    await db.execute(
        """INSERT INTO task_comments (id, task_id, agent_id, agent_name, comment, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (comment_id, task_id, agent_id, agent_name, comment, created_at),
    )
    await db.commit()

    logger.info("Created comment {} for task {}", comment_id, task_id)
    return {
        "id": comment_id,
        "task_id": task_id,
        "agent_id": agent_id,
        "agent_name": agent_name,
        "comment": comment,
        "created_at": created_at,
    }


async def delete_task_comment(db: aiosqlite.Connection, comment_id: str) -> bool:
    """Delete a comment. Returns True if deleted."""
    cursor = await db.execute("DELETE FROM task_comments WHERE id = ?", (comment_id,))
    await db.commit()
    return cursor.rowcount > 0


async def create_artifact(
    db: aiosqlite.Connection,
    task_id: str,
    filename: str,
    path: str,
    mime_type: str,
    kind: str = "screenshot",
    size_bytes: int = 0,
    created_by: Optional[str] = None,
) -> dict[str, Any]:
    """Create a new artifact record."""
    artifact_id = str(uuid.uuid4())
    created_at = datetime.utcnow().isoformat()

    await db.execute(
        """INSERT INTO task_artifacts (id, task_id, kind, filename, path, mime_type, size_bytes, created_by, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (artifact_id, task_id, kind, filename, path, mime_type, size_bytes, created_by, created_at),
    )
    await db.commit()

    logger.info("Created artifact {} for task {}", artifact_id, task_id)
    return {
        "id": artifact_id,
        "task_id": task_id,
        "kind": kind,
        "filename": filename,
        "path": path,
        "mime_type": mime_type,
        "size_bytes": size_bytes,
        "created_by": created_by,
        "created_at": created_at,
    }


async def get_artifacts_for_task(
    db: aiosqlite.Connection,
    task_id: str,
) -> list[dict[str, Any]]:
    """Get all artifacts for a task, ordered by creation time."""
    async with db.execute(
        "SELECT * FROM task_artifacts WHERE task_id = ? ORDER BY created_at ASC",
        (task_id,),
    ) as cursor:
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_artifact_by_id(
    db: aiosqlite.Connection,
    artifact_id: str,
) -> Optional[dict[str, Any]]:
    """Get a single artifact by ID."""
    async with db.execute(
        "SELECT * FROM task_artifacts WHERE id = ?",
        (artifact_id,),
    ) as cursor:
        row = await cursor.fetchone()
        if row:
            return dict(row)
        return None


async def delete_artifact(db: aiosqlite.Connection, artifact_id: str) -> bool:
    """Delete an artifact record. Returns True if deleted."""
    cursor = await db.execute("DELETE FROM task_artifacts WHERE id = ?", (artifact_id,))
    await db.commit()
    return cursor.rowcount > 0


async def count_artifacts_for_task(db: aiosqlite.Connection, task_id: str) -> int:
    """Count artifacts for a specific task."""
    async with db.execute(
        "SELECT COUNT(*) FROM task_artifacts WHERE task_id = ?",
        (task_id,),
    ) as cursor:
        row = await cursor.fetchone()
        return int(row[0]) if row else 0


async def delete_expired_artifacts(
    db: aiosqlite.Connection,
    older_than_days: int = 14,
) -> tuple[int, int]:
    """Delete artifacts older than specified days.

    Returns tuple of (count_deleted, bytes_freed).
    """
    from datetime import timedelta

    cutoff = datetime.utcnow() - timedelta(days=older_than_days)
    cutoff_str = cutoff.isoformat()

    async with db.execute(
        "SELECT id, path, size_bytes FROM task_artifacts WHERE created_at < ?",
        (cutoff_str,),
    ) as cursor:
        rows = await cursor.fetchall()

    count = 0
    bytes_freed = 0
    for row in rows:
        artifact_id = str(row["id"])
        file_path = str(row["path"])
        size = int(row["size_bytes"] or 0)

        actual_path = Path(file_path)
        if actual_path.exists():
            try:
                actual_path.unlink()
                bytes_freed += size
            except OSError:
                pass

        await db.execute("DELETE FROM task_artifacts WHERE id = ?", (artifact_id,))
        count += 1

    await db.commit()
    logger.info("Cleaned {} expired artifacts, freed {} bytes", count, bytes_freed)
    return count, bytes_freed
