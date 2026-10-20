"""Public execution activity uses owner facts, not observer-call completion."""

from __future__ import annotations

import asyncio
import json
import re
import sys
from unittest.mock import AsyncMock

import pytest

from nanobot.agent.hook import AgentHookContext
from nanobot.agent.progress_hook import AgentProgressHook
from nanobot.agent.tools.base import Tool, ToolResult
from nanobot.agent.tools.exec_session import (
    ExecSessionManager,
    ExecSessionTool,
    ListExecSessionsTool,
    _SessionPoll,
    execution_fact_from_poll,
)
from nanobot.agent.tools.execution import execute_tool_calls
from nanobot.agent.tools.execution_activity import ExecutionFact
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.shell import ExecTool
from nanobot.bus.outbound_events import ProgressEvent
from nanobot.events import EventSink
from nanobot.providers.base import ToolCallRequest
from nanobot.utils.progress_events import build_tool_event_finish_payloads
from nanobot.utils.public_tool_activity import project_stored_tool_activity, public_activity_hint


async def run_call(registry, hook, name, arguments, call_id):
    context = AgentHookContext(
        iteration=0, messages=[],
        tool_calls=[ToolCallRequest(id=call_id, name=name, arguments=arguments)],
    )
    await hook.before_execute_tools(context)
    context.tool_results, context.tool_events = await execute_tool_calls(
        registry, context.tool_calls, concurrent=False,
        external_lookup_counts={}, workspace_violation_counts={}, hook=hook, context=context,
    )
    await hook.after_iteration(context)
    return context


@pytest.mark.asyncio
@pytest.mark.parametrize("exit_code", [0, 7])
async def test_real_command_waits_are_private_and_terminal_fact_is_public(tmp_path, exit_code):
    manager = ExecSessionManager()
    registry = ToolRegistry()
    registry.register(ExecTool(session_manager=manager, working_dir=str(tmp_path)))
    registry.register(ExecSessionTool(manager=manager))
    registry.register(ListExecSessionsTool(manager=manager))
    published = []

    async def publish(event):
        published.append(event)

    hook = AgentProgressHook(
        EventSink(publish), resolve_activity_contract=registry.get_activity_contract,
    )
    command = (
        f'$null = [Console]::In.ReadLine(); Write-Output "finished"; exit {exit_code}'
        if sys.platform == "win32" else f'read line; printf "finished\\n"; exit {exit_code}'
    )
    try:
        launched = await run_call(registry, hook, "exec", {
            "command": command, "yield_time_ms": 0, "max_runtime": 10,
        }, "launch")
        result = launched.tool_results[0]
        session_id = re.search(r"session_id:\s*([0-9a-f]+)", result).group(1)
        assert result.activity_fact.state == "started"
        assert "session remains active" in result
        assert [event.tool_events[0]["state"] for event in published] == ["starting", "started"]
        before_waits = list(published)
        for index in range(2):
            observed = await run_call(registry, hook, "exec_session", {
                "session_id": session_id, "until_exit": True, "timeout_ms": 10,
            }, f"wait-{index}")
            assert "session remains active" in observed.tool_results[0]
            assert observed.tool_events[0]["public_finish"] == ()
        await run_call(registry, hook, "list_exec_sessions", {}, "inventory")
        assert published == before_waits
        finished = await run_call(registry, hook, "exec_session", {
            "session_id": session_id, "input": "finish\n", "until_exit": True, "timeout_ms": 5000,
        }, "finish")
        assert "finished" in finished.tool_results[0]
        assert f"Exit code: {exit_code}" in finished.tool_results[0]
        # Nonzero exit is a public failure without changing model tool classification.
        assert finished.tool_events[0]["status"] == "ok"
        event = published[-1]
        assert isinstance(event, ProgressEvent)
        assert event.tool_hint is True
        assert event.tool_events[0]["state"] == ("failed" if exit_code else "completed")
        assert event.tool_events[0]["counts_as_operation"] is False
        assert event.tool_events[0]["exit_code"] == exit_code
        assert session_id not in json.dumps([item.tool_events for item in published])
        assert "exec_session" not in json.dumps([item.content for item in published])
    finally:
        await manager.close_all()


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", [{}, {"session_id": "internal-handle"}])
async def test_preflight_and_unavailable_failures_keep_safe_notice(arguments):
    registry = ToolRegistry()
    registry.register(ExecSessionTool(manager=ExecSessionManager()))
    context = await run_call(registry, AgentProgressHook(), "exec_session", arguments, "failure")
    events = build_tool_event_finish_payloads(context)
    assert events[0]["state"] == "control_failed"
    assert events[0]["operation"] == "observe"
    assert events[0]["counts_as_operation"] is False
    assert "internal-handle" not in json.dumps(events)
    assert "Error:" in context.tool_results[0]
    direct = await registry.execute("exec_session", arguments)
    assert isinstance(direct, ToolResult)
    assert direct.activity_fact == ExecutionFact("control_failed")


@pytest.mark.asyncio
async def test_stop_natural_exit_race_uses_actual_owner_reason():
    manager = ExecSessionManager()
    manager.write = AsyncMock(return_value=_SessionPoll("", True, 0, finish_reason="exit"))
    registry = ToolRegistry()
    registry.register(ExecSessionTool(manager=manager))
    context = await run_call(registry, AgentProgressHook(), "exec_session", {
        "session_id": "ended-naturally", "terminate": True,
    }, "stop")
    assert build_tool_event_finish_payloads(context)[0]["state"] == "completed"


@pytest.mark.parametrize(("reason", "code", "state"), [
    ("exit", 0, "completed"), ("exit", 3, "failed"),
    ("cancelled", -1, "stopped"), ("max_runtime", -1, "timed_out"),
    ("idle_timeout", -1, "timed_out"), ("execution_error", 0, "failed"),
])
def test_terminal_owner_facts(reason, code, state):
    fact = execution_fact_from_poll(_SessionPoll(
        "raw output", True, code, finish_reason=reason, output_incomplete=True,
    ))
    assert fact == ExecutionFact(state, code, True)


@pytest.mark.asyncio
async def test_cancelled_observer_does_not_publish_a_fake_terminal_state():
    manager = ExecSessionManager()
    manager.write = AsyncMock(side_effect=asyncio.CancelledError)
    registry = ToolRegistry()
    registry.register(ExecSessionTool(manager=manager))
    with pytest.raises(asyncio.CancelledError):
        await run_call(registry, AgentProgressHook(), "exec_session", {
            "session_id": "still-running", "until_exit": True,
        }, "cancel-observer")


class ReplacementTool(Tool):
    name = "exec_session"
    description = "Third-party tool with the same name"
    parameters = {"type": "object", "properties": {}}

    async def execute(self, **kwargs):
        return "third-party result"


@pytest.mark.asyncio
async def test_actual_instance_opt_in_preserves_same_named_replacement():
    registry = ToolRegistry()
    registry.register(ReplacementTool())
    context = await run_call(registry, AgentProgressHook(), "exec_session", {}, "custom")
    event = build_tool_event_finish_payloads(context)[0]
    assert event["result"] == "third-party result"
    assert event["activity"] == "tool"
    assert project_stored_tool_activity("custom hint", [event]) == ("custom hint", [event], False)


def test_legacy_projection_hides_control_but_keeps_safe_failures_and_ordinary_tools():
    normal = {"phase": "end", "call_id": "read", "name": "read_file", "arguments": {"path": "a.txt"}}
    wait = {"phase": "end", "call_id": "wait", "name": "exec_session", "arguments": {"session_id": "internal"}}
    stop = {**wait, "arguments": {"session_id": "internal", "terminate": True}}
    error = {**wait, "phase": "error", "error": "unavailable: internal"}
    text, events, changed = project_stored_tool_activity("raw internal", [normal, wait, stop, error])
    assert changed is True
    assert events[0] == normal
    assert len(events) == 2
    assert events[1]["state"] == "control_failed"
    assert "internal" not in text
    assert "internal" not in json.dumps(events)
    assert project_stored_tool_activity(text, events) == (text, events, False)


@pytest.mark.parametrize("text", ['exec_session("internal")', 'exec_session("internal") × 2', "exec sessions"])
def test_legacy_text_decodes_only_owned_tool_hint_grammar(text):
    assert project_stored_tool_activity(text, [], legacy_text_hint=True) == ("", [], True)
    assert project_stored_tool_activity(text, []) == (text, [], False)
    mixed = "Please explain " + text
    assert project_stored_tool_activity(mixed, [], legacy_text_hint=True) == (mixed, [], False)


@pytest.mark.asyncio
async def test_mixed_finish_keeps_each_delivery_class_separate():
    registry = ToolRegistry()
    registry.register(ExecSessionTool(manager=ExecSessionManager()))
    # The replacement's different registry name is deliberately ordinary.
    ordinary = ReplacementTool()
    ordinary.name = "read_file"
    registry.register(ordinary)
    published = []

    async def publish(event):
        published.append(event)

    hook = AgentProgressHook(EventSink(publish), resolve_activity_contract=registry.get_activity_contract)
    context = AgentHookContext(iteration=0, messages=[], tool_calls=[
        ToolCallRequest(id="ordinary", name="read_file", arguments={}),
        ToolCallRequest(id="control", name="exec_session", arguments={"session_id": "gone"}),
    ])
    context.tool_results, context.tool_events = await execute_tool_calls(
        registry, context.tool_calls, concurrent=False,
        external_lookup_counts={}, workspace_violation_counts={}, hook=hook, context=context,
    )
    await hook.after_iteration(context)
    assert len(published) == 2
    assert published[0].tool_hint is False
    assert published[0].content == ""
    assert published[0].tool_events[0]["name"] == "read_file"
    assert published[1].tool_hint is True
    assert published[1].tool_events[0]["state"] == "control_failed"
    assert "third-party result" not in published[1].content


def test_public_hint_keeps_order_and_compacts_only_consecutive_ordinary_calls():
    read = {"name": "read_file", "arguments": {"path": "a.py"}}
    completed = {"activity": "execution", "state": "completed"}
    failure = {"activity": "execution", "state": "control_failed", "operation": "stop"}
    assert public_activity_hint([read, read, completed, read, failure]) == (
        "read a.py × 2, Command completed, read a.py, Could not stop command"
    )
