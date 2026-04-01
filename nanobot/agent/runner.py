"""Shared execution loop for tool-using agents."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Literal

from nanobot.agent.hook import AgentHook, AgentHookContext, ToolError
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.providers.base import LLMProvider, ToolCallRequest
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
    hook: AgentHook | None = None
    error_message: str | None = _DEFAULT_ERROR_MESSAGE
    max_iterations_message: str | None = None
    concurrent_tools: bool = False
    fail_on_tool_error: bool = False
    mode: Literal["execute", "plan", "verify"] = "execute"


@dataclass(slots=True)
class AgentRunResult:
    """Outcome of a shared agent execution."""

    final_content: str | None
    messages: list[dict[str, Any]]
    tools_used: list[str] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    cumulative_usage: dict[str, int] = field(default_factory=dict)
    stop_reason: str = "completed"
    error: str | None = None
    tool_events: list[dict[str, str]] = field(default_factory=list)


class AgentRunner:
    """Run a tool-capable LLM loop without product-layer concerns."""

    def __init__(self, provider: LLMProvider):
        self.provider = provider

    async def run(self, spec: AgentRunSpec) -> AgentRunResult:
        hook = spec.hook or AgentHook()
        messages = list(spec.initial_messages)
        final_content: str | None = None
        tools_used: list[str] = []
        usage = {"prompt_tokens": 0, "completion_tokens": 0}
        cumulative_usage = {"prompt_tokens": 0, "completion_tokens": 0}
        error: str | None = None
        stop_reason = "completed"
        tool_events: list[dict[str, str]] = []
        error_history: list[ToolError] = []

        # Activate plan mode on the tool registry if requested
        if spec.mode == "plan":
            spec.tools.set_plan_mode(True)
        try:
            final_content, tools_used, usage, cumulative_usage, error, stop_reason, tool_events = (
                await self._run_loop(spec, hook, messages, error_history)
            )
        finally:
            if spec.mode == "plan":
                spec.tools.set_plan_mode(False)

        return AgentRunResult(
            final_content=final_content,
            messages=messages,
            tools_used=tools_used,
            usage=usage,
            cumulative_usage=cumulative_usage,
            stop_reason=stop_reason,
            error=error,
            tool_events=tool_events,
        )

    async def _run_loop(
        self,
        spec: AgentRunSpec,
        hook: AgentHook,
        messages: list[dict[str, Any]],
        error_history: list[ToolError],
    ) -> tuple[str | None, list[str], dict, dict, str | None, str, list]:
        final_content: str | None = None
        tools_used: list[str] = []
        usage = {"prompt_tokens": 0, "completion_tokens": 0}
        cumulative_usage = {"prompt_tokens": 0, "completion_tokens": 0}
        error: str | None = None
        stop_reason = "completed"
        tool_events: list[dict[str, str]] = []

        for iteration in range(spec.max_iterations):
            context = AgentHookContext(
                iteration=iteration, messages=messages,
                error_history=error_history,
            )

            # Inject failure summary into context when tools are repeatedly failing
            failure_summary = spec.tools.get_failure_summary()
            if failure_summary:
                self._inject_failure_context(messages, failure_summary)

            await hook.before_iteration(context)
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

            if hook.wants_streaming():
                async def _stream(delta: str) -> None:
                    await hook.on_stream(context, delta)

                response = await self.provider.chat_stream_with_retry(
                    **kwargs,
                    on_content_delta=_stream,
                )
            else:
                response = await self.provider.chat_with_retry(**kwargs)

            raw_usage = response.usage or {}
            usage = {
                "prompt_tokens": int(raw_usage.get("prompt_tokens", 0) or 0),
                "completion_tokens": int(raw_usage.get("completion_tokens", 0) or 0),
            }
            cumulative_usage["prompt_tokens"] += usage["prompt_tokens"]
            cumulative_usage["completion_tokens"] += usage["completion_tokens"]
            context.response = response
            context.usage = usage
            context.tool_calls = list(response.tool_calls)

            if response.has_tool_calls:
                if hook.wants_streaming():
                    await hook.on_stream_end(context, resuming=True)

                messages.append(build_assistant_message(
                    response.content or "",
                    tool_calls=[tc.to_openai_tool_call() for tc in response.tool_calls],
                    reasoning_content=response.reasoning_content,
                    thinking_blocks=response.thinking_blocks,
                ))
                tools_used.extend(tc.name for tc in response.tool_calls)

                await hook.before_execute_tools(context)

                results, new_events, fatal_error = await self._execute_tools(spec, response.tool_calls)

                # Track errors in history
                for tc, event in zip(response.tool_calls, new_events):
                    if event.get("status") == "error":
                        error_history.append(ToolError(
                            tool_name=tc.name,
                            error_message=event.get("detail", "unknown"),
                            iteration=iteration,
                        ))

                tool_events.extend(new_events)
                context.tool_results = list(results)
                context.tool_events = list(new_events)
                if fatal_error is not None:
                    error = f"Error: {type(fatal_error).__name__}: {fatal_error}"
                    stop_reason = "tool_error"
                    context.error = error
                    context.stop_reason = stop_reason
                    await hook.after_iteration(context)
                    break
                for tool_call, result in zip(response.tool_calls, results):
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.name,
                        "content": result,
                    })
                await hook.after_iteration(context)
                continue

            if hook.wants_streaming():
                await hook.on_stream_end(context, resuming=False)

            clean = hook.finalize_content(context, response.content)
            if response.finish_reason == "error":
                final_content = clean or spec.error_message or _DEFAULT_ERROR_MESSAGE
                stop_reason = "error"
                error = final_content
                context.final_content = final_content
                context.error = error
                context.stop_reason = stop_reason
                await hook.after_iteration(context)
                break

            messages.append(build_assistant_message(
                clean,
                reasoning_content=response.reasoning_content,
                thinking_blocks=response.thinking_blocks,
            ))
            final_content = clean
            context.final_content = final_content
            context.stop_reason = stop_reason
            await hook.after_iteration(context)
            break
        else:
            stop_reason = "max_iterations"
            template = spec.max_iterations_message or _DEFAULT_MAX_ITERATIONS_MESSAGE
            final_content = template.format(max_iterations=spec.max_iterations)

        return final_content, tools_used, usage, cumulative_usage, error, stop_reason, tool_events

    @staticmethod
    def _inject_failure_context(messages: list[dict[str, Any]], summary: str) -> None:
        """Inject a system-level hint about repeated tool failures.

        Appends to the last user message so the model sees it on the next turn
        without polluting the conversation structure.
        """
        hint = (
            "\n\n[Tool Failure Notice] The following tools have been failing repeatedly. "
            "Analyze the root cause before retrying — try a different approach:\n" + summary
        )
        # Find last user message and append
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    msg["content"] = content + hint
                elif isinstance(content, list):
                    msg["content"] = content + [{"type": "text", "text": hint}]
                break

    async def _execute_tools(
        self,
        spec: AgentRunSpec,
        tool_calls: list[ToolCallRequest],
    ) -> tuple[list[Any], list[dict[str, str]], BaseException | None]:
        if spec.concurrent_tools:
            # Smart batching: partition into read-only (concurrent) and write (serial)
            batches = self._partition_tool_calls(spec, tool_calls)
            tool_results: list[tuple] = []
            for is_concurrent, batch in batches:
                if is_concurrent and len(batch) > 1:
                    batch_results = await asyncio.gather(*(
                        self._run_tool(spec, tc) for tc in batch
                    ))
                else:
                    batch_results = [await self._run_tool(spec, tc) for tc in batch]
                tool_results.extend(batch_results)
        else:
            tool_results = [
                await self._run_tool(spec, tool_call)
                for tool_call in tool_calls
            ]

        results: list[Any] = []
        events: list[dict[str, str]] = []
        fatal_error: BaseException | None = None
        for result, event, err in tool_results:
            results.append(result)
            events.append(event)
            if err is not None and fatal_error is None:
                fatal_error = err
        return results, events, fatal_error

    @staticmethod
    def _partition_tool_calls(
        spec: AgentRunSpec, tool_calls: list[ToolCallRequest],
    ) -> list[tuple[bool, list[ToolCallRequest]]]:
        """Partition tool calls into batches: consecutive read-only tools run
        concurrently, write tools run serially.
        """
        batches: list[tuple[bool, list[ToolCallRequest]]] = []
        current_batch: list[ToolCallRequest] = []
        current_is_ro: bool | None = None

        for tc in tool_calls:
            tool = spec.tools.get(tc.name)
            is_ro = tool.is_read_only if tool else False

            if current_is_ro is None:
                current_is_ro = is_ro

            if is_ro == current_is_ro:
                current_batch.append(tc)
            else:
                if current_batch:
                    batches.append((current_is_ro, current_batch))
                current_batch = [tc]
                current_is_ro = is_ro

        if current_batch:
            batches.append((current_is_ro or False, current_batch))

        return batches

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
