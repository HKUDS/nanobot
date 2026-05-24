"""Tests for evolution trace recorder."""

from __future__ import annotations

from nanobot.agent.evolution.models import TurnTrace
from nanobot.agent.evolution.trace_recorder import (
    TraceRecorder,
    build_turn_trace,
    infer_outcome,
    parse_tool_calls_from_messages,
    slice_turn_messages,
)
from nanobot.config.schema import EvolutionConfig


def _assistant_tool_call(
    *,
    call_id: str,
    name: str,
    arguments: dict[str, object] | str,
) -> dict:
    if isinstance(arguments, dict):
        args_value: str | dict[str, object] = arguments
    else:
        args_value = arguments
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": args_value},
            }
        ],
    }


def test_infer_outcome_maps_stop_reasons() -> None:
    assert infer_outcome("completed") == "success"
    assert infer_outcome("error") == "fail"
    assert infer_outcome("tool_error") == "fail"
    assert infer_outcome("max_iterations") == "fail"
    assert infer_outcome("empty_final_response") == "partial"


def test_parse_tool_calls_from_messages_extracts_args_and_errors() -> None:
    messages = [
        _assistant_tool_call(call_id="c1", name="exec", arguments={"command": "pytest -q"}),
        {"role": "tool", "tool_call_id": "c1", "name": "exec", "content": "all passed"},
        _assistant_tool_call(call_id="c2", name="read_file", arguments='{"path":"README.md"}'),
        {"role": "tool", "tool_call_id": "c2", "name": "read_file", "content": "Error: not found"},
    ]

    records = parse_tool_calls_from_messages(messages)

    assert len(records) == 2
    assert records[0].name == "exec"
    assert records[0].ok is True
    assert "pytest" in records[0].args_summary
    assert records[1].name == "read_file"
    assert records[1].ok is False


def test_slice_turn_messages_returns_delta_only() -> None:
    all_messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "old"},
        {"role": "assistant", "content": "new"},
    ]

    delta = slice_turn_messages(all_messages, baseline_len=2)

    assert delta == [{"role": "assistant", "content": "new"}]


def test_build_turn_trace_uses_baseline_and_tools_used() -> None:
    all_messages = [
        {"role": "user", "content": "history"},
        _assistant_tool_call(call_id="c1", name="exec", arguments={"command": "ls"}),
        {"role": "tool", "tool_call_id": "c1", "name": "exec", "content": "ok"},
        {"role": "assistant", "content": "done"},
    ]

    trace = build_turn_trace(
        session_key="cli:direct",
        query="list files",
        messages=all_messages,
        stop_reason="completed",
        skills_injected=["cron"],
        tools_used=["exec"],
        turn_id="turn-9",
        token_usage={"prompt": 100, "completion": 20},
        baseline_len=1,
    )

    assert trace.session_key == "cli:direct"
    assert trace.query == "list files"
    assert trace.skills_injected == ("cron",)
    assert trace.tool_call_count == 1
    assert trace.tool_calls[0].name == "exec"
    assert trace.iterations == 2
    assert trace.outcome == "success"
    assert trace.token_usage_dict == {"prompt": 100, "completion": 20}


def test_trace_recorder_skips_when_disabled(tmp_path) -> None:
    recorder = TraceRecorder(tmp_path, EvolutionConfig(enable=False))
    trace = TurnTrace(session_key="cli:x", query="hello")

    stored = recorder.record(trace)

    assert stored is False
    assert recorder.store.count() == 0


def test_trace_recorder_persists_and_prunes_when_enabled(tmp_path) -> None:
    config = EvolutionConfig(enable=True, trace={"retention_days": 30})
    recorder = TraceRecorder(tmp_path, config)

    stored_trace = recorder.record_turn(
        session_key="cli:direct",
        query="deploy cron",
        messages=[
            _assistant_tool_call(call_id="c1", name="exec", arguments={"command": "crontab -l"}),
            {"role": "tool", "tool_call_id": "c1", "name": "exec", "content": "ok"},
            {"role": "assistant", "content": "done"},
        ],
        stop_reason="completed",
        skills_injected=["cron"],
        tools_used=["exec"],
    )

    assert stored_trace is not None
    loaded = recorder.store.get(stored_trace.trace_id)
    assert loaded is not None
    assert loaded.query == "deploy cron"
    assert loaded.tool_call_count == 1
    assert recorder.store.count() == 1
