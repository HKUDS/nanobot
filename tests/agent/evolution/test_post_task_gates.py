"""Tests for PostTask trigger gates (E1 Step 1)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from nanobot.agent.evolution.models import ToolCallRecord, TurnTrace
from nanobot.agent.evolution.post_task import (
    SKIP_COOLDOWN,
    SKIP_EVOLUTION_DISABLED,
    SKIP_NO_TOOL_CALLS,
    SKIP_OUTCOME,
    SKIP_STOP_REASON,
    SKIP_SUBAGENT,
    SKIP_TOOL_CALLS_LOW,
    PostTaskCooldownStore,
    PostTaskEvolver,
)
from nanobot.config.schema import EvolutionConfig, EvolutionPostTaskConfig


def _trace(
    *,
    tool_call_count: int = 5,
    outcome: str = "success",
    stop_reason: str = "completed",
    session_key: str = "cli:direct",
    with_tool_calls: bool = True,
) -> TurnTrace:
    tool_calls = ()
    if with_tool_calls and tool_call_count > 0:
        tool_calls = tuple(
            ToolCallRecord(name=f"tool_{index}", args_summary=f"arg{index}", ok=True)
            for index in range(tool_call_count)
        )
    return TurnTrace(
        session_key=session_key,
        query="deploy to k8s",
        tool_calls=tool_calls,
        tool_call_count=tool_call_count,
        stop_reason=stop_reason,
        outcome=outcome,  # type: ignore[arg-type]
    )


def test_should_trigger_passes_when_all_gates_met(tmp_path: Path) -> None:
    evolver = PostTaskEvolver(tmp_path, EvolutionConfig(enable=True))
    assert evolver.should_trigger(_trace(), is_subagent=False) is None
    assert evolver.evaluate_gate(_trace(), is_subagent=False).should_run is True


def test_should_trigger_skips_when_evolution_disabled(tmp_path: Path) -> None:
    evolver = PostTaskEvolver(tmp_path, EvolutionConfig(enable=False))
    assert evolver.should_trigger(_trace(), is_subagent=False) == SKIP_EVOLUTION_DISABLED


def test_should_trigger_skips_subagent(tmp_path: Path) -> None:
    evolver = PostTaskEvolver(tmp_path, EvolutionConfig(enable=True))
    assert evolver.should_trigger(_trace(), is_subagent=True) == SKIP_SUBAGENT


def test_should_trigger_skips_low_tool_call_count(tmp_path: Path) -> None:
    evolver = PostTaskEvolver(tmp_path, EvolutionConfig(enable=True))
    assert evolver.should_trigger(_trace(tool_call_count=2), is_subagent=False) == SKIP_TOOL_CALLS_LOW


def test_should_trigger_respects_custom_min_tool_calls(tmp_path: Path) -> None:
    cfg = EvolutionConfig(
        enable=True,
        post_task=EvolutionPostTaskConfig(min_tool_calls=3),
    )
    evolver = PostTaskEvolver(tmp_path, cfg)
    assert evolver.should_trigger(_trace(tool_call_count=3), is_subagent=False) is None
    assert evolver.should_trigger(_trace(tool_call_count=2), is_subagent=False) == SKIP_TOOL_CALLS_LOW


def test_should_trigger_skips_empty_tool_calls(tmp_path: Path) -> None:
    evolver = PostTaskEvolver(tmp_path, EvolutionConfig(enable=True))
    trace = TurnTrace(
        session_key="cli:direct",
        query="hello",
        tool_call_count=5,
        tool_calls=(),
        stop_reason="completed",
        outcome="success",
    )
    assert evolver.should_trigger(trace, is_subagent=False) == SKIP_NO_TOOL_CALLS


def test_should_trigger_skips_non_success_outcome(tmp_path: Path) -> None:
    evolver = PostTaskEvolver(tmp_path, EvolutionConfig(enable=True))
    assert evolver.should_trigger(_trace(outcome="fail"), is_subagent=False) == SKIP_OUTCOME
    assert evolver.should_trigger(_trace(outcome="partial"), is_subagent=False) == SKIP_OUTCOME


def test_should_trigger_skips_non_completed_stop_reason(tmp_path: Path) -> None:
    evolver = PostTaskEvolver(tmp_path, EvolutionConfig(enable=True))
    assert evolver.should_trigger(_trace(stop_reason="error"), is_subagent=False) == SKIP_STOP_REASON


def test_cooldown_store_blocks_repeat_within_window(tmp_path: Path) -> None:
    store = PostTaskCooldownStore(tmp_path)
    store.mark("cli:direct")
    assert store.is_active("cli:direct", cooldown_minutes=5) is True
    assert store.is_active("cli:other", cooldown_minutes=5) is False


def test_should_trigger_skips_session_cooldown(tmp_path: Path) -> None:
    cfg = EvolutionConfig(
        enable=True,
        post_task=EvolutionPostTaskConfig(cooldown_minutes=5),
    )
    evolver = PostTaskEvolver(tmp_path, cfg)
    evolver.cooldown_store.mark("cli:direct")
    assert evolver.should_trigger(_trace(session_key="cli:direct"), is_subagent=False) == SKIP_COOLDOWN


def test_cooldown_zero_disables_rate_limit(tmp_path: Path) -> None:
    cfg = EvolutionConfig(
        enable=True,
        post_task=EvolutionPostTaskConfig(cooldown_minutes=0),
    )
    evolver = PostTaskEvolver(tmp_path, cfg)
    evolver.cooldown_store.mark("cli:direct")
    assert evolver.should_trigger(_trace(session_key="cli:direct"), is_subagent=False) is None


def test_cooldown_store_persists_to_disk(tmp_path: Path) -> None:
    store = PostTaskCooldownStore(tmp_path)
    store.mark("ws:1")
    path = tmp_path / ".nanobot" / "post_task_cooldown.json"
    assert path.exists()

    reloaded = PostTaskCooldownStore(tmp_path)
    assert reloaded.is_active("ws:1", cooldown_minutes=5) is True


def test_cooldown_store_expires_after_window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = PostTaskCooldownStore(tmp_path)
    base = 1_700_000_000.0
    monkeypatch.setattr(time, "time", lambda: base)
    store.mark("cli:direct")

    monkeypatch.setattr(time, "time", lambda: base + 5 * 60 + 1)
    reloaded = PostTaskCooldownStore(tmp_path)
    assert reloaded.is_active("cli:direct", cooldown_minutes=5) is False
