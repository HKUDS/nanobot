"""Unit tests for AnswerVerifier (extracted from AgentLoop, LAN-215)."""

from __future__ import annotations

import contextlib
from typing import Any
from unittest.mock import patch

import pytest

from nanobot.agent.verifier import AnswerVerifier
from nanobot.providers.base import LLMResponse
from tests.helpers import ScriptedProvider


@contextlib.asynccontextmanager
async def _noop_span_cm(**kwargs: Any):
    yield None


def _make_verifier_with_provider(
    provider: ScriptedProvider,
    mode: str = "always",
    memory: Any = None,
) -> AnswerVerifier:
    return AnswerVerifier(
        provider=provider,
        model="test-model",
        temperature=0.7,
        max_tokens=4096,
        verification_mode=mode,
        memory_uncertainty_threshold=0.5,
        memory_store=memory,
    )


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


@patch("nanobot.agent.verifier.score_current_trace", new=lambda **kw: None)
@patch("nanobot.agent.verifier.langfuse_span", new=_noop_span_cm)
class TestVerify:
    async def test_off_passthrough(self) -> None:
        provider = ScriptedProvider([])
        v = _make_verifier_with_provider(provider, mode="off")
        result, msgs = await v.verify("What?", "candidate", [])
        assert result == "candidate"
        assert len(provider.call_log) == 0

    async def test_on_uncertainty_skips_non_question(self) -> None:
        provider = ScriptedProvider([])
        v = _make_verifier_with_provider(provider, mode="on_uncertainty")
        result, _ = await v.verify("hello", "candidate", [])
        assert result == "candidate"
        assert len(provider.call_log) == 0

    async def test_always_high_confidence_passes(self) -> None:
        provider = ScriptedProvider(
            [
                LLMResponse(content='{"confidence": 5, "issues": []}'),
            ]
        )
        v = _make_verifier_with_provider(provider)
        result, _ = await v.verify("What?", "candidate", [])
        assert result == "candidate"

    async def test_always_low_confidence_revises(self) -> None:
        provider = ScriptedProvider(
            [
                LLMResponse(content='{"confidence": 1, "issues": ["unsupported claim"]}'),
                LLMResponse(content="revised answer"),
            ]
        )
        v = _make_verifier_with_provider(provider)
        msgs = [{"role": "assistant", "content": "candidate"}]
        result, updated_msgs = await v.verify("What?", "candidate", msgs)
        assert result == "revised answer"
        # System message with issues was injected
        system_msgs = [m for m in updated_msgs if m.get("role") == "system"]
        assert any("unsupported claim" in m["content"] for m in system_msgs)

    async def test_unparseable_json_passthrough(self) -> None:
        provider = ScriptedProvider(
            [
                LLMResponse(content="not valid json"),
            ]
        )
        v = _make_verifier_with_provider(provider)
        result, _ = await v.verify("What?", "candidate", [])
        assert result == "candidate"

    async def test_llm_exception_passthrough(self) -> None:
        provider = ScriptedProvider([])

        async def _raise(**kwargs: Any) -> None:
            raise RuntimeError("LLM down")

        provider.chat = _raise  # type: ignore[assignment]
        v = _make_verifier_with_provider(provider)
        result, _ = await v.verify("What?", "candidate", [])
        assert result == "candidate"


@patch("nanobot.agent.verifier.langfuse_span", new=_noop_span_cm)
class TestAttemptRecovery:
    async def test_recovery_success(self) -> None:
        provider = ScriptedProvider(
            [
                LLMResponse(content="recovered answer"),
            ]
        )
        v = _make_verifier_with_provider(provider)
        all_msgs = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "What is X?"},
        ]
        result = await v.attempt_recovery(channel="cli", chat_id="test", all_msgs=all_msgs)
        assert result == "recovered answer"

    async def test_recovery_missing_messages(self) -> None:
        provider = ScriptedProvider([])
        v = _make_verifier_with_provider(provider)
        # Only tool messages — no system or user
        all_msgs = [{"role": "tool", "name": "exec", "content": "output"}]
        result = await v.attempt_recovery(channel="cli", chat_id="test", all_msgs=all_msgs)
        assert result is None

    async def test_recovery_llm_exception(self) -> None:
        provider = ScriptedProvider([])

        async def _raise(**kwargs: Any) -> None:
            raise RuntimeError("boom")

        provider.chat = _raise  # type: ignore[assignment]
        v = _make_verifier_with_provider(provider)
        all_msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
        ]
        result = await v.attempt_recovery(channel="cli", chat_id="test", all_msgs=all_msgs)
        assert result is None

    async def test_recovery_error_finish_reason(self) -> None:
        provider = ScriptedProvider(
            [
                LLMResponse(content="error detail", finish_reason="error"),
            ]
        )
        v = _make_verifier_with_provider(provider)
        all_msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
        ]
        result = await v.attempt_recovery(channel="cli", chat_id="test", all_msgs=all_msgs)
        assert result is None
