"""Tests for evolution TraceStore."""

from __future__ import annotations

import sqlite3
import time

from nanobot.agent.evolution.models import ToolCallRecord, TurnTrace
from nanobot.agent.evolution.trace_store import TraceStore


def _sample_trace(
    *,
    trace_id: str = "trace-1",
    session_key: str = "cli:direct",
    tool_call_count: int = 6,
    outcome: str = "success",
    used_for_evolution: bool = False,
    timestamp: str = "2026-05-24T12:00:00+00:00",
) -> TurnTrace:
    return TurnTrace(
        trace_id=trace_id,
        session_key=session_key,
        turn_id="turn-1",
        timestamp=timestamp,
        query="deploy cron reminder",
        skills_injected=("cron",),
        tool_calls=(
            ToolCallRecord(name="exec", args_summary="crontab -l", ok=True, duration_ms=50),
            ToolCallRecord(name="write_file", args_summary="skills/cron/SKILL.md", ok=True),
        ),
        tool_call_count=tool_call_count,
        iterations=3,
        stop_reason="completed",
        outcome=outcome,  # type: ignore[arg-type]
        token_usage=(("prompt", 1200), ("completion", 300)),
        used_for_evolution=used_for_evolution,
    )


def test_trace_store_insert_and_get(tmp_path) -> None:
    store = TraceStore(tmp_path)
    trace = _sample_trace()

    store.insert(trace)
    loaded = store.get(trace.trace_id)

    assert loaded is not None
    assert loaded.trace_id == trace.trace_id
    assert loaded.query == "deploy cron reminder"
    assert loaded.skills_injected == ("cron",)
    assert loaded.tool_call_count == 6
    assert loaded.tool_calls[0].name == "exec"
    assert loaded.token_usage_dict == {"prompt": 1200, "completion": 300}
    assert store.count() == 1


def test_trace_store_list_by_session(tmp_path) -> None:
    store = TraceStore(tmp_path)
    store.insert(_sample_trace(trace_id="a", session_key="cli:a"))
    store.insert(_sample_trace(trace_id="b", session_key="cli:b"))
    store.insert(_sample_trace(trace_id="c", session_key="cli:a"))

    rows = store.list_by_session("cli:a")

    assert [row.trace_id for row in rows] == ["c", "a"]


def test_trace_store_list_for_gepa_filters_unused_success(tmp_path) -> None:
    store = TraceStore(tmp_path)
    store.insert(_sample_trace(trace_id="ok", tool_call_count=8, outcome="success"))
    store.insert(_sample_trace(trace_id="low", tool_call_count=2, outcome="success"))
    store.insert(_sample_trace(trace_id="fail", tool_call_count=8, outcome="fail"))
    store.insert(
        _sample_trace(
            trace_id="used",
            tool_call_count=8,
            outcome="success",
            used_for_evolution=True,
        )
    )

    rows = store.list_for_gepa(min_tool_calls=5, unused_only=True)

    assert [row.trace_id for row in rows] == ["ok"]


def test_trace_store_mark_used_for_evolution(tmp_path) -> None:
    store = TraceStore(tmp_path)
    store.insert(_sample_trace(trace_id="t1"))
    store.insert(_sample_trace(trace_id="t2"))

    updated = store.mark_used_for_evolution(["t1"])

    assert updated == 1
    assert store.get("t1").used_for_evolution is True
    assert store.get("t2").used_for_evolution is False


def test_trace_store_prune_old_rows(tmp_path) -> None:
    store = TraceStore(tmp_path)
    store.insert(_sample_trace(trace_id="old"))
    store.insert(_sample_trace(trace_id="new"))

    conn = sqlite3.connect(store.db_path)
    old_cutoff = time.time() - 10 * 86_400
    conn.execute(
        "UPDATE turn_traces SET created_at = ? WHERE trace_id = ?",
        (old_cutoff, "old"),
    )
    conn.commit()
    conn.close()

    deleted = store.prune(retention_days=7)

    assert deleted == 1
    assert store.get("old") is None
    assert store.get("new") is not None


def test_turn_trace_derives_tool_call_count_from_calls() -> None:
    trace = TurnTrace(
        session_key="cli:x",
        query="q",
        tool_calls=(ToolCallRecord(name="read_file"), ToolCallRecord(name="exec")),
    )
    assert trace.tool_call_count == 2


def test_trace_store_creates_db_under_nanobot_dir(tmp_path) -> None:
    store = TraceStore(tmp_path)
    store.insert(_sample_trace())

    assert store.db_path == tmp_path / ".nanobot" / "traces.sqlite"
    assert store.db_path.is_file()
