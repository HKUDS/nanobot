import asyncio
import copy

import pytest

from nanobot.config.schema import Config
from nanobot.providers import factory
from nanobot.providers.base import GenerationSettings, LLMProvider, LLMResponse
from nanobot.providers.fallback_provider import FallbackProvider


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
async def test_chat_with_retry_emits_terminal_progress_when_standard_retries_exhaust(monkeypatch) -> None:
    provider = ScriptedProvider([
        LLMResponse(content="429 rate limit a", finish_reason="error"),
        LLMResponse(content="429 rate limit b", finish_reason="error"),
        LLMResponse(content="429 rate limit c", finish_reason="error"),
        LLMResponse(content="503 final server error", finish_reason="error"),
    ])
    progress: list[str] = []

    async def _fake_sleep(delay: int) -> None:
        return None

    async def _progress(msg: str) -> None:
        progress.append(msg)

    monkeypatch.setattr("nanobot.providers.base.asyncio.sleep", _fake_sleep)

    response = await provider.chat_with_retry(
        messages=[{"role": "user", "content": "hello"}],
        on_retry_wait=_progress,
    )

    assert response.content == "503 final server error"
    assert progress[-1] == "Model request failed after 4 retries, giving up."


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

    response = await provider.chat_with_retry(messages=copy.deepcopy(_IMAGE_MSG))

    assert response.content == "ok, no image"
    assert provider.calls == 2
    msgs_on_retry = provider.last_kwargs["messages"]
    for msg in msgs_on_retry:
        content = msg.get("content")
        if isinstance(content, list):
            assert all(b.get("type") != "image_url" for b in content)
            assert any("[image: /media/test.png]" in (b.get("text") or "") for b in content)


@pytest.mark.asyncio
async def test_successful_image_retry_mutates_original_messages_in_place() -> None:
    """Successful no-image retry should update the caller's message history."""
    provider = ScriptedProvider([
        LLMResponse(content="model does not support images", finish_reason="error"),
        LLMResponse(content="ok, no image"),
    ])
    messages = copy.deepcopy(_IMAGE_MSG)

    response = await provider.chat_with_retry(messages=messages)

    assert response.content == "ok, no image"
    content = messages[0]["content"]
    assert isinstance(content, list)
    assert all(block.get("type") != "image_url" for block in content)
    assert any("[image: /media/test.png]" in (block.get("text") or "") for block in content)


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

    response = await provider.chat_with_retry(messages=copy.deepcopy(_IMAGE_MSG))

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

    response = await provider.chat_with_retry(messages=copy.deepcopy(_IMAGE_MSG_NO_META))

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


def test_extract_retry_after_from_headers_supports_retry_after_ms() -> None:
    assert LLMProvider._extract_retry_after_from_headers({"retry-after-ms": "250"}) == 0.25
    assert LLMProvider._extract_retry_after_from_headers({"Retry-After-Ms": "1000"}) == 1.0
    assert LLMProvider._extract_retry_after_from_headers(
        {"retry-after-ms": "500", "retry-after": "10"},
    ) == 0.5


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
async def test_chat_with_retry_retries_structured_status_code_without_keyword(monkeypatch) -> None:
    provider = ScriptedProvider([
        LLMResponse(
            content="request failed",
            finish_reason="error",
            error_status_code=409,
        ),
        LLMResponse(content="ok"),
    ])
    delays: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr("nanobot.providers.base.asyncio.sleep", _fake_sleep)

    response = await provider.chat_with_retry(messages=[{"role": "user", "content": "hello"}])

    assert response.content == "ok"
    assert provider.calls == 2
    assert delays == [1]


@pytest.mark.asyncio
async def test_chat_with_retry_stops_on_429_quota_exhausted(monkeypatch) -> None:
    provider = ScriptedProvider([
        LLMResponse(
            content='{"error":{"type":"insufficient_quota","code":"insufficient_quota"}}',
            finish_reason="error",
            error_status_code=429,
            error_type="insufficient_quota",
            error_code="insufficient_quota",
        ),
        LLMResponse(content="ok"),
    ])
    delays: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr("nanobot.providers.base.asyncio.sleep", _fake_sleep)

    response = await provider.chat_with_retry(messages=[{"role": "user", "content": "hello"}])

    assert response.finish_reason == "error"
    assert provider.calls == 1
    assert delays == []


@pytest.mark.asyncio
async def test_chat_with_retry_retries_429_transient_rate_limit(monkeypatch) -> None:
    provider = ScriptedProvider([
        LLMResponse(
            content='{"error":{"type":"rate_limit_exceeded","code":"rate_limit_exceeded"}}',
            finish_reason="error",
            error_status_code=429,
            error_type="rate_limit_exceeded",
            error_code="rate_limit_exceeded",
            error_retry_after_s=0.2,
        ),
        LLMResponse(content="ok"),
    ])
    delays: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr("nanobot.providers.base.asyncio.sleep", _fake_sleep)

    response = await provider.chat_with_retry(messages=[{"role": "user", "content": "hello"}])

    assert response.content == "ok"
    assert provider.calls == 2
    assert delays == [0.2]


@pytest.mark.asyncio
async def test_chat_with_retry_retries_structured_timeout_kind(monkeypatch) -> None:
    provider = ScriptedProvider([
        LLMResponse(
            content="request failed",
            finish_reason="error",
            error_kind="timeout",
        ),
        LLMResponse(content="ok"),
    ])
    delays: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr("nanobot.providers.base.asyncio.sleep", _fake_sleep)

    response = await provider.chat_with_retry(messages=[{"role": "user", "content": "hello"}])

    assert response.content == "ok"
    assert provider.calls == 2
    assert delays == [1]


@pytest.mark.asyncio
async def test_chat_with_retry_structured_should_retry_false_disables_retry(monkeypatch) -> None:
    provider = ScriptedProvider([
        LLMResponse(
            content="429 rate limit",
            finish_reason="error",
            error_should_retry=False,
        ),
    ])
    delays: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr("nanobot.providers.base.asyncio.sleep", _fake_sleep)

    response = await provider.chat_with_retry(messages=[{"role": "user", "content": "hello"}])

    assert response.finish_reason == "error"
    assert provider.calls == 1
    assert delays == []


@pytest.mark.asyncio
async def test_chat_with_retry_prefers_structured_retry_after(monkeypatch) -> None:
    provider = ScriptedProvider([
        LLMResponse(
            content="429 rate limit, retry after 99s",
            finish_reason="error",
            error_retry_after_s=0.2,
        ),
        LLMResponse(content="ok"),
    ])
    delays: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr("nanobot.providers.base.asyncio.sleep", _fake_sleep)

    response = await provider.chat_with_retry(messages=[{"role": "user", "content": "hello"}])

    assert response.content == "ok"
    assert delays == [0.2]


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


@pytest.mark.asyncio
async def test_persistent_retry_emits_terminal_progress_on_identical_error_limit(monkeypatch) -> None:
    provider = ScriptedProvider([
        *[LLMResponse(content="429 rate limit", finish_reason="error") for _ in range(10)],
    ])
    progress: list[str] = []

    async def _fake_sleep(delay: float) -> None:
        return None

    async def _progress(msg: str) -> None:
        progress.append(msg)

    monkeypatch.setattr("nanobot.providers.base.asyncio.sleep", _fake_sleep)

    response = await provider.chat_with_retry(
        messages=[{"role": "user", "content": "hello"}],
        retry_mode="persistent",
        on_retry_wait=_progress,
    )

    assert response.finish_reason == "error"
    assert progress[-1] == "Persistent retry stopped after 10 identical errors."


@pytest.mark.asyncio
async def test_chat_with_retry_normalizes_explicit_none_max_tokens() -> None:
    """Explicit max_tokens=None must fall back to generation defaults.

    Regression for #3102: callers that construct AgentRunSpec with
    max_tokens=None propagate None into chat_with_retry, which used to
    reach ``_build_kwargs`` and crash on ``max(1, None)``.
    """
    provider = ScriptedProvider([LLMResponse(content="ok")])

    response = await provider.chat_with_retry(
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=None,
        temperature=None,
    )

    assert response.content == "ok"
    # Generation settings default to 4096 / 0.7; explicit None should
    # have been replaced before reaching chat().
    assert provider.last_kwargs["max_tokens"] == 4096
    assert provider.last_kwargs["temperature"] == 0.7


@pytest.mark.asyncio
async def test_chat_with_retry_retries_zhipu_1302_rate_limit(monkeypatch) -> None:
    """ZhiPu returns code 1302 with Chinese rate-limit text instead of HTTP 429."""
    provider = ScriptedProvider([
        LLMResponse(
            content='Error: {\'code\': \'1302\', \'message\': \'您的账户已达到速率限制，请您控制请求频率\'}',
            finish_reason="error",
        ),
        LLMResponse(content="ok"),
    ])
    delays: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr("nanobot.providers.base.asyncio.sleep", _fake_sleep)

    response = await provider.chat_with_retry(messages=[{"role": "user", "content": "hello"}])

    assert response.content == "ok"
    assert provider.calls == 2
    assert delays == [1]


@pytest.mark.asyncio
async def test_chat_with_retry_retries_zhipu_1302_with_429_status(monkeypatch) -> None:
    """ZhiPu 1302 error with HTTP 429 status should also retry."""
    provider = ScriptedProvider([
        LLMResponse(
            content='Error: {\'code\': \'1302\', \'message\': \'您的账户已达到速率限制，请您控制请求频率\'}',
            finish_reason="error",
            error_status_code=429,
            error_code="1302",
        ),
        LLMResponse(content="ok"),
    ])
    delays: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr("nanobot.providers.base.asyncio.sleep", _fake_sleep)

    response = await provider.chat_with_retry(messages=[{"role": "user", "content": "hello"}])

    assert response.content == "ok"
    assert provider.calls == 2
    assert delays == [1]


@pytest.mark.asyncio
async def test_chat_stream_with_retry_normalizes_explicit_none_max_tokens() -> None:
    """chat_stream_with_retry must apply the same None-guard as chat_with_retry."""
    provider = ScriptedProvider([LLMResponse(content="ok")])

    response = await provider.chat_stream_with_retry(
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=None,
        temperature=None,
    )

    assert response.content == "ok"
    assert provider.last_kwargs["max_tokens"] == 4096
    assert provider.last_kwargs["temperature"] == 0.7


class StreamingErrorProvider(ScriptedProvider):
    async def chat_stream(self, *args, **kwargs) -> LLMResponse:
        self.calls += 1
        self.last_kwargs = kwargs
        on_content_delta = kwargs.get("on_content_delta")
        if on_content_delta:
            await on_content_delta("partial")
        return LLMResponse(content="503 upstream reset", finish_reason="error")


@pytest.mark.asyncio
async def test_fallback_provider_advances_to_next_candidate_after_transient_error(monkeypatch) -> None:
    primary = ScriptedProvider([
        LLMResponse(content="429 rate limit a", finish_reason="error"),
        LLMResponse(content="429 rate limit b", finish_reason="error"),
        LLMResponse(content="429 rate limit c", finish_reason="error"),
        LLMResponse(content="503 final server error", finish_reason="error"),
    ])
    fallback = ScriptedProvider([LLMResponse(content="ok from fallback")])
    provider = FallbackProvider([
        factory.FallbackCandidate(provider=primary, model="gpt-5.4", provider_name="openai"),
        factory.FallbackCandidate(provider=fallback, model="claude-sonnet-4-6", provider_name="anthropic"),
    ])

    async def _fake_sleep(delay: float) -> None:
        return None

    monkeypatch.setattr("nanobot.providers.base.asyncio.sleep", _fake_sleep)

    response = await provider.chat_with_retry(messages=[{"role": "user", "content": "hello"}])

    assert response.content == "ok from fallback"
    assert primary.calls == 4
    assert fallback.calls == 1
    assert primary.last_kwargs["model"] == "gpt-5.4"
    assert fallback.last_kwargs["model"] == "claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_fallback_provider_stops_on_non_transient_error() -> None:
    primary = ScriptedProvider([LLMResponse(content="401 unauthorized", finish_reason="error")])
    fallback = ScriptedProvider([LLMResponse(content="should not run")])
    provider = FallbackProvider([
        factory.FallbackCandidate(provider=primary, model="gpt-5.4", provider_name="openai"),
        factory.FallbackCandidate(provider=fallback, model="claude-sonnet-4-6", provider_name="anthropic"),
    ])

    response = await provider.chat_with_retry(messages=[{"role": "user", "content": "hello"}])

    assert response.content == "401 unauthorized"
    assert primary.calls == 1
    assert fallback.calls == 0


@pytest.mark.asyncio
async def test_fallback_provider_stream_does_not_fail_over_after_first_delta(monkeypatch) -> None:
    fallback = ScriptedProvider([LLMResponse(content="should not run")])
    provider = FallbackProvider([
        factory.FallbackCandidate(provider=StreamingErrorProvider([]), model="gpt-5.4", provider_name="openai"),
        factory.FallbackCandidate(provider=fallback, model="claude-sonnet-4-6", provider_name="anthropic"),
    ])
    deltas: list[str] = []

    async def _fake_sleep(delay: float) -> None:
        return None

    async def _on_delta(delta: str) -> None:
        deltas.append(delta)

    monkeypatch.setattr("nanobot.providers.base.asyncio.sleep", _fake_sleep)

    response = await provider.chat_stream_with_retry(
        messages=[{"role": "user", "content": "hello"}],
        on_content_delta=_on_delta,
    )

    assert response.content == "503 upstream reset"
    assert deltas == ["partial"]
    assert fallback.calls == 0


def test_config_parses_explicit_fallback_targets() -> None:
    config = Config.model_validate({
        "agents": {
            "defaults": {
                "model": "gpt-5.4",
                "fallbacks": [
                    {"model": "claude-sonnet-4-6", "provider": "anthropic"},
                    {"model": "gpt-4.1-mini"},
                ],
            },
        },
    })

    assert [target.model for target in config.agents.defaults.fallbacks] == [
        "claude-sonnet-4-6",
        "gpt-4.1-mini",
    ]
    assert [target.provider for target in config.agents.defaults.fallbacks] == [
        "anthropic",
        "auto",
    ]


def test_build_provider_wraps_primary_and_configured_fallbacks(monkeypatch) -> None:
    config = Config.model_validate({
        "agents": {
            "defaults": {
                "model": "gpt-5.4",
                "provider": "openai",
                "fallbacks": [
                    {"model": "claude-sonnet-4-6", "provider": "anthropic"},
                ],
            },
        },
    })
    created: list[tuple[str, str | None]] = []

    def _fake_build_single_provider(cfg, model, provider_override=None):
        created.append((model, provider_override))
        return ScriptedProvider([LLMResponse(content=f"ok:{model}")]), (provider_override or "auto")

    monkeypatch.setattr(factory, "build_single_provider", _fake_build_single_provider)

    provider = factory.build_provider(config)

    assert isinstance(provider, FallbackProvider)
    assert created == [
        ("gpt-5.4", "openai"),
        ("claude-sonnet-4-6", "anthropic"),
    ]
    assert [candidate.model for candidate in provider._candidates] == [
        "gpt-5.4",
        "claude-sonnet-4-6",
    ]
