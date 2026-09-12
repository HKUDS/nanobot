"""Runtime facade for observation, reflection, reporting, and promotion."""

from __future__ import annotations

import hashlib
import os
import re
import secrets
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from nanobot.config.schema import EvolutionConfig
from nanobot.evolution.evaluator import evaluate_experiment
from nanobot.evolution.governance import EvolutionPolicy
from nanobot.evolution.models import Experience
from nanobot.evolution.optimizer import TokenWasteDetector
from nanobot.evolution.reflection import ReflectionEngine
from nanobot.evolution.store import EvolutionStore

_CORRECTION_RE = re.compile(
    r"(?:\b(?:źle|błędnie)\s+(?:to\s+)?(?:zrobiłeś|zrobiles)|"
    r"\b(?:pomyliłeś|pomyliles)\s+się|\bpopraw\s+(?:to|swój|swoj)|"
    r"\b(?:that(?:'s| is) wrong|you(?:'re| are) wrong|fix that)\b)",
    re.IGNORECASE,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tool_names(messages: list[dict[str, Any]]) -> tuple[str, ...]:
    names: list[str] = []
    for message in messages:
        calls_value = message.get("tool_calls")
        if not isinstance(calls_value, list):
            continue
        for call_value in cast(list[object], calls_value):
            if not isinstance(call_value, dict):
                continue
            call = cast(dict[str, object], call_value)
            function_value = call.get("function")
            function = (
                cast(dict[str, object], function_value)
                if isinstance(function_value, dict)
                else None
            )
            name = function.get("name") if function is not None else call.get("name")
            if isinstance(name, str) and name:
                names.append(name)
    return tuple(names)


class EvolutionService:
    """Fail-contained evolution engine; callers decide how to handle errors."""

    def __init__(self, config: EvolutionConfig, workspace: Path) -> None:
        self.config = config
        root = (workspace / config.storage_dir).resolve()
        workspace_root = workspace.resolve()
        if root != workspace_root and workspace_root not in root.parents:
            raise ValueError("evolution storage must stay inside the workspace")
        self.store = EvolutionStore(root)
        self.policy = EvolutionPolicy(
            mode=config.mode, auto_apply_max_risk=config.auto_apply_max_risk
        )
        self.reflection = ReflectionEngine(config, self.store)
        self.optimizer = TokenWasteDetector(config)
        self._salt = self._load_or_create_salt()
        self._observations_since_reflection = 0

    def _load_or_create_salt(self) -> bytes:
        path = self.store.root / ".identity_salt"
        if path.exists():
            return path.read_bytes()
        value = secrets.token_bytes(32)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.write(fd, value)
            os.fsync(fd)
        finally:
            os.close(fd)
        return value

    def _hash(self, value: str) -> str:
        return hashlib.sha256(self._salt + value.encode("utf-8", errors="replace")).hexdigest()

    def record_turn(
        self,
        *,
        turn_id: str,
        session_key: str,
        channel: str,
        kind: str,
        user_content: str,
        final_content: str,
        messages: list[dict[str, Any]],
        stop_reason: str,
        failure_error_kind: str | None,
        latency_ms: int | None,
        usage: dict[str, Any] | None,
        model: str,
        metadata: dict[str, Any] | None,
        tool_names: list[str] | tuple[str, ...] | None = None,
        runtime_context_chars: int = 0,
    ) -> Experience | None:
        if kind != "user" and not self.config.include_system_turns:
            return None
        created_at = _utc_now()
        record_id = "exp-" + hashlib.sha256(f"{turn_id}\0{created_at}".encode()).hexdigest()[:20]
        # AgentRunner already exposes turn-local tools. The transcript scan is
        # retained only for compatibility with direct callers and old plugins.
        tools = tuple(tool_names) if tool_names is not None else _tool_names(messages)
        feedback = str((metadata or {}).get("feedback", "")).lower()
        correction = feedback in {"negative", "down", "thumbs_down"} or bool(
            _CORRECTION_RE.search(user_content)
        )
        experience = Experience(
            id=record_id,
            created_at=created_at,
            turn_id=turn_id,
            session_hash=self._hash(session_key),
            channel=channel,
            kind=kind,
            model=model,
            outcome="completed" if stop_reason not in {"error", "tool_error"} else stop_reason,
            failure_error_kind=failure_error_kind,
            latency_ms=latency_ms,
            usage=usage,
            input_chars=len(user_content),
            input_hash=self._hash(user_content),
            output_chars=len(final_content),
            tool_calls=len(tools),
            tools=tools,
            correction_signal=correction,
            model_rounds=_usage_int(usage, "request_count"),
            runtime_context_chars=max(0, runtime_context_chars),
            input_excerpt=user_content[:500] if self.config.capture_content else None,
            output_excerpt=final_content[:500] if self.config.capture_content else None,
        )
        self.store.append_experience(experience.to_dict())
        self.store.append_audit(
            {"at": created_at, "action": "experience_recorded", "experience_id": record_id}
        )
        self._observations_since_reflection += 1
        if (
            self.config.mode != "observe"
            and self.config.auto_reflect_every > 0
            and self._observations_since_reflection >= self.config.auto_reflect_every
        ):
            self.reflection.reflect()
            self._observations_since_reflection = 0
        return experience

    def status(self) -> dict[str, Any]:
        experiences = self.store.experiences()
        proposals = list(self.store.records("proposals"))
        return {
            "enabled": self.config.enabled,
            "mode": self.config.mode,
            "capture_content": self.config.capture_content,
            "experiences": len(experiences),
            "open_proposals": sum(item.get("status") == "open" for item in proposals),
            "storage": str(self.store.root),
        }

    def evaluate_and_promote(self, experiment: dict[str, Any]) -> dict[str, Any]:
        result = evaluate_experiment(
            experiment.get("baseline", {}),
            experiment.get("candidate", {}),
            higher_is_better=set(experiment.get("higher_is_better", [])),
            critical_metrics=set(experiment.get("critical_metrics", [])),
            minimum_improvement=float(experiment.get("minimum_improvement", 0.0)),
        )
        experiment_id = str(experiment.get("id", "invalid-experiment"))
        evaluation = {
            "experiment_id": experiment_id,
            "evaluated_at": _utc_now(),
            **result.to_dict(),
        }
        self.store.write_record("evaluations", experiment_id, evaluation)
        decision = self.policy.evaluate(experiment)
        promoted = bool(result.passed and decision.allowed and decision.auto_applicable)
        area = "accepted" if promoted else "rejected"
        artifact = {
            **experiment,
            "evaluation": evaluation,
            "policy": asdict(decision),
            "promoted": promoted,
        }
        self.store.write_record(area, experiment_id, artifact)
        self.store.append_audit(
            {
                "at": _utc_now(),
                "action": "artifact_promoted" if promoted else "artifact_not_promoted",
                "experiment_id": experiment_id,
                "reason": decision.reason if result.passed else result.reason,
            }
        )
        return artifact

    def render_report(self) -> str:
        rows = self.store.experiences(limit=self.config.optimization_window)
        proposals = list(self.store.records("proposals"))
        failures = sum(str(row.get("outcome")) != "completed" for row in rows)
        tools = sum(int(row.get("tool_calls", 0)) for row in rows)
        latency = [int(row["latency_ms"]) for row in rows if isinstance(row.get("latency_ms"), int)]
        optimization = self.optimizer.summarize(rows)
        return (
            "\n".join(
                [
                    "# Evolution report",
                    "",
                    f"Generated: {_utc_now()}",
                    f"Mode: `{self.config.mode}`",
                    f"Observations in window: {len(rows)}",
                    f"Failures: {failures}",
                    f"Average tool calls: {(tools / len(rows)) if rows else 0:.2f}",
                    f"Average latency: {(sum(latency) / len(latency)) if latency else 0:.0f} ms",
                    f"Open proposals: {sum(item.get('status') == 'open' for item in proposals)}",
                    "",
                    "## Token optimization (observation only)",
                    f"Observed tokens: {optimization['observed_tokens']}",
                    f"Input tokens: {optimization['input_tokens']}",
                    f"Output tokens: {optimization['output_tokens']}",
                    f"Cache-read tokens: {optimization['cache_read_tokens']}",
                    f"Above-target token scenario: {optimization['estimated_avoidable_tokens']}",
                    f"Scenario share of observed tokens: {optimization['estimated_saving_pct']:.1f}%",
                    "Measured savings: not established; no quality-controlled before/after comparison.",
                    "Above-target rounds may be necessary. Cached input is not billed like uncached input.",
                    f"Turns above model-round target: {optimization['round_overage_turns']}",
                    f"Turns above output target: {optimization['output_overage_turns']}",
                    f"Runtime memory/context characters supplied: {optimization['runtime_context_chars']}",
                    "",
                    "Estimates do not modify prompts, memory, routing, or runtime behavior.",
                    "Raw prompt and response content is not stored."
                    if not self.config.capture_content
                    else "Content excerpts are enabled.",
                ]
            )
            + "\n"
        )


def _usage_int(usage: dict[str, Any] | None, key: str) -> int:
    if not usage:
        return 0
    value = usage.get(key, 0)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
