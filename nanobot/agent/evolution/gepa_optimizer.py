"""DSPy GEPA optimizer wrapper for SKILL.md body evolution (E4-D4)."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, Literal, Sequence

from loguru import logger

from nanobot.agent.evolution.deps import require_evolution_extra
from nanobot.agent.evolution.gepa_dataset import GepaEvalExample
from nanobot.agent.evolution.gepa_evaluator import (
    GepaEvaluator,
    format_tool_calls,
)
from nanobot.agent.evolution.gepa_skill_module import (
    GepaSkillModule,
    extract_body_from_dspy_module,
)

MetricMode = Literal["trace_fast", "llm_judge"]
GepaAutoBudget = Literal["light", "medium", "heavy"]

SKIP_OPTIMIZATION_FAILED = "GEPA optimization failed"


@dataclass(frozen=True, slots=True)
class GepaOptimizerConfig:
    """GEPA compile settings (sync API for ``asyncio.to_thread``)."""

    optimizer_model: str
    eval_model: str | None = None
    auto: GepaAutoBudget | None = "light"
    max_metric_calls: int | None = None
    max_full_evals: int | None = None
    seed: int = 0
    metric_mode: MetricMode = "trace_fast"
    val_ratio: float = 0.25


@dataclass(frozen=True, slots=True)
class GepaOptimizeResult:
    """Outcome of one GEPA skill optimization run."""

    skill_name: str
    skill_md: str = ""
    evaluation_score: float | None = None
    baseline_score: float | None = None
    improved: bool = False
    trace_ids: tuple[str, ...] = ()
    metric_calls: int | None = None
    skipped: bool = False
    skip_reason: str = ""
    error: str = ""

    @property
    def score_delta(self) -> float | None:
        if self.evaluation_score is None or self.baseline_score is None:
            return None
        return self.evaluation_score - self.baseline_score


def make_dspy_lm(model: str, *, max_tokens: int = 2048, temperature: float | None = None) -> Any:
    """Build a ``dspy.LM`` for student forward / reflection."""
    import dspy

    kwargs: dict[str, Any] = {"max_tokens": max_tokens}
    if temperature is not None:
        kwargs["temperature"] = temperature
    return dspy.LM(model, **kwargs)


def examples_to_dspy(examples: Sequence[GepaEvalExample]) -> list[Any]:
    """Convert nanobot eval examples to DSPy examples for ``SkillModule`` inputs."""
    import dspy

    rows: list[Any] = []
    for example in examples:
        rows.append(
            dspy.Example(
                query=example.query,
                tool_context=format_tool_calls(example.tool_calls),
                trace_id=example.trace_id,
                outcome=example.outcome,
                stop_reason=example.stop_reason,
            ).with_inputs("query", "tool_context")
        )
    return rows


def split_train_val(
    examples: Sequence[GepaEvalExample],
    *,
    val_ratio: float = 0.25,
) -> tuple[tuple[GepaEvalExample, ...], tuple[GepaEvalExample, ...]]:
    """Split examples into train / val (deterministic, preserves order when small)."""
    items = tuple(examples)
    if len(items) <= 1:
        return items, items
    if len(items) == 2:
        return (items[0],), (items[1],)
    val_count = max(1, int(len(items) * val_ratio))
    if val_count >= len(items):
        val_count = max(1, len(items) - 1)
    split_at = len(items) - val_count
    return items[:split_at], items[split_at:]


def build_trace_metric(
    examples_by_trace_id: dict[str, GepaEvalExample],
) -> Any:
    """Sync GEPA metric: compare module output to reference tool trajectory."""

    def metric(
        gold: Any,
        pred: Any,
        trace: Any = None,
        pred_name: str | None = None,
        pred_trace: Any = None,
    ) -> Any:
        from dspy.teleprompt.gepa.gepa_utils import ScoreWithFeedback

        _ = (trace, pred_name, pred_trace)
        trace_id = str(getattr(gold, "trace_id", "") or "")
        score, feedback = fast_trace_score(gold, pred)
        if trace_id and trace_id in examples_by_trace_id:
            example = examples_by_trace_id[trace_id]
            if example.outcome != "success":
                score = min(score, 0.4)
                feedback = f"{feedback} Reference outcome was {example.outcome}."
        return ScoreWithFeedback(score=score, feedback=feedback)

    return metric


def fast_trace_score(gold: Any, pred: Any) -> tuple[float, str]:
    """Lightweight fitness proxy (Hermes ``skill_fitness_metric`` style)."""
    output = str(getattr(pred, "suggested_actions", "") or "").strip()
    reference = str(getattr(gold, "tool_context", "") or "").strip()
    if not output:
        return 0.0, "Skill module returned empty suggested_actions."
    if not reference or reference == "(none)":
        return 0.5, "No reference tool trajectory; neutral score."

    ref_tokens = set(re.findall(r"\w+", reference.lower()))
    out_tokens = set(re.findall(r"\w+", output.lower()))
    if not ref_tokens:
        return 0.5, "Reference trajectory has no scorable tokens."

    overlap = len(ref_tokens & out_tokens) / len(ref_tokens)
    score = max(0.0, min(1.0, 0.3 + 0.7 * overlap))
    feedback = (
        f"Overlap with reference tool trajectory: {overlap:.0%}. "
        "Consider aligning steps with successful tool usage."
    )
    return score, feedback


def _run_async(coro: Any) -> Any:
    """Run async evaluator coroutine from sync GEPA metric / optimize."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


class GepaOptimizer:
    """Run ``dspy.GEPA`` on a :class:`GepaSkillModule` with nanobot eval data."""

    def __init__(
        self,
        config: GepaOptimizerConfig,
        *,
        evaluator: GepaEvaluator | None = None,
    ) -> None:
        self._config = config
        self._evaluator = evaluator

    @property
    def config(self) -> GepaOptimizerConfig:
        return self._config

    def optimize(
        self,
        skill_module: GepaSkillModule,
        trainset: Sequence[GepaEvalExample],
        valset: Sequence[GepaEvalExample] | None = None,
    ) -> GepaOptimizeResult:
        """Optimize *skill_module* body; return best SKILL.md and scores."""
        missing = require_evolution_extra()
        if missing:
            return GepaOptimizeResult(
                skill_name=skill_module.skill_name,
                skipped=True,
                skip_reason=missing,
            )

        train_examples = tuple(trainset)
        if not train_examples:
            return GepaOptimizeResult(
                skill_name=skill_module.skill_name,
                skipped=True,
                skip_reason="trainset is empty",
            )

        trace_ids = tuple(example.trace_id for example in train_examples)
        if valset is None:
            train_examples, val_examples = split_train_val(
                train_examples,
                val_ratio=self._config.val_ratio,
            )
        else:
            val_examples = tuple(valset)
            if not val_examples:
                return GepaOptimizeResult(
                    skill_name=skill_module.skill_name,
                    skipped=True,
                    skip_reason="valset is empty",
                )

        examples_by_id = {example.trace_id: example for example in (*train_examples, *val_examples)}
        baseline_score = self._score_with_evaluator(skill_module, val_examples)

        import dspy

        eval_model = self._config.eval_model or self._config.optimizer_model
        dspy.configure(lm=make_dspy_lm(eval_model, max_tokens=1024, temperature=0.0))
        reflection_lm = make_dspy_lm(
            self._config.optimizer_model,
            max_tokens=4096,
            temperature=1.0,
        )

        student = skill_module.build_dspy_module()
        student_holder: list[Any] = [student]
        metric = self._build_metric(
            examples_by_id,
            skill_module=skill_module,
            student_holder=student_holder,
        )
        gepa = self._build_gepa(dspy, metric=metric, reflection_lm=reflection_lm)

        dspy_train = examples_to_dspy(train_examples)
        dspy_val = examples_to_dspy(val_examples)

        try:
            optimized = gepa.compile(student, trainset=dspy_train, valset=dspy_val)
        except Exception as exc:
            logger.exception("GEPA compile failed for skill {}", skill_module.skill_name)
            return GepaOptimizeResult(
                skill_name=skill_module.skill_name,
                skill_md=skill_module.to_skill_md(),
                baseline_score=baseline_score,
                trace_ids=trace_ids,
                skipped=True,
                skip_reason=SKIP_OPTIMIZATION_FAILED,
                error=str(exc),
            )

        skill_module.sync_from_dspy_module(optimized)
        evolved_md = skill_module.to_skill_md()
        evaluation_score = self._score_with_evaluator(skill_module, val_examples)
        metric_calls = _extract_metric_calls(optimized)

        improved = False
        if baseline_score is not None and evaluation_score is not None:
            improved = evaluation_score > baseline_score

        logger.info(
            "GEPA optimize done skill={} baseline={} evolved={} improved={}",
            skill_module.skill_name,
            baseline_score,
            evaluation_score,
            improved,
        )

        return GepaOptimizeResult(
            skill_name=skill_module.skill_name,
            skill_md=evolved_md,
            evaluation_score=evaluation_score,
            baseline_score=baseline_score,
            improved=improved,
            trace_ids=trace_ids,
            metric_calls=metric_calls,
        )

    def _build_metric(
        self,
        examples_by_id: dict[str, GepaEvalExample],
        *,
        skill_module: GepaSkillModule,
        student_holder: list[Any],
    ) -> Any:
        if self._config.metric_mode == "llm_judge" and self._evaluator is not None:
            return build_llm_judge_metric(
                self._evaluator,
                examples_by_id,
                skill_module=skill_module,
                student_holder=student_holder,
            )
        return build_trace_metric(examples_by_id)

    def _build_gepa(self, dspy: Any, *, metric: Any, reflection_lm: Any) -> Any:
        budget_kwargs: dict[str, Any] = {}
        if self._config.auto is not None:
            budget_kwargs["auto"] = self._config.auto
        elif self._config.max_metric_calls is not None:
            budget_kwargs["max_metric_calls"] = self._config.max_metric_calls
        elif self._config.max_full_evals is not None:
            budget_kwargs["max_full_evals"] = self._config.max_full_evals
        else:
            budget_kwargs["auto"] = "light"

        return dspy.GEPA(
            metric=metric,
            reflection_lm=reflection_lm,
            seed=self._config.seed,
            track_stats=True,
            **budget_kwargs,
        )

    def _score_with_evaluator(
        self,
        skill_module: GepaSkillModule,
        examples: Sequence[GepaEvalExample],
    ) -> float | None:
        if self._evaluator is None or not examples:
            return None
        batch = _run_async(self._evaluator.evaluate_batch(skill_module, examples))
        if batch.aborted and not batch.scores:
            return None
        return batch.average_score


def build_llm_judge_metric(
    evaluator: GepaEvaluator,
    examples_by_trace_id: dict[str, GepaEvalExample],
    *,
    skill_module: GepaSkillModule,
    student_holder: list[Any],
) -> Any:
    """GEPA metric that calls :class:`GepaEvaluator` (expensive; use with care)."""

    def metric(
        gold: Any,
        pred: Any,
        trace: Any = None,
        pred_name: str | None = None,
        pred_trace: Any = None,
    ) -> Any:
        from dspy.teleprompt.gepa.gepa_utils import ScoreWithFeedback

        _ = (pred, trace, pred_name, pred_trace)
        trace_id = str(getattr(gold, "trace_id", "") or "")
        example = examples_by_trace_id.get(trace_id)
        if example is None:
            score, feedback = fast_trace_score(gold, pred)
            return ScoreWithFeedback(score=score, feedback=feedback)

        if student_holder:
            skill_module.body = extract_body_from_dspy_module(student_holder[0])
        result = _run_async(evaluator.evaluate_one(skill_module, example))
        if result.error:
            score, feedback = fast_trace_score(gold, pred)
            feedback = f"{feedback} Judge fallback: {result.error}"
            return ScoreWithFeedback(score=score, feedback=feedback)
        return ScoreWithFeedback(score=result.score, feedback=result.feedback)

    return metric


def _extract_metric_calls(optimized_module: Any) -> int | None:
    detailed = getattr(optimized_module, "detailed_results", None)
    if detailed is None:
        return None
    return getattr(detailed, "total_metric_calls", None)


def resolve_gepa_optimizer_model(
    evolution_gepa_model: str | None,
    fallback_model: str,
) -> str:
    """Pick GEPA optimizer / reflection model from config."""
    model = (evolution_gepa_model or "").strip()
    return model or fallback_model
