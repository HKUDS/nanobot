from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from nanobot.goals import GoalConflictError, GoalError, GoalStore, projection


def _store(tmp_path) -> GoalStore:
    return GoalStore(tmp_path / "goals.sqlite3")


def _plan() -> dict:
    return {
        "action": "plan",
        "nodes": [
            {"id": "build", "title": "Build", "outcome": "Artifact exists", "depends_on": []},
            {
                "id": "publish",
                "title": "Publish",
                "outcome": "Artifact is published",
                "depends_on": ["build"],
            },
        ],
    }


def test_store_uses_two_tables_and_keeps_current_graph_in_one_snapshot(tmp_path) -> None:
    store = _store(tmp_path)
    goal = store.create("cli:test", "Ship safely", "ship")
    planned = store.apply(goal.id, 1, _plan())

    with sqlite3.connect(store.path) as db:
        tables = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }

    assert tables == {"goal_runs", "goal_events"}
    assert planned.version == 2
    assert planned.state["nodes"]["build"]["status"] == "ready"
    assert planned.state["nodes"]["publish"]["status"] == "pending"
    assert [event["type"] for event in store.events(goal.id)] == [
        "goal_planned",
        "goal_created",
    ]


def test_store_closes_read_connections(tmp_path, monkeypatch) -> None:
    store = _store(tmp_path)
    goal = store.create("cli:test", "Close reads")
    connection = store._connect()

    class TrackedConnection:
        closed = False

        def execute(self, *args, **kwargs):
            return connection.execute(*args, **kwargs)

        def close(self):
            self.closed = True
            connection.close()

    tracked = TrackedConnection()
    monkeypatch.setattr(store, "_connect", lambda: tracked)

    assert store.get(goal.id) == goal
    assert tracked.closed is True


def test_success_unlocks_dependencies_and_completion_is_gated(tmp_path) -> None:
    store = _store(tmp_path)
    goal = store.create("cli:test", "Ship")
    goal = store.apply(goal.id, 1, _plan())

    with pytest.raises(GoalError, match="every retained node succeeds"):
        store.close(goal.id, 2, "completed")

    goal = store.apply(goal.id, 2, {"action": "begin", "node_id": "build"})
    goal = store.apply(
        goal.id,
        3,
        {"action": "succeed", "node_id": "build", "result": "build passed"},
    )
    assert goal.state["nodes"]["publish"]["status"] == "ready"
    goal = store.apply(goal.id, 4, {"action": "begin", "node_id": "publish"})
    goal = store.apply(
        goal.id,
        5,
        {"action": "succeed", "node_id": "publish", "result": "published"},
    )

    completed = store.close(goal.id, 6, "completed", "All nodes succeeded")
    assert completed.status == "completed"
    assert store.current("cli:test") is None


def test_blocked_path_preserves_independent_frontier_and_active_goal(tmp_path) -> None:
    store = _store(tmp_path)
    goal = store.create("cli:test", "Try independent paths")
    goal = store.apply(
        goal.id,
        1,
        {
            "action": "plan",
            "nodes": [
                {"id": "primary", "title": "Primary", "outcome": "Done", "depends_on": []},
                {"id": "other", "title": "Other", "outcome": "Done", "depends_on": []},
            ],
        },
    )
    goal = store.apply(goal.id, 2, {"action": "begin", "node_id": "primary"})
    goal = store.apply(
        goal.id,
        3,
        {"action": "block", "node_id": "primary", "reason": "endpoint unavailable"},
    )
    view = projection(goal)

    assert goal.status == "active"
    assert view["needs_replan"] is True
    assert [node["id"] for node in view["frontier"]] == ["other"]
    assert view["blocked"][0]["failure"] == "endpoint unavailable"


def test_invalid_or_stale_graph_commands_do_not_change_state(tmp_path) -> None:
    store = _store(tmp_path)
    goal = store.create("cli:test", "Ship")
    cyclic = {
        "action": "plan",
        "nodes": [
            {"id": "a", "title": "A", "outcome": "A", "depends_on": ["b"]},
            {"id": "b", "title": "B", "outcome": "B", "depends_on": ["a"]},
        ],
    }
    with pytest.raises(GoalError, match="acyclic"):
        store.apply(goal.id, 1, cyclic)
    assert store.get(goal.id).version == 1

    planned = store.apply(goal.id, 1, _plan())
    with pytest.raises(GoalConflictError, match="expected 1"):
        store.apply(goal.id, 1, {"action": "begin", "node_id": "build"})
    assert store.get(goal.id) == planned


def test_replace_is_atomic_and_preserves_one_current_goal_per_session(tmp_path) -> None:
    store = _store(tmp_path)
    old = store.create("cli:test", "Old")
    new = store.replace(old.id, 1, "New", "new")

    assert store.get(old.id).status == "replaced"
    assert store.current("cli:test") == new
    assert new.state["objective"] == "New"
    with pytest.raises(GoalConflictError):
        store.create("cli:test", "Different")


def test_concurrent_create_is_idempotent_across_store_instances(tmp_path) -> None:
    path = tmp_path / "goals.sqlite3"
    stores = [GoalStore(path), GoalStore(path)]
    barrier = Barrier(2)

    def create(store: GoalStore):
        barrier.wait()
        return store.create("cli:test", "Same objective")

    with ThreadPoolExecutor(max_workers=2) as pool:
        goals = list(pool.map(create, stores))

    assert goals[0].id == goals[1].id
    assert len(stores[0].events(goals[0].id)) == 1


def test_concurrent_compare_and_swap_allows_one_writer(tmp_path) -> None:
    path = tmp_path / "goals.sqlite3"
    primary = GoalStore(path)
    goal = primary.apply(primary.create("cli:test", "Ship").id, 1, _plan())
    stores = [GoalStore(path), GoalStore(path)]
    barrier = Barrier(2)

    def begin(store: GoalStore):
        barrier.wait()
        try:
            return store.apply(goal.id, goal.version, {"action": "begin", "node_id": "build"})
        except GoalConflictError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(begin, stores))

    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, GoalConflictError) for result in results) == 1
    assert primary.get(goal.id).version == goal.version + 1


def test_terminal_goal_rejects_further_mutation_and_projection_is_bounded(tmp_path) -> None:
    store = _store(tmp_path)
    goal = store.create("cli:test", "Bound context")
    goal = store.apply(
        goal.id,
        goal.version,
        {
            "action": "plan",
            "nodes": [{"id": "path", "title": "Path", "outcome": "Done", "depends_on": []}],
        },
    )
    goal = store.apply(
        goal.id,
        goal.version,
        {"action": "block", "node_id": "path", "reason": "x" * 8000},
    )
    assert len(projection(goal)["blocked"][0]["failure"]) == 1000

    terminal = store.close(goal.id, goal.version, "cancelled")
    with pytest.raises(GoalError, match="current goal"):
        store.close(terminal.id, terminal.version, "cancelled")
    with pytest.raises(GoalError, match="current goal"):
        store.apply(terminal.id, terminal.version, {"action": "begin", "node_id": "path"})


def test_replan_supersedes_blocked_path_and_rewires_downstream(tmp_path) -> None:
    store = _store(tmp_path)
    goal = store.create("cli:test", "Recover")
    goal = store.apply(
        goal.id,
        goal.version,
        {
            "action": "plan",
            "nodes": [
                {"id": "prep", "title": "Prep", "outcome": "Ready", "depends_on": []},
                {
                    "id": "failed",
                    "title": "Failed path",
                    "outcome": "Artifact",
                    "depends_on": ["prep"],
                },
                {
                    "id": "finish",
                    "title": "Finish",
                    "outcome": "Done",
                    "depends_on": ["failed"],
                },
                {"id": "other", "title": "Other", "outcome": "Done", "depends_on": []},
            ],
        },
    )
    goal = store.apply(goal.id, goal.version, {"action": "begin", "node_id": "prep"})
    goal = store.apply(
        goal.id,
        goal.version,
        {"action": "succeed", "node_id": "prep", "result": "prepared"},
    )
    goal = store.apply(goal.id, goal.version, {"action": "begin", "node_id": "failed"})
    goal = store.apply(
        goal.id,
        goal.version,
        {"action": "block", "node_id": "failed", "reason": "route is unavailable"},
    )
    goal = store.apply(
        goal.id,
        goal.version,
        {
            "action": "replan",
            "node_id": "failed",
            "nodes": [
                {
                    "id": "alternate",
                    "title": "Alternate route",
                    "outcome": "Artifact",
                    "depends_on": ["prep"],
                },
                {
                    "id": "verify_alt",
                    "title": "Verify alternate",
                    "outcome": "Verified artifact",
                    "depends_on": ["alternate"],
                },
            ],
        },
    )

    nodes = goal.state["nodes"]
    assert nodes["failed"]["status"] == "superseded"
    assert nodes["alternate"]["status"] == "ready"
    assert nodes["verify_alt"]["status"] == "pending"
    assert nodes["finish"]["depends_on"] == ["verify_alt"]
    assert nodes["other"]["status"] == "ready"
    assert goal.state["needs_replan"] is False


def test_replan_rejects_dependency_on_unfinished_existing_node(tmp_path) -> None:
    store = _store(tmp_path)
    goal = store.create("cli:test", "Recover")
    goal = store.apply(
        goal.id,
        goal.version,
        {
            "action": "plan",
            "nodes": [
                {"id": "failed", "title": "Failed", "outcome": "Done", "depends_on": []},
                {"id": "other", "title": "Other", "outcome": "Done", "depends_on": []},
            ],
        },
    )
    goal = store.apply(
        goal.id,
        goal.version,
        {"action": "block", "node_id": "failed", "reason": "unavailable"},
    )

    with pytest.raises(GoalError, match="succeeded nodes"):
        store.apply(
            goal.id,
            goal.version,
            {
                "action": "replan",
                "node_id": "failed",
                "nodes": [
                    {
                        "id": "bad_alt",
                        "title": "Bad alternate",
                        "outcome": "Done",
                        "depends_on": ["other"],
                    }
                ],
            },
        )
    assert store.get(goal.id) == goal


def test_coarse_node_becomes_expandable_and_expansion_rewires_downstream(tmp_path) -> None:
    store = _store(tmp_path)
    goal = store.create("cli:test", "Plan progressively")
    goal = store.apply(
        goal.id,
        goal.version,
        {
            "action": "plan",
            "nodes": [
                {"id": "prep", "title": "Prepare", "outcome": "Ready", "depends_on": []},
                {
                    "id": "coarse",
                    "title": "Implement unknown details",
                    "outcome": "Feature exists",
                    "kind": "coarse",
                    "depends_on": ["prep"],
                },
                {
                    "id": "release",
                    "title": "Release",
                    "outcome": "Released",
                    "depends_on": ["coarse"],
                },
            ],
        },
    )
    assert [node["id"] for node in projection(goal)["frontier"]] == ["prep"]
    assert projection(goal)["expandable"] == []

    goal = store.apply(goal.id, goal.version, {"action": "begin", "node_id": "prep"})
    goal = store.apply(
        goal.id,
        goal.version,
        {"action": "succeed", "node_id": "prep", "result": "requirements known"},
    )
    assert goal.state["nodes"]["coarse"]["status"] == "pending"
    assert [node["id"] for node in projection(goal)["expandable"]] == ["coarse"]

    goal = store.apply(
        goal.id,
        goal.version,
        {
            "action": "expand",
            "node_id": "coarse",
            "nodes": [
                {
                    "id": "implement",
                    "title": "Implement",
                    "outcome": "Feature exists",
                    "depends_on": [],
                },
                {
                    "id": "test",
                    "title": "Test",
                    "outcome": "Feature verified",
                    "depends_on": ["implement"],
                },
            ],
        },
    )
    nodes = goal.state["nodes"]
    assert nodes["coarse"]["status"] == "superseded"
    assert nodes["implement"]["depends_on"] == ["prep"]
    assert nodes["implement"]["status"] == "ready"
    assert nodes["test"]["status"] == "pending"
    assert nodes["release"]["depends_on"] == ["test"]
    assert goal.state["needs_replan"] is False
    assert store.events(goal.id)[0]["type"] == "plan_expanded"


def test_expansion_requires_satisfied_dependencies_and_never_uses_blockage(tmp_path) -> None:
    store = _store(tmp_path)
    goal = store.create("cli:test", "Plan progressively")
    goal = store.apply(
        goal.id,
        goal.version,
        {
            "action": "plan",
            "nodes": [
                {"id": "prep", "title": "Prepare", "outcome": "Ready", "depends_on": []},
                {
                    "id": "coarse",
                    "title": "Later work",
                    "outcome": "Done",
                    "kind": "coarse",
                    "depends_on": ["prep"],
                },
            ],
        },
    )
    command = {
        "action": "expand",
        "node_id": "coarse",
        "nodes": [{"id": "detail", "title": "Detail", "outcome": "Done", "depends_on": []}],
    }
    with pytest.raises(GoalError, match="dependencies succeed"):
        store.apply(goal.id, goal.version, command)
    with pytest.raises(GoalError, match="coarse node must be expanded"):
        store.apply(goal.id, goal.version, {"action": "begin", "node_id": "coarse"})
    assert store.get(goal.id) == goal
