"""Shared lifecycle hook primitives for agent runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from nanobot.providers.base import LLMResponse, ToolCallRequest


@dataclass(slots=True)
class AgentHookContext:
    """Mutable per-iteration state exposed to runner hooks."""

    iteration: int
    messages: list[dict[str, Any]]
    response: LLMResponse | None = None
    usage: dict[str, int] = field(default_factory=dict)
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    tool_results: list[Any] = field(default_factory=list)
    tool_events: list[dict[str, str]] = field(default_factory=list)
    final_content: str | None = None
    stop_reason: str | None = None
    error: str | None = None


class AgentHook:
    """Minimal lifecycle surface for shared runner customization."""

    def wants_streaming(self) -> bool:
        return False

    async def before_iteration(self, context: AgentHookContext) -> None:
        pass

    async def on_stream(self, context: AgentHookContext, delta: str) -> None:
        pass

    async def on_stream_end(self, context: AgentHookContext, *, resuming: bool) -> None:
        pass

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        pass

    async def after_iteration(self, context: AgentHookContext) -> None:
        pass

    def finalize_content(self, context: AgentHookContext, content: str | None) -> str | None:
        return content


class TraceHook(AgentHook):
    """Hook that logs LLM requests/responses to a file for debugging.

    Records per-iteration details including messages sent, response received,
    token usage, and tool calls. Output is JSON Lines format.
    """

    __slots__ = ("_log_path", "_session_key", "_start_time", "_llm_start_time", "_current_entry")

    def __init__(self, log_path: Any | None = None) -> None:
        self._log_path: Any | None = log_path
        self._session_key: str | None = None
        self._start_time: float | None = None
        self._llm_start_time: float | None = None
        self._current_entry: dict[str, Any] | None = None

    def set_log_path(self, path: Any) -> None:
        """Set or update the log file path (e.g., when session changes)."""
        self._log_path = path

    @property
    def session_key(self) -> str | None:
        return self._session_key

    @session_key.setter
    def session_key(self, value: str) -> None:
        self._session_key = value

    async def before_iteration(self, context: AgentHookContext) -> None:
        """Start timing and capture request messages."""
        import time
        self._start_time = time.monotonic()
        self._llm_start_time = None
        self._current_entry = {
            "iteration": context.iteration,
            "messages": self._sanitize_messages(context.messages),
        }

    async def on_stream(self, context: AgentHookContext, delta: str) -> None:
        """Track that streaming was used."""
        if self._current_entry is not None:
            self._current_entry["streaming"] = True

    async def after_iteration(self, context: AgentHookContext) -> None:
        """Log the complete iteration details after completion."""
        if not self._log_path:
            return

        import json
        import time
        from datetime import datetime

        # Calculate timing
        elapsed_ms = None
        llm_elapsed_ms = None
        if self._start_time is not None:
            elapsed_ms = int((time.monotonic() - self._start_time) * 1000)

        # Build complete log entry. thinking_blocks (Anthropic extended thinking
        # and its encrypted signature) are stripped: they are verbose, opaque,
        # and useless for debugging — the reasoning_content summary is kept.
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "session_key": self._session_key,
            "iteration": context.iteration,
            "stop_reason": context.stop_reason,
            "elapsed_ms": elapsed_ms,
            "usage": context.usage,
            "request": self._current_entry.get("messages", []) if self._current_entry else [],
            "response": {
                "content": context.final_content,
                "reasoning_content": context.response.reasoning_content if context.response else None,
            } if context.response else {"content": context.final_content},
            "tool_calls": [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                for tc in context.tool_calls
            ] if context.tool_calls else [],
            "tool_results_count": len(context.tool_results) if context.tool_results else 0,
            "tool_events": context.tool_events if context.tool_events else [],
        }

        # Reset state
        self._start_time = None
        self._llm_start_time = None
        self._current_entry = None

        try:
            # Append to log file (JSON Lines format)
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.debug("TraceHook failed to write to {}: {}", self._log_path, e)

    def _sanitize_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Replace base64 image payloads with placeholders and drop thinking_blocks.

        thinking_blocks carry Anthropic extended-thinking payloads (including
        12KB+ encrypted signatures). They are volume noise in llm_logs and
        useless for debugging, so they are removed entirely before writing.
        """
        out: list[dict[str, Any]] = []
        for msg in messages:
            cleaned = {k: v for k, v in msg.items() if k != "thinking_blocks"}
            content = cleaned.get("content")
            if isinstance(content, list):
                sanitized: list[dict[str, Any]] = []
                for block in content:
                    if (
                        isinstance(block, dict)
                        and block.get("type") == "image_url"
                        and isinstance(block.get("image_url"), dict)
                        and str(block["image_url"].get("url", "")).startswith("data:")
                    ):
                        path = (block.get("_meta") or {}).get("path", "")
                        sanitized.append({"type": "text", "text": f"[image: {path}]" if path else "[image]"})
                    else:
                        sanitized.append(block)
                cleaned["content"] = sanitized
            out.append(cleaned)
        return out


class CompositeHook(AgentHook):
    """Fan-out hook that delegates to an ordered list of hooks.

    Error isolation: async methods catch and log per-hook exceptions
    so a faulty custom hook cannot crash the agent loop.
    ``finalize_content`` is a pipeline (no isolation — bugs should surface).
    """

    __slots__ = ("_hooks",)

    def __init__(self, hooks: list[AgentHook]) -> None:
        self._hooks = list(hooks)

    def wants_streaming(self) -> bool:
        return any(h.wants_streaming() for h in self._hooks)

    async def _for_each_hook_safe(self, method_name: str, *args: Any, **kwargs: Any) -> None:
        for h in self._hooks:
            try:
                await getattr(h, method_name)(*args, **kwargs)
            except Exception:
                logger.exception("AgentHook.{} error in {}", method_name, type(h).__name__)

    async def before_iteration(self, context: AgentHookContext) -> None:
        await self._for_each_hook_safe("before_iteration", context)

    async def on_stream(self, context: AgentHookContext, delta: str) -> None:
        await self._for_each_hook_safe("on_stream", context, delta)

    async def on_stream_end(self, context: AgentHookContext, *, resuming: bool) -> None:
        await self._for_each_hook_safe("on_stream_end", context, resuming=resuming)

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        await self._for_each_hook_safe("before_execute_tools", context)

    async def after_iteration(self, context: AgentHookContext) -> None:
        await self._for_each_hook_safe("after_iteration", context)

    def finalize_content(self, context: AgentHookContext, content: str | None) -> str | None:
        for h in self._hooks:
            content = h.finalize_content(context, content)
        return content
