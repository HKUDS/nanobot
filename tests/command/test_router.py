"""Unit tests for CommandRouter."""

import pytest

from blackcat.command.router import CommandContext, CommandRouter


class FakeMessage:
    """Minimal fake message for testing."""

    def __init__(self, content: str, channel: str = "cli", chat_id: str = "test"):
        self.content = content
        self.channel = channel
        self.chat_id = chat_id
        self.sender_id = "user"
        self.session_key = f"{channel}:{chat_id}"
        self.metadata = {}


class TestCommandContext:
    """Tests for CommandContext dataclass."""

    def test_context_attrs(self):
        """Context should hold all needed attributes."""
        msg = FakeMessage("/test arg")
        ctx = CommandContext(msg=msg, session=None, key="cli:test", raw="/test arg", loop=None)

        assert ctx.msg == msg
        assert ctx.session is None
        assert ctx.key == "cli:test"
        assert ctx.raw == "/test arg"
        assert ctx.args == ""


class TestCommandRouter:
    """Tests for CommandRouter."""

    @pytest.fixture
    def router(self):
        """Create a fresh router for each test."""
        return CommandRouter()

    @pytest.mark.asyncio
    async def test_exact_command(self, router):
        """Exact commands should match exactly."""
        called = []

        async def handler(ctx):
            called.append("exact")

        router.exact("/stop", handler)

        msg = FakeMessage("/stop")
        ctx = CommandContext(msg=msg, session=None, key="cli:test", raw="/stop", loop=None)
        result = await router.dispatch(ctx)

        assert result is None  # handler returns None
        assert called == ["exact"]

    @pytest.mark.asyncio
    async def test_exact_command_no_match(self, router):
        """Exact commands shouldn't match partial."""
        called = []

        async def handler(ctx):
            called.append("exact")

        router.exact("/stop", handler)

        msg = FakeMessage("/stop now")
        ctx = CommandContext(msg=msg, session=None, key="cli:test", raw="/stop now", loop=None)
        result = await router.dispatch(ctx)

        assert result is None
        assert called == []  # handler not called

    @pytest.mark.asyncio
    async def test_prefix_command(self, router):
        """Prefix commands should match start of message."""
        called = []

        async def handler(ctx):
            called.append(ctx.args)

        router.prefix("/team ", handler)

        msg = FakeMessage("/team add @user")
        ctx = CommandContext(msg=msg, session=None, key="cli:test", raw="/team add @user", loop=None)
        result = await router.dispatch(ctx)

        assert result is None
        assert called == ["add @user"]

    @pytest.mark.asyncio
    async def test_prefix_command_longest_first(self, router):
        """Longer prefixes should be checked first."""
        called = []

        async def short_handler(ctx):
            called.append("short")
            return "short"

        async def long_handler(ctx):
            called.append("long")
            return "long"

        router.prefix("/team ", short_handler)
        router.prefix("/team add ", long_handler)  # This is longer, should be checked first

        msg = FakeMessage("/team add user")
        ctx = CommandContext(msg=msg, session=None, key="cli:test", raw="/team add user", loop=None)
        result = await router.dispatch(ctx)

        assert result == "long"
        assert called == ["long"]

    @pytest.mark.asyncio
    async def test_priority_command(self, router):
        """Priority commands should be checked before dispatch."""
        called = []

        async def handler(ctx):
            called.append("priority")

        router.priority("/stop", handler)

        # is_priority strips whitespace before matching
        assert router.is_priority("/stop") is True
        assert router.is_priority("/stop ") is True  # whitespace is stripped
        assert router.is_priority("/STOP") is True  # case insensitive
        assert router.is_priority("/other") is False

        msg = FakeMessage("/stop")
        ctx = CommandContext(msg=msg, session=None, key="cli:test", raw="/stop", loop=None)
        result = await router.dispatch_priority(ctx)

        assert result is None
        assert called == ["priority"]

    @pytest.mark.asyncio
    async def test_interceptor(self, router):
        """Interceptors should be called when no exact/prefix match."""
        called = []

        async def interceptor(ctx):
            called.append("intercept")
            return "intercepted"

        router.intercept(interceptor)

        msg = FakeMessage("/unknown")
        ctx = CommandContext(msg=msg, session=None, key="cli:test", raw="/unknown", loop=None)
        result = await router.dispatch(ctx)

        assert result == "intercepted"
        assert called == ["intercept"]

    @pytest.mark.asyncio
    async def test_interceptor_skipped_if_exact_match(self, router):
        """Interceptors should not be called if exact/prefix matches."""
        called = []

        async def handler(ctx):
            called.append("handler")
            return "handled"

        async def interceptor(ctx):
            called.append("intercept")
            return "intercepted"

        router.exact("/test", handler)
        router.intercept(interceptor)

        msg = FakeMessage("/test")
        ctx = CommandContext(msg=msg, session=None, key="cli:test", raw="/test", loop=None)
        result = await router.dispatch(ctx)

        assert result == "handled"
        assert called == ["handler"]
        assert "intercept" not in called

    @pytest.mark.asyncio
    async def test_case_insensitive(self, router):
        """Commands should match case-insensitively."""
        called = []

        async def handler(ctx):
            called.append("matched")

        router.exact("/stop", handler)

        for raw in ["/STOP", "/Stop", "/StOp"]:
            called.clear()
            msg = FakeMessage(raw)
            ctx = CommandContext(msg=msg, session=None, key="cli:test", raw=raw, loop=None)
            await router.dispatch(ctx)
            assert called == ["matched"], f"Failed for {raw}"

    @pytest.mark.asyncio
    async def test_no_match_returns_none(self, router):
        """No match should return None."""
        msg = FakeMessage("/unknown command")
        ctx = CommandContext(msg=msg, session=None, key="cli:test", raw="/unknown command", loop=None)
        result = await router.dispatch(ctx)
        assert result is None

    @pytest.mark.asyncio
    async def test_priority_before_dispatch(self, router):
        """Priority commands can be dispatched without the lock."""
        called = []

        async def handler(ctx):
            called.append("priority")

        router.priority("/restart", handler)

        msg = FakeMessage("/restart")
        ctx = CommandContext(msg=msg, session=None, key="cli:test", raw="/restart", loop=None)

        # dispatch_priority should work
        result = await router.dispatch_priority(ctx)
        assert result is None
        assert called == ["priority"]

        # Regular dispatch should not match (priority is separate)
        called.clear()
        result = await router.dispatch(ctx)
        assert result is None
        assert called == []
