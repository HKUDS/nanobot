from __future__ import annotations

from typing import Any

from nanobot.errors import ToolExecutionError
from nanobot.tools.base import Tool, ToolResult
from nanobot.tools.registry import ToolRegistry


class _OkTool(Tool):
    readonly = True

    @property
    def name(self) -> str:
        return "ok_tool"

    @property
    def description(self) -> str:
        return "ok"

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"x": {"type": "string"}}}

    async def execute(self, **kwargs: Any) -> str | ToolResult:
        return "done"


class _StringErrorTool(_OkTool):
    @property
    def name(self) -> str:
        return "string_error"

    async def execute(self, **kwargs: Any) -> str | ToolResult:
        return "Error: failed"


class _ValidationTool(_OkTool):
    @property
    def name(self) -> str:
        return "validation_tool"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["count"],
            "properties": {"count": {"type": "integer", "minimum": 2}},
        }


class _RaiseTypedTool(_OkTool):
    @property
    def name(self) -> str:
        return "typed_raise"

    async def execute(self, **kwargs: Any) -> str | ToolResult:
        raise ToolExecutionError(self.name, "blocked", error_type="permission")


class _RaiseUnknownTool(_OkTool):
    readonly = False

    @property
    def name(self) -> str:
        return "unknown_raise"

    async def execute(self, **kwargs: Any) -> str | ToolResult:
        raise RuntimeError("boom")


async def test_not_found_and_membership_helpers() -> None:
    reg = ToolRegistry()
    out = await reg.execute("missing", {})
    assert out.success is False
    assert out.metadata["error_type"] == "not_found"
    assert len(reg) == 0
    assert "missing" not in reg


async def test_execute_success_and_string_error_wrapping() -> None:
    reg = ToolRegistry()
    reg.register(_OkTool())
    reg.register(_StringErrorTool())

    ok = await reg.execute("ok_tool", {"x": "a"})
    assert ok.success is True
    assert ok.output == "done"

    err = await reg.execute("string_error", {})
    assert err.success is False
    assert err.output.endswith(reg._HINT)


async def test_validation_error_wrapping() -> None:
    reg = ToolRegistry()
    reg.register(_ValidationTool())
    out = await reg.execute("validation_tool", {"count": 1})
    assert out.success is False
    assert out.metadata["error_type"] == "validation"
    assert out.output.endswith(reg._HINT)


async def test_typed_and_unknown_exception_paths_and_unregister() -> None:
    reg = ToolRegistry()
    reg.register(_RaiseTypedTool())
    reg.register(_RaiseUnknownTool())

    typed = await reg.execute("typed_raise", {})
    assert typed.success is False
    assert typed.metadata["error_type"] == "permission"

    unknown = await reg.execute("unknown_raise", {})
    assert unknown.success is False
    assert unknown.metadata["error_type"] == "unknown"
    assert "Error executing unknown_raise" in unknown.output

    defs = reg.get_definitions()
    assert len(defs) == 2
    assert reg.has("typed_raise") is True
    assert reg.get("typed_raise") is not None
    reg.unregister("typed_raise")
    assert reg.has("typed_raise") is False


def test_snapshot_and_restore() -> None:
    """snapshot() returns a copy; restore() replaces the tool set (AR-M2)."""
    reg = ToolRegistry()
    reg.register(_OkTool())

    snap = reg.snapshot()
    assert "ok_tool" in snap

    # Modifying the registry after snapshot must not affect the snapshot
    reg.unregister("ok_tool")
    assert not reg.has("ok_tool")
    assert "ok_tool" in snap

    # Restore puts the tool back
    reg.restore(snap)
    assert reg.has("ok_tool")


def test_snapshot_is_shallow_copy() -> None:
    """snapshot() returns a dict copy, not a reference to the internal dict."""
    reg = ToolRegistry()
    reg.register(_OkTool())

    snap = reg.snapshot()
    # Mutating the snapshot dict must not affect the registry
    del snap["ok_tool"]
    assert reg.has("ok_tool"), "Registry must not be affected by mutating the snapshot"
