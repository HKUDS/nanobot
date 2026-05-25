"""Tests for GEPA eval dataset construction (E4-D1)."""

from __future__ import annotations

from nanobot.agent.evolution.gepa_dataset import (
    DEFAULT_MIN_TRACES,
    SKIP_INSUFFICIENT_TRACES,
    GepaEvalExample,
    build_gepa_dataset,
    trace_relates_to_skill,
)
from nanobot.agent.evolution.models import ToolCallRecord, TurnTrace
from nanobot.agent.evolution.trace_store import TraceStore


def _trace(
    *,
    trace_id: str = "trace-1",
    skills_injected: tuple[str, ...] = (),
    tool_calls: tuple[ToolCallRecord, ...] = (),
    query: str = "run task",
    used_for_evolution: bool = False,
    tool_call_count: int = 5,
    outcome: str = "success",
) -> TurnTrace:
    return TurnTrace(
        trace_id=trace_id,
        session_key="cli:direct",
        query=query,
        skills_injected=skills_injected,
        tool_calls=tool_calls,
        tool_call_count=tool_call_count,
        stop_reason="completed",
        outcome=outcome,  # type: ignore[arg-type]
        used_for_evolution=used_for_evolution,
    )


def test_trace_relates_to_skill_by_skills_injected() -> None:
    trace = _trace(skills_injected=("deploy-k8s", "cron"))

    assert trace_relates_to_skill(trace, "deploy-k8s") is True
    assert trace_relates_to_skill(trace, "cron") is True
    assert trace_relates_to_skill(trace, "other-skill") is False


def test_trace_relates_to_skill_by_tool_call_pattern() -> None:
    trace = _trace(
        tool_calls=(
            ToolCallRecord(name="read_file", args_summary="skills/deploy-k8s/SKILL.md"),
        )
    )

    assert trace_relates_to_skill(trace, "deploy-k8s") is True
    assert trace_relates_to_skill(trace, "deploy-gcp") is False


def test_build_gepa_dataset_filters_and_maps_examples(tmp_path) -> None:
    store = TraceStore(tmp_path)
    store.insert(
        _trace(
            trace_id="t1",
            skills_injected=("deploy-k8s",),
            query="deploy nginx",
            tool_calls=(ToolCallRecord(name="exec", args_summary="kubectl apply"),),
        )
    )
    store.insert(
        _trace(
            trace_id="t2",
            tool_calls=(ToolCallRecord(name="read_file", args_summary="skills/deploy-k8s/SKILL.md"),),
            query="review deploy skill",
        )
    )
    store.insert(
        _trace(
            trace_id="t3",
            skills_injected=("lint-python",),
            query="lint code",
        )
    )
    store.insert(
        _trace(
            trace_id="t4",
            skills_injected=("deploy-k8s",),
            query="rollout status",
            used_for_evolution=True,
        )
    )

    result = build_gepa_dataset(store, "deploy-k8s", min_traces=2)

    assert result.skipped is False
    assert result.skip_reason == ""
    assert [example.trace_id for example in result.examples] == ["t2", "t1"]
    assert all(isinstance(example, GepaEvalExample) for example in result.examples)
    assert result.examples[0].query == "review deploy skill"
    assert result.examples[0].tool_calls[0].name == "read_file"
    assert result.examples[1].outcome == "success"
    assert result.trace_ids == ("t2", "t1")


def test_build_gepa_dataset_skips_when_insufficient_traces(tmp_path) -> None:
    store = TraceStore(tmp_path)
    store.insert(_trace(trace_id="only-one", skills_injected=("deploy-k8s",)))

    result = build_gepa_dataset(store, "deploy-k8s", min_traces=DEFAULT_MIN_TRACES)

    assert result.skipped is True
    assert result.skip_reason == SKIP_INSUFFICIENT_TRACES
    assert len(result.examples) == 1


def test_build_gepa_dataset_respects_list_for_gepa_filters(tmp_path) -> None:
    store = TraceStore(tmp_path)
    store.insert(
        _trace(
            trace_id="low-tools",
            skills_injected=("deploy-k8s",),
            tool_call_count=1,
        )
    )
    store.insert(
        _trace(
            trace_id="failed",
            skills_injected=("deploy-k8s",),
            outcome="fail",
        )
    )

    result = build_gepa_dataset(store, "deploy-k8s", min_traces=1, min_tool_calls=3)

    assert result.skipped is True
    assert result.examples == ()
