"""Tests for explicit provider attempts at the AgentRunner boundary."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.runner_helpers import make_run_spec
from nanobot.agent.runner import AgentRunner
from nanobot.config.schema import AgentDefaults, ModelPresetConfig
from nanobot.providers.base import (
    LLMProvider,
    LLMResponse,
    ProviderAttempt,
    ProviderCallContext,
    ProviderConversationState,
)
from nanobot.providers.fallback_provider import FallbackProvider


def _error(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        finish_reason="error",
        error_status_code=503,
        error_kind="server_error",
        error_should_retry=True,
    )


class _AttemptProvider(LLMProvider):
    def __init__(
        self,
        name: str,
        responses: list[LLMResponse],
        *,
        resumable: bool = False,
        native_compaction: bool = False,
    ) -> None:
        super().__init__(provider_name=name)
        self._name = name
        self._responses = iter(responses)
        self._resumable = resumable
        self._native_compaction = native_compaction
        self.attempts: list[ProviderAttempt] = []
        self.message_ids: list[int] = []

    def get_default_model(self) -> str:
        return f"{self._name}-model"

    def can_resume_conversation_state(
        self,
        state: ProviderConversationState,
        model: str | None = None,
    ) -> bool:
        _ = state, model
        return self._resumable

    def supports_native_compaction(self, model: str | None = None) -> bool:
        _ = model
        return self._native_compaction

    async def chat_attempt(
        self,
        *,
        attempt: ProviderAttempt,
        provider_context: ProviderCallContext | None,
        **kwargs: Any,
    ) -> LLMResponse:
        _ = provider_context
        self.attempts.append(attempt)
        self.message_ids.append(id(kwargs["messages"]))
        return next(self._responses)

    async def chat(self, **kwargs: Any) -> LLMResponse:
        raise AssertionError("attempt-aware runner must call chat_attempt")


@pytest.mark.asyncio
async def test_retry_stays_within_attempt_and_fallback_rebuilds_from_source() -> None:
    primary = _AttemptProvider(
        "primary",
        [_error(f"primary failure {index}") for index in range(4)],
        resumable=True,
        native_compaction=True,
    )
    fallback = _AttemptProvider("fallback", [LLMResponse(content="fallback ok")])
    fallback_preset = ModelPresetConfig(
        provider="custom",
        model="fallback-model",
        context_window_tokens=65_536,
        max_tokens=1234,
        temperature=0.4,
    )
    provider = FallbackProvider(
        primary,
        [fallback_preset],
        MagicMock(return_value=fallback),
        primary_context_window_tokens=150_000,
    )
    tools = MagicMock()
    tools.get_definitions.return_value = []
    spec = make_run_spec(
        provider,
        initial_messages=[],
        tools=tools,
        model="primary-model",
        context_window_tokens=200_000,
        max_iterations=1,
        max_tool_result_chars=AgentDefaults().max_tool_result_chars,
    )
    messages = [{"role": "user", "content": "keep this source unchanged"}]
    source_snapshot = [dict(message) for message in messages]
    state = ProviderConversationState(
        kind="test",
        provider="primary",
        model="primary-model",
        version=1,
    )
    provider_context = ProviderCallContext(
        conversation_state=state,
        context_window_tokens=200_000,
        session_id="webui:test",
    )

    with patch("nanobot.providers.base.asyncio.sleep", new_callable=AsyncMock):
        response = await AgentRunner()._execute_provider_route(
            spec,
            messages,
            tools=None,
            provider_context=provider_context,
        )

    assert response.content == "fallback ok"
    assert messages == source_snapshot
    assert primary.message_ids == [id(messages)] * 4
    assert fallback.message_ids == [id(messages)]
    assert len({id(attempt) for attempt in primary.attempts}) == 1
    assert primary.attempts[0].model == "primary-model"
    assert primary.attempts[0].context_window_tokens == 150_000
    assert primary.attempts[0].continuation == "resume"
    assert primary.attempts[0].native_compaction is True
    assert primary.attempts[0].provider_context == ProviderCallContext(
        conversation_state=state,
        context_window_tokens=150_000,
        session_id="webui:test",
    )
    assert fallback.attempts[0].model == "fallback-model"
    assert fallback.attempts[0].generation.max_tokens == 1234
    assert fallback.attempts[0].generation.temperature == 0.4
    assert fallback.attempts[0].context_window_tokens == 65_536
    assert fallback.attempts[0].continuation == "rebuild"
    assert fallback.attempts[0].native_compaction is False
    assert fallback.attempts[0].provider_context == ProviderCallContext(
        session_id="webui:test",
    )


@pytest.mark.asyncio
async def test_fallback_wrapper_without_candidates_keeps_one_leaf_attempt() -> None:
    primary = _AttemptProvider("primary", [LLMResponse(content="ok")])
    provider = FallbackProvider(primary, [], MagicMock())
    route = provider.create_attempt_route(
        model="primary-model",
        generation=provider.generation,
        context_window_tokens=128_000,
        provider_context=None,
        retry_mode="persistent",
    )

    attempt = await route.start()

    assert isinstance(attempt, ProviderAttempt)
    assert attempt.provider is primary
    assert attempt.retry_mode == "persistent"


@pytest.mark.asyncio
async def test_native_compaction_fallback_is_refit_from_the_same_source() -> None:
    provider = _AttemptProvider(
        "native",
        [
            LLMResponse(
                content="unsupported compaction",
                finish_reason="error",
                error_kind="native_compaction_fallback",
                error_status_code=400,
            ),
            LLMResponse(content="local fit ok"),
        ],
        native_compaction=True,
    )
    tools = MagicMock()
    tools.get_definitions.return_value = []
    spec = make_run_spec(
        provider,
        initial_messages=[],
        tools=tools,
        model="native-model",
        context_window_tokens=128_000,
        max_iterations=1,
        max_tool_result_chars=AgentDefaults().max_tool_result_chars,
    )
    messages = [{"role": "user", "content": "same source"}]

    response = await AgentRunner()._execute_provider_route(
        spec,
        messages,
        tools=None,
        provider_context=ProviderCallContext(context_window_tokens=128_000),
    )

    assert response.content == "local fit ok"
    assert provider.message_ids == [id(messages), id(messages)]
    assert [attempt.native_compaction for attempt in provider.attempts] == [True, False]
    assert provider.attempts[0] is not provider.attempts[1]


@pytest.mark.asyncio
async def test_runner_defers_terminal_retry_event_until_fallbacks_exhaust() -> None:
    primary = _AttemptProvider(
        "primary",
        [_error("primary unavailable") for _ in range(4)],
    )
    fallback = _AttemptProvider(
        "fallback",
        [_error("fallback unavailable") for _ in range(4)],
    )
    provider = FallbackProvider(
        primary,
        [ModelPresetConfig(provider="custom", model="fallback-model")],
        MagicMock(return_value=fallback),
    )
    tools = MagicMock()
    tools.get_definitions.return_value = []
    events: list[str] = []

    async def on_retry(message: str) -> None:
        events.append(message)

    spec = make_run_spec(
        provider,
        initial_messages=[],
        tools=tools,
        model="primary-model",
        max_iterations=1,
        max_tool_result_chars=AgentDefaults().max_tool_result_chars,
        retry_wait_callback=on_retry,
    )

    with patch("nanobot.providers.base.asyncio.sleep", new_callable=AsyncMock):
        response = await AgentRunner()._execute_provider_route(
            spec,
            [{"role": "user", "content": "hello"}],
            tools=None,
            provider_context=None,
        )

    assert response.finish_reason == "error"
    assert sum("giving up" in event for event in events) == 1
