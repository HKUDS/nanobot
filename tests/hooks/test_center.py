"""Tests for HookCenter: registration, emit, short-circuit, cancel, error isolation."""

from __future__ import annotations

import pytest

from nanobot.hooks.center import HookCenter, get_center, reset_center
from nanobot.hooks.context import HookContext, HookResult


def _ctx(**kwargs) -> HookContext:
    return HookContext(data=kwargs)


@pytest.fixture(autouse=True)
def _reset_global():
    reset_center()
    yield
    reset_center()


class TestHookContext:
    def test_create_and_read(self):
        ctx = HookContext(data={"key": "value"})
        assert ctx.get("key") == "value"

    def test_set_and_read(self):
        ctx = _ctx()
        ctx.set("x", 42)
        assert ctx.get("x") == 42

    def test_get_default(self):
        ctx = _ctx()
        assert ctx.get("missing") is None
        assert ctx.get("missing", "fallback") == "fallback"


class TestHookResult:
    def test_continue(self):
        r = HookResult(action="continue")
        assert r.action == "continue"

    def test_cancel(self):
        r = HookResult(action="cancel", reason="unauthorized")
        assert r.action == "cancel"
        assert r.reason == "unauthorized"

    def test_short_circuit(self):
        r = HookResult(action="short_circuit")
        assert r.action == "short_circuit"


class TestHookCenterRegister:
    def test_register_point(self):
        center = HookCenter()
        center.register_point("tool.before_execute", "Before tool execution")
        assert center.has_point("tool.before_execute")

    def test_register_handler_auto_creates_point(self):
        center = HookCenter()

        async def handler(ctx: HookContext) -> None:
            pass

        center.register_handler("my.point", handler)
        assert len(center.get_handlers("my.point")) == 1

    def test_multiple_handlers(self):
        center = HookCenter()

        async def h1(ctx: HookContext) -> None:
            pass

        async def h2(ctx: HookContext) -> None:
            pass

        center.register_handler("p", h1)
        center.register_handler("p", h2)
        assert len(center.get_handlers("p")) == 2

    def test_duplicate_handler_ignored(self):
        center = HookCenter()

        async def h1(ctx: HookContext) -> None:
            pass

        center.register_handler("p", h1)
        center.register_handler("p", h1)
        assert len(center.get_handlers("p")) == 1


class TestHookCenterEmit:
    @pytest.mark.asyncio
    async def test_emit_no_handlers_returns_continue(self):
        center = HookCenter()
        center.register_point("empty.point")
        result = await center.emit("empty.point", _ctx())
        assert result.action == "continue"

    @pytest.mark.asyncio
    async def test_emit_unknown_point_returns_continue(self):
        center = HookCenter()
        result = await center.emit("nonexistent", _ctx())
        assert result.action == "continue"

    @pytest.mark.asyncio
    async def test_emit_calls_handler(self):
        center = HookCenter()
        calls: list[str] = []

        async def handler(ctx: HookContext) -> None:
            calls.append("called")

        center.register_point("test.point")
        center.register_handler("test.point", handler)
        result = await center.emit("test.point", _ctx())
        assert result.action == "continue"
        assert calls == ["called"]

    @pytest.mark.asyncio
    async def test_emit_multiple_handlers_in_order(self):
        center = HookCenter()
        calls: list[str] = []

        async def h1(ctx: HookContext) -> None:
            calls.append("h1")

        async def h2(ctx: HookContext) -> None:
            calls.append("h2")

        center.register_handler("p", h1)
        center.register_handler("p", h2)
        await center.emit("p", _ctx())
        assert calls == ["h1", "h2"]

    @pytest.mark.asyncio
    async def test_emit_handler_returns_none_continues(self):
        center = HookCenter()
        calls: list[str] = []

        async def h1(ctx: HookContext) -> None:
            calls.append("h1")

        async def h2(ctx: HookContext) -> None:
            calls.append("h2")

        center.register_handler("p", h1)
        center.register_handler("p", h2)
        result = await center.emit("p", _ctx())
        assert result.action == "continue"
        assert calls == ["h1", "h2"]

    @pytest.mark.asyncio
    async def test_emit_context_passed_between_handlers(self):
        center = HookCenter()

        async def h1(ctx: HookContext) -> None:
            ctx.set("seen_by_h1", ctx.get("original"))
            ctx.set("from_h1", True)

        async def h2(ctx: HookContext) -> None:
            ctx.set("seen_by_h2", ctx.get("from_h1"))

        center.register_handler("p", h1)
        center.register_handler("p", h2)
        ctx = _ctx(original="hello")
        await center.emit("p", ctx)
        assert ctx.get("seen_by_h1") == "hello"
        assert ctx.get("seen_by_h2") is True

    @pytest.mark.asyncio
    async def test_emit_short_circuit_skips_remaining(self):
        center = HookCenter()
        calls: list[str] = []

        async def h1(ctx: HookContext) -> HookResult:
            calls.append("h1")
            return HookResult(action="short_circuit")

        async def h2(ctx: HookContext) -> None:
            calls.append("h2")

        center.register_handler("p", h1)
        center.register_handler("p", h2)
        result = await center.emit("p", _ctx())
        assert result.action == "short_circuit"
        assert calls == ["h1"]

    @pytest.mark.asyncio
    async def test_emit_cancel(self):
        center = HookCenter()

        async def h1(ctx: HookContext) -> HookResult:
            return HookResult(action="cancel", reason="unauthorized")

        center.register_handler("p", h1)
        result = await center.emit("p", _ctx())
        assert result.action == "cancel"
        assert result.reason == "unauthorized"


class TestHookCenterErrorIsolation:
    @pytest.mark.asyncio
    async def test_handler_exception_does_not_stop_others(self):
        center = HookCenter()
        calls: list[str] = []

        async def bad(ctx: HookContext) -> None:
            raise RuntimeError("boom")

        async def good(ctx: HookContext) -> None:
            calls.append("good")

        center.register_handler("p", bad)
        center.register_handler("p", good)
        result = await center.emit("p", _ctx())
        assert result.action == "continue"
        assert calls == ["good"]

    @pytest.mark.asyncio
    async def test_handler_exception_between_others(self):
        center = HookCenter()
        calls: list[str] = []

        async def h1(ctx: HookContext) -> None:
            calls.append("h1")

        async def bad(ctx: HookContext) -> None:
            raise RuntimeError("boom")

        async def h3(ctx: HookContext) -> None:
            calls.append("h3")

        center.register_handler("p", h1)
        center.register_handler("p", bad)
        center.register_handler("p", h3)
        result = await center.emit("p", _ctx())
        assert result.action == "continue"
        assert calls == ["h1", "h3"]


class TestHookCenterReset:
    @pytest.mark.asyncio
    async def test_reset_clears_everything(self):
        center = HookCenter()
        center.register_point("p", "desc")

        async def handler(ctx: HookContext) -> None:
            pass

        center.register_handler("p", handler)
        center.reset()
        assert not center.has_point("p")
        assert center.get_handlers("p") == []


class TestGlobalCenter:
    def test_get_center_returns_same_instance(self):
        c1 = get_center()
        c2 = get_center()
        assert c1 is c2

    def test_reset_center_creates_new_instance(self):
        c1 = get_center()
        reset_center()
        c2 = get_center()
        assert c1 is not c2
