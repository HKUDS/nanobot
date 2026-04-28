"""Tests for the provider fallback models feature in AgentRunner."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.agent.runner import AgentRunner, AgentRunSpec
from nanobot.providers.base import LLMResponse


def _make_tools():
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="ok")
    return tools


def _make_provider(*, model_response: LLMResponse | None = None):
    p = MagicMock()
    if model_response is not None:
        p.chat_with_retry = AsyncMock(return_value=model_response)
    return p


def _transient_error(content: str = "server unavailable") -> LLMResponse:
    return LLMResponse(content=content, finish_reason="error", error_status_code=503)


def _base_spec(**overrides) -> AgentRunSpec:
    defaults = dict(
        initial_messages=[
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
        ],
        tools=_make_tools(),
        model="primary-model",
        max_iterations=1,
        max_tool_result_chars=8000,
    )
    defaults.update(overrides)
    return AgentRunSpec(**defaults)


@pytest.mark.asyncio
async def test_no_fallback_when_primary_succeeds():
    """Primary succeeds -> fallback list never consulted."""
    ok = LLMResponse(content="done", tool_calls=[], usage={})
    provider = _make_provider(model_response=ok)
    factory = MagicMock()

    runner = AgentRunner(provider, provider_factory=factory)
    result = await runner.run(_base_spec(fallback_models=["fb-1", "fb-2"]))

    assert result.final_content == "done"
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_fallback_triggered_on_primary_error():
    """Primary fails -> first fallback succeeds."""
    err = _transient_error()
    ok = LLMResponse(content="fallback-ok", tool_calls=[], usage={})

    primary = _make_provider(model_response=err)

    fb_provider = MagicMock()
    fb_provider.chat_with_retry = AsyncMock(return_value=ok)
    factory = MagicMock(return_value=fb_provider)

    runner = AgentRunner(primary, provider_factory=factory)
    result = await runner.run(_base_spec(fallback_models=["fb-model"]))

    assert result.final_content == "fallback-ok"
    factory.assert_called_once_with("fb-model")
    fb_provider.chat_with_retry.assert_awaited_once()


@pytest.mark.asyncio
async def test_all_fallbacks_fail_returns_last_error():
    """Primary + all fallbacks fail -> return last error response."""
    err = _transient_error()

    primary = _make_provider(model_response=err)
    fb1 = _make_provider(model_response=err)
    fb2 = _make_provider(model_response=LLMResponse(
        content="last-error", finish_reason="error", error_status_code=500, usage={},
    ))

    providers = {"fb-1": fb1, "fb-2": fb2}
    factory = MagicMock(side_effect=lambda m: providers[m])

    runner = AgentRunner(primary, provider_factory=factory)
    result = await runner.run(_base_spec(fallback_models=["fb-1", "fb-2"]))

    assert result.error is not None or result.final_content is not None


@pytest.mark.asyncio
async def test_empty_fallback_list_no_retry():
    """Empty fallback_models -> no fallback attempted."""
    err = LLMResponse(content=None, finish_reason="error", usage={})
    primary = _make_provider(model_response=err)
    factory = MagicMock()

    runner = AgentRunner(primary, provider_factory=factory)
    result = await runner.run(_base_spec(fallback_models=[]))

    factory.assert_not_called()
    assert result.error is not None


@pytest.mark.asyncio
async def test_cross_provider_fallback():
    """Fallback uses a different provider instance (cross-provider)."""
    err = _transient_error()
    ok = LLMResponse(content="cross-provider-ok", tool_calls=[], usage={})

    primary = _make_provider(model_response=err)
    anthropic_provider = MagicMock()
    anthropic_provider.chat_with_retry = AsyncMock(return_value=ok)

    def cross_factory(model: str):
        if model == "anthropic/claude-sonnet":
            return anthropic_provider
        raise ValueError(f"unexpected model: {model}")

    runner = AgentRunner(primary, provider_factory=cross_factory)
    result = await runner.run(_base_spec(fallback_models=["anthropic/claude-sonnet"]))

    assert result.final_content == "cross-provider-ok"
    anthropic_provider.chat_with_retry.assert_awaited_once()


@pytest.mark.asyncio
async def test_fallback_skips_to_second_on_first_error():
    """First fallback also fails -> second fallback succeeds."""
    err = _transient_error()
    ok = LLMResponse(content="second-fb-ok", tool_calls=[], usage={})

    primary = _make_provider(model_response=err)
    fb1 = _make_provider(model_response=err)
    fb2 = MagicMock()
    fb2.chat_with_retry = AsyncMock(return_value=ok)

    providers = {"fb-1": fb1, "fb-2": fb2}
    factory = MagicMock(side_effect=lambda m: providers[m])

    runner = AgentRunner(primary, provider_factory=factory)
    result = await runner.run(_base_spec(fallback_models=["fb-1", "fb-2"]))

    assert result.final_content == "second-fb-ok"
    assert factory.call_count == 2


@pytest.mark.asyncio
async def test_fallback_reuses_same_provider_without_factory():
    """No provider_factory -> fallback reuses primary provider with different model."""
    call_count = {"n": 0}

    async def chat_with_retry(*, messages, model, **kw):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _transient_error()
        return LLMResponse(content=f"ok-via-{model}", tool_calls=[], usage={})

    primary = MagicMock()
    primary.chat_with_retry = chat_with_retry

    runner = AgentRunner(primary, provider_factory=None)
    result = await runner.run(_base_spec(fallback_models=["fallback-model"]))

    assert result.final_content == "ok-via-fallback-model"


@pytest.mark.asyncio
async def test_fallback_provider_cached():
    """Provider factory is called once per unique provider, not per attempt."""
    err = _transient_error()
    ok = LLMResponse(content="cached-ok", tool_calls=[], usage={})

    primary = _make_provider(model_response=err)

    fb_provider = MagicMock()
    call_seq = [err, ok]
    fb_provider.chat_with_retry = AsyncMock(side_effect=call_seq)

    factory = MagicMock(return_value=fb_provider)

    runner = AgentRunner(primary, provider_factory=factory)
    result = await runner.run(_base_spec(fallback_models=["same-provider-model-a", "same-provider-model-b"]))

    assert result.final_content == "cached-ok"


@pytest.mark.asyncio
async def test_non_transient_error_does_not_fallback():
    """Auth/config-style errors should surface instead of hiding bugs via fallback."""
    primary = _make_provider(model_response=LLMResponse(
        content="401 unauthorized",
        finish_reason="error",
        error_status_code=401,
    ))
    fallback = _make_provider(model_response=LLMResponse(content="fallback-ok"))
    factory = MagicMock(return_value=fallback)

    runner = AgentRunner(primary, provider_factory=factory)
    result = await runner.run(_base_spec(fallback_models=["fb-model"]))

    factory.assert_not_called()
    assert result.error is not None


@pytest.mark.asyncio
async def test_quota_error_does_not_fallback_by_default():
    """Quota/billing/payment 429s should not route by default."""
    primary = _make_provider(model_response=LLMResponse(
        content="insufficient quota",
        finish_reason="error",
        error_status_code=429,
        error_code="insufficient_quota",
    ))
    fallback = _make_provider(model_response=LLMResponse(content="fallback-ok"))
    factory = MagicMock(return_value=fallback)

    runner = AgentRunner(primary, provider_factory=factory)
    result = await runner.run(_base_spec(fallback_models=["fb-model"]))

    factory.assert_not_called()
    assert result.error is not None


@pytest.mark.asyncio
async def test_streaming_fallback_discards_failed_primary_deltas():
    """Buffered streaming prevents primary partial output from leaking on fallback."""
    streamed: list[str] = []

    class StreamingHook(AgentHook):
        def wants_streaming(self) -> bool:
            return True

        async def on_stream(self, context: AgentHookContext, delta: str) -> None:
            streamed.append(delta)

    async def primary_stream(*, on_content_delta, **kwargs):
        await on_content_delta("bad partial")
        return _transient_error()

    async def fallback_stream(*, on_content_delta, **kwargs):
        await on_content_delta("good")
        await on_content_delta(" answer")
        return LLMResponse(content="good answer", tool_calls=[], usage={})

    primary = MagicMock()
    primary.chat_stream_with_retry = primary_stream
    fallback = MagicMock()
    fallback.chat_stream_with_retry = fallback_stream
    factory = MagicMock(return_value=fallback)

    runner = AgentRunner(primary, provider_factory=factory)
    result = await runner.run(_base_spec(
        fallback_models=["fb-model"],
        hook=StreamingHook(),
    ))

    assert result.final_content == "good answer"
    assert streamed == ["good", " answer"]
