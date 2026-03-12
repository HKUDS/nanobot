"""Tests for nanobot.agent.observability — langfuse integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent import observability


@pytest.fixture(autouse=True)
def _reset_observability():
    """Reset module-level state before and after each test."""
    observability._client = None
    observability._enabled = False
    yield
    observability._client = None
    observability._enabled = False


class TestInitLangfuse:
    """Test init_langfuse with various config states."""

    def test_disabled_by_config(self):
        cfg = MagicMock(enabled=False, public_key="pk", secret_key="sk", host="http://h")
        observability.init_langfuse(cfg)
        assert not observability.is_enabled()
        assert observability.get_langfuse() is None

    def test_missing_public_key(self):
        cfg = MagicMock(enabled=True, public_key="", secret_key="sk", host="http://h")
        observability.init_langfuse(cfg)
        assert not observability.is_enabled()

    def test_missing_secret_key(self):
        cfg = MagicMock(enabled=True, public_key="pk", secret_key="", host="http://h")
        observability.init_langfuse(cfg)
        assert not observability.is_enabled()

    def test_import_error_graceful(self):
        """If langfuse import fails, init should not crash."""
        cfg = MagicMock(enabled=True, public_key="pk", secret_key="sk", host="http://h")
        with patch("builtins.__import__", side_effect=ImportError("no langfuse")):
            observability.init_langfuse(cfg)
        assert not observability.is_enabled()

    def test_successful_init(self):
        """When Langfuse class is importable and instantiable, module becomes enabled."""
        mock_instance = MagicMock()
        mock_lf_cls = MagicMock(return_value=mock_instance)

        cfg = MagicMock(enabled=True, public_key="pk-test", secret_key="sk-test", host="http://h")
        with patch.dict("sys.modules", {"langfuse": MagicMock(Langfuse=mock_lf_cls)}):
            observability.init_langfuse(cfg)
        assert observability.is_enabled()
        assert observability.get_langfuse() is mock_instance


class TestShutdown:
    def test_shutdown_noop_when_no_client(self):
        observability.shutdown()  # should not raise
        assert not observability.is_enabled()

    def test_shutdown_calls_flush_and_shutdown(self):
        mock_client = MagicMock()
        observability._client = mock_client
        observability._enabled = True
        observability.shutdown()
        mock_client.flush.assert_called_once()
        mock_client.shutdown.assert_called_once()
        assert not observability.is_enabled()
        assert observability.get_langfuse() is None

    def test_shutdown_swallows_exceptions(self):
        mock_client = MagicMock()
        mock_client.flush.side_effect = RuntimeError("flush fail")
        observability._client = mock_client
        observability._enabled = True
        observability.shutdown()  # should not raise
        assert not observability.is_enabled()


class TestObserveDecorator:
    def test_noop_sync_when_disabled(self):
        """When disabled, @observe returns a passthrough for sync functions."""

        @observability.observe(name="test")
        def sync_fn(x):
            return x + 1

        assert sync_fn(5) == 6

    async def test_noop_async_when_disabled(self):
        """When disabled, @observe returns a passthrough for async functions."""

        @observability.observe(name="test_async")
        async def async_fn(x):
            return x * 2

        result = await async_fn(3)
        assert result == 6


class TestUpdateCurrentSpan:
    def test_noop_when_disabled(self):
        # Should not raise
        observability.update_current_span(output="test", metadata={"k": "v"})

    def test_calls_client_when_enabled(self):
        mock_client = MagicMock()
        observability._client = mock_client
        observability._enabled = True
        observability.update_current_span(output="hello", metadata={"role": "code"})
        mock_client.update_current_span.assert_called_once_with(
            output="hello", metadata={"role": "code"}
        )

    def test_swallows_exceptions(self):
        mock_client = MagicMock()
        mock_client.update_current_span.side_effect = RuntimeError("boom")
        observability._client = mock_client
        observability._enabled = True
        # Should not raise
        observability.update_current_span(output="test")

    def test_skips_none_fields(self):
        """Only non-None kwargs are forwarded to client."""
        mock_client = MagicMock()
        observability._client = mock_client
        observability._enabled = True
        observability.update_current_span(metadata={"a": 1})
        mock_client.update_current_span.assert_called_once_with(metadata={"a": 1})


class TestScoreCurrentTrace:
    def test_noop_when_disabled(self):
        observability.score_current_trace(name="accuracy", value=0.95)  # no-op

    def test_calls_client_when_enabled(self):
        mock_client = MagicMock()
        observability._client = mock_client
        observability._enabled = True
        observability.score_current_trace(name="accuracy", value=0.9, comment="good")
        mock_client.score_current_trace.assert_called_once_with(
            name="accuracy", value=0.9, comment="good"
        )

    def test_without_comment(self):
        mock_client = MagicMock()
        observability._client = mock_client
        observability._enabled = True
        observability.score_current_trace(name="latency", value=1.5)
        mock_client.score_current_trace.assert_called_once_with(name="latency", value=1.5)

    def test_swallows_exceptions(self):
        mock_client = MagicMock()
        mock_client.score_current_trace.side_effect = RuntimeError("boom")
        observability._client = mock_client
        observability._enabled = True
        observability.score_current_trace(name="x", value=0.0)  # no raise


class TestTraceRequestContextManager:
    async def test_noop_when_disabled(self):
        async with observability.trace_request(name="test") as obs:
            assert obs is None

    async def test_yields_observation_when_enabled(self):
        mock_obs = MagicMock()
        mock_client = MagicMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_obs)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_client.start_as_current_observation.return_value = mock_cm

        observability._client = mock_client
        observability._enabled = True
        async with observability.trace_request(
            name="request", input="hello", metadata={"k": "v"}
        ) as obs:
            assert obs is mock_obs
        mock_client.start_as_current_observation.assert_called_once_with(
            name="request",
            as_type="span",
            input="hello",
            metadata={"k": "v"},
        )

    async def test_swallows_exceptions(self):
        """If start_as_current_observation raises, trace_request yields None."""
        mock_client = MagicMock()
        mock_client.start_as_current_observation.side_effect = RuntimeError("fail")
        observability._client = mock_client
        observability._enabled = True
        async with observability.trace_request(name="test") as obs:
            assert obs is None


class TestToolSpanContextManager:
    async def test_noop_when_disabled(self):
        async with observability.tool_span(name="exec") as obs:
            assert obs is None

    async def test_yields_observation_when_enabled(self):
        mock_obs = MagicMock()
        mock_client = MagicMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_obs)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_client.start_as_current_observation.return_value = mock_cm

        observability._client = mock_client
        observability._enabled = True
        async with observability.tool_span(name="exec", input={"cmd": "ls"}) as obs:
            assert obs is mock_obs
        mock_client.start_as_current_observation.assert_called_once_with(
            name="tool:exec",
            as_type="tool",
            input={"cmd": "ls"},
            metadata=None,
        )


class TestSpanContextManager:
    async def test_noop_when_disabled(self):
        async with observability.span(name="classify") as obs:
            assert obs is None

    async def test_yields_observation_when_enabled(self):
        mock_obs = MagicMock()
        mock_client = MagicMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_obs)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_client.start_as_current_observation.return_value = mock_cm

        observability._client = mock_client
        observability._enabled = True
        async with observability.span(
            name="classify", input="hi", metadata={"model": "gpt-4"}
        ) as obs:
            assert obs is mock_obs
        mock_client.start_as_current_observation.assert_called_once_with(
            name="classify",
            as_type="span",
            input="hi",
            metadata={"model": "gpt-4"},
        )


class TestFlush:
    def test_flush_noop_when_no_client(self):
        observability.flush()  # no error

    def test_flush_calls_client(self):
        mock_client = MagicMock()
        observability._client = mock_client
        observability.flush()
        mock_client.flush.assert_called_once()

    def test_flush_swallows_exceptions(self):
        mock_client = MagicMock()
        mock_client.flush.side_effect = RuntimeError("fail")
        observability._client = mock_client
        observability.flush()  # should not raise


class TestIsEnabled:
    def test_default_disabled(self):
        assert not observability.is_enabled()

    def test_enabled_when_set(self):
        observability._enabled = True
        assert observability.is_enabled()


class TestGetLangfuse:
    def test_returns_none_when_no_client(self):
        assert observability.get_langfuse() is None

    def test_returns_client_when_set(self):
        sentinel = object()
        observability._client = sentinel
        assert observability.get_langfuse() is sentinel
