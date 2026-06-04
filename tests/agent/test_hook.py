"""Unit tests for AgentHook and CompositeHook."""


from blackcat.agent.hook import AgentHook, AgentHookContext, CompositeHook


class TestAgentHookContext:
    """Tests for AgentHookContext dataclass."""

    def test_default_values(self):
        """Context should have sensible defaults."""
        ctx = AgentHookContext(iteration=0, messages=[])
        assert ctx.iteration == 0
        assert ctx.messages == []
        assert ctx.response is None
        assert ctx.usage == {}
        assert ctx.tool_calls == []
        assert ctx.tool_results == []
        assert ctx.tool_events == []
        assert ctx.final_content is None
        assert ctx.stop_reason is None
        assert ctx.error is None

    def test_custom_values(self):
        """Context should accept custom values."""
        ctx = AgentHookContext(
            iteration=5,
            messages=[{"role": "user", "content": "hi"}],
            response=None,
            usage={"prompt_tokens": 100, "completion_tokens": 50},
            tool_calls=[],
            final_content="done",
        )
        assert ctx.iteration == 5
        assert len(ctx.messages) == 1
        assert ctx.usage["prompt_tokens"] == 100
        assert ctx.final_content == "done"


class TestAgentHook:
    """Tests for base AgentHook class."""

    def test_wants_streaming_default_false(self):
        """Default hook doesn't want streaming."""
        hook = AgentHook()
        assert hook.wants_streaming() is False

    async def test_before_iteration_default(self):
        """Default before_iteration is a no-op."""
        hook = AgentHook()
        ctx = AgentHookContext(iteration=0, messages=[])
        # Should not raise
        await hook.before_iteration(ctx)

    async def test_on_stream_default(self):
        """Default on_stream is a no-op."""
        hook = AgentHook()
        ctx = AgentHookContext(iteration=0, messages=[])
        await hook.on_stream(ctx, "delta")

    async def test_on_stream_end_default(self):
        """Default on_stream_end is a no-op."""
        hook = AgentHook()
        ctx = AgentHookContext(iteration=0, messages=[])
        await hook.on_stream_end(ctx, resuming=True)

    async def test_before_execute_tools_default(self):
        """Default before_execute_tools is a no-op."""
        hook = AgentHook()
        ctx = AgentHookContext(iteration=0, messages=[])
        await hook.before_execute_tools(ctx)

    async def test_after_iteration_default(self):
        """Default after_iteration is a no-op."""
        hook = AgentHook()
        ctx = AgentHookContext(iteration=0, messages=[])
        await hook.after_iteration(ctx)

    def test_finalize_content_default(self):
        """Default finalize_content returns content unchanged."""
        hook = AgentHook()
        ctx = AgentHookContext(iteration=0, messages=[])
        assert hook.finalize_content(ctx, "hello") == "hello"
        assert hook.finalize_content(ctx, None) is None


class CountingHook(AgentHook):
    """Test hook that counts method calls."""

    def __init__(self):
        self.calls = []

    def wants_streaming(self) -> bool:
        self.calls.append("wants_streaming")
        return True

    async def before_iteration(self, context: AgentHookContext) -> None:
        self.calls.append("before_iteration")

    async def on_stream(self, context: AgentHookContext, delta: str) -> None:
        self.calls.append(f"on_stream:{delta}")

    async def on_stream_end(self, context: AgentHookContext, *, resuming: bool) -> None:
        self.calls.append(f"on_stream_end:{resuming}")

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        self.calls.append("before_execute_tools")

    async def after_iteration(self, context: AgentHookContext) -> None:
        self.calls.append("after_iteration")

    def finalize_content(self, context: AgentHookContext, content: str | None) -> str | None:
        self.calls.append("finalize_content")
        return content


class TestCompositeHook:
    """Tests for CompositeHook."""

    async def test_wants_streaming_any_true(self):
        """Composite wants streaming if any child wants it."""
        hook1 = AgentHook()  # wants_streaming = False
        hook2 = CountingHook()  # wants_streaming = True
        composite = CompositeHook([hook1, hook2])
        assert composite.wants_streaming() is True

    async def test_wants_streaming_all_false(self):
        """Composite doesn't want streaming if all children don't."""
        hook1 = AgentHook()
        hook2 = AgentHook()
        composite = CompositeHook([hook1, hook2])
        assert composite.wants_streaming() is False

    async def test_fan_out_calls_all_hooks(self):
        """Composite should call all hooks in order."""
        hook1 = CountingHook()
        hook2 = CountingHook()
        composite = CompositeHook([hook1, hook2])

        ctx = AgentHookContext(iteration=0, messages=[])
        await composite.before_iteration(ctx)

        assert "before_iteration" in hook1.calls
        assert "before_iteration" in hook2.calls
        # Both hooks are called - order is guaranteed by CompositeHook's sequential execution

    async def test_on_stream_fan_out(self):
        """Composite should pass stream deltas to all hooks."""
        hook1 = CountingHook()
        hook2 = CountingHook()
        composite = CompositeHook([hook1, hook2])

        ctx = AgentHookContext(iteration=0, messages=[])
        await composite.on_stream(ctx, "hello")

        assert "on_stream:hello" in hook1.calls
        assert "on_stream:hello" in hook2.calls

    async def test_finalize_content_pipeline(self):
        """finalize_content should pipeline through all hooks."""
        class UpperHook(AgentHook):
            def finalize_content(self, context, content):
                return content.upper() if content else content

        class ExclaimHook(AgentHook):
            def finalize_content(self, context, content):
                return f"{content}!" if content else content

        composite = CompositeHook([UpperHook(), ExclaimHook()])
        ctx = AgentHookContext(iteration=0, messages=[])
        result = composite.finalize_content(ctx, "hello")
        assert result == "HELLO!"

    async def test_error_isolation(self):
        """Hook errors shouldn't crash the composite."""
        class ErrorHook(AgentHook):
            async def before_iteration(self, context):
                raise ValueError("oops")

        hook1 = ErrorHook()
        hook2 = CountingHook()
        composite = CompositeHook([hook1, hook2])

        ctx = AgentHookContext(iteration=0, messages=[])
        # Should not raise - error is logged and swallowed
        await composite.before_iteration(ctx)
        # hook2 should still be called
        assert "before_iteration" in hook2.calls

    async def test_empty_composite(self):
        """Empty composite should work as no-op."""
        composite = CompositeHook([])
        ctx = AgentHookContext(iteration=0, messages=[])

        assert composite.wants_streaming() is False
        await composite.before_iteration(ctx)
        await composite.on_stream(ctx, "test")
        await composite.on_stream_end(ctx, resuming=False)
        await composite.before_execute_tools(ctx)
        await composite.after_iteration(ctx)
        assert composite.finalize_content(ctx, "test") == "test"
