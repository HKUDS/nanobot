"""Tests for MultiModelProvider fallback logic."""

from __future__ import annotations

from typing import Any

import pytest

from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.providers.multi_model_provider import MultiModelProvider


class ScriptedProvider(LLMProvider):
    """Provider that returns pre-scripted responses for testing."""

    def __init__(
        self,
        responses: list[LLMResponse | BaseException],
        model_name: str = "test-model",
    ):
        super().__init__()
        self._responses = list(responses)
        self._model_name = model_name
        self.calls = 0
        self.last_kwargs: dict[str, Any] = {}

    async def chat(self, *args: Any, **kwargs: Any) -> LLMResponse:
        self.calls += 1
        self.last_kwargs = kwargs
        response = self._responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    async def chat_stream(self, *args: Any, **kwargs: Any) -> LLMResponse:
        self.calls += 1
        self.last_kwargs = kwargs
        response = self._responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    def get_default_model(self) -> str:
        return self._model_name


def _make_children(
    *pairs: tuple[list[LLMResponse | BaseException], str],
) -> list[tuple[LLMProvider, str]]:
    """Helper to create (provider, model) pairs from scripted responses."""
    return [(ScriptedProvider(responses, model_name=model), model) for responses, model in pairs]


# ---------------------------------------------------------------------------
# Basic fallback tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_model_succeeds_immediately() -> None:
    children = _make_children(
        ([LLMResponse(content="success")], "gpt-4o"),
        ([LLMResponse(content="fallback")], "gpt-4-turbo"),
    )
    provider = MultiModelProvider(children=children, default_model="gpt-4o")

    response = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert response.content == "success"
    assert children[0][0].calls == 1  # type: ignore[attr-defined]
    assert children[1][0].calls == 0  # type: ignore[attr-defined]
    assert provider.active_model == "gpt-4o"


@pytest.mark.asyncio
async def test_fallback_to_second_on_transient_error() -> None:
    children = _make_children(
        ([LLMResponse(content="503 server error", finish_reason="error")], "gpt-4o"),
        ([LLMResponse(content="success from fallback")], "gpt-4-turbo"),
    )
    provider = MultiModelProvider(children=children, default_model="gpt-4o")

    response = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert response.content == "success from fallback"
    assert children[0][0].calls == 1  # type: ignore[attr-defined]
    assert children[1][0].calls == 1  # type: ignore[attr-defined]
    assert provider.active_model == "gpt-4-turbo"


@pytest.mark.asyncio
async def test_fallback_to_third_on_exception() -> None:
    children = _make_children(
        ([RuntimeError("connection refused")], "gpt-4o"),
        ([LLMResponse(content="429 rate limit", finish_reason="error")], "gpt-4-turbo"),
        ([LLMResponse(content="success")], "claude-3-opus"),
    )
    provider = MultiModelProvider(children=children, default_model="gpt-4o")

    response = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert response.content == "success"
    assert children[0][0].calls == 1  # type: ignore[attr-defined]
    assert children[1][0].calls == 1  # type: ignore[attr-defined]
    assert children[2][0].calls == 1  # type: ignore[attr-defined]
    assert provider.active_model == "claude-3-opus"


@pytest.mark.asyncio
async def test_no_fallback_on_non_transient_error() -> None:
    """Non-transient errors (e.g. auth) should not trigger fallback."""
    children = _make_children(
        ([LLMResponse(content="401 unauthorized", finish_reason="error")], "gpt-4o"),
        ([LLMResponse(content="should not reach")], "gpt-4-turbo"),
    )
    provider = MultiModelProvider(children=children, default_model="gpt-4o")

    response = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert response.content == "401 unauthorized"
    assert response.finish_reason == "error"
    assert children[0][0].calls == 1  # type: ignore[attr-defined]
    assert children[1][0].calls == 0  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_returns_last_error_when_all_fail() -> None:
    children = _make_children(
        ([LLMResponse(content="503 error A", finish_reason="error")], "gpt-4o"),
        ([LLMResponse(content="502 error B", finish_reason="error")], "gpt-4-turbo"),
        ([LLMResponse(content="500 error C", finish_reason="error")], "claude-3"),
    )
    provider = MultiModelProvider(children=children, default_model="gpt-4o")

    response = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert response.finish_reason == "error"
    assert response.content == "500 error C"


@pytest.mark.asyncio
async def test_returns_first_non_transient_error_after_transient_failures() -> None:
    """If first models fail transiently and a later one fails non-transiently,
    return the non-transient error (don't keep trying)."""
    children = _make_children(
        ([LLMResponse(content="503 transient", finish_reason="error")], "gpt-4o"),
        ([LLMResponse(content="401 auth fail", finish_reason="error")], "gpt-4-turbo"),
        ([LLMResponse(content="should not reach")], "claude-3"),
    )
    provider = MultiModelProvider(children=children, default_model="gpt-4o")

    response = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert response.content == "401 auth fail"
    assert response.finish_reason == "error"
    assert children[2][0].calls == 0  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Streaming fallback tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_stream_fallback_on_transient_error() -> None:
    children = _make_children(
        ([LLMResponse(content="timeout", finish_reason="error")], "gpt-4o"),
        ([LLMResponse(content="streamed success")], "gpt-4-turbo"),
    )
    provider = MultiModelProvider(children=children, default_model="gpt-4o")

    response = await provider.chat_stream(messages=[{"role": "user", "content": "hi"}])

    assert response.content == "streamed success"
    assert children[0][0].calls == 1  # type: ignore[attr-defined]
    assert children[1][0].calls == 1  # type: ignore[attr-defined]
    assert provider.active_model == "gpt-4-turbo"


@pytest.mark.asyncio
async def test_chat_stream_no_fallback_on_non_transient() -> None:
    children = _make_children(
        ([LLMResponse(content="quota exceeded", finish_reason="error")], "gpt-4o"),
        ([LLMResponse(content="should not reach")], "gpt-4-turbo"),
    )
    provider = MultiModelProvider(children=children, default_model="gpt-4o")

    response = await provider.chat_stream(messages=[{"role": "user", "content": "hi"}])

    assert response.finish_reason == "error"
    assert children[1][0].calls == 0  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Model parameter forwarding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_child_receives_its_own_model_string() -> None:
    children = _make_children(
        ([LLMResponse(content="ok")], "gpt-4o"),
        ([LLMResponse(content="ok")], "claude-3-opus"),
    )
    provider = MultiModelProvider(children=children, default_model="gpt-4o")

    await provider.chat(messages=[{"role": "user", "content": "hi"}])

    # The child provider should receive its own model string, not the one
    # passed to MultiModelProvider.chat()
    assert children[0][0].last_kwargs["model"] == "gpt-4o"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# get_default_model and active_model
# ---------------------------------------------------------------------------


def test_get_default_model() -> None:
    children = _make_children(
        ([LLMResponse(content="ok")], "gpt-4o"),
    )
    provider = MultiModelProvider(children=children, default_model="gpt-4o")
    assert provider.get_default_model() == "gpt-4o"


def test_active_model_defaults_to_default_model() -> None:
    children = _make_children(
        ([LLMResponse(content="ok")], "gpt-4o"),
    )
    provider = MultiModelProvider(children=children, default_model="gpt-4o")
    assert provider.active_model == "gpt-4o"


@pytest.mark.asyncio
async def test_active_model_updates_on_fallback() -> None:
    children = _make_children(
        ([LLMResponse(content="503", finish_reason="error")], "gpt-4o"),
        ([LLMResponse(content="ok")], "gpt-4-turbo"),
    )
    provider = MultiModelProvider(children=children, default_model="gpt-4o")

    await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert provider.active_model == "gpt-4-turbo"


# ---------------------------------------------------------------------------
# Config schema tests
# ---------------------------------------------------------------------------


def test_multi_model_config_defaults() -> None:
    from nanobot.config.schema import MultiModelConfig

    config = MultiModelConfig()
    assert config.enabled is False
    assert config.default_model == ""
    assert config.models == []


def test_multi_model_config_from_dict() -> None:
    from nanobot.config.schema import MultiModelConfig

    config = MultiModelConfig(
        enabled=True,
        default_model="gpt-4o",
        models=["gpt-4o", "gpt-4-turbo", "claude-3-opus"],
    )
    assert config.enabled is True
    assert config.default_model == "gpt-4o"
    assert config.models == ["gpt-4o", "gpt-4-turbo", "claude-3-opus"]


def test_multi_model_config_in_agent_defaults() -> None:
    from nanobot.config.schema import AgentDefaults

    defaults = AgentDefaults()
    assert defaults.multi_model.enabled is False
    assert defaults.multi_model.models == []


# ---------------------------------------------------------------------------
# Structured error metadata fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fallback_on_structured_transient_error() -> None:
    """Fallback should trigger when error_status_code indicates transient (5xx, 429)."""
    children = _make_children(
        (
            [
                LLMResponse(
                    content="server error",
                    finish_reason="error",
                    error_status_code=500,
                )
            ],
            "gpt-4o",
        ),
        ([LLMResponse(content="success")], "gpt-4-turbo"),
    )
    provider = MultiModelProvider(children=children, default_model="gpt-4o")

    response = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert response.content == "success"


@pytest.mark.asyncio
async def test_no_fallback_on_structured_non_transient_429() -> None:
    """429 with insufficient_quota should NOT trigger fallback."""
    children = _make_children(
        (
            [
                LLMResponse(
                    content='{"error":{"type":"insufficient_quota"}}',
                    finish_reason="error",
                    error_status_code=429,
                    error_type="insufficient_quota",
                )
            ],
            "gpt-4o",
        ),
        ([LLMResponse(content="should not reach")], "gpt-4-turbo"),
    )
    provider = MultiModelProvider(children=children, default_model="gpt-4o")

    response = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert response.finish_reason == "error"
    assert "insufficient_quota" in (response.content or "")
    assert children[1][0].calls == 0  # type: ignore[attr-defined]
