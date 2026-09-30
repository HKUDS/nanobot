"""Session cancellation across tool calls, detached resources, and late admission."""

import asyncio
import os
import re
import sys
from unittest.mock import MagicMock

import pytest

from nanobot.agent.goal_permission import goal_mutation_allowed
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.tools.exec_session import ExecSessionManager
from nanobot.agent.tools.shell import ExecTool
from nanobot.apps.cli.service import CliAppManager, CliAppRun
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.command.builtin import cmd_stop
from nanobot.command.router import CommandContext
from nanobot.providers.base import GenerationSettings, LLMResponse
from nanobot.utils.cancellation import CancellationScope
from nanobot.utils.llm_runtime import LLMRuntime


@pytest.mark.asyncio
async def test_direct_goal_work_serializes_with_the_session_and_stops_while_waiting(tmp_path):
    provider = MagicMock()
    provider.generation = GenerationSettings()
    provider.get_default_model.return_value = "test"
    provider.estimate_prompt_tokens.return_value = (100, "test")
    started, release = asyncio.Event(), asyncio.Event()
    permissions = []

    async def respond(**kwargs):
        permissions.append(goal_mutation_allowed())
        if len(permissions) == 1:
            started.set()
            await release.wait()
        return LLMResponse(content="done")

    provider.chat_stream_with_retry = respond
    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path, model="test")
    running = asyncio.create_task(loop.process_direct("Discuss the migration."))
    goal = None
    try:
        await asyncio.wait_for(started.wait(), 3)
        goal = asyncio.create_task(loop.process_direct("/goal Verify the migration."))
        async with asyncio.timeout(3):
            while not any(
                row.get("content") == "/goal Verify the migration."
                for row in loop.sessions.get_or_create("cli:direct").messages
            ):
                await asyncio.sleep(0)
        assert permissions == [False]
        response = await asyncio.wait_for(loop.process_direct("/stop"), 3)
        assert "Stopped 2" in response.content
        results = await asyncio.wait_for(asyncio.gather(running, goal, return_exceptions=True), 3)
        assert all(isinstance(result, asyncio.CancelledError) for result in results)
        assert permissions == [False]
        response = await loop.process_direct("/goal Verify the migration.")
        assert response.content == "done"
        assert permissions == [False, True]
        assert goal_mutation_allowed() is False
    finally:
        release.set()
        await asyncio.gather(running, *([goal] if goal is not None else []), return_exceptions=True)
        await loop.aclose()


@pytest.mark.asyncio
async def test_session_stop_broadcasts_before_parent_exit_and_allows_a_fresh_turn(tmp_path, monkeypatch):
    provider = MagicMock()
    provider.generation = GenerationSettings()
    provider.get_default_model.return_value = "test"
    runtime = LLMRuntime.capture(provider, "test", context_window_tokens=128000)
    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path)
    parent_release, child_stopped, parent_stopped = (asyncio.Event() for _ in range(3))
    ready = {key: asyncio.Event() for key in ("test:a", "test:b")}
    processes, children = {}, []
    cli_started = asyncio.Event()
    original_spawn = ExecTool._spawn

    async def capture_spawn(command, *args, **kwargs):
        process = await original_spawn(command, *args, **kwargs)
        if isinstance(command, list) and "cli-owned" in command[-1]:
            processes["cli"] = process
            cli_started.set()
        return process

    monkeypatch.setattr(ExecTool, "_spawn", capture_spawn)
    cli_plan = CliAppRun(
        name="demo", entry=sys.executable,
        argv=[sys.executable, "-c", "import time; print('cli-owned', flush=True); time.sleep(60)"],
        cwd=tmp_path, timeout=60, env=dict(os.environ), artifact_snapshot={},
    )
    monkeypatch.setattr(CliAppManager, "prepare_run", lambda *args, **kwargs: cli_plan)

    async def child_run(spec):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            child_stopped.set()
            raise

    loop.subagents.runner.run = child_run

    async def process_message(msg, **kwargs):
        key = kwargs.get("session_key", msg.session_key)
        with request_context(RequestContext("test", msg.chat_id, session_key=key, runtime=runtime)):
            if msg.content == "new turn":
                result = await loop.tools.execute("exec", {"command": "echo fresh"})
                return OutboundMessage(channel="test", chat_id=msg.chat_id, content=str(result))
            output = await loop.tools.execute("exec", {
                "command": (
                    "Write-Output ready; Start-Sleep -Seconds 60" if sys.platform == "win32"
                    else "printf 'ready\\n'; sleep 60"
                ),
                "yield_time_ms": 100,
            })
            sid = re.search(r"session_id:\s*([0-9a-f]+)", output).group(1)
            processes[key] = loop._exec_session_manager._sessions[sid].process
            if key == "test:a":
                await loop.tools.execute("spawn", {"task": "background work"})
                cli = asyncio.create_task(loop.tools.execute("run_cli_app", {"name": "demo"}))
                children.append(cli)
                await cli_started.wait()
            ready[key].set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                if key != "test:a":
                    raise
                asyncio.current_task().uncancel()
                parent_stopped.set()
                await parent_release.wait()
                # A dependency may consume the exception, but this old turn cannot
                # start a second child or process after the session broadcast.
                await loop.tools.execute("spawn", {"task": "must not start"})

    monkeypatch.setattr(loop, "_process_message", process_message)
    for chat in ("a", "b"):
        loop._enqueue_session_message(InboundMessage("test", "user", chat, "work"))
    stopping = None
    try:
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in ready.values())), 5)
        assert all(process.returncode is None for process in processes.values())
        stop = InboundMessage("test", "user", "a", "/stop")
        stopping = asyncio.create_task(cmd_stop(CommandContext(
            msg=stop, session=None, key="test:a", raw="/stop", loop=loop,
        )))
        await asyncio.wait_for(parent_stopped.wait(), 1)
        await asyncio.wait_for(child_stopped.wait(), 1)
        await asyncio.wait_for(asyncio.gather(processes["test:a"].wait(), processes["cli"].wait()), 2)
        assert not stopping.done()
        assert processes["test:b"].returncode is None
        parent_release.set()
        result = await asyncio.wait_for(stopping, 2)
        assert "Stopped 4" in result.content
        statuses = loop.subagents.statuses_for_session("test:a")
        assert len(statuses) == 1
        assert next(iter(statuses.values())).state == "cancelled"
        assert loop.bus.inbound_size == 0  # No cancelled child completion revives the session.
        response = await loop.process_direct("new turn", session_key="test:a", channel="test", chat_id="a")
        assert "fresh" in response.content
        assert processes["test:b"].returncode is None
    finally:
        parent_release.set()
        if stopping is not None:
            await asyncio.gather(stopping, return_exceptions=True)
        await loop.aclose()
        await asyncio.gather(*children, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("detached", [False, True])
async def test_process_created_across_cancel_is_cleaned_without_becoming_usable(tmp_path, monkeypatch, detached):
    scope, manager = CancellationScope(), ExecSessionManager()
    spawning, release = asyncio.Event(), asyncio.Event()
    processes = []
    original_spawn = ExecTool._spawn

    async def slow_spawn(*args, **kwargs):
        spawning.set()
        await release.wait()
        process = await original_spawn(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(ExecTool, "_spawn", slow_spawn)
    command = [sys.executable, "-c", "import time; time.sleep(60)"]
    with scope.activate():
        if detached:
            task = asyncio.create_task(manager.start(
                command=command, cwd=str(tmp_path), env=dict(os.environ), timeout=60,
                shell_program=None, login=False, yield_time_ms=0, max_output_chars=1000,
                owner_session_key="owner",
            ))
        else:
            task = asyncio.create_task(ExecTool.run_process(command, str(tmp_path), dict(os.environ)))
    try:
        await spawning.wait()
        scope.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 3)
        await scope.wait()
        assert len(processes) == 1
        assert processes[0].returncode is not None
        assert await manager.list(owner_session_key="owner") == []
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await manager.close_all()


@pytest.mark.asyncio
async def test_failed_stop_callback_does_not_block_broadcast_or_late_resource_cleanup():
    scope, stopped = CancellationScope(), []

    def fail():
        raise OSError("stop failed")

    scope.register(fail)
    scope.register(lambda: stopped.append("sibling"))
    scope.cancel()
    scope.register(lambda: stopped.append("late resource"))
    assert stopped == ["sibling", "late resource"]
    with pytest.raises(ExceptionGroup, match="failed to cancel runtime resources"):
        await scope.wait()
