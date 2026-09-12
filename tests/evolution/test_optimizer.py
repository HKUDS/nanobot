from __future__ import annotations

from nanobot.config.schema import EvolutionConfig
from nanobot.evolution.optimizer import TokenWasteDetector


def test_optimizer_reports_unverified_round_and_output_scenario() -> None:
    detector = TokenWasteDetector(EvolutionConfig(target_model_rounds=2, target_output_tokens=100))
    result = detector.summarize(
        [
            {
                "usage": {
                    "input_tokens": 900,
                    "output_tokens": 250,
                    "total_tokens": 1150,
                    "cache_read_tokens": 300,
                    "request_count": 3,
                },
                "model_rounds": 3,
                "runtime_context_chars": 400,
            },
            {
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "total_tokens": 150,
                    "request_count": 1,
                },
                "model_rounds": 1,
                "runtime_context_chars": 100,
            },
        ]
    )

    assert result["savings_verified"] is False
    assert result["estimate_basis"] == "threshold_scenario_not_measured_savings"
    assert result["observed_tokens"] == 1300
    assert result["input_tokens"] == 1000
    assert result["output_tokens"] == 300
    assert result["cache_read_tokens"] == 300
    assert result["runtime_context_chars"] == 500
    assert result["round_overage_turns"] == 1
    assert result["output_overage_turns"] == 1
    assert result["estimated_avoidable_tokens"] == 450
    assert result["estimated_saving_pct"] == 450 / 1300 * 100


def test_optimizer_handles_missing_or_malformed_usage_without_claiming_savings() -> None:
    detector = TokenWasteDetector(EvolutionConfig())
    result = detector.summarize(
        [
            {"usage": None},
            {"usage": {"total_tokens": "unknown", "request_count": True}},
        ]
    )
    assert result["observed_tokens"] == 0
    assert result["estimated_avoidable_tokens"] == 0
    assert result["estimated_saving_pct"] == 0.0


def test_optimizer_falls_back_to_request_count_when_model_rounds_is_missing() -> None:
    result = TokenWasteDetector(EvolutionConfig(target_model_rounds=2)).summarize([
        {"usage": {"input_tokens": 900, "total_tokens": 900, "request_count": 3}},
    ])
    assert result["round_overage_turns"] == 1
    assert result["estimated_avoidable_tokens"] == 300
    assert result["savings_verified"] is False
