"""Evidence-bound reflection that produces reviewable proposals."""

from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone

from nanobot.config.schema import EvolutionConfig
from nanobot.evolution.models import Proposal, RiskLevel
from nanobot.evolution.store import EvolutionStore


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


class ReflectionEngine:
    def __init__(self, config: EvolutionConfig, store: EvolutionStore) -> None:
        self.config = config
        self.store = store

    def reflect(self) -> list[Proposal]:
        rows = self.store.experiences(limit=self.config.reflection_window)
        if len(rows) < self.config.reflection_min_samples:
            return []

        ids = tuple(str(row.get("id", "")) for row in rows if row.get("id"))
        latencies = [
            int(row["latency_ms"]) for row in rows if isinstance(row.get("latency_ms"), int)
        ]
        failure_count = sum(str(row.get("outcome")) != "completed" for row in rows)
        correction_count = sum(bool(row.get("correction_signal")) for row in rows)
        average_tools = sum(int(row.get("tool_calls", 0)) for row in rows) / len(rows)
        metrics = {
            "sample_size": len(rows),
            "failure_rate": failure_count / len(rows),
            "correction_rate": correction_count / len(rows),
            "latency_p95_ms": _percentile(latencies, 0.95),
            "average_tool_calls": average_tools,
        }

        candidates: list[tuple[str, str, str, RiskLevel]] = []
        if metrics["failure_rate"] >= self.config.failure_rate_threshold:
            candidates.append(
                (
                    "elevated_failure_rate",
                    "Create a regression checklist for the dominant failure paths and validate it in sandbox.",
                    "procedure_checklist",
                    RiskLevel.OBSERVATION,
                )
            )
        if metrics["correction_rate"] >= self.config.correction_rate_threshold:
            candidates.append(
                (
                    "frequent_user_corrections",
                    "Review correction-marked turns and propose a preference or clarification rule without storing raw content.",
                    "preference_review",
                    RiskLevel.APPROVAL_REQUIRED,
                )
            )
        if metrics["latency_p95_ms"] >= self.config.latency_p95_threshold_ms:
            candidates.append(
                (
                    "high_turn_latency",
                    "Benchmark tool ordering and model routing against the current baseline.",
                    "sandbox_benchmark",
                    RiskLevel.REVERSIBLE,
                )
            )
        if metrics["average_tool_calls"] >= self.config.average_tool_calls_threshold:
            candidates.append(
                (
                    "excessive_tool_calls",
                    "Build a sandboxed workflow candidate that reduces redundant tool calls.",
                    "sandbox_workflow",
                    RiskLevel.REVERSIBLE,
                )
            )

        existing = {
            str(value.get("issue"))
            for value in self.store.records("proposals")
            if value.get("status") == "open"
        }
        proposals: list[Proposal] = []
        for issue, change, change_type, risk in candidates:
            if issue in existing:
                continue
            digest = hashlib.sha256((issue + "\0" + "\0".join(ids)).encode()).hexdigest()[:16]
            proposal = Proposal(
                id=f"proposal-{digest}",
                created_at=_utc_now(),
                issue=issue,
                evidence_ids=ids[-20:],
                evidence_summary=metrics,
                proposed_change=change,
                change_type=change_type,
                risk=risk,
            )
            self.store.write_record("proposals", proposal.id, proposal.to_dict())
            self.store.append_audit(
                {
                    "at": proposal.created_at,
                    "action": "proposal_created",
                    "proposal_id": proposal.id,
                    "risk": int(proposal.risk),
                }
            )
            proposals.append(proposal)
        return proposals
