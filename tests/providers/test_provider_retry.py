import asyncio

import pytest

from nanobot.providers.base import GenerationSettings, LLMProvider, LLMResponse


class ScriptedProvider(LLMProvider):
    def __init__(self, responses):
        super().__init__()
        self._responses = list(responses)
        self.calls = 0
        self.last_kwargs: dict = {}

    async def chat(self, *args, **kwargs) -> LLMResponse:
        self.calls += 1
        self.last_kwargs = kwargs
        response = self._responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    def get_default_model(self) -> str:
        return "test-model"


@pytest.mark.asyncio
async def test_chat_with_retry_retries_transient_error_then_succeeds(monkeypatch) -> None:
    provider = ScriptedProvider([
        LLMResponse(content="429 rate limit", finish_reason="error"),
        LLMResponse(content="ok"),
    ])
    delays: list[int] = []

    async def _fake_sleep(delay: int) -> None:
        delays.append(delay)

    monkeypatch.setattr("nanobot.providers.base.asyncio.sleep", _fake_sleep)

    response = await provider.chat_with_retry(messages=[{"role": "user", "content": "hello"}])

    assert response.finish_reason == "stop"
    assert response.content == "ok"
    assert provider.calls == 2
    assert delays == [1]


@pytest.mark.asyncio
async def test_chat_with_retry_does_not_retry_non_transient_error(monkeypatch) -> None:
    provider = ScriptedProvider([
        LLMResponse(content="401 unauthorized", finish_reason="error"),
    ])
    delays: list[int] = []

    async def _fake_sleep(delay: int) -> None:
        delays.append(delay)

    monkeypatch.setattr("nanobot.providers.base.asyncio.sleep", _fake_sleep)

    response = await provider.chat_with_retry(messages=[{"role": "user", "content": "hello"}])

    assert response.content == "401 unauthorized"
    assert provider.calls == 1
    assert delays == []


@pytest.mark.asyncio
async def test_chat_with_retry_returns_final_error_after_retries(monkeypatch) -> None:
    provider = ScriptedProvider([
        LLMResponse(content="429 rate limit a", finish_reason="error"),
        LLMResponse(content="429 rate limit b", finish_reason="error"),
        LLMResponse(content="429 rate limit c", finish_reason="error"),
        LLMResponse(content="503 final server error", finish_reason="error"),
    ])
    delays: list[int] = []

    async def _fake_sleep(delay: int) -> None:
        delays.append(delay)

    monkeypatch.setattr("nanobot.providers.base.asyncio.sleep", _fake_sleep)

    response = await provider.chat_with_retry(messages=[{"role": "user", "content": "hello"}])

    assert response.content == "503 final server error"
    assert provider.calls == 4
    assert delays == [1, 2, 4]


@pytest.mark.asyncio
async def test_chat_with_retry_preserves_cancelled_error() -> None:
    provider = ScriptedProvider([asyncio.CancelledError()])

    with pytest.raises(asyncio.CancelledError):
        await provider.chat_with_retry(messages=[{"role": "user", "content": "hello"}])


@pytest.mark.asyncio
async def test_chat_with_retry_uses_provider_generation_defaults() -> None:
    """When callers omit generation params, provider.generation defaults are used."""
    provider = ScriptedProvider([LLMResponse(content="ok")])
    provider.generation = GenerationSettings(temperature=0.2, max_tokens=321, reasoning_effort="high")

    await provider.chat_with_retry(messages=[{"role": "user", "content": "hello"}])

    assert provider.last_kwargs["temperature"] == 0.2
    assert provider.last_kwargs["max_tokens"] == 321
    assert provider.last_kwargs["reasoning_effort"] == "high"


@pytest.mark.asyncio
async def test_chat_with_retry_explicit_override_beats_defaults() -> None:
    """Explicit kwargs should override provider.generation defaults."""
    provider = ScriptedProvider([LLMResponse(content="ok")])
    provider.generation = GenerationSettings(temperature=0.2, max_tokens=321, reasoning_effort="high")

    await provider.chat_with_retry(
        messages=[{"role": "user", "content": "hello"}],
        temperature=0.9,
        max_tokens=9999,
        reasoning_effort="low",
    )

    assert provider.last_kwargs["temperature"] == 0.9
    assert provider.last_kwargs["max_tokens"] == 9999
    assert provider.last_kwargs["reasoning_effort"] == "low"


# ---------------------------------------------------------------------------
# Image fallback tests
# ---------------------------------------------------------------------------

_IMAGE_MSG = [
    {"role": "user", "content": [
        {"type": "text", "text": "describe this"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}, "_meta": {"path": "/media/test.png"}},
    ]},
]

_IMAGE_MSG_NO_META = [
    {"role": "user", "content": [
        {"type": "text", "text": "describe this"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
    ]},
]


@pytest.mark.asyncio
async def test_non_transient_error_with_images_retries_without_images() -> None:
    """Any non-transient error retries once with images stripped when images are present."""
    provider = ScriptedProvider([
        LLMResponse(content="API调用参数有误,请检查文档", finish_reason="error"),
        LLMResponse(content="ok, no image"),
    ])

    response = await provider.chat_with_retry(messages=_IMAGE_MSG)

    assert response.content == "ok, no image"
    assert provider.calls == 2
    msgs_on_retry = provider.last_kwargs["messages"]
    for msg in msgs_on_retry:
        content = msg.get("content")
        if isinstance(content, list):
            assert all(b.get("type") != "image_url" for b in content)
            assert any("[image: /media/test.png]" in (b.get("text") or "") for b in content)


@pytest.mark.asyncio
async def test_non_transient_error_without_images_no_retry() -> None:
    """Non-transient errors without image content are returned immediately."""
    provider = ScriptedProvider([
        LLMResponse(content="401 unauthorized", finish_reason="error"),
    ])

    response = await provider.chat_with_retry(
        messages=[{"role": "user", "content": "hello"}],
    )

    assert provider.calls == 1
    assert response.finish_reason == "error"


@pytest.mark.asyncio
async def test_image_fallback_returns_error_on_second_failure() -> None:
    """If the image-stripped retry also fails, return that error."""
    provider = ScriptedProvider([
        LLMResponse(content="some model error", finish_reason="error"),
        LLMResponse(content="still failing", finish_reason="error"),
    ])

    response = await provider.chat_with_retry(messages=_IMAGE_MSG)

    assert provider.calls == 2
    assert response.content == "still failing"
    assert response.finish_reason == "error"


@pytest.mark.asyncio
async def test_image_fallback_without_meta_uses_default_placeholder() -> None:
    """When _meta is absent, fallback placeholder is '[image omitted]'."""
    provider = ScriptedProvider([
        LLMResponse(content="error", finish_reason="error"),
        LLMResponse(content="ok"),
    ])

    response = await provider.chat_with_retry(messages=_IMAGE_MSG_NO_META)

    assert response.content == "ok"
    assert provider.calls == 2
    msgs_on_retry = provider.last_kwargs["messages"]
    for msg in msgs_on_retry:
        content = msg.get("content")
        if isinstance(content, list):
            assert any("[image omitted]" in (b.get("text") or "") for b in content)


@pytest.mark.asyncio
async def test_chat_with_retry_uses_retry_after_and_emits_wait_progress(monkeypatch) -> None:
    provider = ScriptedProvider([
        LLMResponse(content="429 rate limit, retry after 7s", finish_reason="error"),
        LLMResponse(content="ok"),
    ])
    delays: list[float] = []
    progress: list[str] = []

    async def _fake_sleep(delay: float) -> None:
        delays.append(delay)

    async def _progress(msg: str) -> None:
        progress.append(msg)

    monkeypatch.setattr("nanobot.providers.base.asyncio.sleep", _fake_sleep)

    response = await provider.chat_with_retry(
        messages=[{"role": "user", "content": "hello"}],
        on_retry_wait=_progress,
    )

    assert response.content == "ok"
    assert delays == [7.0]
    assert progress and "7s" in progress[0]


def test_extract_retry_after_supports_common_provider_formats() -> None:
    assert LLMProvider._extract_retry_after('{"error":{"retry_after":20}}') == 20.0
    assert LLMProvider._extract_retry_after("Rate limit reached, please try again in 20s") == 20.0
    assert LLMProvider._extract_retry_after("retry-after: 20") == 20.0


def test_extract_retry_after_from_headers_supports_numeric_and_http_date() -> None:
    assert LLMProvider._extract_retry_after_from_headers({"Retry-After": "20"}) == 20.0
    assert LLMProvider._extract_retry_after_from_headers({"retry-after": "20"}) == 20.0
    assert LLMProvider._extract_retry_after_from_headers(
        {"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"},
    ) == 0.1


@pytest.mark.asyncio
async def test_chat_with_retry_prefers_structured_retry_after_when_present(monkeypatch) -> None:
    provider = ScriptedProvider([
        LLMResponse(content="429 rate limit", finish_reason="error", retry_after=9.0),
        LLMResponse(content="ok"),
    ])
    delays: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr("nanobot.providers.base.asyncio.sleep", _fake_sleep)

    response = await provider.chat_with_retry(messages=[{"role": "user", "content": "hello"}])

    assert response.content == "ok"
    assert delays == [9.0]


@pytest.mark.asyncio
async def test_persistent_retry_aborts_after_ten_identical_transient_errors(monkeypatch) -> None:
    provider = ScriptedProvider([
        *[LLMResponse(content="429 rate limit", finish_reason="error") for _ in range(10)],
        LLMResponse(content="ok"),
    ])
    delays: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr("nanobot.providers.base.asyncio.sleep", _fake_sleep)

    response = await provider.chat_with_retry(
        messages=[{"role": "user", "content": "hello"}],
        retry_mode="persistent",
    )

    assert response.finish_reason == "error"
    assert response.content == "429 rate limit"
    assert provider.calls == 10
    assert delays == [1, 2, 4, 4, 4, 4, 4, 4, 4]


# ---------------------------------------------------------------------------
# Fallback provider tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_chat_with_retry_uses_fallback_on_429(monkeypatch) -> None:
    """When primary fails with 429, tries fallback before sleeping."""
    primary = ScriptedProvider([
        LLMResponse(content="429 rate limit", finish_reason="error"),
    ])
    fallback = ScriptedProvider([LLMResponse(content="ok from fallback")])
    primary.fallback_providers = [fallback]

    delays: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr("nanobot.providers.base.asyncio.sleep", _fake_sleep)

    response = await primary.chat_with_retry(messages=[{"role": "user", "content": "hello"}])

    assert response.content == "ok from fallback"
    assert primary.calls == 1
    assert fallback.calls == 1
    assert delays == []  # no sleep: fallback succeeded immediately


@pytest.mark.asyncio
async def test_chat_with_retry_fallback_uses_own_default_model(monkeypatch) -> None:
    """Fallback is called with model=None so it uses its own default, not the primary's."""
    primary = ScriptedProvider([
        LLMResponse(content="429 rate limit", finish_reason="error"),
    ])
    fallback = ScriptedProvider([LLMResponse(content="ok")])
    primary.fallback_providers = [fallback]
    monkeypatch.setattr("nanobot.providers.base.asyncio.sleep", lambda _: None)

    await primary.chat_with_retry(
        messages=[{"role": "user", "content": "hello"}],
        model="primary-model-v2",
    )

    assert fallback.last_kwargs["model"] is None


@pytest.mark.asyncio
async def test_chat_with_retry_sleeps_if_all_fallbacks_also_rate_limited(monkeypatch) -> None:
    """If every fallback is also rate-limited, falls back to the existing sleep+retry."""
    primary = ScriptedProvider([
        LLMResponse(content="429 rate limit", finish_reason="error"),
        LLMResponse(content="ok after retry"),
    ])
    fallback = ScriptedProvider([
        LLMResponse(content="429 fallback limited", finish_reason="error"),
    ])
    primary.fallback_providers = [fallback]

    delays: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr("nanobot.providers.base.asyncio.sleep", _fake_sleep)

    response = await primary.chat_with_retry(messages=[{"role": "user", "content": "hello"}])

    assert response.content == "ok after retry"
    assert primary.calls == 2
    assert fallback.calls == 1
    assert delays == [1]


@pytest.mark.asyncio
async def test_chat_with_retry_returns_fallback_non_transient_error(monkeypatch) -> None:
    """A non-transient error from a fallback is returned immediately (no further retries)."""
    primary = ScriptedProvider([
        LLMResponse(content="429 rate limit", finish_reason="error"),
    ])
    fallback = ScriptedProvider([
        LLMResponse(content="401 unauthorized", finish_reason="error"),
    ])
    primary.fallback_providers = [fallback]
    monkeypatch.setattr("nanobot.providers.base.asyncio.sleep", lambda _: None)

    response = await primary.chat_with_retry(messages=[{"role": "user", "content": "hello"}])

    assert response.content == "401 unauthorized"
    assert primary.calls == 1
    assert fallback.calls == 1


@pytest.mark.asyncio
async def test_chat_with_retry_tries_multiple_fallbacks_in_order(monkeypatch) -> None:
    """With multiple fallbacks, they are tried in order until one succeeds."""
    primary = ScriptedProvider([
        LLMResponse(content="429 rate limit", finish_reason="error"),
    ])
    fallback1 = ScriptedProvider([LLMResponse(content="429 also limited", finish_reason="error")])
    fallback2 = ScriptedProvider([LLMResponse(content="ok from fallback2")])
    primary.fallback_providers = [fallback1, fallback2]
    monkeypatch.setattr("nanobot.providers.base.asyncio.sleep", lambda _: None)

    response = await primary.chat_with_retry(messages=[{"role": "user", "content": "hello"}])

    assert response.content == "ok from fallback2"
    assert primary.calls == 1
    assert fallback1.calls == 1
    assert fallback2.calls == 1
