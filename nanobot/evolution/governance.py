"""Non-negotiable safety policy for evolution candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nanobot.evolution.models import RiskLevel

# These lists are code-owned and cannot be changed through evolution artifacts.
AUTO_PROMOTABLE_CHANGE_TYPES = frozenset(
    {
        "benchmark_result",
        "procedure_checklist",
        "test_case",
    }
)

FORBIDDEN_CHANGE_TYPES = frozenset(
    {
        "disable_audit",
        "delete_source_of_truth",
        "modify_constitution",
        "remove_safety_constraint",
        "self_grant_permission",
        "secret_access_expansion",
        "unreviewed_production_deploy",
    }
)


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    auto_applicable: bool
    reason: str


class EvolutionPolicy:
    """Classify candidates without trusting candidate-provided prose."""

    def __init__(self, *, mode: str, auto_apply_max_risk: int = 0) -> None:
        self.mode = mode
        self.auto_apply_max_risk = RiskLevel(auto_apply_max_risk)

    def evaluate(self, candidate: dict[str, Any]) -> PolicyDecision:
        change_type = str(candidate.get("change_type", "")).strip()
        try:
            risk = RiskLevel(int(candidate.get("risk", RiskLevel.PROHIBITED)))
        except (TypeError, ValueError):
            return PolicyDecision(False, False, "invalid or absent risk classification")

        if change_type in FORBIDDEN_CHANGE_TYPES or risk is RiskLevel.PROHIBITED:
            return PolicyDecision(False, False, "candidate violates an immutable safety boundary")
        if risk is RiskLevel.APPROVAL_REQUIRED:
            return PolicyDecision(True, False, "explicit user approval is required")
        if self.mode == "observe":
            return PolicyDecision(True, False, "observe mode never applies changes")
        if self.mode == "propose":
            return PolicyDecision(True, False, "propose mode never applies changes")
        if risk > self.auto_apply_max_risk:
            return PolicyDecision(True, False, "risk exceeds the configured automatic limit")
        if change_type not in AUTO_PROMOTABLE_CHANGE_TYPES:
            return PolicyDecision(
                True, False, "change type is not eligible for automatic promotion"
            )
        # Promotion means accepting an evaluated artifact. It never edits source,
        # permissions, configuration, secrets, or the constitution.
        return PolicyDecision(
            True, True, "eligible for artifact promotion after passing evaluation"
        )
