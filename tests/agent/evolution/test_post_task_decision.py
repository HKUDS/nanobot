"""Tests for PostTask LLM decision parsing and decide() (E1 Step 2)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.evolution.models import ToolCallRecord, TurnTrace
from nanobot.agent.evolution.post_task import (
    PostTaskDecision,
    PostTaskEvolver,
    format_tool_calls_for_prompt,
    parse_post_task_response,
    resolve_post_task_provider,
)
from nanobot.config.schema import EvolutionConfig, EvolutionPostTaskConfig
from nanobot.providers.base import LLMProvider, LLMResponse


def _trace(*, query: str = "deploy nginx to k8s") -> TurnTrace:
    tool_calls = (
        ToolCallRecord(name="read_file", args_summary="path=deploy.yaml", ok=True),
        ToolCallRecord(name="exec", args_summary="kubectl apply", ok=True),
        ToolCallRecord(name="exec", args_summary="kubectl rollout status", ok=True),
        ToolCallRecord(name="read_file", args_summary="path=service.yaml", ok=True),
        ToolCallRecord(name="write_file", args_summary="path=ingress.yaml", ok=True),
    )
    return TurnTrace(
        session_key="cli:direct",
        query=query,
        skills_injected=("github",),
        tool_calls=tool_calls,
        tool_call_count=len(tool_calls),
        iterations=3,
        stop_reason="completed",
        outcome="success",
    )


def test_parse_create_skill_valid_json() -> None:
    raw = (
        '{"action":"create_skill","skill_name":"k8s-deploy","rationale":"repeatable flow",'
        '"confidence":0.9}'
    )
    decision = parse_post_task_response(raw, min_confidence=0.7)
    assert decision.action == "create_skill"
    assert decision.skill_name == "k8s-deploy"
    assert decision.rationale == "repeatable flow"
    assert decision.confidence == pytest.approx(0.9)


def test_parse_strips_json_fence() -> None:
    raw = """```json
{"action":"create_skill","skill_name":"deploy-k8s","rationale":"ok","confidence":0.85}
```"""
    decision = parse_post_task_response(raw, min_confidence=0.7)
    assert decision.action == "create_skill"
    assert decision.skill_name == "deploy-k8s"


def test_parse_none_action() -> None:
    raw = '{"action":"none","skill_name":"","rationale":"one-off","confidence":0.95}'
    decision = parse_post_task_response(raw, min_confidence=0.7)
    assert decision.action == "none"
    assert decision.skill_name == ""
    assert decision.confidence == pytest.approx(0.95)
    assert decision.parsed is True
    assert decision.rationale == "one-off"


def test_parse_none_preserves_confidence_when_below_min_for_create() -> None:
    raw = (
        '{"action":"create_skill","skill_name":"k8s-deploy","rationale":"maybe",'
        '"confidence":0.5}'
    )
    decision = parse_post_task_response(raw, min_confidence=0.7)
    assert decision.action == "none"
    assert decision.confidence == pytest.approx(0.5)
    assert decision.parsed is True


def test_parse_malformed_json_sets_parsed_false() -> None:
    decision = parse_post_task_response("not json", min_confidence=0.7)
    assert decision.action == "none"
    assert decision.parsed is False
    assert decision.confidence == 0.0


def test_parse_update_intent_deferred_to_none() -> None:
    raw = (
        '{"action":"update_skill","skill_name":"github","rationale":"improve","confidence":0.95}'
    )
    decision = parse_post_task_response(raw, min_confidence=0.7)
    assert decision.action == "none"
    assert decision.rationale == "update deferred to GEPA"


def test_parse_low_confidence_becomes_none() -> None:
    raw = (
        '{"action":"create_skill","skill_name":"k8s-deploy","rationale":"maybe",'
        '"confidence":0.5}'
    )
    decision = parse_post_task_response(raw, min_confidence=0.7)
    assert decision.action == "none"
    assert decision.rationale == "maybe"


def test_parse_invalid_skill_name_becomes_none() -> None:
    raw = (
        '{"action":"create_skill","skill_name":"Has Spaces","rationale":"bad",'
        '"confidence":0.9}'
    )
    decision = parse_post_task_response(raw, min_confidence=0.7)
    assert decision.action == "none"


def test_parse_empty_content_sets_parsed_false() -> None:
    decision = parse_post_task_response(None, min_confidence=0.7)
    assert decision.action == "none"
    assert decision.parsed is False


def test_format_tool_calls_for_prompt() -> None:
    text = format_tool_calls_for_prompt(_trace().tool_calls)
    assert "1. read_file [ok]" in text
    assert "kubectl apply" in text


def test_decide_returns_create_skill(tmp_path: Path) -> None:
    async def _run() -> PostTaskDecision:
        provider = MagicMock(spec=LLMProvider)
        provider.chat_with_retry = AsyncMock(
            return_value=LLMResponse(
                content=(
                    '{"action":"create_skill","skill_name":"k8s-deploy","rationale":"repeatable",'
                    '"confidence":0.88}'
                ),
                finish_reason="stop",
            )
        )
        evolver = PostTaskEvolver(
            tmp_path,
            EvolutionConfig(enable=True, post_task=EvolutionPostTaskConfig(min_confidence=0.7)),
            provider=provider,
            llm_timeout_s=5.0,
        )
        return await evolver.decide(_trace())

    decision = asyncio.run(_run())

    assert decision.action == "create_skill"
    assert decision.skill_name == "k8s-deploy"


def test_decide_passes_prompt_and_llm_options(tmp_path: Path) -> None:
    async def _run() -> MagicMock:
        provider = MagicMock(spec=LLMProvider)
        provider.chat_with_retry = AsyncMock(
            return_value=LLMResponse(
                content='{"action":"none","confidence":0.0}',
                finish_reason="stop",
            )
        )
        evolver = PostTaskEvolver(tmp_path, EvolutionConfig(enable=True), provider=provider)
        await evolver.decide(_trace())
        return provider

    provider = asyncio.run(_run())
    provider.chat_with_retry.assert_awaited_once()
    call_kwargs = provider.chat_with_retry.await_args.kwargs
    assert call_kwargs["temperature"] == 0
    assert call_kwargs["max_tokens"] == 2048
    user_content = call_kwargs["messages"][1]["content"]
    assert "deploy nginx to k8s" in user_content
    assert "github" in user_content


def test_decide_timeout_fail_open(tmp_path: Path) -> None:
    async def slow_chat(**_kwargs: object) -> LLMResponse:
        await asyncio.sleep(0.2)
        return LLMResponse(content="{}", finish_reason="stop")

    async def _run() -> PostTaskDecision:
        provider = MagicMock(spec=LLMProvider)
        provider.chat_with_retry = slow_chat
        evolver = PostTaskEvolver(
            tmp_path,
            EvolutionConfig(enable=True),
            provider=provider,
            llm_timeout_s=0.05,
        )
        return await evolver.decide(_trace())

    decision = asyncio.run(_run())
    assert decision == PostTaskDecision.none()


def test_decide_provider_error_fail_open(tmp_path: Path) -> None:
    async def _run() -> PostTaskDecision:
        provider = MagicMock(spec=LLMProvider)
        provider.chat_with_retry = AsyncMock(
            return_value=LLMResponse(content="provider down", finish_reason="error")
        )
        evolver = PostTaskEvolver(tmp_path, EvolutionConfig(enable=True), provider=provider)
        return await evolver.decide(_trace())

    decision = asyncio.run(_run())
    assert decision == PostTaskDecision.none()


def test_decide_without_provider_returns_none(tmp_path: Path) -> None:
    async def _run() -> PostTaskDecision:
        evolver = PostTaskEvolver(tmp_path, EvolutionConfig(enable=True))
        return await evolver.decide(_trace())

    decision = asyncio.run(_run())
    assert decision == PostTaskDecision.none()


def test_resolve_post_task_provider_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    fallback = MagicMock(spec=LLMProvider)
    cfg = EvolutionConfig(enable=True, post_task=EvolutionPostTaskConfig(model=None))

    assert resolve_post_task_provider({}, cfg, fallback) is fallback

    cfg_with_model = EvolutionConfig(
        enable=True,
        post_task=EvolutionPostTaskConfig(model="gpt-4o-mini"),
    )

    def fake_make_provider(_config: object, *, model: str) -> LLMProvider:
        assert model == "gpt-4o-mini"
        return MagicMock(spec=LLMProvider)

    monkeypatch.setattr("nanobot.providers.factory.make_provider", fake_make_provider)
    assert resolve_post_task_provider({}, cfg_with_model, fallback) is not fallback
