"""IT-11: ToolResultCache with ToolRegistry.

Verifies that the cache prevents duplicate tool execution for readonly
cacheable tools returning large output. Does not require LLM API key.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nanobot.tools.base import Tool, ToolResult
from nanobot.tools.registry import ToolRegistry
from nanobot.tools.result_cache import ToolResultCache

pytestmark = pytest.mark.integration

_LARGE_OUTPUT = "x" * 4000  # above the ToolRegistry._SUMMARY_THRESHOLD (3000)


# ---------------------------------------------------------------------------
# Stub tool that counts executions
# ---------------------------------------------------------------------------


class _LargeOutputTool(Tool):
    """Readonly, cacheable tool that returns large output and tracks call count."""

    readonly: bool = True
    cacheable: bool = True
    summarize: bool = False  # skip LLM summary — no provider in tests

    def __init__(self) -> None:
        self._call_count = 0

    @property
    def name(self) -> str:
        return "large_output"

    @property
    def description(self) -> str:
        return "Returns a large string for cache testing."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        self._call_count += 1
        return ToolResult.ok(_LARGE_OUTPUT)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestToolResultCacheIntegration:
    async def test_second_call_returns_cached_result(self, tmp_path: Path) -> None:
        """Duplicate call for the same tool+args returns cached output."""
        tool = _LargeOutputTool()
        reg = ToolRegistry()
        reg.register(tool)
        cache = ToolResultCache(tmp_path)
        reg.set_cache(cache)

        # First call — executes the tool
        result1 = await reg.execute("large_output", {"query": "test"})
        assert result1.success
        assert tool._call_count == 1

        # Second call — should hit cache
        result2 = await reg.execute("large_output", {"query": "test"})
        assert result2.success
        assert tool._call_count == 1, "Tool should not have been called again"

    async def test_different_args_bypass_cache(self, tmp_path: Path) -> None:
        """Different arguments produce a separate cache entry and re-execute."""
        tool = _LargeOutputTool()
        reg = ToolRegistry()
        reg.register(tool)
        cache = ToolResultCache(tmp_path)
        reg.set_cache(cache)

        await reg.execute("large_output", {"query": "alpha"})
        assert tool._call_count == 1

        await reg.execute("large_output", {"query": "beta"})
        assert tool._call_count == 2, "Different args should trigger new execution"

    async def test_cache_persists_to_disk(self, tmp_path: Path) -> None:
        """Cache entries are written to disk JSONL file."""
        tool = _LargeOutputTool()
        reg = ToolRegistry()
        reg.register(tool)
        cache = ToolResultCache(tmp_path)
        reg.set_cache(cache)

        await reg.execute("large_output", {"query": "persist"})

        disk_path = tmp_path / "memory" / "tool_cache.jsonl"
        assert disk_path.exists(), "Cache file should be created on disk"
        content = disk_path.read_text(encoding="utf-8")
        assert len(content.strip()) > 0, "Cache file should have content"

    async def test_no_cache_without_set_cache(self, tmp_path: Path) -> None:
        """Without set_cache, every call executes the tool."""
        tool = _LargeOutputTool()
        reg = ToolRegistry()
        reg.register(tool)
        # Intentionally not calling reg.set_cache(...)

        await reg.execute("large_output", {"query": "test"})
        await reg.execute("large_output", {"query": "test"})
        assert tool._call_count == 2, "Without cache, tool executes every time"
