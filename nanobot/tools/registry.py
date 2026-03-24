"""Tool registry for dynamic tool management.

``ToolRegistry`` is the central hub for agent tool execution.  It handles:

- **Registration** — tools are added via ``register()``; duplicates overwrite.
- **Schema export** — ``get_tools_schema()`` returns OpenAI-compatible
  function definitions for LLM tool-use prompting.
- **Validation** — incoming tool-call arguments are validated against the
  tool's JSON Schema ``parameters`` before execution.
- **Execution** — ``execute()`` runs a single tool; the agent loop decides
  whether to run readonly tools in parallel (``asyncio.gather``) or
  sequentially for write tools.
- **Error wrapping** — failures are caught and wrapped in ``ToolResult.fail``
  with a retry hint appended so the LLM can self-correct.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.errors import ToolExecutionError, ToolNotFoundError, ToolValidationError
from nanobot.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from nanobot.tools.result_cache import ToolResultCache, _ChatProvider


class ToolRegistry:
    """
    Registry for agent tools.

    Allows dynamic registration and execution of tools.
    """

    _HINT = "\n\n[Analyze the error above and try a different approach.]"
    _SUMMARY_THRESHOLD = 3000  # chars — cache results larger than this

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._write_lock = asyncio.Lock()
        self._cache: ToolResultCache | None = None
        self._summary_provider: _ChatProvider | None = None
        self._summary_model: str | None = None

    def set_cache(
        self,
        cache: ToolResultCache,
        provider: _ChatProvider | None = None,
        summary_model: str | None = None,
    ) -> None:
        """Attach a result cache and optional LLM summary provider."""
        self._cache = cache
        self._summary_provider = provider
        self._summary_model = summary_model

    def register(self, tool: Tool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        """Unregister a tool by name."""
        self._tools.pop(name, None)

    def snapshot(self) -> dict[str, Tool]:
        """Return a shallow copy of the current tool set for later restore."""
        return dict(self._tools)

    def restore(self, snap: dict[str, Tool]) -> None:
        """Replace the current tool set with a previously captured snapshot."""
        self._tools = snap

    def get(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def get_all(self) -> dict[str, Tool]:
        """Return a view of all registered tools keyed by name."""
        return self._tools

    def has(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    def get_definitions(self) -> list[dict[str, Any]]:
        """Get tool definitions in OpenAI format, excluding unavailable tools."""
        defs = []
        for tool in self._tools.values():
            available, _reason = tool.check_available()
            if available:
                defs.append(tool.to_schema())
        return defs

    def get_unavailable_summary(self) -> str:
        """Return a human-readable summary of unavailable tools for the system prompt."""
        lines: list[str] = []
        for tool in self._tools.values():
            available, reason = tool.check_available()
            if not available:
                lines.append(f"- {tool.name}: {reason or 'unavailable'}")
        return "\n".join(lines)

    async def execute(self, name: str, params: dict[str, Any]) -> ToolResult:
        """Execute a tool by name with given parameters.

        Always returns a ``ToolResult``.  Legacy tools that still return a
        bare string are automatically wrapped.  Non-readonly tools acquire
        a write lock so parallel delegations don't interleave writes.

        When a cache is attached, duplicate calls for the same tool+args
        return the cached summary without re-executing.
        """
        tool = self._tools.get(name)
        if not tool:
            not_found_err = ToolNotFoundError(name, self.tool_names)
            return ToolResult.fail(str(not_found_err), error_type="not_found")

        # Duplicate-call guard: return cached summary if available
        if self._cache and tool.readonly and tool.cacheable:
            hit_key = self._cache.has(name, params)
            if hit_key:
                entry = self._cache.get(hit_key)
                if entry:
                    logger.info("Cache HIT for {}(…) → {}", name, hit_key)
                    return ToolResult.ok(
                        entry.summary,
                        cache_key=hit_key,
                        cached=True,
                        summary=entry.summary,
                    )

        if tool.readonly:
            return await self._execute_inner(name, tool, params)

        async with self._write_lock:
            return await self._execute_inner(name, tool, params)

    async def _execute_inner(self, name: str, tool: Tool, params: dict[str, Any]) -> ToolResult:
        """Run validation and execute, wrapping errors."""
        from nanobot.metrics import tool_calls_total, tool_latency_seconds
        from nanobot.observability.langfuse import tool_span
        from nanobot.observability.tracing import bind_trace

        t0 = time.monotonic()

        async with tool_span(name=name, input=params):
            try:
                errors = tool.validate_params(params)
                if errors:
                    validation_err = ToolValidationError(name, errors)
                    bind_trace().debug(
                        "Tool {} validation_error duration_ms={:.0f}",
                        name,
                        (time.monotonic() - t0) * 1000,
                    )
                    return ToolResult.fail(
                        str(validation_err) + self._HINT, error_type="validation"
                    )

                raw = await tool.execute(**params)

                # Normalise into ToolResult (supports legacy str returns)
                if isinstance(raw, ToolResult):
                    result = raw
                elif isinstance(raw, str):
                    # Backward compat: detect old-style "Error…" strings.
                    if raw.startswith("Error"):
                        result = ToolResult.fail(raw)
                    else:
                        result = ToolResult.ok(raw)
                else:
                    result = ToolResult.ok(str(raw))

                # Append retry hint for failures
                if not result.success:
                    if not result.output.endswith(self._HINT):
                        result.output += self._HINT

                elapsed = time.monotonic() - t0
                duration_ms = elapsed * 1000
                bind_trace().debug(
                    "Tool {} success={} duration_ms={:.0f}",
                    name,
                    result.success,
                    duration_ms,
                )

                # Prometheus metrics
                tool_calls_total.labels(tool_name=name, success=str(result.success)).inc()
                tool_latency_seconds.labels(tool_name=name).observe(elapsed)

                # Cache large successful results and generate summary
                if (
                    result.success
                    and self._cache
                    and tool.cacheable
                    and len(result.output) > self._SUMMARY_THRESHOLD
                ):
                    if tool.summarize:
                        _, result = await self._cache.store_with_summary(
                            name,
                            params,
                            result,
                            provider=self._summary_provider,
                            model=self._summary_model,
                        )
                    else:
                        _, result = self._cache.store_only(name, params, result)

                return result

            except ToolExecutionError as e:
                elapsed = time.monotonic() - t0
                bind_trace().debug(
                    "Tool {} error={} duration_ms={:.0f}",
                    name,
                    e.error_type,
                    elapsed * 1000,
                )
                tool_calls_total.labels(tool_name=name, success="False").inc()
                tool_latency_seconds.labels(tool_name=name).observe(elapsed)
                return ToolResult.fail(str(e) + self._HINT, error_type=e.error_type)
            except Exception as e:  # crash-barrier: user-provided tool execution
                elapsed = time.monotonic() - t0
                bind_trace().exception(
                    "Tool {} error=unknown duration_ms={:.0f}",
                    name,
                    elapsed * 1000,
                )
                tool_calls_total.labels(tool_name=name, success="False").inc()
                tool_latency_seconds.labels(tool_name=name).observe(elapsed)
                return ToolResult.fail(
                    f"Error executing {name}: {str(e)}" + self._HINT, error_type="unknown"
                )

    @property
    def tool_names(self) -> list[str]:
        """Get list of registered tool names."""
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
