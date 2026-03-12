"""Tests for nanobot.agent.tool_executor — parallel/sequential batch execution."""

from __future__ import annotations

from typing import Any

from nanobot.agent.tool_executor import ToolExecutor
from nanobot.agent.tools.base import Tool, ToolResult
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.providers.base import ToolCallRequest

# ---------------------------------------------------------------------------
# Stub tools
# ---------------------------------------------------------------------------


class _ReadOnlyTool(Tool):
    readonly = True

    def __init__(self, tool_name: str = "ro_tool", output: str = "ok"):
        self._name = tool_name
        self._output = output

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "readonly"

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult.ok(self._output)


class _WriteTool(Tool):
    readonly = False

    def __init__(self, tool_name: str = "wr_tool", output: str = "written"):
        self._name = tool_name
        self._output = output

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "write"

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult.ok(self._output)


class _ErrorTool(Tool):
    readonly = True

    @property
    def name(self) -> str:
        return "err_tool"

    @property
    def description(self) -> str:
        return "always errors"

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> ToolResult:
        raise RuntimeError("boom")


class _OrderTracker(Tool):
    """Records the order in which tools execute."""

    readonly = False

    def __init__(self, tool_name: str, log: list[str]):
        self._name = tool_name
        self._log = log

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return ""

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> ToolResult:
        self._log.append(self._name)
        return ToolResult.ok(self._name)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tc(name: str, **kwargs: Any) -> ToolCallRequest:
    return ToolCallRequest(id="c1", name=name, arguments=kwargs)


def _make_executor(*tools: Tool) -> ToolExecutor:
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    return ToolExecutor(reg)


# ---------------------------------------------------------------------------
# execute_batch tests
# ---------------------------------------------------------------------------


class TestExecuteBatch:
    async def test_empty_batch(self):
        exe = _make_executor()
        results = await exe.execute_batch([])
        assert results == []

    async def test_single_readonly(self):
        exe = _make_executor(_ReadOnlyTool())
        results = await exe.execute_batch([_tc("ro_tool")])
        assert len(results) == 1
        assert results[0].success
        assert results[0].output == "ok"

    async def test_single_write(self):
        exe = _make_executor(_WriteTool())
        results = await exe.execute_batch([_tc("wr_tool")])
        assert len(results) == 1
        assert results[0].success
        assert results[0].output == "written"

    async def test_consecutive_readonly_parallel(self):
        """Multiple consecutive readonly tools should be gathered in parallel."""
        exe = _make_executor(
            _ReadOnlyTool("r1", "a"),
            _ReadOnlyTool("r2", "b"),
            _ReadOnlyTool("r3", "c"),
        )
        results = await exe.execute_batch([_tc("r1"), _tc("r2"), _tc("r3")])
        assert [r.output for r in results] == ["a", "b", "c"]

    async def test_write_breaks_parallel_batch(self):
        """A write tool between readonly tools creates separate batches."""
        log: list[str] = []

        class _ROTracker(Tool):
            readonly = True

            def __init__(self, tool_name: str):
                self._name = tool_name

            @property
            def name(self) -> str:
                return self._name

            @property
            def description(self) -> str:
                return ""

            @property
            def parameters(self) -> dict[str, Any]:
                return {"type": "object", "properties": {}}

            async def execute(self, **kwargs: Any) -> ToolResult:
                log.append(self._name)
                return ToolResult.ok(self._name)

        exe = _make_executor(
            _ROTracker("r1"),
            _OrderTracker("w1", log),
            _ROTracker("r2"),
        )
        results = await exe.execute_batch([_tc("r1"), _tc("w1"), _tc("r2")])
        assert len(results) == 3
        # w1 must come after r1 and before r2
        assert log.index("w1") > log.index("r1")
        assert log.index("r2") > log.index("w1")

    async def test_sequential_writes_preserve_order(self):
        log: list[str] = []
        exe = _make_executor(
            _OrderTracker("w1", log),
            _OrderTracker("w2", log),
            _OrderTracker("w3", log),
        )
        results = await exe.execute_batch([_tc("w1"), _tc("w2"), _tc("w3")])
        assert log == ["w1", "w2", "w3"]
        assert all(r.success for r in results)

    async def test_exception_in_parallel_batch(self):
        """An exception in one readonly tool doesn't break others."""
        exe = _make_executor(
            _ReadOnlyTool("r1", "ok"),
            _ErrorTool(),
        )
        results = await exe.execute_batch([_tc("r1"), _tc("err_tool")])
        assert results[0].success
        assert not results[1].success
        assert "boom" in results[1].output

    async def test_unknown_tool_treated_as_write(self):
        """A tool call for an unregistered name is treated as non-readonly."""
        exe = _make_executor()
        results = await exe.execute_batch([_tc("missing_tool")])
        assert len(results) == 1
        # ToolRegistry.execute returns a ToolResult.fail for unknown tools
        assert not results[0].success


# ---------------------------------------------------------------------------
# format_hint tests
# ---------------------------------------------------------------------------


class TestFormatHint:
    def test_simple_name(self):
        hint = ToolExecutor.format_hint([_tc("list_dir")])
        assert hint == "list_dir"

    def test_with_string_arg(self):
        hint = ToolExecutor.format_hint([_tc("read_file", path="/src/main.py")])
        assert hint == 'read_file("/src/main.py")'

    def test_truncation(self):
        long_val = "a" * 60
        hint = ToolExecutor.format_hint([_tc("search", query=long_val)])
        assert "…" in hint
        assert len(hint) < 80

    def test_non_string_arg(self):
        hint = ToolExecutor.format_hint([_tc("count", n=42)])
        assert hint == "count"

    def test_multiple(self):
        hint = ToolExecutor.format_hint([_tc("a"), _tc("b")])
        assert hint == "a, b"

    def test_empty(self):
        hint = ToolExecutor.format_hint([])
        assert hint == ""


# ---------------------------------------------------------------------------
# Registry delegation tests
# ---------------------------------------------------------------------------


class TestRegistryDelegation:
    def test_register_and_get(self):
        exe = _make_executor()
        tool = _ReadOnlyTool("t1")
        exe.register(tool)
        assert exe.get("t1") is tool

    def test_get_missing(self):
        exe = _make_executor()
        assert exe.get("nonexistent") is None

    def test_has(self):
        exe = _make_executor(_ReadOnlyTool("t1"))
        assert exe.has("t1")
        assert not exe.has("nope")

    def test_unregister(self):
        exe = _make_executor(_ReadOnlyTool("t1"))
        exe.unregister("t1")
        assert not exe.has("t1")

    def test_unregister_missing_noop(self):
        exe = _make_executor()
        exe.unregister("nope")  # should not raise

    def test_get_definitions(self):
        exe = _make_executor(_ReadOnlyTool("t1"), _WriteTool("t2"))
        defs = exe.get_definitions()
        assert len(defs) == 2

    def test_tool_names(self):
        exe = _make_executor(_ReadOnlyTool("b"), _WriteTool("a"))
        names = exe.tool_names
        assert set(names) == {"a", "b"}

    def test_len(self):
        exe = _make_executor(_ReadOnlyTool("t1"), _WriteTool("t2"))
        assert len(exe) == 2

    def test_tools_dict_property(self):
        """The _tools property allows save/restore of registry state."""
        exe = _make_executor(_ReadOnlyTool("t1"))
        saved = exe._tools
        assert "t1" in saved
        # Clear and restore
        exe._tools = {}
        assert len(exe) == 0
        exe._tools = saved
        assert exe.has("t1")
