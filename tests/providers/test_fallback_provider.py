"""Tests for FallbackProvider with circuit breaker."""
import asyncio

import pytest

from nanobot.providers.base import LLMProvider, LLMResponse


class ScriptedProvider(LLMProvider):
    """Provider that returns pre-scripted responses in order."""

    def __init__(self, responses, default_model="test-primary"):
        super().__init__()
        self._responses = list(responses)
        self._default_model = default_model
        self.calls = 0
        self.call_log: list[dict] = []

    async def chat(self, **kwargs) -> LLMResponse:
        self.calls += 1
        self.call_log.append(kwargs)
        if not self._responses:
            return LLMResponse(content="no more responses", finish_reason="error")
        resp = self._responses.pop(0)
        if isinstance(resp, BaseException):
            raise resp
        return resp

    async def chat_stream(self, **kwargs) -> LLMResponse:
        kwargs.pop("on_content_delta", None)
        return await self.chat(**kwargs)

    def get_default_model(self) -> str:
        return self._default_model


def _ok(content="ok"):
    return LLMResponse(content=content)


def _transient(msg="529 overloaded"):
    return LLMResponse(content=f"Error calling LLM: {msg}", finish_reason="error")


def _non_transient(msg="401 unauthorized"):
    return LLMResponse(content=msg, finish_reason="error")


@pytest.mark.asyncio
async def test_primary_succeeds_no_fallback():
    from nanobot.providers.fallback import FallbackProvider

    primary = ScriptedProvider([_ok("primary ok")])
    fb = ScriptedProvider([_ok("should not reach")])
    provider = FallbackProvider(primary, [(fb, "fb-model")])

    resp = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert resp.content == "primary ok"
    assert primary.calls == 1
    assert fb.calls == 0


@pytest.mark.asyncio
async def test_primary_transient_falls_to_first_fallback():
    from nanobot.providers.fallback import FallbackProvider

    primary = ScriptedProvider([_transient()])
    fb = ScriptedProvider([_ok("fallback ok")])
    provider = FallbackProvider(primary, [(fb, "fb-model")])

    resp = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert resp.content == "fallback ok"
    assert primary.calls == 1
    assert fb.calls == 1


@pytest.mark.asyncio
async def test_non_transient_error_not_fallback():
    from nanobot.providers.fallback import FallbackProvider

    primary = ScriptedProvider([_non_transient()])
    fb = ScriptedProvider([_ok("should not reach")])
    provider = FallbackProvider(primary, [(fb, "fb-model")])

    resp = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert resp.content == "401 unauthorized"
    assert fb.calls == 0


@pytest.mark.asyncio
async def test_chain_fallback_first_also_fails():
    from nanobot.providers.fallback import FallbackProvider

    primary = ScriptedProvider([_transient("primary overloaded")])
    fb1 = ScriptedProvider([_transient("fb1 503 server error")])
    fb2 = ScriptedProvider([_ok("fb2 ok")])
    provider = FallbackProvider(primary, [(fb1, "fb1-model"), (fb2, "fb2-model")])

    resp = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert resp.content == "fb2 ok"
    assert primary.calls == 1
    assert fb1.calls == 1
    assert fb2.calls == 1


@pytest.mark.asyncio
async def test_all_fail_returns_last_error():
    from nanobot.providers.fallback import FallbackProvider

    primary = ScriptedProvider([_transient("primary overloaded")])
    fb = ScriptedProvider([_transient("fb 503 server error")])
    provider = FallbackProvider(primary, [(fb, "fb-model")])

    resp = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert resp.finish_reason == "error"
    assert "fb 503 server error" in resp.content


@pytest.mark.asyncio
async def test_circuit_breaker_skips_primary_during_cooldown():
    from nanobot.providers.fallback import FallbackProvider

    primary = ScriptedProvider([_transient(), _ok("primary recovered")])
    fb = ScriptedProvider([_ok("fb first"), _ok("fb second")])
    provider = FallbackProvider(primary, [(fb, "fb-model")], cooldown_s=60)

    # 第一次：primary 失败 → fallback
    resp1 = await provider.chat(messages=[{"role": "user", "content": "1"}])
    assert resp1.content == "fb first"
    assert primary.calls == 1

    # 第二次：cooldown 期间跳过 primary
    resp2 = await provider.chat(messages=[{"role": "user", "content": "2"}])
    assert resp2.content == "fb second"
    assert primary.calls == 1  # 没再打 primary
    assert fb.calls == 2


@pytest.mark.asyncio
async def test_circuit_breaker_retries_primary_after_cooldown():
    from nanobot.providers.fallback import FallbackProvider

    primary = ScriptedProvider([_transient(), _ok("primary back")])
    fb = ScriptedProvider([_ok("fb ok")])
    provider = FallbackProvider(primary, [(fb, "fb-model")], cooldown_s=0.1)

    resp1 = await provider.chat(messages=[{"role": "user", "content": "1"}])
    assert resp1.content == "fb ok"

    await asyncio.sleep(0.15)

    resp2 = await provider.chat(messages=[{"role": "user", "content": "2"}])
    assert resp2.content == "primary back"
    assert primary.calls == 2


@pytest.mark.asyncio
async def test_primary_recovery_resets_circuit_breaker():
    from nanobot.providers.fallback import FallbackProvider

    primary = ScriptedProvider([_transient(), _ok("recovered"), _ok("still good")])
    fb = ScriptedProvider([_ok("fb")])
    provider = FallbackProvider(primary, [(fb, "fb-model")], cooldown_s=0.05)

    await provider.chat(messages=[{"role": "user", "content": "1"}])
    await asyncio.sleep(0.1)

    resp2 = await provider.chat(messages=[{"role": "user", "content": "2"}])
    assert resp2.content == "recovered"

    resp3 = await provider.chat(messages=[{"role": "user", "content": "3"}])
    assert resp3.content == "still good"
    assert primary.calls == 3


@pytest.mark.asyncio
async def test_chat_stream_fallback():
    from nanobot.providers.fallback import FallbackProvider

    primary = ScriptedProvider([_transient()])
    fb = ScriptedProvider([_ok("stream fb ok")])
    provider = FallbackProvider(primary, [(fb, "fb-model")])

    resp = await provider.chat_stream(
        messages=[{"role": "user", "content": "hi"}],
        on_content_delta=None,
    )

    assert resp.content == "stream fb ok"


@pytest.mark.asyncio
async def test_exception_in_primary_treated_as_transient():
    from nanobot.providers.fallback import FallbackProvider

    primary = ScriptedProvider([ConnectionError("connection reset")])
    fb = ScriptedProvider([_ok("fb rescued")])
    provider = FallbackProvider(primary, [(fb, "fb-model")])

    resp = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert resp.content == "fb rescued"


@pytest.mark.asyncio
async def test_generation_settings_inherited():
    from nanobot.providers.base import GenerationSettings
    from nanobot.providers.fallback import FallbackProvider

    primary = ScriptedProvider([_ok("ok")])
    fb = ScriptedProvider([])
    provider = FallbackProvider(primary, [(fb, "fb")])
    provider.generation = GenerationSettings(temperature=0.2, max_tokens=999, reasoning_effort="high")

    await provider.chat_with_retry(messages=[{"role": "user", "content": "hi"}])

    # chat_with_retry 把 generation defaults 传给 chat()，chat() 传给 primary._safe_chat()
    assert primary.call_log[-1]["temperature"] == 0.2
    assert primary.call_log[-1]["max_tokens"] == 999
