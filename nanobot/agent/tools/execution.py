"""Execute tool calls and turn their outcomes into model observations."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, cast

from loguru import logger

from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.agent.tools.registry import ToolRegistry, is_tool_error_result
from nanobot.providers.base import ToolCallRequest
from nanobot.utils.runtime import (
    repeated_external_lookup_error,
    repeated_workspace_violation_error,
)

_RETRY_HINT = "\n\n[Analyze the error above and try a different approach.]"
# SSRF is a hard security block at the tool boundary, but the agent turn
# should recover conversationally instead of aborting the runtime.
_SSRF_MARKERS: tuple[str, ...] = (
    "internal/private url detected",
    "private/internal address",
    "private address",
)
_SSRF_BOUNDARY_NOTE = (
    "This is a non-bypassable security boundary. Stop trying to access "
    "private/internal URLs. Do not retry with curl, wget, encoded IPs, "
    "alternate DNS, redirects, proxies, or another tool. Ask the user for "
    "local files, logs, screenshots, or an explicit safe public URL instead. "
    "If the user explicitly trusts this private URL, ask them to whitelist "
    "the exact IP/CIDR via tools.ssrfWhitelist."
)
# Non-SSRF boundary markers returned to the model as recoverable tool errors.
_WORKSPACE_VIOLATION_MARKERS: tuple[str, ...] = (
    "outside the configured workspace",
    "outside allowed directory",
    "working_dir is outside",
    "working_dir could not be resolved",
    "path outside working dir",
    "path traversal detected",
)


def _with_retry_hint(payload: str) -> str:
    """Append the recovery hint exactly once."""
    if payload.endswith(_RETRY_HINT):
        return payload
    return payload + _RETRY_HINT


async def execute_tool_calls(
    tools: ToolRegistry,
    tool_calls: list[ToolCallRequest],
    *,
    concurrent: bool,
    external_lookup_counts: dict[str, int],
    workspace_violation_counts: dict[str, int],
    hook: AgentHook,
    context: AgentHookContext,
) -> tuple[list[Any], list[dict[str, str]]]:
    """Execute one model response's tool calls in stable result order."""
    tool_results: list[tuple[Any, dict[str, str]]] = []
    for batch in _partition_tool_batches(tools, tool_calls, concurrent=concurrent):
        if concurrent and len(batch) > 1:
            batch_results = await asyncio.gather(*(
                _execute_tool_call(
                    tools,
                    tool_call,
                    external_lookup_counts,
                    workspace_violation_counts,
                    hook,
                    context,
                )
                for tool_call in batch
            ))
            tool_results.extend(batch_results)
        else:
            for tool_call in batch:
                result = await _execute_tool_call(
                    tools,
                    tool_call,
                    external_lookup_counts,
                    workspace_violation_counts,
                    hook,
                    context,
                )
                tool_results.append(result)

    results = [result for result, _event in tool_results]
    events = [event for _result, event in tool_results]
    return results, events


async def _execute_tool_call(
    tools: ToolRegistry,
    tool_call: ToolCallRequest,
    external_lookup_counts: dict[str, int],
    workspace_violation_counts: dict[str, int],
    hook: AgentHook,
    context: AgentHookContext,
) -> tuple[Any, dict[str, str]]:
    lookup_error = repeated_external_lookup_error(
        tool_call.name,
        tool_call.arguments,
        external_lookup_counts,
    )
    if lookup_error:
        event = {
            "name": tool_call.name,
            "status": "error",
            "detail": "repeated external lookup blocked",
        }
        return _with_retry_hint(lookup_error), event

    prepare_call = cast(
        Callable[[str, Any], object] | None,
        getattr(tools, "prepare_call", None),
    )
    tool, params, prep_error = None, tool_call.arguments, None
    if callable(prepare_call):
        prepared = prepare_call(tool_call.name, tool_call.arguments)
        if isinstance(prepared, tuple):
            prepared_tuple = cast(tuple[object, ...], prepared)
            if len(prepared_tuple) == 3:
                tool, params, prep_error = cast(tuple[Any, Any, str | None], prepared_tuple)
    if prep_error:
        payload = _with_retry_hint(prep_error)
        event = {
            "name": tool_call.name,
            "status": "error",
            "detail": prep_error.split(": ", 1)[-1][:120],
        }
        handled = _classify_violation(
            raw_text=prep_error,
            soft_payload=payload,
            event=event,
            tool_call=tool_call,
            workspace_violation_counts=workspace_violation_counts,
        )
        if handled is not None:
            return handled
        return payload, event

    await hook.before_execute_tool(context, tool_call, tool, params)
    try:
        if tool is not None:
            result = await tool.execute(**params)
        else:
            result = await tools.execute(tool_call.name, params)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        await hook.on_execute_tool_error(context, tool_call, tool, params, exc)
        event = {
            "name": tool_call.name,
            "status": "error",
            "detail": str(exc),
        }
        payload = _with_retry_hint(f"Error: {type(exc).__name__}: {exc}")
        handled = _classify_violation(
            raw_text=str(exc),
            soft_payload=payload,
            event=event,
            tool_call=tool_call,
            workspace_violation_counts=workspace_violation_counts,
        )
        if handled is not None:
            return handled
        return payload, event

    if is_tool_error_result(result):
        await hook.on_execute_tool_error(context, tool_call, tool, params, result)
        payload = _with_retry_hint(result)
        event = {
            "name": tool_call.name,
            "status": "error",
            "detail": result.replace("\n", " ").strip()[:120],
        }
        handled = _classify_violation(
            raw_text=result,
            soft_payload=payload,
            event=event,
            tool_call=tool_call,
            workspace_violation_counts=workspace_violation_counts,
        )
        if handled is not None:
            return handled
        return payload, event

    await hook.after_execute_tool(context, tool_call, tool, params, result)

    detail = "" if result is None else str(result)
    detail = detail.replace("\n", " ").strip()
    if not detail:
        detail = "(empty)"
    elif len(detail) > 120:
        detail = detail[:120] + "..."
    return result, {"name": tool_call.name, "status": "ok", "detail": detail}


def is_ssrf_violation(text: str) -> bool:
    """Return whether a tool error describes a blocked private-network request."""
    if not text:
        return False
    lowered = text.lower()
    return any(marker in lowered for marker in _SSRF_MARKERS)


def _is_workspace_violation(text: str) -> bool:
    """Return whether text describes any workspace or network boundary rejection."""
    if not text:
        return False
    lowered = text.lower()
    if is_ssrf_violation(lowered):
        return True
    return any(marker in lowered for marker in _WORKSPACE_VIOLATION_MARKERS)


def _classify_violation(
    *,
    raw_text: str,
    soft_payload: str,
    event: dict[str, str],
    tool_call: ToolCallRequest,
    workspace_violation_counts: dict[str, int],
) -> tuple[Any, dict[str, str]] | None:
    if is_ssrf_violation(raw_text):
        logger.warning(
            "Tool {} blocked by SSRF guard; returning non-retryable tool error: {}",
            tool_call.name,
            raw_text.replace("\n", " ").strip()[:200],
        )
        event["detail"] = _event_detail("ssrf_violation: ", raw_text)
        return _ssrf_soft_payload(raw_text), event

    if _is_workspace_violation(raw_text):
        escalation = repeated_workspace_violation_error(
            tool_call.name,
            tool_call.arguments,
            workspace_violation_counts,
        )
        event["detail"] = _event_detail("workspace_violation: ", raw_text)
        if escalation is not None:
            logger.warning(
                "Tool {} hit workspace boundary repeatedly; escalating hint",
                tool_call.name,
            )
            event["detail"] = _event_detail(
                "workspace_violation_escalated: ",
                raw_text,
            )
            return escalation, event
        return soft_payload, event

    return None


def _ssrf_soft_payload(raw_text: str) -> str:
    text = raw_text.strip() or "Error: request blocked by SSRF guard"
    return f"{text}\n\n{_SSRF_BOUNDARY_NOTE}"


def _event_detail(prefix: str, text: str, limit: int = 160) -> str:
    return (prefix + text.replace("\n", " ").strip())[:limit]


def _partition_tool_batches(
    tools: ToolRegistry,
    tool_calls: list[ToolCallRequest],
    *,
    concurrent: bool,
) -> list[list[ToolCallRequest]]:
    if not concurrent:
        return [[tool_call] for tool_call in tool_calls]

    batches: list[list[ToolCallRequest]] = []
    current: list[ToolCallRequest] = []
    for tool_call in tool_calls:
        get_tool = cast(Callable[[str], Any] | None, getattr(tools, "get", None))
        tool = get_tool(tool_call.name) if callable(get_tool) else None
        can_batch = bool(tool and tool.concurrency_safe)
        if can_batch:
            current.append(tool_call)
            continue
        if current:
            batches.append(current)
            current = []
        batches.append([tool_call])
    if current:
        batches.append(current)
    return batches
