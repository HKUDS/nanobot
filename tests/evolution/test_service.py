from __future__ import annotations

import json
import stat
from pathlib import Path

from nanobot.config.schema import EvolutionConfig
from nanobot.evolution.service import EvolutionService


def _record(
    service: EvolutionService, *, turn_id: str = "turn-1", stop_reason: str = "stop"
) -> None:
    service.record_turn(
        turn_id=turn_id,
        session_key="websocket:user:secret-chat",
        channel="websocket",
        kind="user",
        user_content="private user request",
        final_content="private assistant response",
        messages=[{"role": "assistant", "tool_calls": [{"function": {"name": "read_file"}}]}],
        stop_reason=stop_reason,
        failure_error_kind=None,
        latency_ms=123,
        usage={"total_tokens": 42},
        model="test-model",
        metadata={},
    )


def test_record_turn_is_private_and_does_not_store_content(tmp_path: Path) -> None:
    service = EvolutionService(EvolutionConfig(enabled=True), tmp_path)
    _record(service)

    rows = service.store.experiences()
    assert len(rows) == 1
    assert rows[0]["input_excerpt"] is None
    assert rows[0]["output_excerpt"] is None
    assert "private user request" not in service.store.experiences_path.read_text(encoding="utf-8")
    assert rows[0]["session_hash"] != "websocket:user:secret-chat"
    assert rows[0]["tools"] == ["read_file"]
    assert stat.S_IMODE(service.store.experiences_path.stat().st_mode) == 0o600


def test_explicit_turn_local_tools_override_historical_transcript(tmp_path: Path) -> None:
    service = EvolutionService(EvolutionConfig(enabled=True), tmp_path)
    service.record_turn(
        turn_id="turn-local",
        session_key="websocket:one",
        channel="websocket",
        kind="user",
        user_content="status",
        final_content="done",
        messages=[
            {"role": "assistant", "tool_calls": [{"function": {"name": "old_tool"}}]},
        ],
        tool_names=["current_tool"],
        runtime_context_chars=321,
        stop_reason="stop",
        failure_error_kind=None,
        latency_ms=12,
        usage={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12, "request_count": 1},
        model="test-model",
        metadata={},
    )
    row = service.store.experiences()[0]
    assert row["tools"] == ["current_tool"]
    assert row["tool_calls"] == 1
    assert row["model_rounds"] == 1
    assert row["runtime_context_chars"] == 321


def test_report_includes_zero_llm_optimization_metrics(tmp_path: Path) -> None:
    service = EvolutionService(
        EvolutionConfig(enabled=True, target_model_rounds=1, target_output_tokens=64),
        tmp_path,
    )
    service.record_turn(
        turn_id="turn-report",
        session_key="websocket:one",
        channel="websocket",
        kind="user",
        user_content="status",
        final_content="done",
        messages=[],
        stop_reason="stop",
        failure_error_kind=None,
        latency_ms=12,
        usage={"input_tokens": 200, "output_tokens": 100, "total_tokens": 300, "request_count": 2},
        model="test-model",
        metadata={},
    )
    report = service.render_report()
    assert "Token optimization (observation only)" in report
    assert "Observed tokens: 300" in report
    assert "Above-target token scenario: 136" in report
    assert "Measured savings: not established" in report
    assert "do not modify prompts, memory, routing" in report


def test_reflection_creates_deduplicated_evidence_backed_proposal(tmp_path: Path) -> None:
    config = EvolutionConfig(
        enabled=True,
        mode="propose",
        reflection_min_samples=3,
        reflection_window=10,
        failure_rate_threshold=0.5,
        correction_rate_threshold=1.0,
        latency_p95_threshold_ms=999_999,
        average_tool_calls_threshold=99,
        auto_reflect_every=0,
    )
    service = EvolutionService(config, tmp_path)
    for index in range(3):
        _record(service, turn_id=f"turn-{index}", stop_reason="error" if index < 2 else "stop")

    first = service.reflection.reflect()
    second = service.reflection.reflect()

    assert len(first) == 1
    assert first[0].issue == "elevated_failure_rate"
    assert len(first[0].evidence_ids) == 3
    assert second == []


def test_evaluate_never_promotes_in_observe_mode(tmp_path: Path) -> None:
    service = EvolutionService(EvolutionConfig(enabled=True), tmp_path)
    artifact = service.evaluate_and_promote(
        {
            "id": "experiment-1",
            "change_type": "procedure_checklist",
            "risk": 0,
            "baseline": {"latency_ms": 100.0},
            "candidate": {"latency_ms": 50.0},
        }
    )

    assert artifact["evaluation"]["passed"] is True
    assert artifact["promoted"] is False
    rejected = json.loads((tmp_path / "evolution" / "rejected" / "experiment-1.json").read_text())
    assert rejected["policy"]["auto_applicable"] is False


def test_experiment_id_cannot_escape_storage_root(tmp_path: Path) -> None:
    service = EvolutionService(EvolutionConfig(enabled=True), tmp_path)

    try:
        service.evaluate_and_promote(
            {
                "id": "../../outside",
                "change_type": "procedure_checklist",
                "risk": 0,
                "baseline": {"latency_ms": 100.0},
                "candidate": {"latency_ms": 50.0},
            }
        )
    except ValueError as exc:
        assert "unsafe characters" in str(exc)
    else:
        raise AssertionError("unsafe experiment ID was accepted")

    assert not (tmp_path / "outside.json").exists()
