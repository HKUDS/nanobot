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
    provider = ScriptedProvider(
        [
            LLMResponse(content="429 rate limit", finish_reason="error"),
            LLMResponse(content="ok"),
        ]
    )
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
    provider = ScriptedProvider(
        [
            LLMResponse(content="401 unauthorized", finish_reason="error"),
        ]
    )
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
    provider = ScriptedProvider(
        [
            LLMResponse(content="429 rate limit a", finish_reason="error"),
            LLMResponse(content="429 rate limit b", finish_reason="error"),
            LLMResponse(content="429 rate limit c", finish_reason="error"),
            LLMResponse(content="503 final server error", finish_reason="error"),
        ]
    )
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
    provider.generation = GenerationSettings(
        temperature=0.2, max_tokens=321, reasoning_effort="high"
    )

    await provider.chat_with_retry(messages=[{"role": "user", "content": "hello"}])

    assert provider.last_kwargs["temperature"] == 0.2
    assert provider.last_kwargs["max_tokens"] == 321
    assert provider.last_kwargs["reasoning_effort"] == "high"


@pytest.mark.asyncio
async def test_chat_with_retry_explicit_override_beats_defaults() -> None:
    """Explicit kwargs should override provider.generation defaults."""
    provider = ScriptedProvider([LLMResponse(content="ok")])
    provider.generation = GenerationSettings(
        temperature=0.2, max_tokens=321, reasoning_effort="high"
    )

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
# Image-unsupported fallback tests
# ---------------------------------------------------------------------------

_IMAGE_MSG = [
    {
        "role": "user",
        "content": [
            {"type": "text", "text": "describe this"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
        ],
    },
]


@pytest.mark.asyncio
async def test_image_unsupported_error_retries_without_images() -> None:
    """If the model rejects image_url, retry once with images stripped."""
    provider = ScriptedProvider(
        [
            LLMResponse(
                content="Invalid content type. image_url is only supported by certain models",
                finish_reason="error",
            ),
            LLMResponse(content="ok, no image"),
        ]
    )

    response = await provider.chat_with_retry(messages=_IMAGE_MSG)

    assert response.content == "ok, no image"
    assert provider.calls == 2
    msgs_on_retry = provider.last_kwargs["messages"]
    for msg in msgs_on_retry:
        content = msg.get("content")
        if isinstance(content, list):
            assert all(b.get("type") != "image_url" for b in content)
            assert any("[image omitted]" in (b.get("text") or "") for b in content)


@pytest.mark.asyncio
async def test_image_unsupported_error_no_retry_without_image_content() -> None:
    """If messages don't contain image_url blocks, don't retry on image error."""
    provider = ScriptedProvider(
        [
            LLMResponse(
                content="image_url is only supported by certain models",
                finish_reason="error",
            ),
        ]
    )

    response = await provider.chat_with_retry(
        messages=[{"role": "user", "content": "hello"}],
    )

    assert provider.calls == 1
    assert response.finish_reason == "error"


@pytest.mark.asyncio
async def test_image_unsupported_fallback_returns_error_on_second_failure() -> None:
    """If the image-stripped retry also fails, return that error."""
    provider = ScriptedProvider(
        [
            LLMResponse(
                content="does not support image input",
                finish_reason="error",
            ),
            LLMResponse(content="some other error", finish_reason="error"),
        ]
    )

    response = await provider.chat_with_retry(messages=_IMAGE_MSG)

    assert provider.calls == 2
    assert response.content == "some other error"
    assert response.finish_reason == "error"


@pytest.mark.asyncio
async def test_non_image_error_does_not_trigger_image_fallback() -> None:
    """Regular non-transient errors must not trigger image stripping."""
    provider = ScriptedProvider(
        [
            LLMResponse(content="401 unauthorized", finish_reason="error"),
        ]
    )

    response = await provider.chat_with_retry(messages=_IMAGE_MSG)

    assert provider.calls == 1
    assert response.content == "401 unauthorized"
