"""Execution activity is a process observation, not a successful tool wait."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.runner_helpers import make_run_spec
from nanobot.agent.progress_hook import AgentProgressHook
from nanobot.agent.runner import AgentRunner
from nanobot.agent.tools.exec_session import ExecSessionManager, ExecSessionTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.shell import ExecTool
from nanobot.bus.outbound_events import ProgressEvent
from nanobot.events import EventSink
from nanobot.providers.base import LLMResponse, ToolCallRequest
from nanobot.utils.tool_hints import format_tool_event_hints
from tests.agent.execution_activity_helpers import observed_command, python_command


@pytest.mark.parametrize("exit_code", [0, 7])
async def test_observations_share_activity_and_preserve_model_and_history(tmp_path: Path, exit_code: int):
    progress, result, transcript, session_id = await observed_command(tmp_path, exit_code=exit_code)
    payloads = [tool for event in progress for tool in event.tool_events or []]
    executions = [tool for tool in payloads if "execution" in tool]
    assert len({tool["call_id"] for tool in executions}) == 1
    assert [tool["phase"] for tool in executions] == ["start", "update", "update", "update", "update", "end" if exit_code == 0 else "error"]
    assert [tool["execution"]["state"] for tool in executions] == ["running"] * 5 + ["succeeded" if exit_code == 0 else "failed"]
    sequences = [tool["execution"]["sequence"] for tool in executions]
    assert sequences == sorted(set(sequences))
    assert executions[-1]["execution"]["exit_code"] == exit_code
    assert executions[-1]["execution"]["finish_reason"] == "exit"
    assert all(marker in executions[-1]["result"] for marker in (
        "initial output", "diagnostic", "input accepted", "stdin ended", "final output",
    ))
    assert session_id not in json.dumps(payloads)
    assert [tool["call_id"] for tool in payloads if "execution" not in tool] == ["read", "read", "missing"]
    assert payloads[-1]["phase"] == "error"
    assert "not found" in payloads[-1]["error"]
    model_results = [row["content"] for row in result.messages if row["role"] == "tool"]
    assert session_id in model_results[0]
    assert "Wait timed out after 0s; session remains active." in model_results[1]
    assert "Stdin closed." in model_results[3]
    assert "ordinary output" in "\n".join(model_results)
    assert f"Exit code: {exit_code}" in model_results[-2]
    assert session_id in model_results[-1]  # Model control diagnostics remain unchanged.
    assert all("tool_events" not in row for row in result.messages)
    retained = [tool for row in transcript for tool in row.get("tool_events", [])]
    assert retained == [tool for tool in payloads if not (tool["call_id"] == "read" and tool["phase"] == "start")]
    text = [format_tool_event_hints(event.tool_events or []) for event in progress if event.tool_hint]
    assert len([hint for hint in text if hint]) == 4  # launch, ordinary read, outcome, necessary error
    assert "Command completed" in text[-2] if exit_code == 0 else "Command failed (exit 7)" in text[-2]


@pytest.mark.parametrize("outcome", ["cancelled", "timed_out"])
async def test_real_stop_and_hard_deadline_are_not_observer_success(tmp_path: Path, outcome: str):
    manager = ExecSessionManager()
    tools = ToolRegistry()
    tools.register(ExecTool(working_dir=str(tmp_path), max_runtime=1 if outcome == "timed_out" else 10, session_manager=manager))
    tools.register(ExecSessionTool(manager=manager))
    command = python_command("import sys; print('before stop: outside allowed directory', flush=True); sys.stdin.read()")
    events = []

    async def publish(event):
        if isinstance(event, ProgressEvent):
            events.extend(event.tool_events or [])

    responses = 0

    async def chat(**kwargs):
        nonlocal responses
        responses += 1
        if responses == 1:
            return LLMResponse(content="", tool_calls=[ToolCallRequest(id="start", name="exec", arguments={"command": command, "yield_time_ms": 100})])
        if responses == 2:
            output = next(row["content"] for row in kwargs["messages"] if row["role"] == "tool")
            session_id = output.split("session_id: ")[1].splitlines()[0]
            action = {"terminate": True} if outcome == "cancelled" else {"until_exit": True, "timeout_ms": 3000}
            return LLMResponse(content="", tool_calls=[ToolCallRequest(id="stop", name="exec_session", arguments={"session_id": session_id, **action})])
        return LLMResponse(content="Observed.")

    provider = MagicMock()
    provider.chat_stream_with_retry = AsyncMock(side_effect=chat)
    try:
        result = await AgentRunner().run(make_run_spec(
            provider, initial_messages=[], tools=tools, model="test", max_iterations=3,
            max_tool_result_chars=50_000, hook=AgentProgressHook(EventSink(publish=publish)),
        ))
        assert result.final_content == "Observed."
        assert len(events) == 2
        assert events[0]["execution"]["state"] == "running"
        assert events[1]["execution"]["state"] == outcome
        assert events[1]["execution"]["finish_reason"] == ("cancelled" if outcome == "cancelled" else "max_runtime")
        assert events[0]["call_id"] == events[1]["call_id"]
        assert "before stop" in events[1]["result"]
        assert "Command cancelled" in format_tool_event_hints(events) if outcome == "cancelled" else "Command timed out" in format_tool_event_hints(events)
    finally:
        await manager.close_all()
        assert not manager.has_pending_work


async def test_public_snapshot_is_bounded_and_uses_requested_not_wrapped_command(tmp_path: Path):
    from nanobot.agent.tools.base import ToolResult

    manager = ExecSessionManager()
    command = python_command("print('head-marker' + 'x' * 12000 + 'tail-marker')")
    tool = ExecTool(
        working_dir=str(tmp_path), max_runtime=10, session_manager=manager,
        path_prepend="/synthetic/private-path",
    )
    try:
        result = await tool.execute(command=command, yield_time_ms=1000, max_output_chars=1000)
        assert isinstance(result, ToolResult)
        observation = result.execution
        assert observation is not None and observation.done
        assert observation.command == command
        assert len(observation.output) == 1000
        assert observation.truncated_chars > 11000
        assert "head-marker" in observation.output and "tail-marker" in observation.output
        assert "chars truncated" in result
    finally:
        await manager.close_all()


async def test_completed_agent_turn_does_not_complete_a_still_running_command(tmp_path: Path):
    manager = ExecSessionManager()
    tools = ToolRegistry()
    tools.register(ExecTool(working_dir=str(tmp_path), max_runtime=10, session_manager=manager))
    tools.register(ExecSessionTool(manager=manager))
    public = []

    async def publish(event):
        if isinstance(event, ProgressEvent):
            public.extend(event.tool_events or [])

    async def run(responses):
        provider = MagicMock()
        provider.chat_stream_with_retry = AsyncMock(side_effect=responses)
        return await AgentRunner().run(make_run_spec(
            provider, initial_messages=[], tools=tools, model="test", max_iterations=2,
            max_tool_result_chars=50_000, hook=AgentProgressHook(EventSink(publish=publish)),
        ))

    try:
        first = await run([
            LLMResponse(content="", tool_calls=[ToolCallRequest(id="launch", name="exec", arguments={
                "command": python_command("import sys; print('waiting', flush=True); sys.stdin.read()"),
                "yield_time_ms": 100,
            })]),
            LLMResponse(content="The observation ended, not the command."),
        ])
        assert first.stop_reason == "completed"
        assert len(public) == 1 and public[0]["execution"]["state"] == "running"
        [owned] = await manager.list()
        assert owned.finish_reason is None and owned.returncode is None
        assert manager.has_pending_work
        await run([
            LLMResponse(content="", tool_calls=[ToolCallRequest(id="observe-next-turn", name="exec_session", arguments={
                "session_id": owned.session_id, "close_stdin": True, "until_exit": True, "timeout_ms": 3000,
            })]),
            LLMResponse(content="Now completed."),
        ])
        assert len(public) == 2
        assert public[-1]["call_id"] == public[0]["call_id"]
        assert public[-1]["execution"]["state"] == "succeeded"
        assert public[-1]["execution"]["finish_reason"] == "exit"
        assert "waiting" in public[-1]["result"]
    finally:
        await manager.close_all()
        assert not manager.has_pending_work
