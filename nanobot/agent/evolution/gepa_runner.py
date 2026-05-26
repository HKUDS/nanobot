"""GEPA offline orchestration: dataset → optimize → proposal (E4-D6/D7)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from loguru import logger

from nanobot.agent.evolution.deps import require_evolution_extra
from nanobot.agent.evolution.gepa_dataset import (
    DEFAULT_MIN_TRACES,
    SKIP_INSUFFICIENT_TRACES,
    build_gepa_dataset,
)
from nanobot.agent.evolution.gepa_evaluator import GepaEvaluator, GepaEvaluatorConfig
from nanobot.agent.evolution.gepa_optimizer import (
    GepaOptimizeResult,
    GepaOptimizer,
    GepaOptimizerConfig,
    resolve_gepa_optimizer_model,
)
from nanobot.agent.evolution.gepa_skill_module import GepaSkillModule
from nanobot.agent.evolution.gepa_status import (
    GEPA_SKIP_ALREADY_RUNNING,
    GepaRunLock,
    GepaRunPhase,
    GepaRunStatus,
    GepaRunStore,
    GepaRunTrigger,
)
from nanobot.agent.evolution.git_store import EvolutionGitStore
from nanobot.agent.evolution.proposals import (
    SKIP_PENDING_GEPA_UPDATE,
    ProposalStore,
    validate_gepa_update,
)
from nanobot.agent.evolution.trace_store import TraceStore
from nanobot.config.schema import EvolutionConfig
from nanobot.providers.base import LLMProvider

_SKIP_DIRS = frozenset({".proposals", ".archive", ".rejected"})
DEFAULT_MAX_SKILLS_PER_RUN = 1
SKIP_EVOLUTION_DISABLED = "evolution GEPA disabled"
SKIP_SKILL_NOT_FOUND = "active skill not found"
SKIP_NO_ACTIVE_SKILLS = "no active skills to optimize"


@dataclass(frozen=True, slots=True)
class GepaRunResult:
    """Outcome of a full ``GepaRunner.run`` invocation."""

    run_id: str = ""
    trigger: GepaRunTrigger | None = None
    phase: GepaRunPhase = "idle"
    proposals_created: tuple[str, ...] = ()
    traces_consumed: tuple[str, ...] = ()
    skills_processed: int = 0
    budget_usd_spent: float = 0.0
    message: str = ""
    error: str = ""

    @property
    def skipped(self) -> bool:
        return self.phase == "skipped"


@dataclass(frozen=True, slots=True)
class _SkillProcessOutcome:
    proposal_id: str = ""
    trace_ids: tuple[str, ...] = ()
    budget_usd: float = 0.0
    skip_reason: str = ""


def list_active_skill_names(workspace: Path) -> list[str]:
    """Return kebab-case skill names with ``skills/<name>/SKILL.md``."""
    skills_root = workspace.expanduser().resolve() / "skills"
    if not skills_root.is_dir():
        return []
    names: list[str] = []
    for skill_dir in sorted(skills_root.iterdir()):
        if not skill_dir.is_dir():
            continue
        if skill_dir.name.startswith(".") or skill_dir.name in _SKIP_DIRS:
            continue
        if (skill_dir / "SKILL.md").is_file():
            names.append(skill_dir.name)
    return names


def resolve_gepa_provider(
    config: Any,
    evolution: EvolutionConfig,
    fallback_provider: LLMProvider,
) -> LLMProvider:
    """Return the LLM provider used for GEPA evaluation / reflection routing."""
    model = evolution.gepa.model
    if model:
        from nanobot.providers.factory import make_provider

        try:
            return make_provider(config, model=model)
        except Exception as exc:
            logger.warning(
                "Failed to create GEPA model {!r}: {}; using fallback provider",
                model,
                exc,
            )
    return fallback_provider


class GepaRunner:
    """Orchestrate GEPA skill updates with locking, status, and proposals."""

    def __init__(
        self,
        workspace: Path,
        evolution: EvolutionConfig,
        provider: LLMProvider,
        *,
        provider_config: Any = None,
        fallback_model: str = "",
        optimizer: GepaOptimizer | None = None,
        evaluator: GepaEvaluator | None = None,
        min_traces: int = DEFAULT_MIN_TRACES,
        max_skills_per_run: int = DEFAULT_MAX_SKILLS_PER_RUN,
    ) -> None:
        self._workspace = workspace.expanduser().resolve()
        self._evolution = evolution
        self._provider = provider
        self._provider_config = provider_config
        self._fallback_model = fallback_model
        self._optimizer = optimizer
        self._evaluator = evaluator
        self._min_traces = min_traces
        self._max_skills_per_run = max(1, max_skills_per_run)
        self._store = GepaRunStore(self._workspace)
        self._trace_store = TraceStore(self._workspace)
        self._proposals = ProposalStore(self._workspace)
        self._git = EvolutionGitStore(self._workspace)

    @property
    def status_store(self) -> GepaRunStore:
        return self._store

    async def run(
        self,
        *,
        skill_name: str | None = None,
        trigger: GepaRunTrigger = "cli",
    ) -> GepaRunResult:
        """Run GEPA for one or more active skills (see ``max_skills_per_run``)."""
        if not self._evolution.gepa_enabled():
            return self._skipped_result(trigger, SKIP_EVOLUTION_DISABLED)

        missing = require_evolution_extra()
        if missing:
            return self._skipped_result(trigger, missing)

        lock = GepaRunLock(self._workspace)
        if not lock.try_acquire_run_lock():
            status = GepaRunStatus(
                phase="skipped",
                trigger=trigger,
                skill_name=skill_name,
                message=GEPA_SKIP_ALREADY_RUNNING,
                finished_at=_now_iso(),
            )
            self._store.save(status)
            return GepaRunResult(
                trigger=trigger,
                phase="skipped",
                message=GEPA_SKIP_ALREADY_RUNNING,
            )

        try:
            return await self._run_with_lock(skill_name=skill_name, trigger=trigger)
        except Exception as exc:
            logger.exception("GEPA run failed")
            run_id = str(uuid4())
            self._store.save(
                GepaRunStatus(
                    run_id=run_id,
                    trigger=trigger,
                    skill_name=skill_name,
                    phase="failed",
                    message="GEPA run failed",
                    error=str(exc),
                    finished_at=_now_iso(),
                )
            )
            return GepaRunResult(
                run_id=run_id,
                trigger=trigger,
                phase="failed",
                message="GEPA run failed",
                error=str(exc),
            )
        finally:
            lock.release_run_lock()

    async def _run_with_lock(
        self,
        *,
        skill_name: str | None,
        trigger: GepaRunTrigger,
    ) -> GepaRunResult:
        run_id = str(uuid4())
        started_at = _now_iso()
        status = GepaRunStatus(
            run_id=run_id,
            trigger=trigger,
            skill_name=skill_name,
            phase="starting",
            message="GEPA run starting",
            started_at=started_at,
        )
        self._store.save(status)

        targets = self._resolve_targets(skill_name)
        if not targets:
            reason = SKIP_SKILL_NOT_FOUND if skill_name else SKIP_NO_ACTIVE_SKILLS
            status = status.with_updates(
                phase="failed",
                message=reason,
                finished_at=_now_iso(),
                error=reason,
            )
            self._store.save(status)
            return GepaRunResult(
                run_id=run_id,
                trigger=trigger,
                phase="failed",
                message=reason,
                error=reason,
            )

        status = status.with_updates(
            phase="selecting",
            message=f"selected {len(targets)} skill(s): {', '.join(targets)}",
        )
        self._store.save(status)

        proposals: list[str] = []
        traces: list[str] = []
        budget_total = 0.0
        processed = 0

        for name in targets[: self._max_skills_per_run]:
            processed += 1
            status = status.with_updates(
                phase="optimizing",
                skill_name=name,
                message=f"optimizing skill {name}",
            )
            self._store.save(status)

            outcome = await self._process_skill(name)
            budget_total += outcome.budget_usd

            if outcome.proposal_id:
                status = status.with_updates(phase="writing", message=f"writing proposal for {name}")
                self._store.save(status)
                proposals.append(outcome.proposal_id)
                traces.extend(outcome.trace_ids)
            elif outcome.skip_reason:
                logger.info("GEPA skill {} skipped: {}", name, outcome.skip_reason)

        finished = _now_iso()
        message = (
            f"{len(proposals)} GEPA proposal(s) ready"
            if proposals
            else "GEPA run finished with no new proposals"
        )
        status = status.with_updates(
            phase="completed",
            message=message,
            finished_at=finished,
            proposals_created=tuple(proposals),
            traces_consumed=tuple(traces),
            budget_usd_spent=budget_total,
        )
        self._store.save(status)

        logger.info(
            "GEPA [done] run_id={} proposals={} traces={} budget=${:.4f}",
            run_id,
            len(proposals),
            len(traces),
            budget_total,
        )

        return GepaRunResult(
            run_id=run_id,
            trigger=trigger,
            phase="completed",
            proposals_created=tuple(proposals),
            traces_consumed=tuple(traces),
            skills_processed=processed,
            budget_usd_spent=budget_total,
            message=message,
        )

    def _resolve_targets(self, skill_name: str | None) -> list[str]:
        if skill_name:
            needle = skill_name.strip()
            if needle not in list_active_skill_names(self._workspace):
                return []
            return [needle]
        return list_active_skill_names(self._workspace)

    async def _process_skill(self, skill_name: str) -> _SkillProcessOutcome:
        dataset = build_gepa_dataset(
            self._trace_store,
            skill_name,
            min_traces=self._min_traces,
        )
        if dataset.skipped:
            return _SkillProcessOutcome(skip_reason=dataset.skip_reason or SKIP_INSUFFICIENT_TRACES)

        try:
            module = GepaSkillModule.from_active_skill(self._workspace, skill_name)
        except FileNotFoundError:
            return _SkillProcessOutcome(skip_reason=SKIP_SKILL_NOT_FOUND)

        base_md = module.to_skill_md()
        base_sha = self._git.head_sha() or ""

        optimizer = self._get_optimizer()
        evaluator = self._get_evaluator()
        budget_before = evaluator.budget.spent_usd if evaluator else 0.0

        opt_result = await asyncio.to_thread(
            optimizer.optimize,
            module,
            dataset.examples,
        )

        budget_spent = 0.0
        if evaluator is not None:
            budget_spent = max(0.0, evaluator.budget.spent_usd - budget_before)

        if opt_result.skipped:
            return _SkillProcessOutcome(
                skip_reason=opt_result.skip_reason or opt_result.error,
                budget_usd=budget_spent,
            )

        validation_error = validate_gepa_update(
            opt_result.skill_md,
            base_md,
            skill_name=skill_name,
            base_skill=skill_name,
        )
        if validation_error:
            logger.warning("GEPA validation failed for {}: {}", skill_name, validation_error)
            return _SkillProcessOutcome(skip_reason=validation_error, budget_usd=budget_spent)

        if not _is_improved(opt_result, base_md):
            return _SkillProcessOutcome(
                skip_reason="no improvement over baseline",
                budget_usd=budget_spent,
            )

        rationale = _build_rationale(opt_result)
        try:
            proposal_id = self._proposals.write_gepa_proposal(
                skill_name,
                opt_result.skill_md,
                base_sha=base_sha,
                evaluation_score=opt_result.evaluation_score,
                trace_ids=dataset.trace_ids,
                rationale=rationale,
            )
        except ValueError as exc:
            if str(exc) == SKIP_PENDING_GEPA_UPDATE:
                return _SkillProcessOutcome(skip_reason=SKIP_PENDING_GEPA_UPDATE, budget_usd=budget_spent)
            raise

        marked = self._trace_store.mark_used_for_evolution(list(dataset.trace_ids))
        logger.info(
            "GEPA proposal {} for skill {} (marked {} traces, base_sha={})",
            proposal_id,
            skill_name,
            marked,
            base_sha,
        )
        return _SkillProcessOutcome(
            proposal_id=proposal_id,
            trace_ids=dataset.trace_ids,
            budget_usd=budget_spent,
        )

    def _get_optimizer(self) -> GepaOptimizer:
        if self._optimizer is not None:
            return self._optimizer
        model = resolve_gepa_optimizer_model(
            self._evolution.gepa.model,
            self._fallback_model,
        )
        return GepaOptimizer(
            GepaOptimizerConfig(optimizer_model=model, eval_model=model, auto="light"),
            evaluator=self._get_evaluator(),
        )

    def _get_evaluator(self) -> GepaEvaluator:
        if self._evaluator is not None:
            return self._evaluator
        provider = resolve_gepa_provider(
            self._provider_config,
            self._evolution,
            self._provider,
        )
        model = resolve_gepa_optimizer_model(
            self._evolution.gepa.model,
            self._fallback_model,
        )
        self._evaluator = GepaEvaluator(
            provider,
            model,
            config=GepaEvaluatorConfig(max_budget_usd=self._evolution.gepa.max_budget_usd),
        )
        return self._evaluator

    def _skipped_result(self, trigger: GepaRunTrigger, reason: str) -> GepaRunResult:
        self._store.save(
            GepaRunStatus(
                phase="skipped",
                trigger=trigger,
                message=reason,
                finished_at=_now_iso(),
            )
        )
        return GepaRunResult(trigger=trigger, phase="skipped", message=reason)


def _is_improved(opt_result: GepaOptimizeResult, base_md: str) -> bool:
    if (
        opt_result.evaluation_score is not None
        and opt_result.baseline_score is not None
    ):
        return opt_result.evaluation_score > opt_result.baseline_score
    if opt_result.improved:
        return True
    return opt_result.skill_md.strip() != base_md.strip()


def _build_rationale(opt_result: GepaOptimizeResult) -> str:
    if opt_result.baseline_score is not None and opt_result.evaluation_score is not None:
        return (
            f"GEPA improved validation score from {opt_result.baseline_score:.3f} "
            f"to {opt_result.evaluation_score:.3f}"
        )
    if opt_result.score_delta is not None:
        return f"GEPA improved skill (delta {opt_result.score_delta:+.3f})"
    return "GEPA optimized skill body from successful turn traces"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
