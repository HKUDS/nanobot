"""Tests for FallbackProvider model failover."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from loguru import logger

from nanobot.config.schema import ModelPresetConfig
from nanobot.providers.base import (
    LLMProvider,
    LLMResponse,
    ProviderCallContext,
    ProviderConversationState,
)
from nanobot.providers.conversation_state import ProviderConversationStateController
from nanobot.providers.fallback_provider import FallbackProvider
from nanobot.providers.openai_responses import resolve_compact_threshold


def _make_response(
    content: str = "ok",
    finish_reason: str = "stop",
    *,
    error_kind: str | None = None,
    error_status_code: int | None = None,
    error_type: str | None = None,
    error_code: str | None = None,
    error_should_retry: bool | None = None,
) -> LLMResponse:
    return LLMResponse(
        content=content,
        finish_reason=finish_reason,
        error_kind=error_kind,
        error_status_code=error_status_code,
        error_type=error_type,
        error_code=error_code,
        error_should_retry=error_should_retry,
    )


def _error_response(content: str = "api error") -> LLMResponse:
    return _make_response(content, finish_reason="error", error_kind="server_error")


def _retryable_error(content: str = "") -> LLMResponse:
    return _make_response(content, finish_reason="error", error_status_code=503)


def _fallback(
    model: str,
    provider: str = "custom",
    *,
    max_tokens: int = 8192,
    context_window_tokens: int = 65_536,
    temperature: float = 0.1,
    reasoning_effort: str | None = None,
) -> ModelPresetConfig:
    return ModelPresetConfig(
        model=model,
        provider=provider,
        max_tokens=max_tokens,
        context_window_tokens=context_window_tokens,
        temperature=temperature,
        reasoning_effort=reasoning_effort,
    )


class _FakeProvider(LLMProvider):
    """Fake provider for testing."""

    def __init__(
        self,
        name: str = "fake",
        response: LLMResponse | None = None,
        *,
        responses: list[LLMResponse] | None = None,
    ):
        super().__init__(provider_name=name)
        self.name = name
        self._response = response or _make_response()
        self._responses = iter(responses) if responses is not None else None
        self.chat_calls: list[dict[str, Any]] = []
        self.chat_stream_calls: list[dict[str, Any]] = []
        self.context_calls: list[ProviderCallContext | None] = []
        self.resumable = False
        self.compact = False

    def _next_response(self) -> LLMResponse:
        return next(self._responses) if self._responses is not None else self._response

    def get_default_model(self) -> str:
        return f"{self.name}/model"

    async def chat(self, **kwargs: Any) -> LLMResponse:
        self.chat_calls.append(dict(kwargs))
        return self._next_response()

    async def chat_stream(self, **kwargs: Any) -> LLMResponse:
        self.chat_stream_calls.append(dict(kwargs))
        response = self._next_response()
        on_delta = kwargs.get("on_content_delta")
        if on_delta and response.content:
            await on_delta(response.content)
        return response

    async def chat_with_context(
        self,
        provider_context: ProviderCallContext | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        self.context_calls.append(provider_context)
        return await self.chat(**kwargs)

    def can_resume_conversation_state(
        self,
        state: ProviderConversationState,
        model: str | None = None,
    ) -> bool:
        _ = state, model
        return self.resumable

    def supports_native_compaction(self, model: str | None = None) -> bool:
        _ = model
        return self.compact


# -- config-level tests --


def test_fallback_models_default_empty() -> None:
    from nanobot.config.schema import AgentDefaults

    defaults = AgentDefaults()

    assert defaults.fallback_models == []


def test_fallback_models_accept_preset_refs_and_inline_configs() -> None:
    from nanobot.config.schema import Config, InlineFallbackConfig

    config = Config.model_validate({
        "agents": {
            "defaults": {
                "fallbackModels": [
                    "deep",
                    {
                        "provider": "openai",
                        "model": "gpt-4.1",
                        "maxTokens": 4096,
                    },
                ]
            }
        },
        "modelPresets": {
            "deep": {"provider": "anthropic", "model": "claude-opus-4-7"}
        },
    })

    assert config.agents.defaults.fallback_models[0] == "deep"
    assert config.agents.defaults.fallback_models[1] == InlineFallbackConfig(
        provider="openai",
        model="gpt-4.1",
        max_tokens=4096,
    )


def test_fallback_model_preset_ref_must_exist() -> None:
    from nanobot.config.schema import Config

    with pytest.raises(ValueError, match="fallback_models.*not found"):
        Config.model_validate({
            "agents": {"defaults": {"fallbackModels": ["missing"]}},
            "modelPresets": {},
        })


def test_provider_signature_tracks_fallback_presets_and_provider_config() -> None:
    from nanobot.config.schema import Config
    from nanobot.providers.factory import provider_signature

    base = {
        "agents": {
            "defaults": {
                "modelPreset": "fast",
                "fallbackModels": ["deep"],
            }
        },
        "modelPresets": {
            "fast": {"model": "openai/gpt-4.1", "provider": "openai"},
            "deep": {"model": "anthropic/claude-sonnet-4-6", "provider": "anthropic"},
        },
        "providers": {
            "openai": {"apiKey": "primary-key"},
            "anthropic": {"apiKey": "fallback-key"},
        },
    }
    changed_fallback = {
        **base,
        "agents": {"defaults": {"modelPreset": "fast", "fallbackModels": ["backup"]}},
        "modelPresets": {
            **base["modelPresets"],
            "backup": {"model": "deepseek/deepseek-chat", "provider": "deepseek"},
        },
        "providers": {
            **base["providers"],
            "deepseek": {"apiKey": "deepseek-key"},
        },
    }
    changed_key = {
        **base,
        "providers": {
            "openai": {"apiKey": "primary-key"},
            "anthropic": {"apiKey": "new-fallback-key"},
        },
    }

    signature = provider_signature(Config.model_validate(base))

    assert signature != provider_signature(Config.model_validate(changed_fallback))
    assert signature != provider_signature(Config.model_validate(changed_key))


def test_provider_snapshot_uses_smallest_fallback_context_window() -> None:
    from nanobot.config.schema import Config
    from nanobot.providers.factory import build_provider_snapshot

    config = Config.model_validate({
        "agents": {
            "defaults": {
                "modelPreset": "fast",
                "fallbackModels": ["deep"],
            }
        },
        "modelPresets": {
            "fast": {
                "model": "openai/gpt-4.1",
                "provider": "openai",
                "contextWindowTokens": 128000,
            },
            "deep": {
                "model": "deepseek/deepseek-chat",
                "provider": "deepseek",
                "contextWindowTokens": 64000,
            },
        },
        "providers": {
            "openai": {"apiKey": "primary-key"},
            "deepseek": {"apiKey": "fallback-key"},
        },
    })

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        snapshot = build_provider_snapshot(config)

    assert snapshot.context_window_tokens == 64000
    assert isinstance(snapshot.provider, FallbackProvider)
    assert snapshot.provider._primary_context_window_tokens == 128000


def test_factory_injects_configured_identity_into_primary_and_fallback_leaves() -> None:
    from nanobot.config.schema import Config
    from nanobot.providers.factory import build_provider_snapshot

    config = Config.model_validate({
        "agents": {
            "defaults": {
                "modelPreset": "primary",
                "fallbackModels": ["backup"],
            }
        },
        "modelPresets": {
            "primary": {"model": "primary-model", "provider": "primary_edge"},
            "backup": {"model": "backup-model", "provider": "backup_edge"},
        },
        "providers": {
            "primary_edge": {
                "apiKey": "primary-key",
                "apiBase": "https://primary.example/v1",
            },
            "backup_edge": {
                "apiKey": "backup-key",
                "apiBase": "https://backup.example/v1",
            },
        },
    })

    snapshot = build_provider_snapshot(config)

    assert isinstance(snapshot.provider, FallbackProvider)
    assert snapshot.provider._primary.provider_name == "primary_edge"
    fallback = snapshot.provider._provider_factory(snapshot.provider._fallback_presets[0])
    assert fallback.provider_name == "backup_edge"


def test_inline_fallback_reasoning_effort_does_not_inherit_primary() -> None:
    from nanobot.config.schema import Config
    from nanobot.providers.factory import provider_signature

    config = Config.model_validate({
        "agents": {
            "defaults": {
                "modelPreset": "fast",
                "fallbackModels": [
                    {"provider": "openai", "model": "gpt-4.1"}
                ],
            }
        },
        "modelPresets": {
            "fast": {
                "model": "anthropic/claude-opus-4-5",
                "provider": "anthropic",
                "reasoningEffort": "high",
            }
        },
        "providers": {
            "anthropic": {"apiKey": "primary-key"},
            "openai": {"apiKey": "fallback-key"},
        },
    })

    signature = provider_signature(config)
    fallback_signatures = signature[-1]

    assert fallback_signatures[0][13] is None


# -- FallbackProvider tests --


class TestNoFallbackWhenPrimarySucceeds:
    @pytest.mark.asyncio
    async def test(self) -> None:
        primary = _FakeProvider("primary", _make_response("primary ok"))
        factory = MagicMock()
        fb = FallbackProvider(
            primary=primary,
            fallback_presets=[_fallback("fallback-a")],
            provider_factory=factory,
        )

        result = await fb.chat(messages=[{"role": "user", "content": "hi"}])
        assert result.content == "primary ok"
        assert result.finish_reason == "stop"
        factory.assert_not_called()


class TestFallbackOnPrimaryError:
    @pytest.mark.asyncio
    async def test_first_fallback_succeeds(self) -> None:
        primary = _FakeProvider("primary", _error_response())
        fallback = _FakeProvider("fallback", _make_response("fallback ok"))
        factory = MagicMock(return_value=fallback)

        fb = FallbackProvider(
            primary=primary,
            fallback_presets=[_fallback("fallback-a")],
            provider_factory=factory,
        )

        result = await fb.chat(messages=[{"role": "user", "content": "hi"}], model="primary-model")
        assert result.content == "fallback ok"
        assert result.finish_reason == "stop"
        factory.assert_called_once_with(_fallback("fallback-a"))
        assert primary.chat_calls[0]["model"] == "primary-model"
        assert fallback.chat_calls[0]["model"] == "fallback-a"

    @pytest.mark.asyncio
    async def test_primary_compaction_uses_primary_context_window(self) -> None:
        primary = _FakeProvider("primary", _make_response("primary ok"))
        primary.compact = True
        fb = FallbackProvider(
            primary=primary,
            fallback_presets=[
                _fallback("small-chat", context_window_tokens=50_000),
            ],
            provider_factory=MagicMock(),
            primary_context_window_tokens=200_000,
        )

        await fb.chat_with_context(
            messages=[{"role": "user", "content": "hi"}],
            model="gpt-5.6",
            max_tokens=10_000,
            provider_context=ProviderCallContext(
                context_window_tokens=50_000,
                session_id="webui:cache-test",
            ),
        )

        primary_context = primary.context_calls[0]
        assert primary_context is not None
        assert primary_context.context_window_tokens == 200_000
        assert primary_context.session_id == "webui:cache-test"
        assert resolve_compact_threshold(
            primary_context.context_window_tokens,
            10_000,
        ) == 180_000

    @pytest.mark.asyncio
    async def test_native_fallback_compaction_uses_its_own_context_window(self) -> None:
        primary = _FakeProvider("primary", _error_response())
        primary.compact = True
        fallback = _FakeProvider("fallback", _make_response("fallback ok"))
        fallback.compact = True
        fb = FallbackProvider(
            primary=primary,
            fallback_presets=[
                _fallback("fallback-a", context_window_tokens=120_000),
            ],
            provider_factory=MagicMock(return_value=fallback),
            primary_context_window_tokens=200_000,
        )

        result = await fb.chat_with_context(
            messages=[{"role": "user", "content": "hi"}],
            model="gpt-5.6",
            provider_context=ProviderCallContext(context_window_tokens=50_000),
        )

        assert result.content == "fallback ok"
        assert primary.context_calls == [
            ProviderCallContext(context_window_tokens=200_000)
        ]
        assert fallback.context_calls == [
            ProviderCallContext(context_window_tokens=120_000)
        ]

    @pytest.mark.asyncio
    async def test_native_fallback_gets_context_when_primary_does_not_use_it(self) -> None:
        primary = _FakeProvider("primary", _error_response())
        fallback = _FakeProvider("fallback", _make_response("fallback ok"))
        fallback.compact = True
        fb = FallbackProvider(
            primary=primary,
            fallback_presets=[
                _fallback("fallback-a", context_window_tokens=120_000),
            ],
            provider_factory=MagicMock(return_value=fallback),
            primary_context_window_tokens=200_000,
        )
        messages = [{"role": "user", "content": "hi"}]
        controller = ProviderConversationStateController(
            provider=fb,
            model="primary-model",
            messages=messages,
        )
        assert fb.supports_native_compaction("primary-model") is False
        provider_context = controller.prepare_request(
            messages,
            context_window_tokens=50_000,
        )

        assert provider_context == ProviderCallContext(
            context_window_tokens=50_000
        )
        result = await fb.chat_with_context(
            messages=messages,
            model="primary-model",
            provider_context=provider_context,
        )

        assert result.content == "fallback ok"
        assert primary.context_calls == [ProviderCallContext()]
        assert fallback.context_calls == [
            ProviderCallContext(context_window_tokens=120_000)
        ]

    @pytest.mark.asyncio
    async def test_responses_chat_fallback_responses_rebuilds_state(self) -> None:
        primary = _FakeProvider("primary", _error_response())
        primary.resumable = True
        primary.compact = True
        fallback = _FakeProvider("fallback", _make_response("fallback ok"))
        messages = [{"role": "user", "content": "hi"}]
        state = ProviderConversationState(
            kind="openai_responses",
            provider="openai:test",
            model="gpt-5.6",
            version=1,
            payload={"items": [{"type": "reasoning", "encrypted_content": "opaque"}]},
            pending_messages=list(messages),
        )
        fb = FallbackProvider(
            primary=primary,
            fallback_presets=[_fallback("fallback-a")],
            provider_factory=MagicMock(return_value=fallback),
        )
        controller = ProviderConversationStateController(
            provider=fb,
            model="gpt-5.6",
            messages=messages,
            state=state,
        )
        provider_context = controller.prepare_request(
            messages,
            context_window_tokens=200_000,
        )
        assert provider_context is not None

        result = await fb.chat_with_context(
            messages=messages,
            model="gpt-5.6",
            provider_context=provider_context,
        )

        assert result.content == "fallback ok"
        assert primary.context_calls == [provider_context]
        assert fallback.context_calls == [ProviderCallContext()]
        assert fallback.chat_calls[0]["messages"] == messages

        controller.observe_response(result, messages)
        messages.append({"role": "assistant", "content": result.content})
        assert controller.finish(messages) is None

        recovered_state = ProviderConversationState(
            kind="openai_responses",
            provider="openai:test",
            model="gpt-5.6",
            version=1,
            payload={"items": [{"type": "reasoning", "encrypted_content": "recovered"}]},
        )
        primary._response = LLMResponse(
            content="primary recovered",
            provider_state=recovered_state,
        )
        next_turn = ProviderConversationStateController(
            provider=fb,
            model="gpt-5.6",
            messages=messages,
        )
        next_context = next_turn.prepare_request(
            messages,
            context_window_tokens=200_000,
        )
        assert next_context == ProviderCallContext(context_window_tokens=200_000)

        recovered = await fb.chat_with_context(
            messages=messages,
            model="gpt-5.6",
            provider_context=next_context,
        )

        assert recovered.provider_state is recovered_state
        assert primary.context_calls[-1] == next_context
        assert primary.chat_calls[-1]["messages"] == messages

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("primary_error_kind", "primary_status", "primary_should_retry"),
        [
            ("server_error", 503, True),
            ("authentication", 401, False),
        ],
        ids=["transient", "authentication"],
    )
    async def test_final_fallback_error_uses_primary_state_disposition(
        self,
        primary_error_kind: str,
        primary_status: int,
        primary_should_retry: bool,
    ) -> None:
        primary = _FakeProvider(
            "primary",
            _make_response(
                "primary unavailable",
                finish_reason="error",
                error_kind=primary_error_kind,
                error_status_code=primary_status,
                error_should_retry=primary_should_retry,
            ),
        )
        primary.resumable = True
        fallback = _FakeProvider(
            "fallback",
            _make_response(
                "fallback invalid request",
                finish_reason="error",
                error_kind="invalid_request",
                error_status_code=400,
                error_should_retry=False,
            ),
        )
        messages = [{"role": "user", "content": "continue"}]
        state = ProviderConversationState(
            kind="openai_responses",
            provider="openai:test",
            model="gpt-5.6",
            version=1,
            payload={"items": [{"type": "reasoning", "encrypted_content": "opaque"}]},
            pending_messages=list(messages),
        )
        provider = FallbackProvider(
            primary=primary,
            fallback_presets=[_fallback("fallback-a")],
            provider_factory=MagicMock(return_value=fallback),
        )
        controller = ProviderConversationStateController(
            provider=provider,
            model="gpt-5.6",
            messages=messages,
            state=state,
        )
        provider_context = controller.prepare_request(
            messages,
            context_window_tokens=200_000,
        )
        assert provider_context is not None

        response = await provider.chat_with_context(
            messages=messages,
            model="gpt-5.6",
            provider_context=provider_context,
        )
        controller.observe_response(response, messages)

        assert response.content == "fallback invalid request"
        assert response.preserve_provider_state_on_error is True
        restored = controller.finish(messages)
        assert restored is not None
        assert restored.payload == state.payload

    @pytest.mark.asyncio
    async def test_reports_only_the_successful_fallback_model(self) -> None:
        primary = _FakeProvider("primary", _error_response())
        failed_fallback = _FakeProvider("failed", _error_response("backup overloaded"))
        successful_fallback = _FakeProvider("fallback", _make_response("fallback ok"))
        fallback_models: list[str] = []

        async def _observe(model: str) -> None:
            fallback_models.append(model)

        fb = FallbackProvider(
            primary=primary,
            fallback_presets=[
                _fallback("fallback-a", provider="backup"),
                _fallback("fallback-b", provider="backup"),
            ],
            provider_factory=MagicMock(side_effect=[failed_fallback, successful_fallback]),
            fallback_model_observer=_observe,
        )

        result = await fb.chat_with_retry(
            messages=[{"role": "user", "content": "hi"}],
            model="primary-model",
        )

        assert result.content == "fallback ok"
        assert fallback_models == ["fallback-b"]

    @pytest.mark.asyncio
    async def test_logs_primary_error_before_fallback(self) -> None:
        primary = _FakeProvider("primary", _error_response("primary overloaded"))
        fallback = _FakeProvider("fallback", _make_response("fallback ok"))
        factory = MagicMock(return_value=fallback)
        logs: list[str] = []
        sink_id = logger.add(lambda message: logs.append(str(message)), format="{message}")

        try:
            fb = FallbackProvider(
                primary=primary,
                fallback_presets=[_fallback("fallback-a")],
                provider_factory=factory,
            )
            await fb.chat(messages=[{"role": "user", "content": "hi"}], model="primary-model")
        finally:
            logger.remove(sink_id)

        assert any(
            "Primary model 'primary-model' failed: primary overloaded; trying fallback 'fallback-a'"
            in line
            for line in logs
        )


class TestNoFallbackWhenContentStreamed:
    @pytest.mark.asyncio
    async def test_non_timeout_error_skips_failover(self) -> None:
        primary = _FakeProvider("primary", _error_response())
        factory = MagicMock()
        fb = FallbackProvider(
            primary=primary,
            fallback_presets=[_fallback("fallback-a")],
            provider_factory=factory,
        )

        async def _delta(text: str) -> None:
            pass

        result = await fb.chat_stream(
            messages=[{"role": "user", "content": "hi"}],
            on_content_delta=_delta,
        )
        assert result.finish_reason == "error"
        factory.assert_not_called()


class TestFallbackOnStreamStalledAfterContent:
    @pytest.mark.asyncio
    async def test_timeout_with_streamed_content_falls_back(self) -> None:
        primary = _FakeProvider(
            "primary",
            _make_response("stream stalled", finish_reason="error", error_kind="timeout"),
        )
        fallback = _FakeProvider("fallback", _make_response("fallback ok"))
        factory = MagicMock(return_value=fallback)
        fb = FallbackProvider(
            primary=primary,
            fallback_presets=[_fallback("fallback-a")],
            provider_factory=factory,
        )

        streamed: list[str] = []
        recoveries: list[str] = []

        async def _delta(text: str) -> None:
            streamed.append(text)

        async def _recover() -> None:
            recoveries.append("recover")

        result = await fb.chat_stream(
            messages=[{"role": "user", "content": "hi"}],
            on_content_delta=_delta,
            on_stream_recover=_recover,
        )
        assert result.finish_reason == "stop"
        assert result.content == "fallback ok"
        factory.assert_called_once_with(_fallback("fallback-a"))
        assert streamed == ["stream stalled", "fallback ok"]
        assert recoveries == ["recover"]


class TestFailoverOnEmptyChoices:
    """Fallback should trigger when API returns empty choices (no error metadata)."""

    @pytest.mark.asyncio
    async def test_empty_choices_text_fallback(self) -> None:
        """_should_fallback should return True for 'API returned empty choices'."""
        from nanobot.providers.fallback_provider import FallbackProvider

        response = _make_response(
            "Error: API returned empty choices.",
            finish_reason="error",
            error_kind="empty",
        )
        # error_kind="empty" matches _FALLBACK_ERROR_KINDS via kind check
        assert FallbackProvider._should_fallback(response)

    @pytest.mark.asyncio
    async def test_empty_choices_no_error_kind_text_fallback(self) -> None:
        """_should_fallback should also match via text token when error_kind is None."""
        from nanobot.providers.fallback_provider import FallbackProvider

        response = _make_response(
            "Error: API returned empty choices.",
            finish_reason="error",
            # error_kind=None, no status — pure text matching
        )
        # "empty" token in _FALLBACK_ERROR_TOKENS matches via text fallback
        assert FallbackProvider._should_fallback(response)

    @pytest.mark.asyncio
    async def test_empty_choices_triggers_failover(self) -> None:
        """End-to-end: empty choices on primary triggers fallback."""
        primary = _FakeProvider(
            "primary",
            _make_response("Error: API returned empty choices.", finish_reason="error"),
        )
        fallback = _FakeProvider("fallback", _make_response("fallback ok"))
        factory = MagicMock(return_value=fallback)
        fb = FallbackProvider(
            primary=primary,
            fallback_presets=[_fallback("fallback-a")],
            provider_factory=factory,
        )

        result = await fb.chat(messages=[{"role": "user", "content": "hi"}])
        assert result.content == "fallback ok"
        assert result.finish_reason == "stop"
        factory.assert_called_once()


class TestFailoverOnTransientError:
    @pytest.mark.asyncio
    async def test_rate_limit(self) -> None:
        primary = _FakeProvider("primary", _error_response("rate limit exceeded"))
        fallback = _FakeProvider("fallback", _make_response("fallback ok"))
        factory = MagicMock(return_value=fallback)
        fb = FallbackProvider(
            primary=primary,
            fallback_presets=[_fallback("fallback-a")],
            provider_factory=factory,
        )

        result = await fb.chat(messages=[{"role": "user", "content": "hi"}])
        assert result.content == "fallback ok"
        assert result.finish_reason == "stop"
        factory.assert_called_once_with(_fallback("fallback-a"))


class TestRetryBeforeFailover:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("retry_mode", ["standard", "persistent"])
    async def test_primary_recovers_before_fallback(self, retry_mode: str) -> None:
        primary = _FakeProvider(
            "primary",
            responses=[_error_response("rate limited"), _make_response("primary ok")],
        )
        factory = MagicMock()
        provider = FallbackProvider(primary, [_fallback("fallback-a")], factory)

        with patch("nanobot.providers.base.asyncio.sleep", new_callable=AsyncMock):
            result = await provider.chat_with_retry(
                [{"role": "user", "content": "hi"}],
                retry_mode=retry_mode,
            )

        assert result.content == "primary ok"
        assert len(primary.chat_calls) == 2
        factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_primary_exhausts_before_fallback_without_terminal_event(self) -> None:
        primary = _FakeProvider(
            "primary",
            responses=[_retryable_error(f"attempt {attempt}") for attempt in range(4)],
        )
        fallback = _FakeProvider("fallback", _make_response("fallback ok"))
        factory = MagicMock(return_value=fallback)
        retry_events = AsyncMock()
        provider = FallbackProvider(primary, [_fallback("fallback-a")], factory)

        with patch("nanobot.providers.base.asyncio.sleep", new_callable=AsyncMock):
            result = await provider.chat_with_retry(
                [{"role": "user", "content": "hi"}],
                on_retry_wait=retry_events,
            )

        assert result.content == "fallback ok"
        assert len(primary.chat_calls) == 4
        assert not any("giving up" in call.args[0] for call in retry_events.await_args_list)
        factory.assert_called_once_with(_fallback("fallback-a"))

    @pytest.mark.asyncio
    async def test_all_candidates_exhaust_emit_one_terminal_event(self) -> None:
        primary = _FakeProvider("primary", _retryable_error("primary unavailable"))
        fallback = _FakeProvider("fallback", _retryable_error("fallback unavailable"))
        retry_events = AsyncMock()
        terminal_event = AsyncMock()
        provider = FallbackProvider(
            primary,
            [_fallback("fallback-a")],
            MagicMock(return_value=fallback),
        )

        with patch("nanobot.providers.base.asyncio.sleep", new_callable=AsyncMock):
            result = await provider.chat_with_retry(
                [{"role": "user", "content": "hi"}],
                on_retry_wait=retry_events,
                on_retry_exhausted=terminal_event,
            )

        assert result.finish_reason == "error"
        assert len(primary.chat_calls) == len(fallback.chat_calls) == 4
        assert not any("giving up" in call.args[0] for call in retry_events.await_args_list)
        terminal_event.assert_awaited_once_with(
            "Model request failed after 4 attempts, giving up."
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("factory_fails", [False, True])
    async def test_persistent_mode_repeats_the_whole_chain(
        self,
        factory_fails: bool,
    ) -> None:
        primary = _FakeProvider("primary", _retryable_error("primary unavailable"))
        fallback = _FakeProvider("fallback", _retryable_error("fallback unavailable"))
        factory = (
            MagicMock(side_effect=ValueError("missing fallback credentials"))
            if factory_fails
            else MagicMock(return_value=fallback)
        )
        terminal_event = AsyncMock()
        provider = FallbackProvider(primary, [_fallback("fallback-a")], factory)
        provider._PERSISTENT_IDENTICAL_ERROR_LIMIT = 2

        with patch("nanobot.providers.base.asyncio.sleep", new_callable=AsyncMock):
            result = await provider.chat_with_retry(
                [{"role": "user", "content": "hi"}],
                retry_mode="persistent",
                on_retry_exhausted=terminal_event,
            )

        assert result.finish_reason == "error"
        assert len(primary.chat_calls) == 8
        assert len(fallback.chat_calls) == (0 if factory_fails else 8)
        assert factory.call_count == 2
        terminal_event.assert_awaited_once_with(
            "Persistent retry stopped after 2 identical errors."
        )

    @pytest.mark.asyncio
    async def test_open_primary_circuit_remains_retryable_when_factory_fails(self) -> None:
        primary = _FakeProvider("primary")
        factory = MagicMock(side_effect=ValueError("missing fallback credentials"))
        terminal_event = AsyncMock()
        provider = FallbackProvider(primary, [_fallback("fallback-a")], factory)
        provider._primary_tripped_at = 100.0
        provider._PERSISTENT_IDENTICAL_ERROR_LIMIT = 2

        with (
            patch("nanobot.providers.fallback_provider.time.monotonic", return_value=100.0),
            patch("nanobot.providers.base.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await provider.chat_with_retry(
                [{"role": "user", "content": "hi"}],
                retry_mode="persistent",
                on_retry_exhausted=terminal_event,
            )

        assert result.error_should_retry is True
        assert result.error_retry_after_s == 60
        assert primary.chat_calls == []
        assert factory.call_count == 2
        terminal_event.assert_awaited_once_with(
            "Persistent retry stopped after 2 identical errors."
        )

    @pytest.mark.asyncio
    async def test_fallback_retries_before_trying_next_model(self) -> None:
        primary = _FakeProvider(
            "primary",
            _make_response(
                "unauthorized",
                finish_reason="error",
                error_kind="authentication",
                error_should_retry=False,
            ),
        )
        fallback_a = _FakeProvider(
            "fallback-a",
            responses=[_error_response("rate limited"), _make_response("fallback a ok")],
        )
        factory = MagicMock(side_effect=[fallback_a, _FakeProvider("fallback-b")])
        fallback_a_preset = _fallback("fallback-a")
        provider = FallbackProvider(
            primary,
            [fallback_a_preset, _fallback("fallback-b")],
            factory,
        )

        with patch("nanobot.providers.base.asyncio.sleep", new_callable=AsyncMock):
            result = await provider.chat_with_retry([{"role": "user", "content": "hi"}])

        assert result.content == "fallback a ok"
        assert len(fallback_a.chat_calls) == 2
        factory.assert_called_once_with(fallback_a_preset)

    @pytest.mark.asyncio
    async def test_stream_recovery_keeps_fallback_eligible(self) -> None:
        primary = _FakeProvider(
            "primary",
            responses=[
                _make_response("partial", finish_reason="error", error_kind="timeout"),
                *[_retryable_error() for _ in range(3)],
            ],
        )
        fallback = _FakeProvider("fallback", _make_response("fallback ok"))
        factory = MagicMock(return_value=fallback)
        streamed = AsyncMock()
        recovered = AsyncMock()
        provider = FallbackProvider(primary, [_fallback("fallback-a")], factory)

        with patch("nanobot.providers.base.asyncio.sleep", new_callable=AsyncMock):
            result = await provider.chat_stream_with_retry(
                [{"role": "user", "content": "hi"}],
                on_content_delta=streamed,
                on_stream_recover=recovered,
            )

        assert result.content == "fallback ok"
        assert len(primary.chat_stream_calls) == 4
        assert [call.args[0] for call in streamed.await_args_list] == ["partial", "fallback ok"]
        recovered.assert_awaited_once_with()
        factory.assert_called_once_with(_fallback("fallback-a"))

    @pytest.mark.asyncio
    async def test_stream_without_delta_callback_retries_before_fallback(self) -> None:
        primary = _FakeProvider(
            "primary",
            responses=[_retryable_error(f"attempt {attempt}") for attempt in range(4)],
        )
        fallback = _FakeProvider("fallback", _make_response("fallback ok"))
        factory = MagicMock(return_value=fallback)
        provider = FallbackProvider(primary, [_fallback("fallback-a")], factory)

        with patch("nanobot.providers.base.asyncio.sleep", new_callable=AsyncMock):
            result = await provider.chat_stream_with_retry(
                [{"role": "user", "content": "hi"}]
            )

        assert result.content == "fallback ok"
        assert len(primary.chat_stream_calls) == 4
        factory.assert_called_once_with(_fallback("fallback-a"))

    @pytest.mark.asyncio
    async def test_unrecovered_stream_keeps_non_timeout_fallback_blocked(self) -> None:
        primary = _FakeProvider(
            "primary",
            responses=[
                _make_response("partial", finish_reason="error", error_kind="timeout"),
                _retryable_error(),
                _retryable_error(),
                _retryable_error("last error"),
            ],
        )
        factory = MagicMock()
        streamed = AsyncMock()
        provider = FallbackProvider(primary, [_fallback("fallback-a")], factory)

        with patch("nanobot.providers.base.asyncio.sleep", new_callable=AsyncMock):
            result = await provider.chat_stream_with_retry(
                [{"role": "user", "content": "hi"}],
                on_content_delta=streamed,
            )

        assert result.content == "last error"
        streamed.assert_awaited_once_with("partial")
        factory.assert_not_called()


class TestFailoverOnArrearageError:
    @pytest.mark.asyncio
    async def test_non_retryable_quota_tries_configured_fallback(self) -> None:
        arrearage = _make_response(
            "insufficient quota",
            finish_reason="error",
            error_status_code=429,
            error_type="insufficient_quota",
            error_should_retry=False,
        )
        primary = _FakeProvider("primary", arrearage)
        fallback = _FakeProvider("fallback", _make_response("fallback ok"))
        fallback_preset = _fallback("fallback-a")
        factory = MagicMock(return_value=fallback)
        fb = FallbackProvider(
            primary=primary,
            fallback_presets=[fallback_preset],
            provider_factory=factory,
        )

        result = await fb.chat(messages=[{"role": "user", "content": "hi"}])

        assert result.content == "fallback ok"
        factory.assert_called_once_with(fallback_preset)

    @pytest.mark.asyncio
    async def test_without_fallback_presets_returns_original_error(self) -> None:
        arrearage = _make_response(
            "payment required",
            finish_reason="error",
            error_status_code=402,
            error_should_retry=False,
        )
        primary = _FakeProvider("primary", arrearage)
        factory = MagicMock()
        fb = FallbackProvider(
            primary=primary,
            fallback_presets=[],
            provider_factory=factory,
        )

        result = await fb.chat(messages=[{"role": "user", "content": "hi"}])

        assert result is arrearage
        factory.assert_not_called()


class TestFailoverOnAuthenticationError:
    @pytest.mark.parametrize(
        "authentication_error",
        [
            pytest.param(
                _make_response(
                    (
                        "Error: {'error': {'type': 'authentication_error', "
                        "'message': 'The API Key appears to be invalid or may have expired.'}}"
                    ),
                    finish_reason="error",
                    error_type="authentication_error",
                    error_should_retry=False,
                ),
                id="authentication-error-type",
            ),
            pytest.param(
                _make_response(
                    "unauthorized",
                    finish_reason="error",
                    error_status_code=401,
                    error_kind="http",
                    error_should_retry=False,
                ),
                id="http-401",
            ),
            pytest.param(
                _make_response(
                    "bad key",
                    finish_reason="error",
                    error_type="invalid_request_error",
                    error_code="invalid_api_key",
                    error_should_retry=False,
                ),
                id="invalid-api-key-code",
            ),
            pytest.param(
                _make_response(
                    "credentials have expired",
                    finish_reason="error",
                    error_should_retry=False,
                ),
                id="expired-credentials-text",
            ),
            pytest.param(
                _make_response(
                    "permission denied",
                    finish_reason="error",
                    error_status_code=403,
                    error_kind="permission",
                    error_should_retry=False,
                ),
                id="permission-error",
            ),
        ],
    )
    @pytest.mark.asyncio
    async def test_tries_configured_fallback(
        self,
        authentication_error: LLMResponse,
    ) -> None:
        primary = _FakeProvider("primary", authentication_error)
        fallback = _FakeProvider("fallback", _make_response("fallback ok"))
        fallback_preset = _fallback("fallback-a")
        factory = MagicMock(return_value=fallback)
        fb = FallbackProvider(
            primary=primary,
            fallback_presets=[fallback_preset],
            provider_factory=factory,
        )

        result = await fb.chat(messages=[{"role": "user", "content": "hi"}])

        assert result.content == "fallback ok"
        factory.assert_called_once_with(fallback_preset)


class TestNoFallbackOnNonRetryableError:
    @pytest.mark.asyncio
    async def test_bad_request(self) -> None:
        primary = _FakeProvider(
            "primary",
            _make_response(
                "invalid request",
                finish_reason="error",
                error_status_code=400,
                error_kind="invalid_request",
            ),
        )
        factory = MagicMock()
        fb = FallbackProvider(
            primary=primary,
            fallback_presets=[_fallback("fallback-a")],
            provider_factory=factory,
        )

        result = await fb.chat(messages=[{"role": "user", "content": "hi"}])

        assert result.finish_reason == "error"
        factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_content_filter_takes_precedence_over_403(self) -> None:
        primary = _FakeProvider(
            "primary",
            _make_response(
                "request blocked by content filter",
                finish_reason="error",
                error_status_code=403,
                error_kind="content_filter",
                error_should_retry=False,
            ),
        )
        factory = MagicMock()
        fb = FallbackProvider(
            primary=primary,
            fallback_presets=[_fallback("fallback-a")],
            provider_factory=factory,
        )

        result = await fb.chat(messages=[{"role": "user", "content": "hi"}])

        assert result.finish_reason == "error"
        factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_timeout(self) -> None:
        primary = _FakeProvider(
            "primary",
            _make_response("timed out", finish_reason="error", error_kind="timeout"),
        )
        fallback = _FakeProvider("fallback", _make_response("fallback ok"))
        factory = MagicMock(return_value=fallback)
        fb = FallbackProvider(
            primary=primary,
            fallback_presets=[_fallback("fallback-a")],
            provider_factory=factory,
        )

        result = await fb.chat(messages=[{"role": "user", "content": "hi"}])
        assert result.content == "fallback ok"
        assert result.finish_reason == "stop"
        factory.assert_called_once_with(_fallback("fallback-a"))


class TestFallbackTriesModelsInOrder:
    @pytest.mark.asyncio
    async def test(self) -> None:
        primary = _FakeProvider("primary", _error_response("primary fail"))
        fallback_a = _FakeProvider("a", _error_response("a fail"))
        fallback_b = _FakeProvider("b", _make_response("b ok"))
        factory = MagicMock(side_effect=[fallback_a, fallback_b])

        fb = FallbackProvider(
            primary=primary,
            fallback_presets=[_fallback("fallback-a"), _fallback("fallback-b")],
            provider_factory=factory,
        )

        result = await fb.chat(messages=[{"role": "user", "content": "hi"}])
        assert result.content == "b ok"
        assert factory.call_count == 2
        factory.assert_any_call(_fallback("fallback-a"))
        factory.assert_any_call(_fallback("fallback-b"))


class TestAllFallbacksFail:
    @pytest.mark.asyncio
    async def test(self) -> None:
        primary = _FakeProvider("primary", _error_response("primary fail"))
        fallback = _FakeProvider("fallback", _error_response("all fail"))
        factory = MagicMock(return_value=fallback)

        fb = FallbackProvider(
            primary=primary,
            fallback_presets=[_fallback("fallback-a")],
            provider_factory=factory,
        )

        result = await fb.chat(messages=[{"role": "user", "content": "hi"}])
        assert result.finish_reason == "error"
        assert "all fail" in result.content


class TestFactoryExceptionSkipsModel:
    @pytest.mark.asyncio
    async def test(self) -> None:
        primary = _FakeProvider("primary", _error_response())
        fallback_b = _FakeProvider("b", _make_response("b ok"))
        factory = MagicMock(side_effect=[ValueError("no key"), fallback_b])

        fb = FallbackProvider(
            primary=primary,
            fallback_presets=[_fallback("fallback-a"), _fallback("fallback-b")],
            provider_factory=factory,
        )

        result = await fb.chat(messages=[{"role": "user", "content": "hi"}])
        assert result.content == "b ok"
        assert factory.call_count == 2


class TestFallbackModelParameter:
    @pytest.mark.asyncio
    async def test(self) -> None:
        """Fallback calls should use the fallback model name."""
        primary = _FakeProvider("primary", _error_response())
        fallback = _FakeProvider("fallback", _make_response("ok"))
        factory = MagicMock(return_value=fallback)

        fb = FallbackProvider(
            primary=primary,
            fallback_presets=[_fallback("fallback-model")],
            provider_factory=factory,
        )

        await fb.chat(messages=[{"role": "user", "content": "hi"}], model="primary-model")
        assert fallback.chat_calls[0]["model"] == "fallback-model"

    @pytest.mark.asyncio
    async def test_uses_fallback_generation_fields(self) -> None:
        primary = _FakeProvider("primary", _error_response())
        fallback = _FakeProvider("fallback", _make_response("ok"))
        fb = FallbackProvider(
            primary=primary,
            fallback_presets=[
                _fallback(
                    "fallback-model",
                    max_tokens=1234,
                    temperature=0.4,
                    reasoning_effort=None,
                )
            ],
            provider_factory=MagicMock(return_value=fallback),
        )

        await fb.chat(
            messages=[{"role": "user", "content": "hi"}],
            model="primary-model",
            max_tokens=8192,
            temperature=0.1,
            reasoning_effort="high",
        )

        assert fallback.chat_calls[0]["model"] == "fallback-model"
        assert fallback.chat_calls[0]["max_tokens"] == 1234
        assert fallback.chat_calls[0]["temperature"] == 0.4
        assert "reasoning_effort" not in fallback.chat_calls[0]


class TestNoFallbackWhenEmptyList:
    @pytest.mark.asyncio
    async def test(self) -> None:
        primary = _FakeProvider("primary", _error_response())
        factory = MagicMock()

        fb = FallbackProvider(
            primary=primary,
            fallback_presets=[],
            provider_factory=factory,
        )

        result = await fb.chat(messages=[{"role": "user", "content": "hi"}])
        assert result.finish_reason == "error"
        factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_retry_entrypoints_delegate_to_primary(self) -> None:
        primary = _FakeProvider("primary")
        provider = FallbackProvider(primary, [], MagicMock())
        response = _make_response("primary ok")

        with (
            patch.object(
                primary, "chat_with_retry", new_callable=AsyncMock, return_value=response
            ) as chat_retry,
            patch.object(
                primary,
                "chat_stream_with_retry",
                new_callable=AsyncMock,
                return_value=response,
            ) as stream_retry,
        ):
            assert (await provider.chat_with_retry([])) is response
            assert (await provider.chat_stream_with_retry([])) is response

        chat_retry.assert_awaited_once()
        stream_retry.assert_awaited_once()


class TestChatStreamFailover:
    @pytest.mark.asyncio
    async def test_fallback_succeeds(self) -> None:
        # Use empty content so on_content_delta is not triggered on the error
        primary = _FakeProvider("primary", _error_response(""))
        fallback = _FakeProvider("fallback", _make_response("stream ok"))
        factory = MagicMock(return_value=fallback)

        fb = FallbackProvider(
            primary=primary,
            fallback_presets=[_fallback("fallback-a")],
            provider_factory=factory,
        )

        result = await fb.chat_stream(messages=[{"role": "user", "content": "hi"}])
        assert result.content == "stream ok"
        assert result.finish_reason == "stop"


class TestGetDefaultModel:
    def test(self) -> None:
        primary = _FakeProvider("primary")
        fb = FallbackProvider(
            primary=primary,
            fallback_presets=[_fallback("a")],
            provider_factory=MagicMock(),
        )
        assert fb.get_default_model() == "primary/model"


class TestCircuitBreaker:
    @pytest.mark.asyncio
    async def test_skips_primary_after_three_failures(self) -> None:
        primary = _FakeProvider("primary", _error_response())
        fallback = _FakeProvider("fallback", _make_response("fallback ok"))
        factory = MagicMock(return_value=fallback)
        fb = FallbackProvider(
            primary=primary,
            fallback_presets=[_fallback("fallback-a")],
            provider_factory=factory,
        )

        # 3 failures — primary should still be called each time
        for _ in range(3):
            result = await fb.chat(messages=[{"role": "user", "content": "hi"}])
            assert result.content == "fallback ok"

        assert len(primary.chat_calls) == 3

        # 4th call — primary circuit is open, should be skipped
        primary.chat_calls.clear()
        result = await fb.chat(messages=[{"role": "user", "content": "hi"}])
        assert result.content == "fallback ok"
        assert len(primary.chat_calls) == 0

    @pytest.mark.asyncio
    async def test_resets_on_success(self) -> None:
        primary = _FakeProvider("primary", _error_response())
        fallback = _FakeProvider("fallback", _make_response("fallback ok"))
        factory = MagicMock(return_value=fallback)
        fb = FallbackProvider(
            primary=primary,
            fallback_presets=[_fallback("fallback-a")],
            provider_factory=factory,
        )

        # 2 failures
        for _ in range(2):
            await fb.chat(messages=[{"role": "user", "content": "hi"}])

        # 3rd call: primary succeeds — circuit resets
        primary._response = _make_response("primary ok")
        result = await fb.chat(messages=[{"role": "user", "content": "hi"}])
        assert result.content == "primary ok"

        # 4th call: primary fails again — should still be called (counter reset)
        primary._response = _error_response()
        primary.chat_calls.clear()
        result = await fb.chat(messages=[{"role": "user", "content": "hi"}])
        assert result.content == "fallback ok"
        assert len(primary.chat_calls) == 1


class TestGenerationForwarded:
    def test(self) -> None:
        from nanobot.providers.base import GenerationSettings
        primary = _FakeProvider("primary")
        primary.generation = GenerationSettings(temperature=0.5, max_tokens=1024)
        fb = FallbackProvider(
            primary=primary,
            fallback_presets=[_fallback("a")],
            provider_factory=MagicMock(),
        )
        assert fb.generation.temperature == 0.5
        assert fb.generation.max_tokens == 1024
