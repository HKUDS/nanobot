"""Tests for GEPA batch evaluator (E4-D3)."""

from __future__ import annotations

import asyncio

import pytest

from nanobot.agent.evolution.gepa_dataset import GepaEvalExample
from nanobot.agent.evolution.gepa_evaluator import (
    SKIP_BUDGET_EXCEEDED,
    GepaBatchEvalResult,
    GepaBudgetTracker,
    GepaEvaluator,
    GepaEvaluatorConfig,
    GepaEvalScore,
    composite_score,
    estimate_llm_cost_usd,
    format_tool_calls,
    length_penalty_for_body,
    parse_score_tool_call,
)
from nanobot.agent.evolution.gepa_skill_module import GepaSkillModule
from nanobot.agent.evolution.models import ToolCallRecord
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

_SKILL_MD = """---
name: deploy-k8s
description: Deploy workloads to Kubernetes clusters
---

# Deploy K8s

## Steps
1. kubectl apply -f manifest.yaml
"""


class DummyProvider(LLMProvider):
    def __init__(self, responses: list[LLMResponse]):
        super().__init__()
        self._responses = list(responses)
        self.calls = 0

    async def chat(self, *args, **kwargs) -> LLMResponse:
        self.calls += 1
        if self._responses:
            return self._responses.pop(0)
        return LLMResponse(content="", tool_calls=[])

    def get_default_model(self) -> str:
        return "test-model"


def _score_response(
    *,
    correctness: float = 0.8,
    procedure_following: float = 0.7,
    conciseness: float = 0.9,
    feedback: str = "Add rollout verification.",
    usage: dict[str, int] | None = None,
) -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=[
            ToolCallRequest(
                id="score_1",
                name="score_skill_candidate",
                arguments={
                    "correctness": correctness,
                    "procedure_following": procedure_following,
                    "conciseness": conciseness,
                    "feedback": feedback,
                },
            )
        ],
        usage=usage or {"prompt_tokens": 1000, "completion_tokens": 200},
    )


def _example(trace_id: str = "trace-1") -> GepaEvalExample:
    return GepaEvalExample(
        trace_id=trace_id,
        query="deploy nginx to k8s",
        tool_calls=(ToolCallRecord(name="exec", args_summary="kubectl apply -f nginx.yaml"),),
        outcome="success",
        stop_reason="completed",
    )


def test_composite_score_and_length_penalty() -> None:
    assert composite_score(correctness=1.0, procedure_following=1.0, conciseness=1.0) == 1.0
    assert composite_score(
        correctness=0.8,
        procedure_following=0.6,
        conciseness=0.5,
        length_penalty=0.1,
    ) == pytest.approx(0.58)
    assert length_penalty_for_body("x" * 18_500, max_body_chars=20_000) > 0.0
    assert length_penalty_for_body("short", max_body_chars=20_000) == 0.0


def test_estimate_llm_cost_usd() -> None:
    cost = estimate_llm_cost_usd(
        {"prompt_tokens": 1_000_000, "completion_tokens": 0},
        model="test",
        input_cost_per_million=2.0,
        output_cost_per_million=10.0,
    )
    assert cost == pytest.approx(2.0)


def test_parse_score_tool_call() -> None:
    parsed = parse_score_tool_call(_score_response(correctness=0.9, procedure_following=0.8))
    assert parsed is not None
    correctness, procedure, conciseness, _, feedback = parsed
    assert correctness == pytest.approx(0.9)
    assert procedure == pytest.approx(0.8)
    assert feedback == "Add rollout verification."
    assert parse_score_tool_call(LLMResponse(content="no tool", tool_calls=[])) is None


def test_format_tool_calls() -> None:
    rendered = format_tool_calls(
        (ToolCallRecord(name="exec", args_summary="kubectl apply"),),
    )
    assert "exec(kubectl apply)" in rendered
    assert format_tool_calls(()) == "(none)"


@pytest.mark.asyncio
async def test_evaluate_one_returns_repeatable_score() -> None:
    provider = DummyProvider([_score_response(), _score_response()])
    evaluator = GepaEvaluator(provider, "test-model")
    module = GepaSkillModule.from_skill_md(_SKILL_MD)

    first = await evaluator.evaluate_one(module, _example())
    second = await evaluator.evaluate_one(module, _example())

    assert first.ok is True
    assert first.score == second.score
    assert first.feedback == "Add rollout verification."
    assert first.cost_usd > 0.0
    assert first.reflection_trace()["score"] == first.score


@pytest.mark.asyncio
async def test_evaluate_batch_averages_scores() -> None:
    provider = DummyProvider(
        [
            _score_response(correctness=1.0, procedure_following=1.0, conciseness=1.0),
            _score_response(correctness=0.5, procedure_following=0.5, conciseness=0.5),
        ]
    )
    evaluator = GepaEvaluator(provider, "test-model")
    module = GepaSkillModule.from_skill_md(_SKILL_MD)
    examples = [_example("t1"), _example("t2")]

    result = await evaluator.evaluate_batch(module, examples)

    assert isinstance(result, GepaBatchEvalResult)
    assert len(result.scores) == 2
    assert result.average_score == pytest.approx(0.75)
    assert result.budget_usd_spent > 0.0
    assert result.aborted is False
    assert len(result.reflection_traces) == 2


@pytest.mark.asyncio
async def test_evaluate_batch_aborts_when_budget_exceeded() -> None:
    expensive = _score_response(
        usage={"prompt_tokens": 10_000_000, "completion_tokens": 0},
    )
    provider = DummyProvider([expensive, expensive, expensive])
    config = GepaEvaluatorConfig(max_budget_usd=0.01, max_concurrency=1)
    budget = GepaBudgetTracker(max_budget_usd=0.01)
    evaluator = GepaEvaluator(provider, "test-model", config=config, budget=budget)
    module = GepaSkillModule.from_skill_md(_SKILL_MD)
    examples = [_example("t1"), _example("t2"), _example("t3")]

    result = await evaluator.evaluate_batch(module, examples)

    assert result.aborted is True
    assert result.abort_reason == SKIP_BUDGET_EXCEEDED
    assert provider.calls >= 1
    assert len(result.scores) >= 1
    assert result.budget_usd_spent >= config.max_budget_usd


@pytest.mark.asyncio
async def test_evaluate_one_skips_when_budget_already_exhausted() -> None:
    provider = DummyProvider([_score_response()])
    budget = GepaBudgetTracker(max_budget_usd=1.0, spent_usd=1.0)
    evaluator = GepaEvaluator(provider, "test-model", budget=budget)
    module = GepaSkillModule.from_skill_md(_SKILL_MD)

    score = await evaluator.evaluate_one(module, _example())

    assert score.error == SKIP_BUDGET_EXCEEDED
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_evaluate_one_timeout_returns_error_score() -> None:
    class SlowProvider(DummyProvider):
        async def chat(self, *args, **kwargs) -> LLMResponse:
            await asyncio.sleep(0.2)
            return _score_response()

    provider = SlowProvider([])
    config = GepaEvaluatorConfig(timeout_s=0.05)
    evaluator = GepaEvaluator(provider, "test-model", config=config)
    module = GepaSkillModule.from_skill_md(_SKILL_MD)

    score = await evaluator.evaluate_one(module, _example())

    assert isinstance(score, GepaEvalScore)
    assert score.ok is False
    assert score.error == "eval timeout"
