"""Unit tests for AnswerVerifier (extracted from AgentLoop, LAN-215)."""

from __future__ import annotations

import contextlib
from typing import Any
from unittest.mock import patch  # noqa: F401 – used by async tests (Task 4)

import pytest

from nanobot.agent.verifier import AnswerVerifier
from nanobot.providers.base import LLMResponse  # noqa: F401 – used by async tests (Task 4)
from tests.helpers import ScriptedProvider


@contextlib.asynccontextmanager
async def _noop_span_cm(**kwargs: Any):
    yield None


class TestLooksLikeQuestion:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("What is X?", True),
            ("how do I do this", True),
            ("is it ready?", True),
            ("who wrote this", True),
            ("can you help", True),
            ("Hello", False),
            ("Save this note", False),
            ("", False),
            ("  ", False),
            ("Tell me about cats", False),
            ("Something with a ? mark", True),
        ],
    )
    def test_question_detection(self, text: str, expected: bool) -> None:
        assert AnswerVerifier._looks_like_question(text) is expected


class TestBuildNoAnswerExplanation:
    def test_no_tool_results(self) -> None:
        result = AnswerVerifier.build_no_answer_explanation("What?", [])
        assert "did not produce" in result

    def test_exit_code_error(self) -> None:
        msgs = [{"role": "tool", "name": "exec", "content": "exit code: 1"}]
        result = AnswerVerifier.build_no_answer_explanation("What?", msgs)
        assert "no matching data" in result

    def test_permission_denied(self) -> None:
        msgs = [{"role": "tool", "name": "exec", "content": "permission denied"}]
        result = AnswerVerifier.build_no_answer_explanation("What?", msgs)
        assert "permission error" in result

    def test_question_input_suggests_rephrase(self) -> None:
        result = AnswerVerifier.build_no_answer_explanation("What is X?", [])
        assert "rephrasing" in result.lower() or "rephras" in result.lower()

    def test_statement_input_suggests_sharing(self) -> None:
        result = AnswerVerifier.build_no_answer_explanation("My name is Carlos", [])
        assert "share the fact" in result.lower()

    def test_quota_error(self) -> None:
        msgs = [{"role": "tool", "name": "web", "content": "429 rate limited"}]
        result = AnswerVerifier.build_no_answer_explanation("Search for X?", msgs)
        assert "quota" in result.lower() or "rate limit" in result.lower()


class TestEstimateGroundingConfidence:
    def _make_verifier(self, memory: Any = None) -> AnswerVerifier:
        provider = ScriptedProvider([])
        return AnswerVerifier(
            provider=provider,
            model="test-model",
            temperature=0.7,
            max_tokens=4096,
            verification_mode="off",
            memory_uncertainty_threshold=0.5,
            memory_store=memory,
        )

    def test_no_memory_returns_zero(self) -> None:
        v = self._make_verifier(memory=None)
        assert v._estimate_grounding_confidence("anything") == 0.0

    def test_empty_results_returns_zero(self) -> None:
        memory = type("FakeMemory", (), {"retrieve": lambda self, q, top_k=1: []})()
        v = self._make_verifier(memory=memory)
        assert v._estimate_grounding_confidence("anything") == 0.0

    def test_score_clamped_to_unit_interval(self) -> None:
        memory = type("FakeMemory", (), {"retrieve": lambda self, q, top_k=1: [{"score": 1.5}]})()
        v = self._make_verifier(memory=memory)
        assert v._estimate_grounding_confidence("anything") == 1.0

    def test_memory_exception_returns_zero(self) -> None:
        def _explode(q, top_k=1):
            raise RuntimeError("boom")

        memory = type("FakeMemory", (), {"retrieve": _explode})()
        v = self._make_verifier(memory=memory)
        assert v._estimate_grounding_confidence("anything") == 0.0

    def test_normal_score_returned(self) -> None:
        memory = type("FakeMemory", (), {"retrieve": lambda self, q, top_k=1: [{"score": 0.75}]})()
        v = self._make_verifier(memory=memory)
        assert v._estimate_grounding_confidence("anything") == 0.75
