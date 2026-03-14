"""Tests for nanobot.agent.observability — langfuse integration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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
        mock_instance.auth_check.return_value = True
        mock_lf_cls = MagicMock(return_value=mock_instance)

        cfg = MagicMock(enabled=True, public_key="pk-test", secret_key="sk-test", host="http://h")
        with patch.dict("sys.modules", {"langfuse": MagicMock(Langfuse=mock_lf_cls)}):
            observability.init_langfuse(cfg)
        assert observability.is_enabled()
        assert observability.get_langfuse() is mock_instance

    def test_auth_check_called_on_init(self):
        """auth_check() is called after client creation."""
        mock_instance = MagicMock()
        mock_instance.auth_check.return_value = True
        mock_lf_cls = MagicMock(return_value=mock_instance)

        cfg = MagicMock(enabled=True, public_key="pk", secret_key="sk", host="http://h")
        with patch.dict("sys.modules", {"langfuse": MagicMock(Langfuse=mock_lf_cls)}):
            observability.init_langfuse(cfg)
        mock_instance.auth_check.assert_called_once()

    def test_auth_check_failure_logs_warning(self):
        """Failed auth_check does not disable Langfuse but logs a warning."""
        mock_instance = MagicMock()
        mock_instance.auth_check.return_value = False
        mock_lf_cls = MagicMock(return_value=mock_instance)

        cfg = MagicMock(enabled=True, public_key="pk", secret_key="sk", host="http://h")
        with patch.dict("sys.modules", {"langfuse": MagicMock(Langfuse=mock_lf_cls)}):
            observability.init_langfuse(cfg)
        # Should remain enabled despite failed auth check
        assert observability.is_enabled()

    def test_auth_check_exception_does_not_crash(self):
        """Exception in auth_check does not crash init."""
        mock_instance = MagicMock()
        mock_instance.auth_check.side_effect = RuntimeError("network error")
        mock_lf_cls = MagicMock(return_value=mock_instance)

        cfg = MagicMock(enabled=True, public_key="pk", secret_key="sk", host="http://h")
        with patch.dict("sys.modules", {"langfuse": MagicMock(Langfuse=mock_lf_cls)}):
            observability.init_langfuse(cfg)
        assert observability.is_enabled()

    def test_atexit_registered_on_init(self):
        """atexit.register(shutdown) is called during successful init."""
        mock_instance = MagicMock()
        mock_instance.auth_check.return_value = True
        mock_lf_cls = MagicMock(return_value=mock_instance)

        cfg = MagicMock(enabled=True, public_key="pk", secret_key="sk", host="http://h")
        with (
            patch.dict("sys.modules", {"langfuse": MagicMock(Langfuse=mock_lf_cls)}),
            patch("atexit.register") as mock_atexit,
        ):
            observability.init_langfuse(cfg)
        mock_atexit.assert_called_once_with(observability.shutdown)


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
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_obs)
        mock_cm.__exit__ = MagicMock(return_value=False)
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
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_obs)
        mock_cm.__exit__ = MagicMock(return_value=False)
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
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_obs)
        mock_cm.__exit__ = MagicMock(return_value=False)
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

    async def test_swallows_exceptions(self):
        mock_client = MagicMock()
        mock_client.start_as_current_observation.side_effect = RuntimeError("fail")
        observability._client = mock_client
        observability._enabled = True
        async with observability.span(name="test") as obs:
            assert obs is None


class TestLoggingFilters:
    """Test the logging filters installed by init_langfuse."""

    def test_proxy_filter_suppresses_message(self):
        import logging

        from nanobot.agent.observability import init_langfuse

        mock_lf_cls = MagicMock()
        cfg = MagicMock(enabled=True, public_key="pk", secret_key="sk", host="http://h")
        with patch.dict("sys.modules", {"langfuse": MagicMock(Langfuse=mock_lf_cls)}):
            init_langfuse(cfg)

        litellm_logger = logging.getLogger("LiteLLM")
        record = logging.LogRecord(
            name="LiteLLM",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg="Proxy Server is not installed. Skipping OpenTelemetry initialization.",
            args=(),
            exc_info=None,
        )
        # At least one filter should suppress this record
        assert not all(f.filter(record) for f in litellm_logger.filters)

    def test_span_ctx_filter_suppresses_message(self):
        import logging

        from nanobot.agent.observability import init_langfuse

        mock_lf_cls = MagicMock()
        cfg = MagicMock(enabled=True, public_key="pk", secret_key="sk", host="http://h")
        with patch.dict("sys.modules", {"langfuse": MagicMock(Langfuse=mock_lf_cls)}):
            init_langfuse(cfg)

        langfuse_logger = logging.getLogger("langfuse")
        record = logging.LogRecord(
            name="langfuse",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg="No active span in current context",
            args=(),
            exc_info=None,
        )
        assert not all(f.filter(record) for f in langfuse_logger.filters)

    def test_proxy_filter_passes_normal_messages(self):
        import logging

        from nanobot.agent.observability import init_langfuse

        mock_lf_cls = MagicMock()
        cfg = MagicMock(enabled=True, public_key="pk", secret_key="sk", host="http://h")
        with patch.dict("sys.modules", {"langfuse": MagicMock(Langfuse=mock_lf_cls)}):
            init_langfuse(cfg)

        litellm_logger = logging.getLogger("LiteLLM")
        record = logging.LogRecord(
            name="LiteLLM",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Normal log message",
            args=(),
            exc_info=None,
        )
        assert all(f.filter(record) for f in litellm_logger.filters)


class TestUpdateCurrentSpanAllKwargs:
    """Cover all optional kwargs paths in update_current_span."""

    def test_all_kwargs(self):
        mock_client = MagicMock()
        observability._client = mock_client
        observability._enabled = True
        observability.update_current_span(
            input="in", output="out", metadata={"k": "v"}, name="step", level="WARNING"
        )
        mock_client.update_current_span.assert_called_once_with(
            input="in", output="out", metadata={"k": "v"}, name="step", level="WARNING"
        )

    def test_empty_kwargs_no_call(self):
        mock_client = MagicMock()
        observability._client = mock_client
        observability._enabled = True
        observability.update_current_span()
        mock_client.update_current_span.assert_not_called()


class TestObserveDecoratorWhenEnabled:
    """Cover the observe() path when _enabled is True."""

    def test_observe_delegates_to_langfuse(self):
        observability._enabled = True
        mock_lf_observe = MagicMock(return_value=lambda f: f)

        with patch.dict(
            "sys.modules",
            {"langfuse": MagicMock(observe=mock_lf_observe)},
        ):
            observability.observe(name="test_op", as_type="span")

        mock_lf_observe.assert_called_once_with(
            name="test_op", as_type="span", capture_input=None, capture_output=None
        )


class TestToolSpanException:
    async def test_tool_span_swallows_exceptions(self):
        mock_client = MagicMock()
        mock_client.start_as_current_observation.side_effect = RuntimeError("fail")
        observability._client = mock_client
        observability._enabled = True
        async with observability.tool_span(name="broken") as obs:
            assert obs is None


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


class TestEndedSpanFilter:
    """Test the _EndedSpanFilter for opentelemetry.sdk.trace logger."""

    def test_suppresses_ended_span_message(self):
        import logging

        mock_lf_cls = MagicMock()
        cfg = MagicMock(enabled=True, public_key="pk", secret_key="sk", host="http://h")
        with patch.dict("sys.modules", {"langfuse": MagicMock(Langfuse=mock_lf_cls)}):
            observability.init_langfuse(cfg)

        otel_logger = logging.getLogger("opentelemetry.sdk.trace")
        record = logging.LogRecord(
            name="opentelemetry.sdk.trace",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg="Tried to set_status on an ended span",
            args=(),
            exc_info=None,
        )
        assert not all(f.filter(record) for f in otel_logger.filters)

    def test_suppresses_ended_span_attribute_message(self):
        import logging

        mock_lf_cls = MagicMock()
        cfg = MagicMock(enabled=True, public_key="pk", secret_key="sk", host="http://h")
        with patch.dict("sys.modules", {"langfuse": MagicMock(Langfuse=mock_lf_cls)}):
            observability.init_langfuse(cfg)

        otel_logger = logging.getLogger("opentelemetry.sdk.trace")
        record = logging.LogRecord(
            name="opentelemetry.sdk.trace",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg="Setting attribute on ended span",
            args=(),
            exc_info=None,
        )
        assert not all(f.filter(record) for f in otel_logger.filters)

    def test_passes_normal_otel_messages(self):
        import logging

        mock_lf_cls = MagicMock()
        cfg = MagicMock(enabled=True, public_key="pk", secret_key="sk", host="http://h")
        with patch.dict("sys.modules", {"langfuse": MagicMock(Langfuse=mock_lf_cls)}):
            observability.init_langfuse(cfg)

        otel_logger = logging.getLogger("opentelemetry.sdk.trace")
        record = logging.LogRecord(
            name="opentelemetry.sdk.trace",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Span started successfully",
            args=(),
            exc_info=None,
        )
        assert all(f.filter(record) for f in otel_logger.filters)


class TestTraceRequestPropagateAttributes:
    """trace_request forwards session_id/user_id/tags to propagate_attributes."""

    async def test_propagate_called_with_session_and_user(self):
        mock_obs = MagicMock()
        mock_client = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_obs)
        mock_cm.__exit__ = MagicMock(return_value=False)
        mock_client.start_as_current_observation.return_value = mock_cm

        observability._client = mock_client
        observability._enabled = True

        mock_propagate_cm = MagicMock()
        mock_propagate_cm.__enter__ = MagicMock(return_value=None)
        mock_propagate_cm.__exit__ = MagicMock(return_value=False)
        mock_propagate = MagicMock(return_value=mock_propagate_cm)

        # propagate_attributes is imported locally inside trace_request as:
        # from langfuse import propagate_attributes as _propagate
        # We need to patch it in the langfuse module so the local import picks it up.
        import langfuse

        with patch.object(langfuse, "propagate_attributes", mock_propagate):
            async with observability.trace_request(
                name="request",
                session_id="sess-123",
                user_id="user-456",
                tags=["web"],
            ) as obs:
                assert obs is mock_obs

        mock_propagate.assert_called_once_with(
            session_id="sess-123",
            user_id="user-456",
            trace_name="request",
            tags=["web"],
        )

    async def test_propagate_not_called_without_session_or_user(self):
        """When neither session_id nor user_id is provided, propagate_attributes is skipped."""
        mock_obs = MagicMock()
        mock_client = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_obs)
        mock_cm.__exit__ = MagicMock(return_value=False)
        mock_client.start_as_current_observation.return_value = mock_cm

        observability._client = mock_client
        observability._enabled = True

        import langfuse

        with patch.object(langfuse, "propagate_attributes") as mock_propagate:
            async with observability.trace_request(
                name="request",
            ) as obs:
                assert obs is mock_obs

            mock_propagate.assert_not_called()


class TestLitellmCallbackWiring:
    """init_langfuse appends 'otel' to litellm callbacks and sets env vars."""

    def test_otel_added_to_litellm_callbacks(self):
        mock_lf_cls = MagicMock()
        cfg = MagicMock(enabled=True, public_key="pk", secret_key="sk", host="http://h")

        mock_litellm = MagicMock()
        mock_litellm.success_callback = []
        mock_litellm.failure_callback = []

        mock_otel_cls = MagicMock()

        with (
            patch.dict(
                "sys.modules",
                {
                    "langfuse": MagicMock(Langfuse=mock_lf_cls),
                    "litellm": mock_litellm,
                    "litellm.integrations": MagicMock(),
                    "litellm.integrations.opentelemetry": MagicMock(OpenTelemetry=mock_otel_cls),
                },
            ),
        ):
            observability.init_langfuse(cfg)

        assert "otel" in mock_litellm.success_callback
        assert "otel" in mock_litellm.failure_callback

    def test_otel_not_duplicated_if_already_present(self):
        mock_lf_cls = MagicMock()
        cfg = MagicMock(enabled=True, public_key="pk", secret_key="sk", host="http://h")

        mock_litellm = MagicMock()
        mock_litellm.success_callback = ["otel"]
        mock_litellm.failure_callback = ["otel"]

        mock_otel_cls = MagicMock()

        with (
            patch.dict(
                "sys.modules",
                {
                    "langfuse": MagicMock(Langfuse=mock_lf_cls),
                    "litellm": mock_litellm,
                    "litellm.integrations": MagicMock(),
                    "litellm.integrations.opentelemetry": MagicMock(OpenTelemetry=mock_otel_cls),
                },
            ),
        ):
            observability.init_langfuse(cfg)

        assert mock_litellm.success_callback.count("otel") == 1
        assert mock_litellm.failure_callback.count("otel") == 1

    def test_env_vars_set(self):
        mock_lf_cls = MagicMock()
        cfg = MagicMock(enabled=True, public_key="pk", secret_key="sk", host="http://h")

        mock_otel_cls = MagicMock()

        import os

        # Remove env vars if they exist so setdefault takes effect
        env_backup = {}
        for key in ("OTEL_SERVICE_NAME", "USE_OTEL_LITELLM_REQUEST_SPAN"):
            env_backup[key] = os.environ.pop(key, None)

        try:
            with patch.dict(
                "sys.modules",
                {
                    "langfuse": MagicMock(Langfuse=mock_lf_cls),
                    "litellm": MagicMock(success_callback=[], failure_callback=[]),
                    "litellm.integrations": MagicMock(),
                    "litellm.integrations.opentelemetry": MagicMock(OpenTelemetry=mock_otel_cls),
                },
            ):
                observability.init_langfuse(cfg)

            assert os.environ.get("OTEL_SERVICE_NAME") == "nanobot"
            assert os.environ.get("USE_OTEL_LITELLM_REQUEST_SPAN") == "true"
        finally:
            # Restore env vars
            for key, val in env_backup.items():
                if val is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = val


class TestMonkeyPatchRawRequest:
    """init_langfuse monkey-patches _maybe_log_raw_request to a no-op."""

    def test_maybe_log_raw_request_patched(self):
        mock_lf_cls = MagicMock()
        cfg = MagicMock(enabled=True, public_key="pk", secret_key="sk", host="http://h")

        original_method = MagicMock()
        mock_otel_cls = MagicMock()
        mock_otel_cls._maybe_log_raw_request = original_method

        with patch.dict(
            "sys.modules",
            {
                "langfuse": MagicMock(Langfuse=mock_lf_cls),
                "litellm": MagicMock(success_callback=[], failure_callback=[]),
                "litellm.integrations": MagicMock(),
                "litellm.integrations.opentelemetry": MagicMock(OpenTelemetry=mock_otel_cls),
            },
        ):
            observability.init_langfuse(cfg)

        # The method should have been replaced with a no-op lambda
        assert mock_otel_cls._maybe_log_raw_request is not original_method
        # Calling it should be a no-op (returns None)
        result = mock_otel_cls._maybe_log_raw_request(None, "arg1", key="val")
        assert result is None
