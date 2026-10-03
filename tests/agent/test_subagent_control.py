"""Private task ownership, message receipts, cancellation, and shell lifetime."""

import asyncio
import json
import os
import re
import shlex
import subprocess
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.memory import Consolidator
from nanobot.agent.runner import AgentRunResult
from nanobot.agent.subagent import SubagentManager
from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.tools.registry import ToolRegistry, is_tool_error_result
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.subagent import SubagentTool
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import GenerationSettings, LLMProvider, LLMResponse, ToolCallRequest
from nanobot.utils.llm_runtime import LLMRuntime


def setup(tmp_path, **kwargs):
    manager = SubagentManager(
        workspace=tmp_path, bus=MessageBus(), max_tool_result_chars=16000,
        consolidator=MagicMock(spec=Consolidator), **kwargs,
    )
    provider = MagicMock(spec=LLMProvider)
    provider.generation = GenerationSettings()
    runtime = LLMRuntime.capture(provider, "test", context_window_tokens=128000)
    ctx = RequestContext("websocket", "route", session_key="owner", runtime=runtime)
    return manager, provider, ctx


async def spawn(manager, ctx, text="task"):
    with request_context(ctx):
        result = await SubagentTool(manager).execute(action="create", task=text)
    task_id = re.search(r"id: ([\w-]+)", result).group(1)
    assert str(uuid.UUID(task_id)) == task_id
    return task_id


async def control(manager, ctx, task_id, action=None, message=None):
    with request_context(ctx):
        return await SubagentTool(manager).execute(action or "check", task_id, message)


async def settled(manager):
    await asyncio.gather(*list(manager._running_tasks.values()), return_exceptions=True)
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_direct_turn_waits_for_child_without_a_background_consumer(loop_factory):
    loop = loop_factory()
    loop.provider.provider_name = "test"
    loop.provider.chat_stream_with_retry = AsyncMock(side_effect=[
        LLMResponse(content=None, tool_calls=[ToolCallRequest(
            id="delegate", name="subagent",
            arguments={"action": "create", "task": "Inspect the configuration"},
        )]),
        LLMResponse(content="Verified child findings"),
        LLMResponse(content="Parent conclusion from the child findings"),
    ])
    try:
        response = await loop.process_direct("Delegate this inspection")
        assert response.content == "Parent conclusion from the child findings"
        parent_followup = loop.provider.chat_stream_with_retry.call_args_list[-1].kwargs["messages"]
        assert any(m.get("role") == "tool" and m.get("content") == "Verified child findings"
                   for m in parent_followup)
        assert loop.bus.inbound_size == 0
        assert loop.subagents.get_running_count() == 0
        assert next(iter(loop.subagents.statuses_for_session("cli:direct").values())).state == "done"
    finally:
        await loop.subagents.close()


@pytest.mark.asyncio
async def test_owner_canonical_fallback_and_absent_context(tmp_path):
    manager, _, ctx = setup(tmp_path)
    manager.runner.run = AsyncMock(return_value=AgentRunResult(messages=[], final_content="private"))
    task_id = await spawn(manager, ctx)
    receipt = manager.send(task_id, "owner", "follow-up")
    snapshot = manager.statuses_for_session("owner")[task_id]
    snapshot.state = "cancelled"
    snapshot.owner = "other"
    snapshot.receipts.clear()
    current = manager.runtime_statuses()[task_id]
    assert current.state == "queued"
    assert current.owner == "owner"
    assert current.receipts == {receipt["message_id"]: "accepted"}
    await settled(manager)
    terminal = await manager.cancel(task_id, "owner")
    terminal.result = "tampered"
    terminal.receipts.clear()
    current = manager.statuses_for_session("owner")[task_id]
    assert current.result == "private"
    assert current.receipts == {receipt["message_id"]: "undelivered"}
    denied = await SubagentTool(manager).execute("cancel", task_id)
    assert is_tool_error_result(denied)
    for stranger in [RequestContext("websocket", "route", session_key="other"),
                     RequestContext("websocket", "route"), RequestContext("", "")]:
        for action in [None, "send", "cancel"]:
            assert await control(manager, stranger, task_id, action, "secret") == denied
    assert await control(manager, ctx, "missing") == denied
    # Canonical identity, not the transport route, owns the task.
    same_owner = RequestContext("cli", "different", session_key="owner")
    assert json.loads(await control(manager, same_owner, task_id))["result"] == "private"
    fallback = RequestContext("cli", "fallback", runtime=ctx.runtime)
    fallback_id = await spawn(manager, fallback)
    await settled(manager)
    assert await control(manager, fallback, fallback_id, "cancel") == denied
    explicit_owner = RequestContext("cli", "fallback", session_key="cli:fallback")
    assert json.loads(await control(manager, explicit_owner, fallback_id))["state"] == "done"
    assert manager.statuses_for_session(None) == {}
    await manager.close()


@pytest.mark.asyncio
async def test_bounded_fifo_snapshot_and_terminal_receipts(tmp_path):
    manager, _, ctx = setup(tmp_path)
    entered, drain, drained, finish = (asyncio.Event() for _ in range(4))
    snapshots = []

    async def run(spec):
        entered.set()
        await drain.wait()
        snapshots.append(await spec.injection_callback())
        drained.set()
        await finish.wait()
        return AgentRunResult(messages=[], final_content="done")

    manager.runner.run = run
    task_id = await spawn(manager, ctx)
    await entered.wait()
    for invalid in ["", "  ", "x" * 8193, "界" * 2731]:
        assert is_tool_error_result(await control(manager, ctx, task_id, "send", invalid))
    receipts = []
    for i in range(manager.MAX_INBOX):
        receipt = json.loads(await control(manager, ctx, task_id, "send", str(i)))
        assert receipt["receipt"] == "accepted" and not receipt["delivered"]
        receipts.append(receipt["message_id"])
    assert is_tool_error_result(await control(manager, ctx, task_id, "send", "overflow"))
    drain.set()
    await drained.wait()
    assert snapshots == [[{"role": "user", "content": str(i)} for i in range(manager.MAX_INBOX)]]
    last = json.loads(await control(manager, ctx, task_id, "send", "late"))["message_id"]
    finish.set()
    await settled(manager)
    status = json.loads(await control(manager, ctx, task_id))
    assert status["state"] == "done"
    assert status["receipts"] == {**dict.fromkeys(receipts, "delivered"), last: "undelivered"}
    assert is_tool_error_result(await control(manager, ctx, task_id, "send", "no restart"))
    notice = await manager.bus.consume_inbound()
    assert notice.metadata["subagent_task_id"] == task_id
    assert notice.metadata["subagent_message_receipts"] == status["receipts"]
    assert last in notice.content
    assert manager.bus.inbound_size == 0
    await manager.close()


@pytest.mark.asyncio
async def test_lifetime_receipt_limit_rejects_without_silent_eviction(tmp_path):
    manager, _, ctx = setup(tmp_path)
    manager.MAX_MESSAGES = 2
    entered = asyncio.Event()
    specs = []

    async def run(spec):
        specs.append(spec)
        entered.set()
        await asyncio.Event().wait()

    manager.runner.run = run
    task_id = await spawn(manager, ctx)
    await entered.wait()
    for text in ["one", "two"]:
        assert not is_tool_error_result(await control(manager, ctx, task_id, "send", text))
        await specs[0].injection_callback()
    assert is_tool_error_result(await control(manager, ctx, task_id, "send", "three"))
    await control(manager, ctx, task_id, "cancel")
    assert len(json.loads(await control(manager, ctx, task_id))["receipts"]) == 2
    await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("begun", [False, True])
async def test_queued_cancel_is_idempotent_and_never_admitted(tmp_path, begun):
    manager, _, ctx = setup(tmp_path, max_concurrent_subagents=1)
    entered = asyncio.Event()
    calls = []

    async def run(spec):
        calls.append(spec.initial_messages[-1]["content"])
        entered.set()
        await asyncio.Event().wait()

    manager.runner.run = run
    await spawn(manager, ctx, "occupy")
    await entered.wait()
    queued = await spawn(manager, ctx, "queued")
    accepted = json.loads(await control(manager, ctx, queued, "send", "pending"))
    if begun:
        await asyncio.sleep(0)
    a, b = await asyncio.gather(control(manager, ctx, queued, "cancel"),
                                control(manager, ctx, queued, "cancel"))
    assert json.loads(a) == json.loads(b)
    assert json.loads(a)["state"] == "cancelled"
    assert json.loads(a)["receipts"][accepted["message_id"]] == "undelivered"
    assert calls == ["occupy"]
    assert manager.bus.inbound_size == 1
    await manager.close()
    assert manager.bus.inbound_size == 1
    with request_context(ctx):
        assert is_tool_error_result(await SubagentTool(manager).execute(action="create", task="after close"))


@pytest.mark.asyncio
async def test_real_runner_injects_followup_without_durable_child_session(tmp_path):
    manager, provider, ctx = setup(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    requests = []

    async def chat(**kwargs):
        requests.append([dict(m) for m in kwargs["messages"]])
        if len(requests) == 1:
            entered.set()
            await release.wait()
        return LLMResponse(content="answer")

    provider.chat_stream_with_retry = AsyncMock(side_effect=chat)
    task_id = await spawn(manager, ctx)
    await entered.wait()
    ids = [json.loads(await control(manager, ctx, task_id, "send", text))["message_id"]
           for text in ["first update", "second update"]]
    release.set()
    await settled(manager)
    assert len(requests) == 2
    user_text = "\n".join(m["content"] for m in requests[-1] if m["role"] == "user")
    assert user_text.index("first update") < user_text.index("second update")
    assert json.loads(await control(manager, ctx, task_id))["receipts"] == dict.fromkeys(ids, "delivered")
    assert not (tmp_path / "sessions").exists()
    await manager.close()


@pytest.mark.asyncio
async def test_iteration_limit_returns_partial_findings_without_success_notice(tmp_path):
    manager, provider, ctx = setup(tmp_path, max_iterations=1)
    (tmp_path / "note.txt").write_text("evidence", encoding="utf-8")
    provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(
        content="Found the relevant file; verification is still pending.",
        tool_calls=[ToolCallRequest("read", "read_file", {"path": "note.txt"})],
    ))
    task_id = await spawn(manager, ctx)
    await settled(manager)
    status = json.loads(await control(manager, ctx, task_id))
    assert status["state"] == "incomplete"
    assert status["stop_reason"] == "max_iterations"
    assert status["partial"] is True
    assert status["result"] == "Found the relevant file; verification is still pending."
    notice = await manager.bus.consume_inbound()
    assert "completed successfully" not in notice.content
    assert notice.metadata["subagent_state"] == "incomplete"
    assert notice.metadata["subagent_partial"] is True
    assert notice.metadata["subagent_stop_reason"] == "max_iterations"
    with request_context(ctx):
        inline = await SubagentTool(manager).execute("create", task="verify", wait=True)
    assert is_tool_error_result(inline)
    assert "max_iterations" in inline
    assert "verification is still pending" in inline
    await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("inline", [False, True])
async def test_cancel_preserves_completed_iteration_output_and_receipts(tmp_path, inline):
    manager, provider, ctx = setup(tmp_path)
    (tmp_path / "note.txt").write_text("evidence", encoding="utf-8")
    entered = asyncio.Event()
    calls = 0

    async def chat(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return LLMResponse(content="Found a possible cause; not yet verified.", tool_calls=[
                ToolCallRequest("read", "read_file", {"path": "note.txt"}),
            ])
        entered.set()
        await asyncio.Event().wait()

    provider.chat_stream_with_retry = AsyncMock(side_effect=chat)
    if inline:
        execution = asyncio.create_task(manager.run_inline(
            task="task", session_key=ctx.session_key, runtime=ctx.runtime,
        ))
    else:
        task_id = await spawn(manager, ctx)
    await entered.wait()
    if inline:
        task_id = next(iter(manager.statuses_for_session(ctx.session_key)))
    receipt = json.loads(await control(manager, ctx, task_id, "send", "please verify"))
    status = json.loads(await control(manager, ctx, task_id, "cancel"))
    assert status["state"] == "cancelled"
    assert status["partial"] is True
    assert status["result"] == "Found a possible cause; not yet verified."
    assert status["receipts"][receipt["message_id"]] == "undelivered"
    if inline:
        result = await execution
        assert is_tool_error_result(result)
        assert result == f"Task cancelled.\nPartial result:\n{status['result']}"
        assert manager.bus.inbound_size == 0
    else:
        notice = await manager.bus.consume_inbound()
        assert status["result"] in notice.content
        assert notice.metadata["subagent_state"] == "cancelled"
    await manager.close()


@pytest.mark.asyncio
async def test_empty_final_response_is_a_failure(tmp_path):
    manager, provider, ctx = setup(tmp_path)
    provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content=""))
    task_id = await spawn(manager, ctx)
    await settled(manager)
    status = json.loads(await control(manager, ctx, task_id))
    assert status["state"] == "error"
    assert status["stop_reason"] == "empty_final_response"
    assert status["error"]
    notice = await manager.bus.consume_inbound()
    assert "completed successfully" not in notice.content
    assert notice.metadata["subagent_state"] == "error"
    await manager.close()


@pytest.mark.asyncio
async def test_host_without_background_consumer_returns_the_child_result(tmp_path):
    manager, _, ctx = setup(tmp_path)
    ctx = RequestContext("cli", "oneshot", session_key="cli:oneshot", runtime=ctx.runtime,
                         background_subagents=False)
    manager.runner.run = AsyncMock(return_value=AgentRunResult(messages=[], final_content="verified"))
    with request_context(ctx):
        result = await SubagentTool(manager).execute("create", task="verify")
    assert result == "verified"
    assert manager.get_running_count() == 0
    assert manager.bus.inbound_size == 0
    await manager.close()


@pytest.mark.asyncio
async def test_provider_suppressed_cancellation_cannot_execute_returned_tools(tmp_path):
    manager, provider, ctx = setup(tmp_path)
    entered = asyncio.Event()

    async def chat(**kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(
                id="write", name="write_file", arguments={"path": "resurrected.txt", "content": "bad"},
            )])

    provider.chat_stream_with_retry = AsyncMock(side_effect=chat)
    task_id = await spawn(manager, ctx)
    await entered.wait()
    assert json.loads(await control(manager, ctx, task_id, "cancel"))["state"] == "cancelled"
    assert provider.chat_stream_with_retry.await_count == 1
    assert not (tmp_path / "resurrected.txt").exists()
    assert manager.bus.inbound_size == 1
    await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["done", "error", "cancel"])
async def test_real_task_process_cleanup_preserves_sibling_parent_and_work_products(tmp_path, ending):
    manager, _, ctx = setup(tmp_path)
    script = tmp_path / "worker.py"
    script.write_text("import sys\nprint('READY', flush=True)\nfor line in sys.stdin:\n print(line.strip(), flush=True)\n")
    argv = [sys.executable, "-u", str(script)]
    command = subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
    kwargs = {"command": command, "yield_time_ms": 100, "timeout": 60}
    if os.name == "nt":
        kwargs["shell"] = "cmd"
    events = {name: asyncio.Event() for name in ["one", "two"]}
    releases = {name: asyncio.Event() for name in events}
    exec_ids = {}
    processes = {}

    async def run(spec):
        name = spec.initial_messages[-1]["content"]
        written = await spec.tools.execute("write_file", {"path": f"{name}-output.txt", "content": name})
        assert not is_tool_error_result(written), written
        output = await spec.tools.execute("exec", kwargs)
        assert not is_tool_error_result(output), output
        exec_ids[name] = re.search(r"session_id: (\w+)", output).group(1)
        exec_manager = spec.tools.get("exec")._session_manager
        processes[name] = exec_manager._sessions[exec_ids[name]].process
        events[name].set()
        await releases[name].wait()
        if name == "one" and ending == "error":
            raise RuntimeError("task failed")
        return AgentRunResult(messages=[], final_content="finished")

    manager.runner.run = run
    # The parent's exec manager must not be closed by task cancellation.
    parent_exec = ExecTool(working_dir=str(tmp_path), session_manager=manager._exec_session_manager)
    try:
        with request_context(ctx):
            output = await parent_exec.execute(**kwargs)
        parent_id = re.search(r"session_id: (\w+)", output).group(1)
        one = await spawn(manager, ctx, "one")
        two = await spawn(manager, ctx, "two")
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in events.values())), 15)
        one_exec_manager = manager._tasks[one].exec_manager
        if ending == "cancel":
            await control(manager, ctx, one, "cancel")
        else:
            releases["one"].set()
            await asyncio.gather(manager._running_tasks[one], return_exceptions=True)
        expected = {"cancel": "cancelled", "error": "error", "done": "done"}[ending]
        assert json.loads(await control(manager, ctx, one))["state"] == expected
        assert await asyncio.wait_for(processes["one"].wait(), timeout=5) is not None
        with pytest.raises(KeyError):
            await one_exec_manager.write(
                session_id=exec_ids["one"], chars=None, close_stdin=False, terminate=False,
                yield_time_ms=0, max_output_chars=1000, owner_session_key=f"subagent:{one}",
            )
        for session_id, owner, exec_manager in [
            (exec_ids["two"], f"subagent:{two}", manager._tasks[two].exec_manager),
            (parent_id, "owner", manager._exec_session_manager),
        ]:
            poll = await exec_manager.write(
                session_id=session_id, chars="SURVIVED\n", close_stdin=False, terminate=False,
                yield_time_ms=1000, max_output_chars=1000, owner_session_key=owner,
            )
            assert not poll.done
            assert "SURVIVED" in poll.output
        assert script.exists()
        assert await manager.cancel_by_session("owner") == 1
        assert manager.bus.inbound_size == 1  # No cancelled sibling notice on parent stop.
        parent_poll = await manager._exec_session_manager.write(
            session_id=parent_id, chars="STILL ALIVE\n", close_stdin=False, terminate=False,
            yield_time_ms=1000, max_output_chars=1000, owner_session_key="owner",
        )
        assert not parent_poll.done and "STILL ALIVE" in parent_poll.output
    finally:
        await manager.close()
    assert script.exists()
    assert (tmp_path / "one-output.txt").read_text() == "one"
    assert (tmp_path / "two-output.txt").read_text() == "two"


@pytest.mark.asyncio
async def test_terminal_retention_and_active_capacity_are_bounded(tmp_path):
    manager, _, ctx = setup(tmp_path)
    manager.MAX_TERMINAL = 2
    manager.MAX_ACTIVE = 1
    entered, release = asyncio.Event(), asyncio.Event()

    async def run(spec):
        entered.set()
        await release.wait()
        return AgentRunResult(messages=[], final_content="done")

    manager.runner.run = run
    first = await spawn(manager, ctx)
    await entered.wait()
    with request_context(ctx):
        assert is_tool_error_result(await SubagentTool(manager).execute(action="create", task="overflow"))
    release.set()
    await settled(manager)
    for _ in range(3):
        await spawn(manager, ctx)
        await settled(manager)
    assert len(manager.runtime_statuses()) == 2
    assert len(manager.statuses_for_session("owner")) == 2
    assert is_tool_error_result(await control(manager, ctx, first))
    await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("shutdown", [False, True])
async def test_completion_wins_cancel_race_and_rejects_late_messages(tmp_path, shutdown):
    manager, _, ctx = setup(tmp_path)
    manager.runner.run = AsyncMock(return_value=AgentRunResult(messages=[], final_content="finished"))
    cleaning, release = asyncio.Event(), asyncio.Event()
    task_id = await spawn(manager, ctx)
    exec_manager = manager._tasks[task_id].exec_manager
    cleanup = exec_manager.close_all

    async def gated_cleanup():
        cleaning.set()
        await release.wait()
        return await cleanup()

    exec_manager.close_all = gated_cleanup
    message_id = json.loads(await control(manager, ctx, task_id, "send", "too late"))["message_id"]
    await cleaning.wait()
    assert json.loads(await control(manager, ctx, task_id))["state"] == "stopping"
    assert is_tool_error_result(await control(manager, ctx, task_id, "send", "rejected"))
    cancellation = asyncio.create_task(manager.close() if shutdown else control(manager, ctx, task_id, "cancel"))
    await asyncio.sleep(0)
    release.set()
    await cancellation
    await settled(manager)
    state = json.loads(await control(manager, ctx, task_id))
    assert state["state"] == "done"
    assert state["receipts"][message_id] == "undelivered"
    assert state["result"] == "finished"
    assert manager.bus.inbound_size == (0 if shutdown else 1)
    await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("late_failure", [False, True])
async def test_cancel_wins_over_late_execution_result(tmp_path, late_failure):
    manager, _, ctx = setup(tmp_path)
    entered, stopping, release = (asyncio.Event() for _ in range(3))

    async def run(spec):
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            stopping.set()
            await release.wait()
            if late_failure:
                raise RuntimeError("late failure")
            return AgentRunResult(messages=[], final_content="not success")

    manager.runner.run = run
    task_id = await spawn(manager, ctx)
    await entered.wait()
    message_id = json.loads(await control(manager, ctx, task_id, "send", "pending"))["message_id"]
    cancelled = asyncio.create_task(control(manager, ctx, task_id, "cancel"))
    await stopping.wait()
    assert is_tool_error_result(await control(manager, ctx, task_id, "send", "late"))
    release.set()
    state = json.loads(await cancelled)
    assert state["state"] == "cancelled"
    assert state["receipts"][message_id] == "undelivered"
    assert state["result"] == "Task cancelled."
    assert json.loads(await control(manager, ctx, task_id, "cancel")) == state
    assert manager.bus.inbound_size == 1
    await manager.close()


@pytest.mark.asyncio
async def test_inline_caller_cancel_closes_child_without_notice(tmp_path):
    manager, _, ctx = setup(tmp_path)
    entered = asyncio.Event()

    async def run(spec):
        entered.set()
        await asyncio.Event().wait()

    manager.runner.run = run
    with request_context(ctx):
        inline = asyncio.create_task(SubagentTool(manager).execute(action="create", task="wait", wait=True))
    await entered.wait()
    inline.cancel()
    with pytest.raises(asyncio.CancelledError):
        await inline
    assert [s.state for s in manager.statuses_for_session("owner").values()] == ["cancelled"]
    assert manager.get_running_count() == 0
    assert manager.bus.inbound_size == 0
    await manager.close()


@pytest.mark.asyncio
async def test_cleanup_failure_survives_status_eviction_and_shutdown_retries(tmp_path):
    manager, _, ctx = setup(tmp_path)
    manager.MAX_TERMINAL = 1
    manager.runner.run = AsyncMock(return_value=AgentRunResult(
        messages=[], final_content="x" * (manager.max_tool_result_chars + 1),
    ))
    task_id = await spawn(manager, ctx)
    exec_manager = manager._tasks[task_id].exec_manager
    original_cleanup = exec_manager.close_all
    exec_manager.close_all = AsyncMock(side_effect=RuntimeError("cleanup failed"))
    message_id = json.loads(await control(manager, ctx, task_id, "send", "pending"))["message_id"]
    await settled(manager)
    state = json.loads(await control(manager, ctx, task_id))
    assert state["state"] == "error"
    assert "cleanup failed" in state["error"]
    assert state["receipts"][message_id] == "undelivered"
    assert json.loads(await control(manager, ctx, task_id, "cancel")) == state
    exec_manager.close_all.assert_awaited_once()
    assert manager.bus.inbound_size == 1
    assert task_id in manager._tasks
    assert len(manager._tasks[task_id].outcome.result) == manager.max_tool_result_chars
    newer = await spawn(manager, ctx)
    await settled(manager)
    assert json.loads(await control(manager, ctx, newer))["state"] == "done"
    assert is_tool_error_result(await control(manager, ctx, task_id, "cancel"))
    manager.MAX_ACTIVE = 1
    with request_context(ctx):
        assert is_tool_error_result(await SubagentTool(manager).execute(action="create", task="over capacity"))
    exec_manager.close_all = original_cleanup
    await manager.close()
    assert not manager._tasks
    assert list(manager.runtime_statuses()) == [newer]


@pytest.mark.asyncio
async def test_tool_suppressed_cancellation_cannot_start_next_tool(tmp_path):
    manager, provider, ctx = setup(tmp_path)
    entered = asyncio.Event()
    calls = []

    class PauseTool(Tool):
        name = "pause"
        description = "Wait for a signal."
        parameters = {"type": "object", "properties": {}}

        async def execute(self, **kwargs):
            calls.append("pause")
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return "suppressed"

    registry = ToolRegistry()
    registry.register(PauseTool())
    manager._build_tools = lambda **kwargs: registry
    provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(
        content=None,
        tool_calls=[ToolCallRequest(id=str(i), name="pause", arguments={}) for i in range(2)],
    ))
    task_id = await spawn(manager, ctx)
    await entered.wait()
    assert json.loads(await control(manager, ctx, task_id, "cancel"))["state"] == "cancelled"
    assert calls == ["pause"]
    assert provider.chat_stream_with_retry.await_count == 1
    await manager.close()


@pytest.mark.asyncio
async def test_long_running_task_receipts_survive_newer_task_retention(tmp_path):
    manager, _, ctx = setup(tmp_path)
    manager.MAX_TERMINAL = 1
    entered, release = asyncio.Event(), asyncio.Event()

    async def run(spec):
        if spec.initial_messages[-1]["content"] == "old":
            entered.set()
            await release.wait()
        return AgentRunResult(messages=[], final_content="done")

    manager.runner.run = run
    old = await spawn(manager, ctx, "old")
    await entered.wait()
    message_id = json.loads(await control(manager, ctx, old, "send", "pending"))["message_id"]
    newer = await spawn(manager, ctx, "new")
    await manager._running_tasks[newer]
    release.set()
    await settled(manager)
    assert is_tool_error_result(await control(manager, ctx, newer))
    assert json.loads(await control(manager, ctx, old))["receipts"][message_id] == "undelivered"
    await manager.bus.consume_inbound()
    notice = await manager.bus.consume_inbound()
    assert notice.metadata["subagent_task_id"] == old
    assert notice.metadata["subagent_message_receipts"] == {message_id: "undelivered"}
    await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["cancel", "session", "close", "inline"])
async def test_resistant_dependency_has_bounded_stop_and_no_late_result(tmp_path, operation):
    manager, provider, ctx = setup(tmp_path, max_concurrent_subagents=1)
    manager.CANCEL_WAIT_SECONDS = 0.02
    entered, cancelled, release = (asyncio.Event() for _ in range(3))

    async def chat(**kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()
            return LLMResponse(content="must not publish", tool_calls=[ToolCallRequest(
                id="late", name="write_file", arguments={"path": "late.txt", "content": "bad"},
            )])

    provider.chat_stream_with_retry = AsyncMock(side_effect=chat)
    inline = None
    if operation == "inline":
        with request_context(ctx):
            inline = asyncio.create_task(SubagentTool(manager).execute(action="create", task="wait", wait=True))
        await entered.wait()
        task_id = next(iter(manager.statuses_for_session("owner")))
    else:
        task_id = await spawn(manager, ctx)
        await entered.wait()
    record = manager._tasks[task_id]
    status = record.status
    try:
        if operation == "cancel":
            result = await asyncio.wait_for(control(manager, ctx, task_id, "cancel"), 1)
            assert json.loads(result)["state"] == "stopping"
        elif operation == "session":
            assert await asyncio.wait_for(manager.cancel_by_session("owner"), 1) == 1
        elif operation == "close":
            await asyncio.wait_for(manager.close(), 1)
        else:
            inline.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(inline, 1)
        assert cancelled.is_set()
        assert status.state == "stopping"
        assert manager.get_running_count() == 1
        assert manager._run_slots.locked()
        assert record.cleanup_task.done()
        assert record.exec_manager._closed
        assert is_tool_error_result(await control(manager, ctx, task_id, "send", "rejected"))
        # Repeated cancel is bounded and must not interrupt the resistant coroutine.
        assert json.loads(await control(manager, ctx, task_id, "cancel"))["state"] == "stopping"
        assert manager.bus.inbound_size == 0
    finally:
        release.set()
        await asyncio.wait_for(settled(manager), 2)
        await manager.close()
    assert status.state == "cancelled"
    assert not (tmp_path / "late.txt").exists()
    assert provider.chat_stream_with_retry.await_count == 1
    assert manager.get_running_count() == 0
    assert manager.bus.inbound_size == (1 if operation == "cancel" else 0)


@pytest.mark.asyncio
async def test_targeted_inline_cancel_does_not_cancel_waiting_parent(tmp_path):
    manager, _, ctx = setup(tmp_path)
    entered = asyncio.Event()

    async def run(spec):
        entered.set()
        await asyncio.Event().wait()

    manager.runner.run = run
    with request_context(ctx):
        parent = asyncio.create_task(SubagentTool(manager).execute(action="create", task="wait", wait=True))
    await entered.wait()
    task_id = next(iter(manager.statuses_for_session("owner")))
    await control(manager, ctx, task_id, "cancel")
    assert is_tool_error_result(await parent)
    assert not parent.cancelled()
    assert manager.bus.inbound_size == 0
    await manager.close()


@pytest.mark.asyncio
async def test_cleanup_wait_is_bounded_and_repeated_cancel_does_not_interrupt_it(tmp_path):
    manager, _, ctx = setup(tmp_path)
    manager.CANCEL_WAIT_SECONDS = 0.02
    manager.runner.run = AsyncMock(return_value=AgentRunResult(messages=[], final_content="done"))
    cleaning, release = asyncio.Event(), asyncio.Event()
    task_id = await spawn(manager, ctx)
    record = manager._tasks[task_id]
    status = record.status
    original = record.exec_manager.close_all

    async def cleanup():
        cleaning.set()
        await release.wait()
        return await original()

    record.exec_manager.close_all = cleanup
    await cleaning.wait()
    try:
        assert json.loads(await asyncio.wait_for(control(manager, ctx, task_id, "cancel"), 1))["state"] == "stopping"
        await asyncio.wait_for(manager.close(), 1)
        assert status.state == "stopping"
        assert manager.get_running_count() == 1
        assert not record.cleanup_task.done()
    finally:
        release.set()
        await asyncio.wait_for(settled(manager), 2)
    assert status.state == "done"
    assert manager.bus.inbound_size == 0


def test_subagent_schema_exposes_task_actions(tmp_path):
    manager, _, _ = setup(tmp_path)
    properties = SubagentTool(manager).parameters["properties"]
    assert properties["action"]["enum"] == ["create", "send", "cancel", "check"]
    assert "owner" not in properties
    tool = SubagentTool(manager)
    assert tool.validate_params({"action": "create", "task": "review"}) == []
    assert tool.validate_params({"action": "check"}) == []
    assert tool.validate_params({"action": "send", "task_id": "task", "message": "update"}) == []
    assert tool.validate_params({"action": "cancel", "task_id": "task"}) == []
