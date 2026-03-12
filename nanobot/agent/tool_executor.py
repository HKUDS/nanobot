"""Parallel / sequential tool-call orchestration.

``ToolExecutor`` sits above ``ToolRegistry`` and decides *how* to run a batch
of tool calls:

- Consecutive **readonly** calls are gathered concurrently.
- **Write** calls execute one-at-a-time, preserving ordering.

This was extracted from ``AgentLoop._execute_tools_parallel`` (ADR-002,
ADR-004) to keep the agent loop focused on orchestration.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import ToolResult
from nanobot.agent.tracing import bind_trace

if TYPE_CHECKING:
    from nanobot.agent.tools.base import Tool
    from nanobot.agent.tools.registry import ToolRegistry
    from nanobot.providers.base import ToolCallRequest


class ToolExecutor:
    """Orchestrates parallel/sequential tool execution over a ToolRegistry."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    # -- delegation to registry ------------------------------------------

    @property
    def _tools(self) -> dict[str, Any]:
        """Expose internal dict for role-based save/restore in AgentLoop."""
        return self._registry._tools

    @_tools.setter
    def _tools(self, value: dict[str, Any]) -> None:
        self._registry._tools = value

    def get(self, name: str) -> Tool | None:
        return self._registry.get(name)

    def has(self, name: str) -> bool:
        return self._registry.has(name)

    def register(self, tool: Tool) -> None:
        return self._registry.register(tool)

    def unregister(self, name: str) -> None:
        return self._registry.unregister(name)

    def get_definitions(self) -> list[dict[str, Any]]:
        return self._registry.get_definitions()

    @property
    def tool_names(self) -> list[str]:
        return self._registry.tool_names

    def __len__(self) -> int:
        return len(self._registry)

    # -- batch execution -------------------------------------------------

    async def execute_batch(
        self,
        tool_calls: list[ToolCallRequest],
    ) -> list[ToolResult]:
        """Execute a batch of tool calls with smart parallelism.

        Read-only tools that appear consecutively are awaited concurrently
        via ``asyncio.gather``.  Write-capable tools run sequentially to
        preserve ordering semantics.
        """
        t0_batch = time.monotonic()
        results: list[ToolResult] = [ToolResult.ok("")] * len(tool_calls)

        i = 0
        while i < len(tool_calls):
            tc = tool_calls[i]
            tool_obj = self._registry.get(tc.name)
            is_readonly = tool_obj.readonly if tool_obj else False

            if is_readonly:
                # Collect consecutive readonly calls into a parallel batch.
                batch_start = i
                while i < len(tool_calls):
                    t = self._registry.get(tool_calls[i].name)
                    if t and t.readonly:
                        i += 1
                    else:
                        break
                batch = tool_calls[batch_start:i]
                coros = [self._registry.execute(t.name, t.arguments) for t in batch]
                batch_results = await asyncio.gather(*coros, return_exceptions=True)
                for j, br in enumerate(batch_results):
                    if isinstance(br, BaseException):
                        results[batch_start + j] = ToolResult.fail(f"Error: {br}")
                    else:
                        results[batch_start + j] = br
            else:
                results[i] = await self._registry.execute(tc.name, tc.arguments)
                i += 1

        failed = sum(1 for r in results if not r.success)
        bind_trace().info(
            "tool_batch_complete | count={} | failed={} | {:.0f}ms",
            len(tool_calls), failed, (time.monotonic() - t0_batch) * 1000,
        )
        return results

    @staticmethod
    def format_hint(tool_calls: list[ToolCallRequest]) -> str:
        """Format tool calls as a concise hint, e.g. ``web_search("query")``."""

        def _fmt(tc: ToolCallRequest) -> str:
            val = next(iter(tc.arguments.values()), None) if tc.arguments else None
            if not isinstance(val, str):
                return tc.name
            return f'{tc.name}("{val[:40]}…")' if len(val) > 40 else f'{tc.name}("{val}")'

        return ", ".join(_fmt(tc) for tc in tool_calls)
