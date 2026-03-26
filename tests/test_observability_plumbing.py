"""Tests for observability plumbing: token usage metadata, generation names, span metadata.

Verifies that:
1. OutboundMessage from _process_message carries usage metadata (prompt + completion tokens).
2. stream_agent_response finish event surfaces token counts from message metadata.
3. generation_name metadata flows through StreamingLLMCaller to the provider.
4. update_current_span metadata does not include redundant token counts.
5. Verifier calls score_current_trace with parsed confidence.
6. process_direct passes session_id/user_id/tags to trace_request.
7. ToolRegistry wraps execution in tool_span.
8. Context builder wraps compression in a span.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from nanobot.agent.agent_factory import build_agent
from nanobot.agent.loop import AgentLoop
from nanobot.agent.streaming import StreamingLLMCaller
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.agent import AgentConfig
from nanobot.config.memory import MemoryConfig
from nanobot.providers.base import LLMProvider, LLMResponse, StreamChunk
from nanobot.web.streaming import stream_agent_response
from tests.helpers import ScriptedProvider

# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------


class StreamCapturingProvider(LLMProvider):
    """Provider that records metadata passed to stream_chat / chat."""

    def __init__(self, chunks: list[StreamChunk]):
        super().__init__()
        self._chunks = chunks
        self.chat_metadata: list[dict[str, Any] | None] = []
        self.stream_metadata: list[dict[str, Any] | None] = []

    def get_default_model(self) -> str:
        return "test-model"

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        metadata: dict[str, Any] | None = None,
    ) -> LLMResponse:
        self.chat_metadata.append(metadata)
        return LLMResponse(
            content="non-streaming", usage={"prompt_tokens": 10, "completion_tokens": 5}
        )

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        metadata: dict[str, Any] | None = None,
    ):
        self.stream_metadata.append(metadata)
        for chunk in self._chunks:
            yield chunk


def _make_config(tmp_path: Path, **overrides: Any) -> AgentConfig:
    defaults: dict[str, Any] = dict(
        workspace=str(tmp_path),
        model="test-model",
        memory=MemoryConfig(window=10),
        max_iterations=5,
        planning_enabled=False,
        verification_mode="off",
    )
    defaults.update(overrides)
    return AgentConfig(**defaults)


def _make_loop(tmp_path: Path, provider: LLMProvider, **config_overrides: Any) -> AgentLoop:
    bus = MessageBus()
    config = _make_config(tmp_path, **config_overrides)
    return build_agent(bus=bus, provider=provider, config=config)


def _make_inbound(text: str, channel: str = "cli", chat_id: str = "test-user") -> InboundMessage:
    return InboundMessage(
        channel=channel,
        chat_id=chat_id,
        sender_id="user-1",
        content=text,
    )


# ---------------------------------------------------------------------------
# 1. OutboundMessage carries usage metadata
# ---------------------------------------------------------------------------


class TestOutboundMessageUsageMetadata:
    """_process_message attaches prompt/completion token counts to the OutboundMessage."""

    async def test_usage_in_response_metadata(self, tmp_path: Path):
        provider = ScriptedProvider(
            [
                LLMResponse(
                    content="Hello!",
                    usage={"prompt_tokens": 100, "completion_tokens": 25},
                ),
            ]
        )
        loop = _make_loop(tmp_path, provider)
        msg = _make_inbound("Hi")
        result = await loop._process_message(msg)

        assert result is not None
        usage = result.metadata.get("usage")
        assert usage is not None
        assert usage["prompt_tokens"] == 100
        assert usage["completion_tokens"] == 25

    async def test_usage_accumulates_across_llm_calls(self, tmp_path: Path):
        """When the agent makes multiple LLM calls (e.g. tool use), tokens accumulate."""
        from nanobot.providers.base import ToolCallRequest

        provider = ScriptedProvider(
            [
                # First call: tool use
                LLMResponse(
                    content=None,
                    tool_calls=[ToolCallRequest(id="1", name="list_dir", arguments={"path": "."})],
                    usage={"prompt_tokens": 200, "completion_tokens": 10},
                ),
                # Second call: final answer
                LLMResponse(
                    content="Here are the files.",
                    usage={"prompt_tokens": 300, "completion_tokens": 50},
                ),
            ]
        )
        loop = _make_loop(tmp_path, provider)
        msg = _make_inbound("List files")
        result = await loop._process_message(msg)

        assert result is not None
        usage = result.metadata["usage"]
        assert usage["prompt_tokens"] == 500  # 200 + 300
        assert usage["completion_tokens"] == 60  # 10 + 50


# ---------------------------------------------------------------------------
# 2. stream_agent_response finish event surfaces token counts
# ---------------------------------------------------------------------------


class _FakeWebChannel:
    """Minimal stub for WebChannel used by stream_agent_response."""

    def __init__(self, messages: list[OutboundMessage | None]):
        self._messages = messages
        self._queue: asyncio.Queue[OutboundMessage | None] | None = None

    def register_stream(self, chat_id: str) -> asyncio.Queue[OutboundMessage | None]:
        q: asyncio.Queue[OutboundMessage | None] = asyncio.Queue()
        for m in self._messages:
            q.put_nowait(m)
        self._queue = q
        return q

    def unregister_stream(self, chat_id: str) -> None:
        pass

    async def publish_user_message(
        self, chat_id: str, content: str, *, media: Any = None, metadata: Any = None
    ) -> None:
        pass


class TestStreamAgentResponseTokenCounts:
    """The SSE finish event reads token counts from OutboundMessage metadata."""

    async def test_finish_event_has_token_counts(self):
        final_msg = OutboundMessage(
            channel="web",
            chat_id="chat-1",
            content="Answer",
            metadata={"usage": {"prompt_tokens": 500, "completion_tokens": 42}},
        )
        channel = _FakeWebChannel([final_msg])

        events: list[str] = []
        async for event in stream_agent_response(channel, "chat-1", "question"):  # type: ignore[arg-type]
            events.append(event)

        # finish event in ui-message-stream: event: message / data: {"type":"finish",...}
        import json as _json

        finish_events = [
            _json.loads(line[len("data:") :].strip())
            for chunk in events
            for line in chunk.splitlines()
            if line.startswith("data:") and '"finish"' in line
        ]
        assert len(finish_events) == 1
        payload = finish_events[0]
        assert payload["usage"]["inputTokens"] == 500
        assert payload["usage"]["outputTokens"] == 42

    async def test_finish_event_defaults_to_zero_without_metadata(self):
        """When OutboundMessage has no usage metadata, finish event has zero counts."""
        final_msg = OutboundMessage(
            channel="web",
            chat_id="chat-1",
            content="Answer",
            metadata={},
        )
        channel = _FakeWebChannel([final_msg])

        events: list[str] = []
        async for event in stream_agent_response(channel, "chat-1", "question"):  # type: ignore[arg-type]
            events.append(event)

        import json as _json

        finish_events = [
            _json.loads(line[len("data:") :].strip())
            for chunk in events
            for line in chunk.splitlines()
            if line.startswith("data:") and '"finish"' in line
        ]
        payload = finish_events[0]
        assert payload["usage"]["inputTokens"] == 0
        assert payload["usage"]["outputTokens"] == 0


# ---------------------------------------------------------------------------
# 3. generation_name flows through StreamingLLMCaller to provider
# ---------------------------------------------------------------------------


class TestGenerationNameMetadata:
    """StreamingLLMCaller passes generation_name metadata to provider calls."""

    async def test_non_streaming_passes_generation_name(self):
        provider = StreamCapturingProvider(chunks=[])
        caller = StreamingLLMCaller(
            provider=provider, model="test-model", temperature=0.7, max_tokens=4096
        )
        await caller.call(
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
            on_progress=None,  # non-streaming path
        )

        assert len(provider.chat_metadata) == 1
        assert provider.chat_metadata[0] == {"generation_name": "chat_completion"}

    async def test_streaming_passes_generation_name(self):
        provider = StreamCapturingProvider(
            chunks=[StreamChunk(content_delta="Hello", finish_reason="stop", done=True)]
        )
        caller = StreamingLLMCaller(
            provider=provider, model="test-model", temperature=0.7, max_tokens=4096
        )

        async def noop_progress(*args: Any, **kwargs: Any) -> None:
            pass

        await caller.call(
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
            on_progress=noop_progress,  # streaming path
        )

        assert len(provider.stream_metadata) == 1
        assert provider.stream_metadata[0] == {"generation_name": "chat_completion"}


# ---------------------------------------------------------------------------
# 4. Span metadata includes token counts
# ---------------------------------------------------------------------------


class TestSpanMetadataWithTokenCounts:
    """update_current_span is called with prompt_tokens/completion_tokens/duration_ms."""

    async def test_span_metadata_includes_token_counts(self, tmp_path: Path):
        provider = ScriptedProvider(
            [
                LLMResponse(
                    content="Response text",
                    usage={"prompt_tokens": 100, "completion_tokens": 25},
                ),
            ]
        )
        loop = _make_loop(tmp_path, provider)
        msg = _make_inbound("Hello")

        captured_metadata: list[dict[str, Any]] = []

        original_update = "nanobot.agent.loop.update_current_span"
        with patch(original_update) as mock_update:

            def capture_call(**kwargs: Any) -> None:
                if "metadata" in kwargs:
                    captured_metadata.append(kwargs["metadata"])

            mock_update.side_effect = capture_call
            await loop._process_message(msg)

        # Should have been called at least once with metadata
        assert len(captured_metadata) >= 1

        # Verify expected keys are present
        last_meta = captured_metadata[-1]
        assert "channel" in last_meta
        assert "model" in last_meta
        assert "llm_calls" in last_meta
        assert "prompt_tokens" in last_meta, "span metadata should have prompt_tokens"
        assert "completion_tokens" in last_meta, "span metadata should have completion_tokens"
        assert "duration_ms" in last_meta, "span metadata should have duration_ms"


# ---------------------------------------------------------------------------
# 5. Verifier calls score_current_trace with parsed confidence
# ---------------------------------------------------------------------------


class TestVerifierScoreCurrentTrace:
    """AnswerVerifier.verify() calls score_current_trace after parsing confidence."""

    async def test_score_called_with_confidence_and_issues(self):
        from nanobot.agent.verifier import AnswerVerifier
        from nanobot.providers.base import LLMResponse

        critique_json = json.dumps({"confidence": 4, "issues": ["minor issue"]})
        provider = ScriptedProvider(
            [
                LLMResponse(
                    content=critique_json, usage={"prompt_tokens": 50, "completion_tokens": 20}
                )
            ]
        )
        verifier = AnswerVerifier(
            provider=provider,
            model="test-model",
            temperature=0.7,
            max_tokens=4096,
            verification_mode="always",
            memory_uncertainty_threshold=0.5,
        )
        messages = [
            {"role": "user", "content": "What is 2+2?"},
            {"role": "assistant", "content": "4"},
        ]

        with patch("nanobot.agent.verifier.score_current_trace") as mock_score:
            result, _ = await verifier.verify("What is 2+2?", "4", messages)

        mock_score.assert_called_once_with(
            name="verification_confidence",
            value=4,
            comment="minor issue",
        )

    async def test_score_called_with_passed_when_no_issues(self):
        from nanobot.agent.verifier import AnswerVerifier
        from nanobot.providers.base import LLMResponse

        critique_json = json.dumps({"confidence": 5, "issues": []})
        provider = ScriptedProvider(
            [
                LLMResponse(
                    content=critique_json, usage={"prompt_tokens": 50, "completion_tokens": 20}
                )
            ]
        )
        verifier = AnswerVerifier(
            provider=provider,
            model="test-model",
            temperature=0.7,
            max_tokens=4096,
            verification_mode="always",
            memory_uncertainty_threshold=0.5,
        )
        messages = [
            {"role": "user", "content": "What is 2+2?"},
            {"role": "assistant", "content": "4"},
        ]

        with patch("nanobot.agent.verifier.score_current_trace") as mock_score:
            result, _ = await verifier.verify("What is 2+2?", "4", messages)

        mock_score.assert_called_once_with(
            name="verification_confidence",
            value=5,
            comment="passed",
        )


# ---------------------------------------------------------------------------
# 6. process_direct passes trace metadata to trace_request
# ---------------------------------------------------------------------------


class TestProcessDirectTraceMetadata:
    """process_direct passes session_id, user_id, tags to trace_request."""

    async def test_trace_request_receives_session_user_tags(self, tmp_path: Path):
        provider = ScriptedProvider(
            [LLMResponse(content="Hello!", usage={"prompt_tokens": 10, "completion_tokens": 2})]
        )
        loop = _make_loop(tmp_path, provider)

        captured_kwargs: list[dict[str, Any]] = []

        @contextlib.asynccontextmanager
        async def fake_trace_request(**kwargs: Any):
            captured_kwargs.append(kwargs)
            yield None

        with patch("nanobot.agent.loop.trace_request", side_effect=fake_trace_request):
            await loop.process_direct(
                "Hi",
                session_key="cli:test-session",
                channel="cli",
            )

        assert len(captured_kwargs) == 1
        kw = captured_kwargs[0]
        assert kw["session_id"] == "cli:test-session"
        assert kw["user_id"] == "cli"
        assert kw["tags"] == ["cli"]
        assert kw["name"] == "request"


# ---------------------------------------------------------------------------
# 7. ToolRegistry wraps execution in tool_span
# ---------------------------------------------------------------------------


class TestToolRegistryToolSpan:
    """ToolRegistry._execute_inner wraps tool execution in a tool_span."""

    async def test_tool_span_called_with_name_and_input(self):
        from nanobot.tools.base import Tool, ToolResult
        from nanobot.tools.registry import ToolRegistry

        class DummyTool(Tool):
            name = "dummy"
            description = "A dummy tool"
            parameters = {"type": "object", "properties": {}}

            async def execute(self, **kwargs: Any) -> ToolResult:
                return ToolResult.ok("done")

        registry = ToolRegistry()
        registry.register(DummyTool())

        captured_spans: list[dict[str, Any]] = []

        @contextlib.asynccontextmanager
        async def fake_tool_span(**kwargs: Any):
            captured_spans.append(kwargs)
            yield None

        with patch("nanobot.observability.langfuse.tool_span", side_effect=fake_tool_span):
            result = await registry.execute("dummy", {})

        assert result.success
        assert len(captured_spans) == 1
        assert captured_spans[0]["name"] == "dummy"
        assert captured_spans[0]["input"] == {}


# ---------------------------------------------------------------------------
# 8. Context builder wraps compression in a langfuse span
# ---------------------------------------------------------------------------


class TestContextBuilderSpan:
    """summarize_and_compress wraps LLM compression in a langfuse span."""

    async def test_compress_span_created(self):
        from nanobot.context.compression import summarize_and_compress
        from nanobot.providers.base import LLMResponse

        provider = ScriptedProvider(
            [
                LLMResponse(
                    content="Summary of conversation.",
                    usage={"prompt_tokens": 30, "completion_tokens": 10},
                )
            ]
        )

        captured_spans: list[dict[str, Any]] = []

        @contextlib.asynccontextmanager
        async def fake_span(**kwargs: Any):
            captured_spans.append(kwargs)
            yield None

        # Build messages that exceed the budget to trigger compression
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": "You are a helpful assistant."},
        ]
        # Add enough user/assistant messages to exceed a small budget
        for i in range(20):
            messages.append({"role": "user", "content": f"Message {i} " + "x" * 200})
            messages.append({"role": "assistant", "content": f"Reply {i} " + "y" * 200})

        with patch("nanobot.context.compression.langfuse_span", side_effect=fake_span):
            await summarize_and_compress(
                messages=messages,
                provider=provider,
                model="test-model",
                max_tokens=500,  # small budget to force compression
            )

        # Should have created a "compress" span
        compress_spans = [s for s in captured_spans if s.get("name") == "compress"]
        assert len(compress_spans) >= 1
        assert "metadata" in compress_spans[0]
        assert "before_tokens" in compress_spans[0]["metadata"]
        assert "input" in compress_spans[0]
        assert "middle_msgs" in compress_spans[0]["input"]


# ---------------------------------------------------------------------------
# 9. ToolRegistry tool_span captures output via obs.update()
# ---------------------------------------------------------------------------


class TestToolSpanOutputCaptured:
    """ToolRegistry._execute_inner calls obs.update() with tool result output."""

    async def test_successful_tool_captures_output(self):
        from nanobot.tools.base import Tool, ToolResult
        from nanobot.tools.registry import ToolRegistry

        class EchoTool(Tool):
            name = "echo"
            description = "Echo tool"
            parameters = {"type": "object", "properties": {}}

            async def execute(self, **kwargs: Any) -> ToolResult:
                return ToolResult.ok("hello world")

        registry = ToolRegistry()
        registry.register(EchoTool())

        update_calls: list[dict[str, Any]] = []

        class FakeObs:
            def update(self, **kwargs: Any) -> None:
                update_calls.append(kwargs)

        @contextlib.asynccontextmanager
        async def fake_tool_span(**kwargs: Any):
            yield FakeObs()

        with patch("nanobot.observability.langfuse.tool_span", side_effect=fake_tool_span):
            result = await registry.execute("echo", {})

        assert result.success
        assert result.output == "hello world"
        assert len(update_calls) == 1
        assert "hello world" in update_calls[0]["output"]
        assert update_calls[0]["metadata"]["success"] is True
        assert "duration_ms" in update_calls[0]["metadata"]

    async def test_validation_error_captures_output(self):
        from nanobot.tools.base import Tool, ToolResult
        from nanobot.tools.registry import ToolRegistry

        class StrictTool(Tool):
            name = "strict"
            description = "Strict tool"
            parameters = {
                "type": "object",
                "properties": {"x": {"type": "integer"}},
                "required": ["x"],
            }

            async def execute(self, **kwargs: Any) -> ToolResult:
                return ToolResult.ok("ok")

        registry = ToolRegistry()
        registry.register(StrictTool())

        update_calls: list[dict[str, Any]] = []

        class FakeObs:
            def update(self, **kwargs: Any) -> None:
                update_calls.append(kwargs)

        @contextlib.asynccontextmanager
        async def fake_tool_span(**kwargs: Any):
            yield FakeObs()

        with patch("nanobot.observability.langfuse.tool_span", side_effect=fake_tool_span):
            result = await registry.execute("strict", {})  # missing required 'x'

        assert not result.success
        assert len(update_calls) == 1
        assert update_calls[0]["metadata"]["success"] is False
        assert update_calls[0]["metadata"]["error_type"] == "validation"

    async def test_obs_none_does_not_crash(self):
        """When Langfuse is disabled, obs is None — no crash."""
        from nanobot.tools.base import Tool, ToolResult
        from nanobot.tools.registry import ToolRegistry

        class EchoTool(Tool):
            name = "echo"
            description = "Echo tool"
            parameters = {"type": "object", "properties": {}}

            async def execute(self, **kwargs: Any) -> ToolResult:
                return ToolResult.ok("hello world")

        registry = ToolRegistry()
        registry.register(EchoTool())

        @contextlib.asynccontextmanager
        async def fake_tool_span(**kwargs: Any):
            yield None

        with patch("nanobot.observability.langfuse.tool_span", side_effect=fake_tool_span):
            result = await registry.execute("echo", {})

        assert result.success
        assert result.output == "hello world"


# ---------------------------------------------------------------------------
# 10. Cache-hit path creates a tool_span
# ---------------------------------------------------------------------------


class TestToolSpanCacheHit:
    """ToolRegistry.execute() wraps cache hits in a tool_span."""

    async def test_cache_hit_creates_span_with_metadata(self):
        from unittest.mock import MagicMock

        from nanobot.tools.base import Tool, ToolResult
        from nanobot.tools.registry import ToolRegistry

        class CacheableTool(Tool):
            name = "cached_tool"
            description = "A cacheable tool"
            readonly = True
            cacheable = True
            parameters = {"type": "object", "properties": {}}

            async def execute(self, **kwargs: Any) -> ToolResult:
                return ToolResult.ok("should not be called")

        registry = ToolRegistry()
        registry.register(CacheableTool())

        # Set up mock cache that returns a hit
        mock_cache = MagicMock()
        mock_cache.has.return_value = "cache_key_123"
        mock_entry = MagicMock()
        mock_entry.summary = "cached summary text"
        mock_cache.get.return_value = mock_entry

        registry.set_cache(mock_cache)

        captured_spans: list[dict[str, Any]] = []
        update_calls: list[dict[str, Any]] = []

        class FakeObs:
            def update(self, **kwargs: Any) -> None:
                update_calls.append(kwargs)

        @contextlib.asynccontextmanager
        async def fake_tool_span(**kwargs: Any):
            captured_spans.append(kwargs)
            yield FakeObs()

        with patch("nanobot.observability.langfuse.tool_span", side_effect=fake_tool_span):
            result = await registry.execute("cached_tool", {"arg": "val"})

        assert result.success
        assert result.output == "cached summary text"
        assert result.metadata.get("cached") is True

        # Verify span was created with cache metadata
        assert len(captured_spans) == 1
        assert captured_spans[0]["name"] == "cached_tool"
        assert captured_spans[0]["input"] == {"arg": "val"}
        assert captured_spans[0]["metadata"]["cache"] == "hit"
        assert captured_spans[0]["metadata"]["cache_key"] == "cache_key_123"

        # Verify obs.update was called with output
        assert len(update_calls) == 1
        assert "cached summary text" in update_calls[0]["output"]

    async def test_cache_hit_obs_none_does_not_crash(self):
        from unittest.mock import MagicMock

        from nanobot.tools.base import Tool, ToolResult
        from nanobot.tools.registry import ToolRegistry

        class CacheableTool(Tool):
            name = "cached_tool"
            description = "A cacheable tool"
            readonly = True
            cacheable = True
            parameters = {"type": "object", "properties": {}}

            async def execute(self, **kwargs: Any) -> ToolResult:
                return ToolResult.ok("should not be called")

        registry = ToolRegistry()
        registry.register(CacheableTool())

        mock_cache = MagicMock()
        mock_cache.has.return_value = "cache_key_456"
        mock_entry = MagicMock()
        mock_entry.summary = "cached text"
        mock_cache.get.return_value = mock_entry

        registry.set_cache(mock_cache)

        @contextlib.asynccontextmanager
        async def fake_tool_span(**kwargs: Any):
            yield None

        with patch("nanobot.observability.langfuse.tool_span", side_effect=fake_tool_span):
            result = await registry.execute("cached_tool", {})

        assert result.success
        assert result.output == "cached text"
        assert result.metadata.get("cached") is True


# ---------------------------------------------------------------------------
# 11. Compression span captures input, output, and enriched metadata
# ---------------------------------------------------------------------------


class TestCompressSpanEnriched:
    """summarize_and_compress span includes input/output and compression metadata."""

    async def test_compress_span_has_output_and_metadata(self):
        from nanobot.context.compression import _summary_cache, summarize_and_compress
        from nanobot.providers.base import LLMResponse

        _summary_cache.clear()

        provider = ScriptedProvider(
            [
                LLMResponse(
                    content="Summary of conversation.",
                    usage={"prompt_tokens": 30, "completion_tokens": 10},
                )
            ]
        )

        update_calls: list[dict[str, Any]] = []

        class FakeObs:
            def update(self, **kwargs: Any) -> None:
                update_calls.append(kwargs)

        @contextlib.asynccontextmanager
        async def fake_span(**kwargs: Any):
            yield FakeObs()

        # Build messages that exceed the budget to trigger compression
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": "You are a helpful assistant."},
        ]
        for i in range(20):
            messages.append({"role": "user", "content": f"Message {i} " + "x" * 200})
            messages.append({"role": "assistant", "content": f"Reply {i} " + "y" * 200})

        with patch("nanobot.context.compression.langfuse_span", side_effect=fake_span):
            await summarize_and_compress(
                messages=messages,
                provider=provider,
                model="test-model",
                max_tokens=500,
            )

        assert len(update_calls) == 1
        call = update_calls[0]
        assert "Summary" in call["output"]
        assert "compression_ratio" in call["metadata"]
        assert "before_tokens" in call["metadata"]
        assert call["metadata"]["model"] == "test-model"

    async def test_compress_span_obs_none_no_crash(self):
        """When Langfuse is disabled (obs is None), no crash occurs."""
        from nanobot.context.compression import _summary_cache, summarize_and_compress
        from nanobot.providers.base import LLMResponse

        _summary_cache.clear()

        provider = ScriptedProvider(
            [
                LLMResponse(
                    content="Summary of conversation.",
                    usage={"prompt_tokens": 30, "completion_tokens": 10},
                )
            ]
        )

        @contextlib.asynccontextmanager
        async def fake_span(**kwargs: Any):
            yield None

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": "You are a helpful assistant."},
        ]
        for i in range(20):
            messages.append({"role": "user", "content": f"Message {i} " + "x" * 200})
            messages.append({"role": "assistant", "content": f"Reply {i} " + "y" * 200})

        with patch("nanobot.context.compression.langfuse_span", side_effect=fake_span):
            result = await summarize_and_compress(
                messages=messages,
                provider=provider,
                model="test-model",
                max_tokens=500,
            )

        # Should not crash and should return valid messages
        assert isinstance(result, list)
        assert len(result) >= 1


# ---------------------------------------------------------------------------
# 9. Verify span enriched with input/output and revision sub-span
# ---------------------------------------------------------------------------


class TestVerifySpanEnriched:
    """verify() enriches the verify span with input/output and wraps revision in a sub-span."""

    async def test_verify_pass_updates_span_with_passed(self):
        from unittest.mock import MagicMock

        from nanobot.agent.verifier import AnswerVerifier
        from nanobot.providers.base import LLMResponse

        critique_json = json.dumps({"confidence": 8, "issues": []})
        provider = ScriptedProvider(
            [
                LLMResponse(
                    content=critique_json,
                    usage={"prompt_tokens": 50, "completion_tokens": 20},
                )
            ]
        )
        verifier = AnswerVerifier(
            provider=provider,
            model="test-model",
            temperature=0.7,
            max_tokens=4096,
            verification_mode="always",
            memory_uncertainty_threshold=0.5,
        )
        messages = [
            {"role": "user", "content": "What is 2+2?"},
            {"role": "assistant", "content": "4"},
        ]

        mock_obs = MagicMock()
        captured_span_kwargs: list[dict[str, Any]] = []

        @contextlib.asynccontextmanager
        async def fake_span(**kwargs: Any):
            captured_span_kwargs.append(kwargs)
            yield mock_obs

        with (
            patch("nanobot.agent.verifier.langfuse_span", side_effect=fake_span),
            patch("nanobot.agent.verifier.score_current_trace"),
        ):
            result, _ = await verifier.verify("What is 2+2?", "4", messages)

        assert result == "4"
        # Span should have been created with input containing question and candidate
        assert len(captured_span_kwargs) == 1
        span_kw = captured_span_kwargs[0]
        assert span_kw["name"] == "verify"
        assert span_kw["input"]["question"] == "What is 2+2?"
        assert span_kw["input"]["candidate"] == "4"

        # obs.update should have been called with output="passed"
        mock_obs.update.assert_called_once()
        update_kwargs = mock_obs.update.call_args[1]
        assert update_kwargs["output"] == "passed"
        assert update_kwargs["metadata"]["confidence"] == 8
        assert update_kwargs["metadata"]["passed"] is True

    async def test_verify_revision_creates_sub_span(self):
        from unittest.mock import MagicMock

        from nanobot.agent.verifier import AnswerVerifier
        from nanobot.providers.base import LLMResponse

        critique_json = json.dumps({"confidence": 1, "issues": ["factual error"]})
        provider = ScriptedProvider(
            [
                LLMResponse(
                    content=critique_json,
                    usage={"prompt_tokens": 50, "completion_tokens": 20},
                ),
                LLMResponse(
                    content="Revised answer: 4",
                    usage={"prompt_tokens": 60, "completion_tokens": 30},
                ),
            ]
        )
        verifier = AnswerVerifier(
            provider=provider,
            model="test-model",
            temperature=0.7,
            max_tokens=4096,
            verification_mode="always",
            memory_uncertainty_threshold=0.5,
        )
        messages = [
            {"role": "user", "content": "What is 2+2?"},
            {"role": "assistant", "content": "wrong answer"},
        ]

        mock_obs = MagicMock()
        mock_rev_obs = MagicMock()
        span_call_count = 0
        captured_span_kwargs: list[dict[str, Any]] = []

        @contextlib.asynccontextmanager
        async def fake_span(**kwargs: Any):
            nonlocal span_call_count
            captured_span_kwargs.append(kwargs)
            if span_call_count == 0:
                span_call_count += 1
                yield mock_obs
            else:
                yield mock_rev_obs

        with (
            patch("nanobot.agent.verifier.langfuse_span", side_effect=fake_span),
            patch("nanobot.agent.verifier.score_current_trace"),
        ):
            result, _ = await verifier.verify("What is 2+2?", "wrong answer", messages)

        assert result == "Revised answer: 4"

        # Two spans: verify + revision
        assert len(captured_span_kwargs) == 2
        assert captured_span_kwargs[0]["name"] == "verify"
        assert captured_span_kwargs[1]["name"] == "revision"
        assert captured_span_kwargs[1]["input"]["issues"] == ["factual error"]
        assert captured_span_kwargs[1]["input"]["confidence"] == 1

        # Revision obs should have output set
        mock_rev_obs.update.assert_called_once()
        rev_update_kwargs = mock_rev_obs.update.call_args[1]
        assert rev_update_kwargs["output"] == "Revised answer: 4"

        # Verify obs should have output="revised"
        mock_obs.update.assert_called_once()
        obs_update_kwargs = mock_obs.update.call_args[1]
        assert obs_update_kwargs["output"] == "revised"
        assert obs_update_kwargs["metadata"]["passed"] is False
        assert obs_update_kwargs["metadata"]["issues"] == ["factual error"]

    async def test_verify_parse_error_updates_span(self):
        """When critique JSON is unparseable, span records parse_error."""
        from unittest.mock import MagicMock

        from nanobot.agent.verifier import AnswerVerifier
        from nanobot.providers.base import LLMResponse

        provider = ScriptedProvider([LLMResponse(content="not valid json", usage={})])
        verifier = AnswerVerifier(
            provider=provider,
            model="test",
            temperature=0.0,
            max_tokens=1000,
            verification_mode="always",
            memory_uncertainty_threshold=0.5,
        )
        mock_obs = MagicMock()

        @contextlib.asynccontextmanager
        async def fake_span(**kwargs: Any):
            yield mock_obs

        with (
            patch("nanobot.agent.verifier.langfuse_span", side_effect=fake_span),
            patch("nanobot.agent.verifier.score_current_trace"),
        ):
            result, _ = await verifier.verify("Q?", "A.", [])

        assert result == "A."  # original returned on parse error
        mock_obs.update.assert_called_once()
        kwargs = mock_obs.update.call_args[1]
        assert kwargs["output"] == "parse_error"
        assert kwargs["metadata"]["skipped"] is True

    async def test_verify_call_error_updates_span(self):
        """When the critique LLM call raises, span records call_error."""
        from unittest.mock import MagicMock

        from nanobot.agent.verifier import AnswerVerifier

        class FailingProvider:
            async def chat(self, **kwargs: Any):
                raise RuntimeError("LLM down")

        verifier = AnswerVerifier(
            provider=FailingProvider(),  # type: ignore[arg-type]
            model="test",
            temperature=0.0,
            max_tokens=1000,
            verification_mode="always",
            memory_uncertainty_threshold=0.5,
        )
        mock_obs = MagicMock()

        @contextlib.asynccontextmanager
        async def fake_span(**kwargs: Any):
            yield mock_obs

        with (
            patch("nanobot.agent.verifier.langfuse_span", side_effect=fake_span),
            patch("nanobot.agent.verifier.score_current_trace"),
        ):
            result, _ = await verifier.verify("Q?", "A.", [])

        assert result == "A."  # original returned on error
        mock_obs.update.assert_called_once()
        kwargs = mock_obs.update.call_args[1]
        assert kwargs["output"] == "call_error"
        assert kwargs["metadata"]["skipped"] is True


# ---------------------------------------------------------------------------
# 11. Delegation span captures output via obs.update()
# ---------------------------------------------------------------------------


class TestDelegationSpanOutput:
    """DelegationDispatcher.dispatch() calls obs.update() on the delegate span."""

    async def test_delegation_span_captures_result(self, tmp_path: Path):
        from unittest.mock import AsyncMock, MagicMock

        from nanobot.config.schema import AgentRoleConfig
        from nanobot.coordination.delegation import DelegationConfig, DelegationDispatcher

        config = DelegationConfig(
            workspace=tmp_path,
            model="test-model",
            temperature=0.7,
            max_tokens=4096,
            max_iterations=5,
            restrict_to_workspace=True,
            brave_api_key=None,
            exec_config=None,
            role_name="orchestrator",
        )

        # Minimal coordinator mock that returns a role
        mock_coordinator = MagicMock()
        target_role = AgentRoleConfig(name="researcher", system_prompt="You research.")
        mock_coordinator.route_direct.return_value = target_role

        dispatcher = DelegationDispatcher(
            config=config,
            provider=MagicMock(),
            coordinator=mock_coordinator,
        )

        # Patch execute_delegated_agent to return a known result
        dispatcher.execute_delegated_agent = AsyncMock(  # type: ignore[method-assign]
            return_value=("Here is the research summary.", ["read_file", "web_fetch"])
        )

        # Capture obs.update() calls
        update_calls: list[dict[str, Any]] = []

        class FakeObs:
            def update(self, **kwargs: Any) -> None:
                update_calls.append(kwargs)

        @contextlib.asynccontextmanager
        async def fake_span(**kwargs: Any):
            yield FakeObs()

        with patch(
            "nanobot.coordination.delegation.langfuse_span",
            side_effect=fake_span,
        ):
            result = await dispatcher.dispatch("researcher", "Find the answer", None)

        assert result.content == "Here is the research summary."
        assert len(update_calls) == 1
        assert "research summary" in update_calls[0]["output"]
        assert update_calls[0]["metadata"]["success"] is True
        assert update_calls[0]["metadata"]["tools_used"] == ["read_file", "web_fetch"]
        assert update_calls[0]["metadata"]["tools_used_count"] == 2

    async def test_delegation_span_truncates_long_output(self, tmp_path: Path):
        from unittest.mock import AsyncMock, MagicMock

        from nanobot.config.schema import AgentRoleConfig
        from nanobot.coordination.delegation import DelegationConfig, DelegationDispatcher

        config = DelegationConfig(
            workspace=tmp_path,
            model="test-model",
            temperature=0.7,
            max_tokens=4096,
            max_iterations=5,
            restrict_to_workspace=True,
            brave_api_key=None,
            exec_config=None,
            role_name="orchestrator",
        )

        mock_coordinator = MagicMock()
        target_role = AgentRoleConfig(name="researcher", system_prompt="You research.")
        mock_coordinator.route_direct.return_value = target_role

        dispatcher = DelegationDispatcher(
            config=config,
            provider=MagicMock(),
            coordinator=mock_coordinator,
        )

        long_result = "x" * 1000
        dispatcher.execute_delegated_agent = AsyncMock(  # type: ignore[method-assign]
            return_value=(long_result, [])
        )

        update_calls: list[dict[str, Any]] = []

        class FakeObs:
            def update(self, **kwargs: Any) -> None:
                update_calls.append(kwargs)

        @contextlib.asynccontextmanager
        async def fake_span(**kwargs: Any):
            yield FakeObs()

        with patch(
            "nanobot.coordination.delegation.langfuse_span",
            side_effect=fake_span,
        ):
            await dispatcher.dispatch("researcher", "Do something", None)

        assert len(update_calls) == 1
        assert len(update_calls[0]["output"]) <= 500

    async def test_delegation_span_obs_none_no_crash(self, tmp_path: Path):
        """When Langfuse is disabled (obs is None), no crash occurs."""
        from unittest.mock import AsyncMock, MagicMock

        from nanobot.config.schema import AgentRoleConfig
        from nanobot.coordination.delegation import DelegationConfig, DelegationDispatcher

        config = DelegationConfig(
            workspace=tmp_path,
            model="test-model",
            temperature=0.7,
            max_tokens=4096,
            max_iterations=5,
            restrict_to_workspace=True,
            brave_api_key=None,
            exec_config=None,
            role_name="orchestrator",
        )

        mock_coordinator = MagicMock()
        target_role = AgentRoleConfig(name="researcher", system_prompt="You research.")
        mock_coordinator.route_direct.return_value = target_role

        dispatcher = DelegationDispatcher(
            config=config,
            provider=MagicMock(),
            coordinator=mock_coordinator,
        )

        dispatcher.execute_delegated_agent = AsyncMock(  # type: ignore[method-assign]
            return_value=("Result text", ["list_dir"])
        )

        @contextlib.asynccontextmanager
        async def fake_span(**kwargs: Any):
            yield None

        with patch(
            "nanobot.coordination.delegation.langfuse_span",
            side_effect=fake_span,
        ):
            result = await dispatcher.dispatch("researcher", "Task", None)

        assert result.content == "Result text"
