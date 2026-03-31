"""Shared execution loop for tool-using agents."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from nanobot.agent.tools.registry import ToolRegistry
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from nanobot.utils.helpers import build_assistant_message

_DEFAULT_MAX_ITERATIONS_MESSAGE = (
    "I reached the maximum number of tool call iterations ({max_iterations}) "
    "without completing the task. You can try breaking the task into smaller steps."
)
_DEFAULT_ERROR_MESSAGE = "Sorry, I encountered an error calling the AI model."


@dataclass(slots=True)
class AgentRunSpec:
    """Configuration for a single agent execution."""

    initial_messages: list[dict[str, Any]]
    tools: ToolRegistry
    model: str
    max_iterations: int
    temperature: float | None = None
    max_tokens: int | None = None
    reasoning_effort: str | None = None
    on_stream: Callable[[str], Awaitable[None]] | None = None
    on_stream_end: Callable[..., Awaitable[None]] | None = None
    on_tool_calls: Callable[[LLMResponse], Awaitable[None] | None] | None = None
    before_execute_tools: Callable[[list[ToolCallRequest]], Awaitable[None] | None] | None = None
    finalize_content: Callable[[str | None], str | None] | None = None
    error_message: str | None = _DEFAULT_ERROR_MESSAGE
    max_iterations_message: str | None = None
    concurrent_tools: bool = False
    fail_on_tool_error: bool = False
    # context pruning: transient softTrim/hardClear before each LLM call
    pruner: Any | None = None               # ContextPruner | None
    context_window_chars: int = 262144 * 4  # used by pruner


@dataclass(slots=True)
class AgentRunResult:
    """Outcome of a shared agent execution."""

    final_content: str | None
    messages: list[dict[str, Any]]
    tools_used: list[str] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    elapsed_ms: int = 0
    llm_elapsed_ms: int = 0
    stop_reason: str = "completed"
    error: str | None = None
    tool_events: list[dict[str, str]] = field(default_factory=list)


class AgentRunner:
    """Run a tool-capable LLM loop without product-layer concerns."""

    def __init__(self, provider: LLMProvider):
        self.provider = provider

    async def run(self, spec: AgentRunSpec) -> AgentRunResult:
        import time as _time
        _t0 = _time.monotonic()
        _llm_ms = 0
        messages = list(spec.initial_messages)
        final_content: str | None = None
        tools_used: list[str] = []
        usage = {"prompt_tokens": 0, "completion_tokens": 0}
        error: str | None = None
        stop_reason = "completed"
        tool_events: list[dict[str, str]] = []

        for _ in range(spec.max_iterations):
            # transient context pruning（每次 LLM call 前轻量修剪 tool results）
            if spec.pruner is not None:
                messages = spec.pruner.prune(messages, context_window_chars=spec.context_window_chars)

            kwargs: dict[str, Any] = {
                "messages": messages,
                "tools": spec.tools.get_definitions(),
                "model": spec.model,
            }
            if spec.temperature is not None:
                kwargs["temperature"] = spec.temperature
            if spec.max_tokens is not None:
                kwargs["max_tokens"] = spec.max_tokens
            if spec.reasoning_effort is not None:
                kwargs["reasoning_effort"] = spec.reasoning_effort

            _llm_t0 = _time.monotonic()
            if spec.on_stream:
                response = await self.provider.chat_stream_with_retry(
                    **kwargs,
                    on_content_delta=spec.on_stream,
                )
            else:
                response = await self.provider.chat_with_retry(**kwargs)
            _llm_ms += int((_time.monotonic() - _llm_t0) * 1000)

            raw_usage = response.usage or {}
            for k, v in raw_usage.items():
                if isinstance(v, (int, float)):
                    usage[k] = usage.get(k, 0) + int(v)

            if response.has_tool_calls:
                if spec.on_stream_end:
                    await spec.on_stream_end(resuming=True)
                if spec.on_tool_calls:
                    maybe = spec.on_tool_calls(response)
                    if maybe is not None:
                        await maybe

                messages.append(build_assistant_message(
                    response.content or "",
                    tool_calls=[tc.to_openai_tool_call() for tc in response.tool_calls],
                    reasoning_content=response.reasoning_content,
                    thinking_blocks=response.thinking_blocks,
                ))
                tools_used.extend(tc.name for tc in response.tool_calls)

                if spec.before_execute_tools:
                    maybe = spec.before_execute_tools(response.tool_calls)
                    if maybe is not None:
                        await maybe

                results, new_events, fatal_error = await self._execute_tools(spec, response.tool_calls)
                tool_events.extend(new_events)
                if fatal_error is not None:
                    error = f"Error: {type(fatal_error).__name__}: {fatal_error}"
                    stop_reason = "tool_error"
                    break
                for tool_call, result in zip(response.tool_calls, results):
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.name,
                        "content": result,
                    })
                continue

            if spec.on_stream_end:
                await spec.on_stream_end(resuming=False)

            clean = spec.finalize_content(response.content) if spec.finalize_content else response.content
            if response.finish_reason == "error":
                final_content = clean or spec.error_message or _DEFAULT_ERROR_MESSAGE
                stop_reason = "error"
                error = final_content
                break

            messages.append(build_assistant_message(
                clean,
                reasoning_content=response.reasoning_content,
                thinking_blocks=response.thinking_blocks,
            ))
            final_content = clean
            break
        else:
            stop_reason = "max_iterations"
            template = spec.max_iterations_message or _DEFAULT_MAX_ITERATIONS_MESSAGE
            final_content = template.format(max_iterations=spec.max_iterations)

        _elapsed_ms = int((_time.monotonic() - _t0) * 1000)
        return AgentRunResult(
            final_content=final_content,
            messages=messages,
            tools_used=tools_used,
            usage=usage,
            elapsed_ms=_elapsed_ms,
            llm_elapsed_ms=_llm_ms,
            stop_reason=stop_reason,
            error=error,
            tool_events=tool_events,
        )

    async def _execute_tools(
        self,
        spec: AgentRunSpec,
        tool_calls: list[ToolCallRequest],
    ) -> tuple[list[Any], list[dict[str, str]], BaseException | None]:
        if spec.concurrent_tools:
            tool_results = await asyncio.gather(*(
                self._run_tool(spec, tool_call)
                for tool_call in tool_calls
            ))
        else:
            tool_results = [
                await self._run_tool(spec, tool_call)
                for tool_call in tool_calls
            ]

        results: list[Any] = []
        events: list[dict[str, str]] = []
        fatal_error: BaseException | None = None
        for result, event, error in tool_results:
            results.append(result)
            events.append(event)
            if error is not None and fatal_error is None:
                fatal_error = error
        return results, events, fatal_error

    async def _run_tool(
        self,
        spec: AgentRunSpec,
        tool_call: ToolCallRequest,
    ) -> tuple[Any, dict[str, str], BaseException | None]:
        try:
            result = await spec.tools.execute(tool_call.name, tool_call.arguments)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            event = {
                "name": tool_call.name,
                "status": "error",
                "detail": str(exc),
            }
            if spec.fail_on_tool_error:
                return f"Error: {type(exc).__name__}: {exc}", event, exc
            return f"Error: {type(exc).__name__}: {exc}", event, None

        detail = "" if result is None else str(result)
        detail = detail.replace("\n", " ").strip()
        if not detail:
            detail = "(empty)"
        elif len(detail) > 120:
            detail = detail[:120] + "..."
        return result, {
            "name": tool_call.name,
            "status": "error" if isinstance(result, str) and result.startswith("Error") else "ok",
            "detail": detail,
        }, None
