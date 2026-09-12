"""Deterministic baseline-versus-candidate experiment evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    passed: bool
    improvements: dict[str, float]
    regressions: dict[str, float]
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "improvements": self.improvements,
            "regressions": self.regressions,
            "reason": self.reason,
        }


def evaluate_experiment(
    baseline: Mapping[str, float],
    candidate: Mapping[str, float],
    *,
    higher_is_better: set[str] | None = None,
    critical_metrics: set[str] | None = None,
    minimum_improvement: float = 0.0,
) -> EvaluationResult:
    """Compare common metrics; lower is better unless explicitly declared."""
    higher_is_better = higher_is_better or {"success_rate", "user_rating"}
    critical_metrics = critical_metrics or set()
    common = sorted(set(baseline) & set(candidate))
    if not common:
        return EvaluationResult(False, {}, {}, "baseline and candidate share no metrics")

    improvements: dict[str, float] = {}
    regressions: dict[str, float] = {}
    for metric in common:
        before = float(baseline[metric])
        after = float(candidate[metric])
        raw_delta = after - before if metric in higher_is_better else before - after
        # Normalize unlike units before computing a net result.
        delta = raw_delta / max(abs(before), 1e-12)
        if delta >= 0:
            improvements[metric] = delta
        else:
            regressions[metric] = -delta

    critical_regressions = sorted(critical_metrics & regressions.keys())
    if critical_regressions:
        return EvaluationResult(
            False,
            improvements,
            regressions,
            "critical regression: " + ", ".join(critical_regressions),
        )
    net = sum(improvements.values()) - sum(regressions.values())
    if net <= minimum_improvement:
        return EvaluationResult(
            False, improvements, regressions, "required net improvement not reached"
        )
    return EvaluationResult(
        True, improvements, regressions, "candidate improved without critical regressions"
    )
