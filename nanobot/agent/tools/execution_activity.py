"""Pure execution facts and the opt-in public activity contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, NotRequired, TypedDict, cast

ExecutionRole = Literal["launch", "control", "inventory"]
ExecutionOperation = Literal["launch", "observe", "input", "stop", "inventory"]
ExecutionState = Literal[
    "starting", "started", "completed", "failed", "timed_out", "stopped", "control_failed",
]


@dataclass(frozen=True, slots=True)
class ExecutionActivityContract:
    name: str
    role: ExecutionRole


EXEC_ACTIVITY = ExecutionActivityContract("exec", "launch")
EXEC_SESSION_ACTIVITY = ExecutionActivityContract("exec_session", "control")
LIST_EXEC_SESSIONS_ACTIVITY = ExecutionActivityContract("list_exec_sessions", "inventory")
LEGACY_EXECUTION_CONTRACTS = {
    contract.name: contract
    for contract in (EXEC_ACTIVITY, EXEC_SESSION_ACTIVITY, LIST_EXEC_SESSIONS_ACTIVITY)
}


@dataclass(frozen=True, slots=True)
class ExecutionFact:
    """A return-point observation, not another command lifecycle owner."""

    state: ExecutionState
    exit_code: int | None = None
    output_incomplete: bool = False


class PublicExecutionActivity(TypedDict):
    version: Literal[2]
    activity: Literal["execution"]
    name: Literal["command_launch", "command_result"]
    call_id: str
    phase: Literal["start", "end", "error"]
    state: ExecutionState
    operation: ExecutionOperation
    counts_as_operation: bool
    command: str | None
    exit_code: int | None
    output_incomplete: bool


class ToolExecutionReport(TypedDict):
    name: str
    status: str
    detail: str
    public_finish: NotRequired[tuple[PublicExecutionActivity, ...]]


def execution_operation(
    contract: ExecutionActivityContract, arguments: object,
) -> ExecutionOperation:
    if contract.role == "launch":
        return "launch"
    if contract.role == "inventory":
        return "inventory"
    if isinstance(arguments, dict):
        values = cast(dict[str, object], arguments)
        if values.get("terminate") is True:
            return "stop"
        if values.get("input") is not None or values.get("close_stdin") is True:
            return "input"
    return "observe"


def public_execution_finish(
    contract: ExecutionActivityContract,
    *,
    call_id: str,
    arguments: object,
    fact: ExecutionFact | None,
    failed: bool,
) -> tuple[PublicExecutionActivity, ...]:
    if fact is None:
        if not failed:
            return ()
        fact = ExecutionFact("control_failed")
    if contract.role != "launch" and fact.state == "started":
        return ()
    return (PublicExecutionActivity(
        version=2, activity="execution",
        name="command_launch" if contract.role == "launch" else "command_result", call_id=call_id,
        phase="error" if fact.state in {"failed", "timed_out", "control_failed"} else "end",
        state=fact.state,
        operation=execution_operation(contract, arguments),
        counts_as_operation=contract.role == "launch",
        command=command_summary(arguments) if contract.role == "launch" else None,
        exit_code=fact.exit_code,
        output_incomplete=fact.output_incomplete,
    ),)


def command_summary(arguments: object) -> str | None:
    if not isinstance(arguments, dict):
        return None
    values = cast(dict[str, object], arguments)
    command = values.get("command") or values.get("cmd")
    if isinstance(command, list):
        parts = cast(list[object], command)
        if all(isinstance(part, str) for part in parts):
            command = " ".join(cast(list[str], parts))
    if not isinstance(command, str):
        return None
    return " ".join(command.split())[:200] or None
