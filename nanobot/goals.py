"""Small durable state graph for sustained goals.

The whole current graph is one versioned JSON snapshot. SQLite provides atomic compare-and-swap
writes and a compact audit log; graph policy stays in the pure :func:`reduce_goal` function.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from nanobot.config.paths import get_runtime_subdir

_CURRENT_STATUSES = ("active", "waiting")
_NODE_ID = re.compile(r"[A-Za-z0-9_.-]{1,64}")
_NODE_STATUSES = {"pending", "ready", "running", "succeeded", "blocked", "superseded"}
_MAX_NODES = 64
_MAX_DEPTH = 16
MAX_RECOVERY_ATTEMPTS = 4


class GoalError(RuntimeError):
    pass


class GoalConflictError(GoalError):
    pass


@dataclass(frozen=True, slots=True)
class Goal:
    id: str
    session_key: str
    status: str
    version: int
    summary: str
    state: dict[str, Any]


def workspace_fingerprint(workspace: str | Path) -> str:
    resolved = Path(workspace).expanduser().resolve(strict=False)
    normalized = os.path.normcase(str(resolved)).replace("\\", "/")
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


class GoalStore:
    """Two-table SQLite store with short connections and optimistic versions."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._initialized = False
        self._init_lock = threading.Lock()

    @classmethod
    def for_workspace(
        cls,
        workspace: str | Path,
        *,
        root: str | Path | None = None,
    ) -> GoalStore:
        base = Path(root) if root is not None else get_runtime_subdir("goals")
        return cls(base / workspace_fingerprint(workspace) / "goals.sqlite3")

    def initialize(self) -> None:
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            for attempt in range(5):
                try:
                    with closing(self._connect()) as db:
                        db.executescript(
                            """
                            PRAGMA journal_mode = WAL;
                            CREATE TABLE IF NOT EXISTS goal_runs (
                                id TEXT PRIMARY KEY,
                                session_key TEXT NOT NULL,
                                status TEXT NOT NULL,
                                version INTEGER NOT NULL,
                                summary TEXT NOT NULL,
                                state_json TEXT NOT NULL,
                                created_at TEXT NOT NULL,
                                updated_at TEXT NOT NULL
                            );
                            CREATE UNIQUE INDEX IF NOT EXISTS uq_goal_current_session
                            ON goal_runs(session_key) WHERE status IN ('active', 'waiting');
                            CREATE TABLE IF NOT EXISTS goal_events (
                                goal_id TEXT NOT NULL REFERENCES goal_runs(id) ON DELETE CASCADE,
                                sequence INTEGER NOT NULL,
                                event_type TEXT NOT NULL,
                                payload_json TEXT NOT NULL,
                                created_at TEXT NOT NULL,
                                PRIMARY KEY(goal_id, sequence)
                            );
                            """
                        )
                    break
                except sqlite3.OperationalError as exc:
                    if "locked" not in str(exc).lower() or attempt == 4:
                        raise
                    time.sleep(0.05 * (attempt + 1))
            self._initialized = True

    def create(
        self,
        session_key: str,
        objective: str,
        summary: str = "",
        route: Mapping[str, str] | None = None,
    ) -> Goal:
        session_key, objective = session_key.strip(), objective.strip()
        if not session_key or not objective:
            raise ValueError("session key and objective are required")
        state = {
            "schema": 1,
            "objective": objective,
            "revision": 0,
            "nodes": {},
            "needs_replan": False,
            "recovery_attempts": 0,
            "route": dict(route or {}),
        }
        now, goal_id = _now(), f"goal_{uuid.uuid4().hex}"
        self.initialize()
        try:
            with self._write() as db:
                existing = db.execute(
                    "SELECT * FROM goal_runs WHERE session_key=? AND status IN ('active','waiting')",
                    (session_key,),
                ).fetchone()
                if existing is not None:
                    goal = _goal(existing)
                    if goal.state.get("objective") == objective:
                        return goal
                    raise GoalConflictError("this session already has a current goal")
                db.execute(
                    "INSERT INTO goal_runs VALUES (?,?,?,?,?,?,?,?)",
                    (goal_id, session_key, "active", 1, summary[:120], _json(state), now, now),
                )
                self._event(db, goal_id, 1, "goal_created", {"objective": objective}, now)
                return self._require(db, goal_id)
        except sqlite3.IntegrityError as exc:
            raise GoalConflictError("this session already has a current goal") from exc

    def get(self, goal_id: str) -> Goal | None:
        self.initialize()
        with closing(self._connect()) as db:
            row = db.execute("SELECT * FROM goal_runs WHERE id=?", (goal_id,)).fetchone()
            return _goal(row) if row is not None else None

    def current(self, session_key: str) -> Goal | None:
        self.initialize()
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT * FROM goal_runs WHERE session_key=? AND status IN ('active','waiting')",
                (session_key,),
            ).fetchone()
            return _goal(row) if row is not None else None

    def active(self) -> list[Goal]:
        """Return active Goals for restart/periodic driving."""
        self.initialize()
        with closing(self._connect()) as db:
            rows = db.execute("SELECT * FROM goal_runs WHERE status='active'").fetchall()
        return [_goal(row) for row in rows]

    def apply(
        self,
        goal_id: str,
        expected_version: int,
        command: Mapping[str, Any],
    ) -> Goal:
        """Apply one pure state command and append its event in the same transaction."""
        self.initialize()
        with self._write() as db:
            current = self._require(db, goal_id)
            if current.version != expected_version:
                raise GoalConflictError(
                    f"goal is at version {current.version}, expected {expected_version}"
                )
            if current.status not in _CURRENT_STATUSES:
                raise GoalError("only a current goal can be updated")
            state, event_type = reduce_goal(current.state, command)
            version, now = current.version + 1, _now()
            cursor = db.execute(
                "UPDATE goal_runs SET version=?, state_json=?, updated_at=? "
                "WHERE id=? AND version=? AND status IN ('active','waiting')",
                (version, _json(state), now, goal_id, expected_version),
            )
            if cursor.rowcount != 1:
                raise GoalConflictError("goal changed while applying the command")
            self._event(db, goal_id, version, event_type, dict(command), now)
            return self._require(db, goal_id)

    def close(self, goal_id: str, expected_version: int, status: str, recap: str = "") -> Goal:
        if status not in {"completed", "cancelled"}:
            raise ValueError("invalid terminal goal status")
        self.initialize()
        with self._write() as db:
            current = self._require(db, goal_id)
            if current.version != expected_version:
                raise GoalConflictError(
                    f"goal is at version {current.version}, expected {expected_version}"
                )
            if current.status not in _CURRENT_STATUSES:
                raise GoalError("only a current goal can be closed")
            if status == "completed":
                nodes = _nodes(current.state)
                retained = [node for node in nodes.values() if node["status"] != "superseded"]
                if retained and any(node["status"] != "succeeded" for node in retained):
                    raise GoalError("goal cannot complete until every retained node succeeds")
            version, now = current.version + 1, _now()
            state = {**current.state, "recap": recap[:8000]}
            db.execute(
                "UPDATE goal_runs SET status=?, version=?, state_json=?, updated_at=? "
                "WHERE id=? AND version=?",
                (status, version, _json(state), now, goal_id, expected_version),
            )
            self._event(db, goal_id, version, f"goal_{status}", {"recap": recap}, now)
            return self._require(db, goal_id)

    def set_status(
        self,
        goal_id: str,
        expected_version: int,
        status: str,
        reason: str = "",
    ) -> Goal:
        """Pause, resume, or fail a Goal without changing its graph."""
        if status not in {"active", "waiting", "failed"}:
            raise ValueError("invalid goal status transition")
        self.initialize()
        with self._write() as db:
            current = self._require(db, goal_id)
            if current.version != expected_version:
                raise GoalConflictError(
                    f"goal is at version {current.version}, expected {expected_version}"
                )
            allowed = (
                current.status == "active" and status in {"waiting", "failed"}
            ) or (current.status == "waiting" and status == "active")
            if not allowed:
                raise GoalError(f"goal cannot transition from {current.status} to {status}")
            version, now = current.version + 1, _now()
            state = deepcopy(current.state)
            state["status_reason"] = reason[:8000]
            state.pop("driver", None)
            if status == "active":
                state["recovery_attempts"] = 0
            db.execute(
                "UPDATE goal_runs SET status=?,version=?,state_json=?,updated_at=? "
                "WHERE id=? AND version=?",
                (status, version, _json(state), now, goal_id, expected_version),
            )
            self._event(db, goal_id, version, f"goal_{status}", {"reason": reason}, now)
            return self._require(db, goal_id)

    def replace(
        self,
        goal_id: str,
        expected_version: int,
        objective: str,
        summary: str = "",
    ) -> Goal:
        objective = objective.strip()
        if not objective:
            raise ValueError("replacement objective is required")
        self.initialize()
        with self._write() as db:
            old = self._require(db, goal_id)
            if old.version != expected_version:
                raise GoalConflictError(
                    f"goal is at version {old.version}, expected {expected_version}"
                )
            if old.status not in _CURRENT_STATUSES:
                raise GoalError("only a current goal can be replaced")
            now, new_id = _now(), f"goal_{uuid.uuid4().hex}"
            db.execute(
                "UPDATE goal_runs SET status='replaced',version=?,updated_at=? WHERE id=?",
                (old.version + 1, now, old.id),
            )
            self._event(db, old.id, old.version + 1, "goal_replaced", {"by": new_id}, now)
            state = {
                "schema": 1,
                "objective": objective,
                "previous_objective": str(old.state.get("objective") or "")[:4000],
                "revision": 0,
                "nodes": {},
                "needs_replan": False,
                "recovery_attempts": 0,
                "route": dict(old.state.get("route") or {}),
            }
            db.execute(
                "INSERT INTO goal_runs VALUES (?,?,?,?,?,?,?,?)",
                (new_id, old.session_key, "active", 1, summary[:120], _json(state), now, now),
            )
            self._event(db, new_id, 1, "goal_created", {"objective": objective}, now)
            return self._require(db, new_id)

    def events(self, goal_id: str, limit: int = 50) -> list[dict[str, Any]]:
        self.initialize()
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT * FROM goal_events WHERE goal_id=? ORDER BY sequence DESC LIMIT ?",
                (goal_id, max(1, min(limit, 100))),
            ).fetchall()
        return [
            {
                "sequence": row["sequence"],
                "type": row["event_type"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=5000")
        return db

    def _write(self):
        return _Transaction(self._connect())

    @staticmethod
    def _require(db: sqlite3.Connection, goal_id: str) -> Goal:
        row = db.execute("SELECT * FROM goal_runs WHERE id=?", (goal_id,)).fetchone()
        if row is None:
            raise GoalError("goal does not exist")
        return _goal(row)

    @staticmethod
    def _event(
        db: sqlite3.Connection,
        goal_id: str,
        sequence: int,
        event_type: str,
        payload: Mapping[str, Any],
        created_at: str,
    ) -> None:
        db.execute(
            "INSERT INTO goal_events VALUES (?,?,?,?,?)",
            (goal_id, sequence, event_type, _json(dict(payload)), created_at),
        )


class _Transaction:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def __enter__(self) -> sqlite3.Connection:
        self.db.execute("BEGIN IMMEDIATE")
        return self.db

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            self.db.rollback() if exc_type else self.db.commit()
        finally:
            self.db.close()


def reduce_goal(state: Mapping[str, Any], command: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    """Pure, deterministic transition for plan and node commands."""
    next_state = deepcopy(dict(state))
    nodes = _nodes(next_state)
    action = str(command.get("action") or "").strip()
    if action == "driver_turn":
        driver = dict(next_state.get("driver") or {})
        progressed = bool(command.get("progressed"))
        next_state["driver"] = {"stalls": 0 if progressed else int(driver.get("stalls", 0)) + 1}
        return next_state, "goal_driver_turn"
    if action == "recovery_attempt":
        node_id = str(command.get("node_id") or "").strip()
        node = nodes.get(node_id)
        if node is None or node["status"] != "blocked":
            raise GoalError("recovery requires a blocked node")
        attempts = int(next_state.get("recovery_attempts", 0))
        if attempts >= MAX_RECOVERY_ATTEMPTS:
            raise GoalError("Goal recovery budget is exhausted")
        next_state["recovery_attempts"] = attempts + 1
        return next_state, "recovery_attempted"
    if action == "plan":
        if nodes:
            raise GoalError("initial plan already exists")
        planned = _parse_nodes(command.get("nodes"))
        _validate_graph(planned)
        _unlock(planned)
        next_state.update(nodes=planned, revision=1, needs_replan=False)
        return next_state, "goal_planned"

    node_id = str(command.get("node_id") or "").strip()
    node = nodes.get(node_id)
    if node is None:
        raise GoalError("node is not in the current plan")
    if action == "begin":
        if node.get("kind", "action") != "action":
            raise GoalError("a coarse node must be expanded before execution")
        if node["status"] != "ready":
            raise GoalError("only a ready node can begin")
        node["status"] = "running"
        event = "node_started"
    elif action == "succeed":
        if node["status"] != "running":
            raise GoalError("only a running node can succeed")
        result = str(command.get("result") or "").strip()
        if not result:
            raise GoalError("a successful node requires a result summary")
        node.update(status="succeeded", result=result[:8000])
        _unlock(nodes)
        event = "node_succeeded"
    elif action == "block":
        if node["status"] not in {"ready", "running"}:
            raise GoalError("only a ready or running node can be blocked")
        reason = str(command.get("reason") or "").strip()
        if not reason:
            raise GoalError("a blocked node requires failure evidence")
        node.update(status="blocked", failure=reason[:8000])
        next_state["needs_replan"] = True
        event = "node_blocked"
    elif action == "expand":
        if node.get("kind", "action") != "coarse" or node["status"] != "pending":
            raise GoalError("only a pending coarse node can be expanded")
        if not all(nodes[dep]["status"] == "succeeded" for dep in node["depends_on"]):
            raise GoalError("a coarse node can expand only after its dependencies succeed")
        _replace_with_subgraph(nodes, node_id, command.get("nodes"), inherit_dependencies=True)
        event = "plan_expanded"
    elif action == "replan":
        if node["status"] != "blocked":
            raise GoalError("only a blocked node can be replanned")
        _replace_with_subgraph(nodes, node_id, command.get("nodes"))
        next_state["needs_replan"] = any(
            item["status"] == "blocked" for item in nodes.values()
        )
        next_state["recovery_attempts"] = 0
        event = "goal_replanned"
    else:
        raise GoalError("unknown goal command")
    next_state["revision"] = int(next_state.get("revision", 0)) + 1
    return next_state, event


def _parse_nodes(
    specs: Any,
    *,
    existing_ids: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    if not isinstance(specs, list) or not specs or len(specs) > _MAX_NODES:
        raise GoalError(f"plan must contain 1-{_MAX_NODES} nodes")
    existing_ids = existing_ids or set()
    planned: dict[str, dict[str, Any]] = {}
    for raw in specs:
        if not isinstance(raw, Mapping):
            raise GoalError("plan nodes must be objects")
        node_id = str(raw.get("id") or "").strip()
        if _NODE_ID.fullmatch(node_id) is None or node_id in planned or node_id in existing_ids:
            raise GoalError("node ids must be unique letters, numbers, dot, dash, or underscore")
        title = str(raw.get("title") or "").strip()
        outcome = str(raw.get("outcome") or "").strip()
        kind = str(raw.get("kind") or "action").strip()
        deps = raw.get("depends_on", [])
        if (
            not title
            or not outcome
            or kind not in {"action", "coarse"}
            or not isinstance(deps, list)
            or len(deps) > _MAX_NODES
        ):
            raise GoalError("each node needs title, outcome, and depends_on")
        planned[node_id] = {
            "id": node_id,
            "title": title[:300],
            "outcome": outcome[:2000],
            "kind": kind,
            "depends_on": list(dict.fromkeys(str(dep).strip() for dep in deps)),
            "status": "pending",
        }
    return planned


def _replace_with_subgraph(
    nodes: dict[str, dict[str, Any]],
    node_id: str,
    specs: Any,
    *,
    inherit_dependencies: bool = False,
) -> None:
    replacements = _parse_nodes(specs, existing_ids=set(nodes))
    if len(nodes) + len(replacements) > _MAX_NODES:
        raise GoalError(f"replacement plan would exceed {_MAX_NODES} total nodes")
    succeeded = {item_id for item_id, item in nodes.items() if item["status"] == "succeeded"}
    if any(
        dep in nodes and dep not in succeeded
        for replacement in replacements.values()
        for dep in replacement["depends_on"]
    ):
        raise GoalError("replacement nodes may depend only on new or succeeded nodes")
    replacement_ids = set(replacements)
    if inherit_dependencies:
        inherited = nodes[node_id]["depends_on"]
        for replacement in replacements.values():
            if not any(dep in replacement_ids for dep in replacement["depends_on"]):
                replacement["depends_on"] = list(
                    dict.fromkeys([*inherited, *replacement["depends_on"]])
                )
    referenced = {dep for item in replacements.values() for dep in item["depends_on"]}
    leaves = [item_id for item_id in replacements if item_id not in referenced]
    nodes[node_id]["status"] = "superseded"
    for downstream in nodes.values():
        if node_id in downstream["depends_on"]:
            downstream["depends_on"] = list(
                dict.fromkeys(
                    dep
                    for original in downstream["depends_on"]
                    for dep in (leaves if original == node_id else [original])
                )
            )
    nodes.update(replacements)
    _validate_graph(nodes)
    _unlock(nodes)


def projection(goal: Goal, limit: int = 8) -> dict[str, Any]:
    nodes = _nodes(goal.state)
    ordered = list(nodes.values())
    return {
        "goal_id": goal.id,
        "status": goal.status,
        "version": goal.version,
        "objective": goal.state.get("objective", ""),
        "revision": goal.state.get("revision", 0),
        "expandable": [
            _project_node(node)
            for node in ordered
            if node.get("kind") == "coarse"
            and node["status"] == "pending"
            and all(nodes[dep]["status"] == "succeeded" for dep in node["depends_on"])
        ][:limit],
        "frontier": [_project_node(node) for node in ordered if node["status"] == "ready"][
            :limit
        ],
        "running": [_project_node(node) for node in ordered if node["status"] == "running"][
            :limit
        ],
        "blocked": [_project_node(node) for node in ordered if node["status"] == "blocked"][
            :limit
        ],
        "succeeded": [
            _project_node(node) for node in ordered if node["status"] == "succeeded"
        ][-limit:],
        "needs_replan": bool(goal.state.get("needs_replan")),
        "recovery_attempts": int(goal.state.get("recovery_attempts", 0)),
        "max_recovery_attempts": MAX_RECOVERY_ATTEMPTS,
        "status_reason": str(goal.state.get("status_reason") or "")[:1000],
        "node_count": len(nodes),
    }


def _project_node(node: Mapping[str, Any]) -> dict[str, Any]:
    projected = dict(node)
    for field in ("result", "failure"):
        if field in projected:
            projected[field] = str(projected[field])[:1000]
    return projected


def compact_ref(goal: Goal, workspace: str | Path) -> dict[str, Any]:
    ref = {
        "schema": 1,
        "goal_id": goal.id,
        "workspace": workspace_fingerprint(workspace),
        "status": goal.status,
        "version": goal.version,
        # Compatibility/display snapshot only; GoalStore remains authoritative.
        "objective": str(goal.state.get("objective") or "")[:4000],
        "ui_summary": goal.summary,
    }
    for field in ("previous_objective", "recap"):
        value = str(goal.state.get(field) or "")
        if value:
            ref[field] = value[:8000]
    return ref


def _validate_graph(nodes: Mapping[str, Mapping[str, Any]]) -> None:
    for node_id, node in nodes.items():
        deps = node["depends_on"]
        if node_id in deps or any(dep not in nodes for dep in deps):
            raise GoalError("dependencies must reference other nodes in the plan")
    visiting: set[str] = set()
    depths: dict[str, int] = {}

    def visit(node_id: str) -> int:
        if node_id in visiting:
            raise GoalError("plan dependencies must be acyclic")
        if node_id in depths:
            return depths[node_id]
        visiting.add(node_id)
        depth = 1 + max((visit(dep) for dep in nodes[node_id]["depends_on"]), default=0)
        visiting.remove(node_id)
        if depth > _MAX_DEPTH:
            raise GoalError(f"plan depth exceeds {_MAX_DEPTH}")
        depths[node_id] = depth
        return depth

    for node_id in nodes:
        visit(node_id)


def _unlock(nodes: Mapping[str, dict[str, Any]]) -> None:
    for node in nodes.values():
        if (
            node["status"] == "pending"
            and node.get("kind", "action") == "action"
            and all(
            nodes[dep]["status"] == "succeeded" for dep in node["depends_on"]
            )
        ):
            node["status"] = "ready"


def _nodes(state: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    nodes = state.get("nodes")
    if not isinstance(nodes, dict):
        raise GoalError("goal state has invalid nodes")
    for node in nodes.values():
        if not isinstance(node, dict) or node.get("status") not in _NODE_STATUSES:
            raise GoalError("goal state contains an invalid node")
    return nodes


def _goal(row: sqlite3.Row) -> Goal:
    try:
        state = json.loads(row["state_json"])
    except (json.JSONDecodeError, TypeError) as exc:
        raise GoalError("goal state is not valid JSON") from exc
    if not isinstance(state, dict):
        raise GoalError("goal state must be a JSON object")
    return Goal(
        id=str(row["id"]),
        session_key=str(row["session_key"]),
        status=str(row["status"]),
        version=int(row["version"]),
        summary=str(row["summary"]),
        state=state,
    )


def _json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise GoalError("goal data must be JSON serializable") from exc


def _now() -> str:
    return datetime.now(UTC).isoformat()
