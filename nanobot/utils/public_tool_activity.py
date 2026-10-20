"""The common public projection for owned execution activity and legacy hints."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from itertools import groupby
from typing import Any

from nanobot.agent.tools.execution_activity import (
    LEGACY_EXECUTION_CONTRACTS,
    ExecutionActivityContract,
    ExecutionFact,
    PublicExecutionActivity,
    command_summary,
    public_execution_finish,
)
from nanobot.providers.base import ToolCallRequest
from nanobot.utils.tool_hints import format_tool_hints

_EXECUTION_LABELS = {
    "starting": "Starting command",
    "started": "Command started",
    "completed": "Command completed",
    "failed": "Command failed",
    "timed_out": "Command timed out",
    "stopped": "Command stopped",
    "control_failed": "Command operation failed",
}
_CONTROL_LABELS = {
    "launch": "Could not start command",
    "observe": "Could not check command",
    "input": "Could not send command input",
    "stop": "Could not stop command",
    "inventory": "Could not list commands",
}


def execution_start(
    call: ToolCallRequest, contract: ExecutionActivityContract,
) -> PublicExecutionActivity | None:
    if contract.role != "launch":
        return None
    return PublicExecutionActivity(
        version=2, activity="execution", name="command_launch", call_id=call.id,
        phase="start", state="starting", operation="launch", counts_as_operation=True,
        command=command_summary(call.arguments), exit_code=None, output_incomplete=False,
    )


def execution_activity_text(event: dict[str, Any]) -> str:
    state = str(event.get("state") or "")
    label = _EXECUTION_LABELS.get(state, "Command operation failed")
    if state == "control_failed":
        label = _CONTROL_LABELS.get(str(event.get("operation") or ""), label)
    code = event.get("exit_code")
    if isinstance(code, int) and state == "failed":
        label += f" (exit code {code})"
    if event.get("output_incomplete") is True:
        label += " — output may be incomplete"
    command = event.get("command")
    if isinstance(command, str) and command:
        label += f": {command}"
    return label


def public_activity_batches(
    events: list[dict[str, Any]],
) -> Iterator[tuple[bool, list[dict[str, Any]]]]:
    """Keep ordinary tool delivery and execution notices in causal order."""
    for execution, items in groupby(events, key=lambda item: item.get("activity") == "execution"):
        yield execution, list(items)


def public_activity_hint(events: list[dict[str, Any]], *, max_length: int = 40) -> str:
    """Derive text from exactly the items sent to structured consumers."""
    parts: list[str] = []
    for execution, batch in public_activity_batches(events):
        if execution:
            parts.extend(execution_activity_text(event) for event in batch)
        else:
            calls = [ToolCallRequest(
                id=str(event.get("call_id") or ""), name=str(event.get("name") or ""),
                arguments=event["arguments"] if isinstance(event.get("arguments"), dict) else {},
            ) for event in batch]
            parts.append(format_tool_hints(calls, max_length=max_length))
    return ", ".join(part for part in parts if part)


def _legacy_text_is_internal(text: str) -> bool:
    """Decode only a whole, unambiguous owned hint, never assistant prose."""
    text = text.strip()
    hint, separator, count = text.rpartition(" × ")
    if separator and count.isdecimal() and int(count) > 1:
        text = hint
    if text == "exec sessions":
        return True
    try:
        expression = ast.parse(text, mode="eval").body
    except (SyntaxError, ValueError):
        return False
    if not isinstance(expression, ast.Call) or not isinstance(expression.func, ast.Name):
        return False
    contract = LEGACY_EXECUTION_CONTRACTS.get(expression.func.id)
    if contract is None or contract.role == "launch":
        return False
    if expression.keywords or len(expression.args) > 1:
        return False
    try:
        return all(isinstance(ast.literal_eval(argument), str) for argument in expression.args)
    except (ValueError, TypeError):
        return False


def project_stored_tool_activity(
    text: str, events: list[dict[str, Any]], *, legacy_text_hint: bool = False,
) -> tuple[str, list[dict[str, Any]], bool]:
    """Read projection only: stored records and actual model prose stay untouched."""
    if not events:
        return ("", [], True) if legacy_text_hint and _legacy_text_is_internal(text) else (text, events, False)
    visible: list[dict[str, Any]] = []
    changed = False
    for event in events:
        # Current ordinary/hosted tools explicitly retain their default presentation.
        if event.get("activity") in {"execution", "tool"}:
            visible.append(event)
            continue
        contract = LEGACY_EXECUTION_CONTRACTS.get(str(event.get("name") or ""))
        if contract is None or contract.role == "launch":
            visible.append(event)
            continue
        changed = True
        if event.get("phase") == "error":
            visible.extend(dict(item) for item in public_execution_finish(
                contract, call_id=str(event.get("call_id") or ""),
                arguments=event.get("arguments"), fact=ExecutionFact("control_failed"),
                failed=True,
            ))
    if not changed:
        return text, events, False
    return public_activity_hint(visible), visible, True
