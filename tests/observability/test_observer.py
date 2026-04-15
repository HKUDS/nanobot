"""Tests for the OTel-based observability layer."""

import asyncio
from unittest.mock import patch

import pytest

from opentelemetry.trace import NoOpTracer
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult

from nanobot.providers.base import GenerationSettings, LLMProvider, LLMResponse


class _ListExporter(SpanExporter):
    """Collects spans in a list for test assertions."""
    def __init__(self):
        self.spans = []

    def export(self, spans):
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class ScriptedProvider(LLMProvider):
    def __init__(self, responses):
        super().__init__()
        self._responses = list(responses)
        self.calls = 0

    async def chat(self, *args, **kwargs) -> LLMResponse:
        self.calls += 1
        return self._responses.pop(0)

    def get_default_model(self) -> str:
        return "test-model"


def _make_test_tracer():
    """Create a tracer with list exporter for assertions."""
    exporter = _ListExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test")
    return tracer, exporter, provider


# ---------------------------------------------------------------------------
# Default tracer (NoOp)
# ---------------------------------------------------------------------------


def test_provider_default_tracer_is_noop():
    provider = ScriptedProvider([])
    assert isinstance(provider.tracer, NoOpTracer)


def test_provider_tracer_setter():
    provider = ScriptedProvider([])
    tracer, _, _ = _make_test_tracer()
    provider.tracer = tracer
    assert provider.tracer is tracer


# ---------------------------------------------------------------------------
# Tracer wiring in chat_with_retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_with_retry_creates_llm_span():
    tracer, exporter, tp = _make_test_tracer()
    provider = ScriptedProvider([LLMResponse(content="hello", usage={"prompt_tokens": 10, "completion_tokens": 5})])
    provider.tracer = tracer

    response = await provider.chat_with_retry(
        messages=[{"role": "user", "content": "hi"}], model="gpt-4",
    )

    tp.force_flush()
    spans = exporter.spans
    assert response.content == "hello"
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "llm-call"
    attrs = dict(span.attributes)
    assert attrs["gen_ai.request.model"] == "gpt-4"
    assert attrs["gen_ai.response.model"] == "gpt-4"
    assert attrs["gen_ai.usage.input_tokens"] == 10
    assert attrs["gen_ai.usage.output_tokens"] == 5
    # LangSmith-style prompt attributes
    assert attrs["gen_ai.prompt.0.role"] == "user"
    assert attrs["gen_ai.prompt.0.content"] == "hi"
    # LangSmith-style completion attributes
    assert attrs["gen_ai.completion.0.role"] == "assistant"
    assert attrs["gen_ai.completion.0.content"] == "hello"


@pytest.mark.asyncio
async def test_chat_with_retry_sets_error_status_on_non_transient_error():
    tracer, exporter, tp = _make_test_tracer()
    provider = ScriptedProvider([
        LLMResponse(content="401 unauthorized", finish_reason="error"),
    ])
    provider.tracer = tracer

    response = await provider.chat_with_retry(
        messages=[{"role": "user", "content": "hi"}],
    )

    tp.force_flush()
    spans = exporter.spans
    assert response.finish_reason == "error"
    assert len(spans) == 1
    from opentelemetry.trace import StatusCode
    assert spans[0].status.status_code == StatusCode.ERROR


@pytest.mark.asyncio
async def test_chat_with_retry_single_span_across_retries(monkeypatch):
    """Retries produce a single span, not one per attempt."""
    tracer, exporter, tp = _make_test_tracer()
    provider = ScriptedProvider([
        LLMResponse(content="429 rate limit", finish_reason="error"),
        LLMResponse(content="ok"),
    ])
    provider.tracer = tracer

    async def _fake_sleep(_):
        pass

    monkeypatch.setattr("nanobot.providers.base.asyncio.sleep", _fake_sleep)

    response = await provider.chat_with_retry(
        messages=[{"role": "user", "content": "hi"}],
    )

    tp.force_flush()
    spans = exporter.spans
    assert response.content == "ok"
    assert provider.calls == 2
    # Only ONE span
    assert len(spans) == 1
    assert spans[0].name == "llm-call"


@pytest.mark.asyncio
async def test_chat_with_retry_all_retries_exhausted(monkeypatch):
    tracer, exporter, tp = _make_test_tracer()
    provider = ScriptedProvider([
        LLMResponse(content="429 rate limit", finish_reason="error"),
        LLMResponse(content="429 rate limit", finish_reason="error"),
        LLMResponse(content="429 rate limit", finish_reason="error"),
        LLMResponse(content="503 server error", finish_reason="error"),
    ])
    provider.tracer = tracer

    async def _fake_sleep(_):
        pass

    monkeypatch.setattr("nanobot.providers.base.asyncio.sleep", _fake_sleep)

    response = await provider.chat_with_retry(
        messages=[{"role": "user", "content": "hi"}],
    )

    tp.force_flush()
    spans = exporter.spans
    assert response.finish_reason == "error"
    assert len(spans) == 1
    from opentelemetry.trace import StatusCode
    assert spans[0].status.status_code == StatusCode.ERROR


# ---------------------------------------------------------------------------
# Tracer wiring in chat_stream_with_retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_stream_with_retry_creates_llm_span():
    tracer, exporter, tp = _make_test_tracer()
    provider = ScriptedProvider([LLMResponse(content="streamed")])
    provider.tracer = tracer

    response = await provider.chat_stream_with_retry(
        messages=[{"role": "user", "content": "hi"}], model="claude-3",
    )

    tp.force_flush()
    spans = exporter.spans
    assert response.content == "streamed"
    assert len(spans) == 1
    assert spans[0].name == "llm-call"
    assert dict(spans[0].attributes)["gen_ai.request.model"] == "claude-3"


@pytest.mark.asyncio
async def test_chat_stream_with_retry_sets_error_on_failure():
    tracer, exporter, tp = _make_test_tracer()
    provider = ScriptedProvider([
        LLMResponse(content="401 bad key", finish_reason="error"),
    ])
    provider.tracer = tracer

    response = await provider.chat_stream_with_retry(
        messages=[{"role": "user", "content": "hi"}],
    )

    tp.force_flush()
    spans = exporter.spans
    assert response.finish_reason == "error"
    assert len(spans) == 1
    from opentelemetry.trace import StatusCode
    assert spans[0].status.status_code == StatusCode.ERROR


# ---------------------------------------------------------------------------
# Factory tests
# ---------------------------------------------------------------------------


def test_create_tracer_returns_noop_when_no_backends():
    from nanobot.config.schema import ObservabilityConfig
    from nanobot.observability.tracer import create_tracer
    tracer = create_tracer(ObservabilityConfig())
    assert isinstance(tracer, NoOpTracer)


def test_create_tracer_returns_noop_for_unknown_backend():
    from nanobot.config.schema import ObservabilityConfig
    from nanobot.observability.tracer import create_tracer
    tracer = create_tracer(ObservabilityConfig(backends=["unknown_backend"]))
    assert isinstance(tracer, NoOpTracer)


def test_make_tracer_returns_noop_when_disabled():
    from nanobot.config.schema import Config
    from nanobot.cli.commands import _make_tracer

    config = Config()
    tracer = _make_tracer(config)
    assert isinstance(tracer, NoOpTracer)


# ---------------------------------------------------------------------------
# Trace-level attributes
# ---------------------------------------------------------------------------


def test_set_trace_attributes_sets_span_kind():
    from nanobot.observability.tracer import set_trace_attributes, detach_trace_context

    tracer, exporter, tp = _make_test_tracer()
    with tracer.start_as_current_span("root") as span:
        tokens = set_trace_attributes(span, session_id="s1", user_id="u1", input="hello")
        detach_trace_context(tokens)

    tp.force_flush()
    attrs = dict(exporter.spans[0].attributes)
    assert attrs["langsmith.span.kind"] == "chain"
    assert attrs["langfuse.observation.type"] == "span"
    assert attrs["langfuse.session.id"] == "s1"
    assert attrs["langfuse.user.id"] == "u1"
    # input should be the plain string, not json-encoded
    assert attrs["input.value"] == "hello"
    assert attrs["langfuse.trace.input"] == "hello"


# ---------------------------------------------------------------------------
# Tool span attributes (P1)
# ---------------------------------------------------------------------------


def test_tool_span_attributes():
    from nanobot.observability.tracer import set_tool_attributes, set_tool_result

    tracer, exporter, tp = _make_test_tracer()
    with tracer.start_as_current_span("tool:test_tool") as span:
        set_tool_attributes(span, name="test_tool", arguments={"path": "/tmp"})
        set_tool_result(span, result="file contents here")

    tp.force_flush()
    attrs = dict(exporter.spans[0].attributes)
    assert attrs["gen_ai.tool.name"] == "test_tool"
    assert attrs["langsmith.span.kind"] == "tool"
    assert attrs["langfuse.observation.type"] == "span"
    assert '"path": "/tmp"' in attrs["langfuse.observation.input"]
    assert "file contents here" in attrs["output.value"]
