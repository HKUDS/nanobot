"""Build GEPA evaluation datasets from turn traces (E4-D1)."""

from __future__ import annotations

from dataclasses import dataclass

from nanobot.agent.evolution.models import ToolCallRecord, TurnTrace, TurnTraceOutcome
from nanobot.agent.evolution.trace_store import TraceStore

DEFAULT_MIN_TRACES = 3
SKIP_INSUFFICIENT_TRACES = "insufficient traces for GEPA eval"


@dataclass(frozen=True, slots=True)
class GepaEvalExample:
    """One historical turn used to score a skill candidate during GEPA."""

    trace_id: str
    query: str
    tool_calls: tuple[ToolCallRecord, ...]
    outcome: TurnTraceOutcome
    stop_reason: str
    skills_injected: tuple[str, ...] = ()
    session_key: str = ""


@dataclass(frozen=True, slots=True)
class GepaDatasetResult:
    """Outcome of assembling eval examples for one target skill."""

    skill_name: str
    examples: tuple[GepaEvalExample, ...] = ()
    skipped: bool = False
    skip_reason: str = ""

    @property
    def trace_ids(self) -> tuple[str, ...]:
        return tuple(example.trace_id for example in self.examples)


def trace_relates_to_skill(trace: TurnTrace, skill_name: str) -> bool:
    """Return True when *trace* is relevant to optimizing *skill_name*."""
    if skill_name in trace.skills_injected:
        return True

    skill_path = f"skills/{skill_name}/"
    for call in trace.tool_calls:
        haystack = f"{call.name} {call.args_summary}".lower()
        if skill_path in haystack or skill_name.lower() in haystack:
            return True
    return False


def build_gepa_dataset(
    trace_store: TraceStore,
    skill_name: str,
    *,
    min_traces: int = DEFAULT_MIN_TRACES,
    min_tool_calls: int = 1,
    limit: int = 100,
    unused_only: bool = True,
) -> GepaDatasetResult:
    """Build eval examples for *skill_name* from ``TraceStore.list_for_gepa()``."""
    needle = skill_name.strip()
    if not needle:
        return GepaDatasetResult(
            skill_name=skill_name,
            skipped=True,
            skip_reason="skill_name is empty",
        )

    candidates = trace_store.list_for_gepa(
        min_tool_calls=min_tool_calls,
        outcome="success",
        limit=limit,
        unused_only=unused_only,
    )
    examples = tuple(
        _trace_to_example(trace)
        for trace in candidates
        if trace_relates_to_skill(trace, needle)
    )

    if len(examples) < min_traces:
        return GepaDatasetResult(
            skill_name=needle,
            examples=examples,
            skipped=True,
            skip_reason=SKIP_INSUFFICIENT_TRACES,
        )

    return GepaDatasetResult(skill_name=needle, examples=examples)


def _trace_to_example(trace: TurnTrace) -> GepaEvalExample:
    return GepaEvalExample(
        trace_id=trace.trace_id,
        query=trace.query,
        tool_calls=trace.tool_calls,
        outcome=trace.outcome,
        stop_reason=trace.stop_reason,
        skills_injected=trace.skills_injected,
        session_key=trace.session_key,
    )
