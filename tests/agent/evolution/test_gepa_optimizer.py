"""Tests for GEPA optimizer wrapper (E4-D4)."""

from __future__ import annotations

from typing import Any

import pytest

from nanobot.agent.evolution.deps import evolution_extra_available
from nanobot.agent.evolution.gepa_dataset import GepaEvalExample
from nanobot.agent.evolution.gepa_evaluator import (
    GepaEvaluator,
    GepaEvaluatorConfig,
)
from nanobot.agent.evolution.gepa_optimizer import (
    GepaOptimizeResult,
    GepaOptimizer,
    GepaOptimizerConfig,
    examples_to_dspy,
    fast_trace_score,
    split_train_val,
)
from nanobot.agent.evolution.gepa_skill_module import (
    GepaSkillModule,
    _set_predictor_instructions,
)
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

_EVOLVED_BODY = """# Deploy K8s

## Steps
1. kubectl apply -f manifest.yaml
2. kubectl rollout status deploy/nginx
"""


def _example(trace_id: str = "t1", query: str = "deploy nginx") -> GepaEvalExample:
    return GepaEvalExample(
        trace_id=trace_id,
        query=query,
        tool_calls=(
            ToolCallRecord(name="exec", args_summary="kubectl apply -f nginx.yaml"),
            ToolCallRecord(name="exec", args_summary="kubectl rollout status deploy/nginx"),
        ),
        outcome="success",
        stop_reason="completed",
    )


class _JudgeProvider(LLMProvider):
    def __init__(self, score: float = 0.9) -> None:
        super().__init__()
        self.score = score
        self.calls = 0

    async def chat(self, *args, **kwargs) -> LLMResponse:
        self.calls += 1
        return LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="s1",
                    name="score_skill_candidate",
                    arguments={
                        "correctness": self.score,
                        "procedure_following": self.score,
                        "conciseness": self.score,
                        "feedback": "good",
                    },
                )
            ],
            usage={"prompt_tokens": 100, "completion_tokens": 50},
        )

    def get_default_model(self) -> str:
        return "test-model"


class _FakePrediction:
    def __init__(self, suggested_actions: str) -> None:
        self.suggested_actions = suggested_actions


def test_fast_trace_score_uses_reference_overlap() -> None:
    gold = type("Gold", (), {"tool_context": "- exec(kubectl apply -f nginx.yaml) [ok]"})()
    pred = _FakePrediction("Run kubectl apply -f nginx.yaml then check rollout status")

    score, feedback = fast_trace_score(gold, pred)

    assert score > 0.5
    assert "Overlap" in feedback


def test_examples_to_dspy_and_split() -> None:
    examples = [_example("t1"), _example("t2"), _example("t3"), _example("t4")]
    train, val = split_train_val(examples, val_ratio=0.25)
    assert len(train) == 3
    assert len(val) == 1

    dspy_rows = examples_to_dspy(train)
    assert len(dspy_rows) == 3
    assert dspy_rows[0].query == "deploy nginx"
    assert "kubectl apply" in dspy_rows[0].tool_context


@pytest.mark.skipif(not evolution_extra_available(), reason="evolution extra not installed")
def test_optimize_with_mock_gepa_mutates_skill_md(monkeypatch: pytest.MonkeyPatch) -> None:
    import dspy

    class FakeGEPA:
        def __init__(self, metric: Any, **kwargs: Any) -> None:
            self.metric = metric
            self.kwargs = kwargs

        def compile(
            self,
            student: Any,
            *,
            trainset: list[Any],
            valset: list[Any] | None = None,
        ) -> Any:
            _ = (trainset, valset)
            if trainset:
                gold = trainset[0]
                pred = _FakePrediction("kubectl apply kubectl rollout status")
                self.metric(gold, pred)
            _set_predictor_instructions(student, _EVOLVED_BODY)
            student.detailed_results = type(
                "DR",
                (),
                {"total_metric_calls": 3},
            )()
            return student

    monkeypatch.setattr(dspy, "GEPA", FakeGEPA)
    monkeypatch.setattr(
        "nanobot.agent.evolution.gepa_optimizer.make_dspy_lm",
        lambda model, **kwargs: f"lm:{model}",
    )
    module = GepaSkillModule.from_skill_md(_SKILL_MD)
    optimizer = GepaOptimizer(
        GepaOptimizerConfig(
            optimizer_model="openai/gpt-4.1-mini",
            auto="light",
        )
    )
    examples = [_example("t1"), _example("t2"), _example("t3")]

    result = optimizer.optimize(module, examples)

    assert isinstance(result, GepaOptimizeResult)
    assert result.skipped is False
    assert "rollout status" in result.skill_md
    assert result.metric_calls == 3
    assert module.body == _EVOLVED_BODY.strip()
    assert result.evaluation_score is None


@pytest.mark.skipif(not evolution_extra_available(), reason="evolution extra not installed")
def test_optimize_with_evaluator_scores_baseline_and_evolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dspy

    class FakeGEPA:
        def __init__(self, metric: Any, **kwargs: Any) -> None:
            self.metric = metric

        def compile(self, student: Any, *, trainset: list[Any], valset: list[Any] | None = None) -> Any:
            _set_predictor_instructions(student, _EVOLVED_BODY)
            student.detailed_results = type("DR", (), {"total_metric_calls": 1})()
            return student

    monkeypatch.setattr(dspy, "GEPA", FakeGEPA)
    monkeypatch.setattr(
        "nanobot.agent.evolution.gepa_optimizer.make_dspy_lm",
        lambda model, **kwargs: f"lm:{model}",
    )

    module = GepaSkillModule.from_skill_md(_SKILL_MD)
    provider = _JudgeProvider(score=0.6)
    evaluator = GepaEvaluator(
        provider,
        "test-model",
        config=GepaEvaluatorConfig(max_budget_usd=50.0),
    )
    optimizer = GepaOptimizer(
        GepaOptimizerConfig(optimizer_model="openai/gpt-4.1-mini", auto="light"),
        evaluator=evaluator,
    )
    examples = [_example("t1"), _example("t2")]

    result = optimizer.optimize(module, examples, valset=(_example("v1"),))

    assert result.skipped is False
    assert result.baseline_score == pytest.approx(0.6)
    assert result.evaluation_score == pytest.approx(0.6)
    assert provider.calls == 2


def test_optimize_skips_without_evolution_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nanobot.agent.evolution.gepa_optimizer.require_evolution_extra",
        lambda: "install evolution extra",
    )
    module = GepaSkillModule.from_skill_md(_SKILL_MD)
    optimizer = GepaOptimizer(GepaOptimizerConfig(optimizer_model="test"))
    result = optimizer.optimize(module, [_example()])
    assert result.skipped is True
    assert "evolution" in result.skip_reason
