from __future__ import annotations

from nanobot.evolution.evaluator import evaluate_experiment


def test_evaluator_accepts_net_improvement_without_critical_regression() -> None:
    result = evaluate_experiment(
        {"success_rate": 0.8, "latency_ms": 100.0},
        {"success_rate": 0.9, "latency_ms": 90.0},
        critical_metrics={"success_rate"},
    )

    assert result.passed is True
    assert result.regressions == {}


def test_evaluator_rejects_critical_regression_even_with_other_gain() -> None:
    result = evaluate_experiment(
        {"success_rate": 0.9, "latency_ms": 1000.0},
        {"success_rate": 0.8, "latency_ms": 10.0},
        critical_metrics={"success_rate"},
    )

    assert result.passed is False
    assert result.reason == "critical regression: success_rate"
