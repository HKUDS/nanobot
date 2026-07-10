"""Tests for task-based per-turn model routing."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.model_routing import (
    ModelRouter,
    RoutingContext,
    TurnRoute,
    _parse_classifier_response,
    _rule_matches,
    infer_task_kind,
)
from nanobot.agent.runner import AgentRunner, AgentRunSpec
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.schema import (
    Config,
    ModelPresetConfig,
    ModelRouteMatch,
    ModelRouteRule,
    ModelRoutingConfig,
)
from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.providers.factory import ProviderSnapshot


def _provider(model: str = "test-model") -> MagicMock:
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = model
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="ok"))
    provider.chat = AsyncMock(
        return_value=LLMResponse(
            content='{"task_type":"coding","complexity":"high","reason":"debug"}',
        ),
    )
    return provider


def _snapshot(model: str, provider: MagicMock | None = None) -> ProviderSnapshot:
    return ProviderSnapshot(
        provider=provider or _provider(model),
        model=model,
        context_window_tokens=128_000,
        signature=("test", model),
    )


def _router(
    *,
    routing: ModelRoutingConfig,
    presets: dict[str, ModelPresetConfig] | None = None,
    classifier_response: str | None = None,
) -> ModelRouter:
    presets = presets or {
        "fast": ModelPresetConfig(model="fast-model", provider="auto"),
        "deep": ModelPresetConfig(model="deep-model", provider="auto"),
    }
    classifier_provider = _provider("classifier-model")
    classifier_provider.chat_with_retry = AsyncMock(
        return_value=LLMResponse(
            content=classifier_response
            or '{"task_type":"coding","complexity":"high","reason":"debug"}',
        ),
    )

    def load_preset(name: str) -> ProviderSnapshot:
        preset = presets[name if name != "default" else "fast"]
        if name == routing.classifier_preset:
            return _snapshot(preset.model, classifier_provider)
        return _snapshot(preset.model, _provider(preset.model))

    def resolve_preset(name: str) -> ModelPresetConfig:
        if name == "default":
            return presets["fast"]
        return presets[name]

    return ModelRouter(
        routing=routing,
        dream=Config().agents.defaults.dream,
        load_preset=load_preset,
        build_inline_snapshot=lambda preset: _snapshot(preset.model),
        resolve_preset=resolve_preset,
    )


def test_config_rejects_unknown_routing_preset() -> None:
    with pytest.raises(ValueError, match="model_routing"):
        Config.model_validate({
            "modelPresets": {
                "fast": {"model": "fast-model", "provider": "auto"},
            },
            "agents": {
                "defaults": {
                    "modelRouting": {
                        "enabled": True,
                        "classifierPreset": "fast",
                        "rules": [{"match": {"complexity": "low"}, "preset": "missing"}],
                    }
                }
            },
        })


def test_infer_task_kind_for_subagent_and_dream() -> None:
    assert infer_task_kind(
        session_key="cli:direct",
        session_metadata=None,
        message_metadata=None,
        explicit_task_kind="subagent",
    ) == "subagent"
    assert infer_task_kind(
        session_key="dream:20260101-120000",
        session_metadata=None,
        message_metadata=None,
    ) == "dream"
    assert infer_task_kind(
        session_key="cron:job-1",
        session_metadata=None,
        message_metadata=None,
    ) == "cron"


def test_rule_matching_precedence() -> None:
    ctx = RoutingContext(user_text="fix bug", task_kind="chat", task_type="coding", complexity="high")
    rules = [
        ModelRouteRule(match=ModelRouteMatch(complexity="low"), preset="fast"),
        ModelRouteRule(match=ModelRouteMatch(task_type="coding", complexity="high"), preset="deep"),
    ]
    assert _rule_matches(ctx, rules[0]) is False
    assert _rule_matches(ctx, rules[1]) is True


def test_parse_classifier_response_accepts_json_and_fenced_json() -> None:
    task_type, complexity = _parse_classifier_response(
        '```json\n{"task_type":"research","complexity":"medium","reason":"docs"}\n```'
    )
    assert task_type == "research"
    assert complexity == "medium"
    assert _parse_classifier_response("not json") == (None, None)


@pytest.mark.asyncio
async def test_resolve_turn_route_uses_classifier_for_chat() -> None:
    router = _router(
        routing=ModelRoutingConfig(
            enabled=True,
            classifier_preset="fast",
            rules=[
                ModelRouteRule(
                    match=ModelRouteMatch(task_type="coding", complexity="high"),
                    preset="deep",
                ),
            ],
        ),
    )
    route = await router.resolve_turn_route(
        RoutingContext(user_text="refactor the auth module", task_kind="chat"),
        baseline_model="fast-model",
        baseline_preset="fast",
    )
    assert isinstance(route, TurnRoute)
    assert route.preset_name == "deep"
    assert route.snapshot.model == "deep-model"
    assert route.task_type == "coding"
    assert route.complexity == "high"


@pytest.mark.asyncio
async def test_resolve_turn_route_skips_when_same_as_baseline() -> None:
    router = _router(
        routing=ModelRoutingConfig(
            enabled=True,
            classifier_preset="fast",
            rules=[
                ModelRouteRule(match=ModelRouteMatch(complexity="low"), preset="fast"),
            ],
        ),
        classifier_response='{"task_type":"chat","complexity":"low","reason":"hi"}',
    )
    route = await router.resolve_turn_route(
        RoutingContext(user_text="hello", task_kind="chat"),
        baseline_model="fast-model",
        baseline_preset="fast",
    )
    assert route is None


@pytest.mark.asyncio
async def test_subagent_task_kind_skips_classifier() -> None:
    classifier_provider = _provider("classifier-model")
    classifier_provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="should not run"))
    router = _router(
        routing=ModelRoutingConfig(
            enabled=True,
            classifier_preset="fast",
            rules=[ModelRouteRule(match=ModelRouteMatch(task_kind="subagent"), preset="deep")],
        ),
    )
    router._refresh_classifier_snapshot = lambda: _snapshot("classifier-model", classifier_provider)  # type: ignore[method-assign]
    route = await router.resolve_turn_route(
        RoutingContext(user_text="background task", task_kind="subagent"),
        baseline_model="fast-model",
        baseline_preset="fast",
    )
    classifier_provider.chat_with_retry.assert_not_called()
    assert route is not None
    assert route.preset_name == "deep"


@pytest.mark.asyncio
async def test_runner_uses_route_provider_without_changing_default() -> None:
    default_provider = _provider("default-model")
    routed_provider = _provider("routed-model")
    routed_provider.chat_with_retry = AsyncMock(
        return_value=LLMResponse(content="routed reply"),
    )
    default_provider.chat_with_retry = AsyncMock(
        return_value=LLMResponse(content="default reply"),
    )
    runner = AgentRunner(default_provider)
    tools = ToolRegistry()
    result = await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "hello"}],
        tools=tools,
        model="routed-model",
        max_iterations=1,
        max_tool_result_chars=1000,
        route_provider=routed_provider,
        routed_preset="deep",
    ))
    routed_provider.chat_with_retry.assert_awaited()
    default_provider.chat_with_retry.assert_not_awaited()
    assert result.final_content == "routed reply"
    assert runner.provider is default_provider
