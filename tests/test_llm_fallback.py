"""Tests for LLM fallback chain on retriable errors."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.providers.base import LLMProvider, LLMResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeProvider(LLMProvider):
    """Provider that returns pre-configured responses per model."""

    def __init__(self, responses: dict[str, LLMResponse]):
        super().__init__()
        self._responses = responses
        self.calls: list[str] = []  # track which models were called

    async def chat(self, messages, tools=None, model=None, max_tokens=4096, temperature=0.7):
        model = model or "primary"
        self.calls.append(model)
        return self._responses.get(model, LLMResponse(content="unknown model", finish_reason="error"))

    def get_default_model(self):
        return "primary"


def _ok_response(text: str = "OK") -> LLMResponse:
    return LLMResponse(content=text, finish_reason="stop")


def _retriable_error(msg: str = "503 Service Unavailable") -> LLMResponse:
    return LLMResponse(content=f"Error calling LLM: {msg}", finish_reason="retriable_error")


def _fatal_error(msg: str = "401 Unauthorized") -> LLMResponse:
    return LLMResponse(content=f"Error calling LLM: {msg}", finish_reason="error")


def _make_agent_loop(provider, fallbacks=None, tmp_path=None):
    """Create a minimal AgentLoop for testing."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    workspace = tmp_path or Path("/tmp/test-workspace")
    workspace.mkdir(parents=True, exist_ok=True)
    bus = MessageBus()

    return AgentLoop(
        bus=bus,
        provider=provider,
        workspace=workspace,
        model="primary",
        fallbacks=fallbacks or [],
        max_iterations=5,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCallWithFallback:
    """Tests for AgentLoop._call_with_fallback."""

    @pytest.mark.asyncio
    async def test_primary_succeeds_no_fallback_tried(self, tmp_path):
        """When primary model succeeds, no fallback should be attempted."""
        provider = FakeProvider({"primary": _ok_response("hello")})
        agent = _make_agent_loop(provider, fallbacks=["fallback-1"], tmp_path=tmp_path)

        resp = await agent._call_with_fallback([{"role": "user", "content": "hi"}])

        assert resp.content == "hello"
        assert resp.finish_reason == "stop"
        assert provider.calls == ["primary"]

    @pytest.mark.asyncio
    async def test_primary_fails_fallback_succeeds(self, tmp_path):
        """When primary returns retriable error, first working fallback should be used."""
        provider = FakeProvider({
            "primary": _retriable_error(),
            "fallback-1": _ok_response("from fallback"),
        })
        agent = _make_agent_loop(provider, fallbacks=["fallback-1"], tmp_path=tmp_path)

        resp = await agent._call_with_fallback([{"role": "user", "content": "hi"}])

        assert resp.content == "from fallback"
        assert resp.finish_reason == "stop"
        assert provider.calls == ["primary", "fallback-1"]

    @pytest.mark.asyncio
    async def test_primary_and_first_fallback_fail_second_succeeds(self, tmp_path):
        """Should try fallbacks in order until one succeeds."""
        provider = FakeProvider({
            "primary": _retriable_error(),
            "fallback-1": _retriable_error("also down"),
            "fallback-2": _ok_response("third time's the charm"),
        })
        agent = _make_agent_loop(
            provider, fallbacks=["fallback-1", "fallback-2"], tmp_path=tmp_path
        )

        resp = await agent._call_with_fallback([{"role": "user", "content": "hi"}])

        assert resp.content == "third time's the charm"
        assert provider.calls == ["primary", "fallback-1", "fallback-2"]

    @pytest.mark.asyncio
    async def test_all_models_fail_returns_primary_error(self, tmp_path):
        """When all models fail, should return the primary error."""
        provider = FakeProvider({
            "primary": _retriable_error("primary down"),
            "fallback-1": _retriable_error("fallback down"),
        })
        agent = _make_agent_loop(provider, fallbacks=["fallback-1"], tmp_path=tmp_path)

        resp = await agent._call_with_fallback([{"role": "user", "content": "hi"}])

        assert "primary down" in resp.content
        assert resp.finish_reason == "error"
        assert provider.calls == ["primary", "fallback-1"]

    @pytest.mark.asyncio
    async def test_non_retriable_error_no_fallback(self, tmp_path):
        """Non-retriable errors (auth, bad request) should NOT trigger fallback."""
        provider = FakeProvider({
            "primary": _fatal_error("401 Unauthorized"),
            "fallback-1": _ok_response("should not reach"),
        })
        agent = _make_agent_loop(provider, fallbacks=["fallback-1"], tmp_path=tmp_path)

        resp = await agent._call_with_fallback([{"role": "user", "content": "hi"}])

        assert "401 Unauthorized" in resp.content
        assert resp.finish_reason == "error"
        assert provider.calls == ["primary"]  # fallback NOT tried

    @pytest.mark.asyncio
    async def test_no_fallbacks_configured(self, tmp_path):
        """When no fallbacks configured, retriable error is returned as-is."""
        provider = FakeProvider({"primary": _retriable_error()})
        agent = _make_agent_loop(provider, fallbacks=[], tmp_path=tmp_path)

        resp = await agent._call_with_fallback([{"role": "user", "content": "hi"}])

        assert resp.finish_reason == "retriable_error"
        assert provider.calls == ["primary"]


class TestLiteLLMProviderRetriableErrors:
    """Tests for retriable vs non-retriable error classification in LiteLLMProvider."""

    @pytest.mark.asyncio
    async def test_timeout_is_retriable(self):
        """litellm.Timeout should produce retriable_error finish_reason."""
        import litellm
        from nanobot.providers.litellm_provider import LiteLLMProvider

        provider = LiteLLMProvider(api_key="test-key", default_model="test/model")
        with patch("nanobot.providers.litellm_provider.acompletion") as mock:
            mock.side_effect = litellm.Timeout(
                message="Connection timed out",
                model="test/model",
                llm_provider="test",
            )
            resp = await provider.chat([{"role": "user", "content": "hi"}])

        assert resp.finish_reason == "retriable_error"
        assert "timed out" in resp.content.lower() or "Timeout" in resp.content

    @pytest.mark.asyncio
    async def test_service_unavailable_is_retriable(self):
        """litellm.ServiceUnavailableError should produce retriable_error."""
        import litellm
        from nanobot.providers.litellm_provider import LiteLLMProvider

        provider = LiteLLMProvider(api_key="test-key", default_model="test/model")
        with patch("nanobot.providers.litellm_provider.acompletion") as mock:
            mock.side_effect = litellm.ServiceUnavailableError(
                message="503 Service Unavailable",
                model="test/model",
                llm_provider="test",
            )
            resp = await provider.chat([{"role": "user", "content": "hi"}])

        assert resp.finish_reason == "retriable_error"

    @pytest.mark.asyncio
    async def test_auth_error_is_not_retriable(self):
        """litellm.AuthenticationError should produce regular error, not retriable."""
        import litellm
        from nanobot.providers.litellm_provider import LiteLLMProvider

        provider = LiteLLMProvider(api_key="test-key", default_model="test/model")
        with patch("nanobot.providers.litellm_provider.acompletion") as mock:
            mock.side_effect = litellm.AuthenticationError(
                message="Invalid API key",
                model="test/model",
                llm_provider="test",
            )
            resp = await provider.chat([{"role": "user", "content": "hi"}])

        assert resp.finish_reason == "error"


class TestSchemaFallbacks:
    """Tests for fallbacks field in AgentDefaults."""

    def test_default_fallbacks_empty(self):
        from nanobot.config.schema import AgentDefaults
        defaults = AgentDefaults()
        assert defaults.fallbacks == []

    def test_fallbacks_from_config(self):
        from nanobot.config.schema import AgentDefaults
        defaults = AgentDefaults(fallbacks=["model-a", "model-b"])
        assert defaults.fallbacks == ["model-a", "model-b"]
