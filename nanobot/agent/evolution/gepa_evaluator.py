"""Batch LLM-as-judge evaluator for GEPA skill candidates (E4-D3)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from loguru import logger

from nanobot.agent.evolution.gepa_dataset import GepaEvalExample
from nanobot.agent.evolution.gepa_skill_module import GepaSkillModule
from nanobot.agent.evolution.models import ToolCallRecord
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from nanobot.utils.prompt_templates import render_template

DEFAULT_MAX_CONCURRENCY = 4
DEFAULT_TIMEOUT_S = 60.0
DEFAULT_INPUT_COST_PER_MILLION = 3.0
DEFAULT_OUTPUT_COST_PER_MILLION = 15.0
DEFAULT_MAX_BODY_CHARS = 20_000
SKIP_BUDGET_EXCEEDED = "GEPA eval budget exceeded"

_SCORE_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "score_skill_candidate",
            "description": (
                "Score a candidate SKILL.md body against a reference successful turn."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "correctness": {
                        "type": "number",
                        "description": "0.0-1.0: useful, accurate outcome for the query",
                    },
                    "procedure_following": {
                        "type": "number",
                        "description": "0.0-1.0: aligns with reference tool trajectory",
                    },
                    "conciseness": {
                        "type": "number",
                        "description": "0.0-1.0: focused without unnecessary verbosity",
                    },
                    "feedback": {
                        "type": "string",
                        "description": "Specific, actionable feedback for GEPA reflection",
                    },
                },
                "required": [
                    "correctness",
                    "procedure_following",
                    "conciseness",
                    "feedback",
                ],
            },
        },
    }
]


@dataclass(frozen=True, slots=True)
class GepaEvaluatorConfig:
    """Runtime limits for batch skill evaluation."""

    max_budget_usd: float = 10.0
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY
    timeout_s: float = DEFAULT_TIMEOUT_S
    input_cost_per_million: float = DEFAULT_INPUT_COST_PER_MILLION
    output_cost_per_million: float = DEFAULT_OUTPUT_COST_PER_MILLION
    max_body_chars: int = DEFAULT_MAX_BODY_CHARS


@dataclass(frozen=True, slots=True)
class GepaEvalScore:
    """One example's rubric score plus reflection payload for GEPA."""

    trace_id: str
    score: float
    correctness: float = 0.0
    procedure_following: float = 0.0
    conciseness: float = 0.0
    length_penalty: float = 0.0
    feedback: str = ""
    cost_usd: float = 0.0
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    def reflection_trace(self) -> dict[str, Any]:
        """Structured trace for GEPA reflective analysis."""
        return {
            "trace_id": self.trace_id,
            "score": self.score,
            "correctness": self.correctness,
            "procedure_following": self.procedure_following,
            "conciseness": self.conciseness,
            "length_penalty": self.length_penalty,
            "feedback": self.feedback,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class GepaBatchEvalResult:
    """Outcome of evaluating one skill candidate over many examples."""

    scores: tuple[GepaEvalScore, ...] = ()
    average_score: float = 0.0
    budget_usd_spent: float = 0.0
    aborted: bool = False
    abort_reason: str = ""

    @property
    def reflection_traces(self) -> tuple[dict[str, Any], ...]:
        return tuple(score.reflection_trace() for score in self.scores)


@dataclass
class GepaBudgetTracker:
    """Accumulates LLM spend and signals when a run should stop."""

    max_budget_usd: float
    spent_usd: float = 0.0

    @property
    def exhausted(self) -> bool:
        return self.spent_usd >= self.max_budget_usd

    def add_usage(self, usage: dict[str, int], *, model: str, config: GepaEvaluatorConfig) -> float:
        cost = estimate_llm_cost_usd(
            usage,
            model=model,
            input_cost_per_million=config.input_cost_per_million,
            output_cost_per_million=config.output_cost_per_million,
        )
        self.spent_usd += cost
        return cost


class SupportsChatWithRetry(Protocol):
    async def chat_with_retry(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResponse: ...


def estimate_llm_cost_usd(
    usage: dict[str, int],
    *,
    model: str,
    input_cost_per_million: float = DEFAULT_INPUT_COST_PER_MILLION,
    output_cost_per_million: float = DEFAULT_OUTPUT_COST_PER_MILLION,
) -> float:
    """Estimate USD cost from provider token usage."""
    _ = model
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    if prompt_tokens == 0 and completion_tokens == 0:
        total = int(usage.get("total_tokens") or 0)
        if total > 0:
            prompt_tokens = total
    input_cost = prompt_tokens * input_cost_per_million / 1_000_000
    output_cost = completion_tokens * output_cost_per_million / 1_000_000
    return input_cost + output_cost


def composite_score(
    *,
    correctness: float,
    procedure_following: float,
    conciseness: float,
    length_penalty: float = 0.0,
) -> float:
    """Weighted rubric score used as GEPA fitness signal."""
    raw = 0.5 * correctness + 0.3 * procedure_following + 0.2 * conciseness
    return max(0.0, min(1.0, raw - length_penalty))


def length_penalty_for_body(body: str, *, max_body_chars: int) -> float:
    """Penalize skill bodies approaching the size limit (Hermes length guard)."""
    if max_body_chars <= 0:
        return 0.0
    ratio = len(body) / max_body_chars
    if ratio <= 0.9:
        return 0.0
    return min(0.3, (ratio - 0.9) * 3.0)


def format_tool_calls(tool_calls: Sequence[ToolCallRecord]) -> str:
    if not tool_calls:
        return "(none)"
    lines: list[str] = []
    for call in tool_calls:
        status = "ok" if call.ok else "failed"
        lines.append(f"- {call.name}({call.args_summary}) [{status}]")
    return "\n".join(lines)


def parse_score_tool_call(response: LLMResponse) -> tuple[float, float, float, float, str] | None:
    """Parse rubric dimensions from ``score_skill_candidate`` tool output."""
    if not response.should_execute_tools or not response.tool_calls:
        return None
    call = response.tool_calls[0]
    if call.name != "score_skill_candidate":
        return None
    args = call.arguments
    correctness = _clamp_score(args.get("correctness"))
    procedure = _clamp_score(args.get("procedure_following"))
    conciseness = _clamp_score(args.get("conciseness"))
    feedback = str(args.get("feedback") or "").strip()
    return correctness, procedure, conciseness, 0.0, feedback


class GepaEvaluator:
    """Score skill candidates against historical traces with budget + concurrency limits."""

    def __init__(
        self,
        provider: LLMProvider,
        model: str,
        *,
        config: GepaEvaluatorConfig | None = None,
        budget: GepaBudgetTracker | None = None,
    ) -> None:
        self._provider = provider
        self._model = model
        self._config = config or GepaEvaluatorConfig()
        self._budget = budget or GepaBudgetTracker(max_budget_usd=self._config.max_budget_usd)

    @property
    def budget(self) -> GepaBudgetTracker:
        return self._budget

    @property
    def config(self) -> GepaEvaluatorConfig:
        return self._config

    async def evaluate_one(
        self,
        skill_module: GepaSkillModule,
        example: GepaEvalExample,
    ) -> GepaEvalScore:
        if self._budget.exhausted:
            return GepaEvalScore(
                trace_id=example.trace_id,
                score=0.0,
                error=SKIP_BUDGET_EXCEEDED,
            )

        penalty = length_penalty_for_body(
            skill_module.body,
            max_body_chars=self._config.max_body_chars,
        )
        try:
            response = await asyncio.wait_for(
                self._judge(skill_module, example),
                timeout=self._config.timeout_s,
            )
        except TimeoutError:
            logger.warning("GEPA eval timeout for trace {}", example.trace_id)
            return GepaEvalScore(
                trace_id=example.trace_id,
                score=0.0,
                length_penalty=penalty,
                error="eval timeout",
            )
        except Exception as exc:
            logger.warning("GEPA eval failed for trace {}: {}", example.trace_id, exc)
            return GepaEvalScore(
                trace_id=example.trace_id,
                score=0.0,
                length_penalty=penalty,
                error=str(exc),
            )

        cost = self._budget.add_usage(response.usage, model=self._model, config=self._config)
        parsed = parse_score_tool_call(response)
        if parsed is None:
            return GepaEvalScore(
                trace_id=example.trace_id,
                score=0.0,
                length_penalty=penalty,
                cost_usd=cost,
                error="judge returned no score tool call",
            )

        correctness, procedure, conciseness, _, feedback = parsed
        score = composite_score(
            correctness=correctness,
            procedure_following=procedure,
            conciseness=conciseness,
            length_penalty=penalty,
        )
        return GepaEvalScore(
            trace_id=example.trace_id,
            score=score,
            correctness=correctness,
            procedure_following=procedure,
            conciseness=conciseness,
            length_penalty=penalty,
            feedback=feedback,
            cost_usd=cost,
        )

    async def evaluate_batch(
        self,
        skill_module: GepaSkillModule,
        examples: Sequence[GepaEvalExample],
    ) -> GepaBatchEvalResult:
        if not examples:
            return GepaBatchEvalResult()

        if self._budget.exhausted:
            return GepaBatchEvalResult(
                budget_usd_spent=self._budget.spent_usd,
                aborted=True,
                abort_reason=SKIP_BUDGET_EXCEEDED,
            )

        semaphore = asyncio.Semaphore(max(1, self._config.max_concurrency))
        lock = asyncio.Lock()
        scores: list[GepaEvalScore | None] = [None] * len(examples)
        aborted = False
        abort_reason = ""

        async def _run(index: int, example: GepaEvalExample) -> None:
            nonlocal aborted, abort_reason
            if aborted:
                return
            async with semaphore:
                if aborted or self._budget.exhausted:
                    async with lock:
                        if not aborted:
                            aborted = True
                            abort_reason = SKIP_BUDGET_EXCEEDED
                    return
                score = await self.evaluate_one(skill_module, example)
                async with lock:
                    scores[index] = score
                    if self._budget.exhausted:
                        aborted = True
                        abort_reason = SKIP_BUDGET_EXCEEDED

        await asyncio.gather(*(_run(index, example) for index, example in enumerate(examples)))

        completed = tuple(score for score in scores if score is not None)
        average = sum(score.score for score in completed) / max(1, len(completed))
        return GepaBatchEvalResult(
            scores=completed,
            average_score=average,
            budget_usd_spent=self._budget.spent_usd,
            aborted=aborted,
            abort_reason=abort_reason,
        )

    async def _judge(self, skill_module: GepaSkillModule, example: GepaEvalExample) -> LLMResponse:
        messages = [
            {
                "role": "system",
                "content": render_template("agent/evolution_gepa_evaluator.md", part="system"),
            },
            {
                "role": "user",
                "content": render_template(
                    "agent/evolution_gepa_evaluator.md",
                    part="user",
                    query=example.query,
                    outcome=example.outcome,
                    stop_reason=example.stop_reason,
                    tool_calls=format_tool_calls(example.tool_calls),
                    skill_body=skill_module.body,
                ),
            },
        ]
        chat = getattr(self._provider, "chat_with_retry", None)
        if callable(chat):
            return await chat(
                messages,
                tools=_SCORE_TOOL,
                model=self._model,
                max_tokens=512,
                temperature=0.0,
            )
        return await self._provider.chat(
            messages,
            tools=_SCORE_TOOL,
            model=self._model,
            max_tokens=512,
            temperature=0.0,
        )


def _clamp_score(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.5
