"""A real gated command through the supported runner/tool/event boundary."""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from agent.runner_helpers import make_run_spec
from nanobot.agent.hook import CompositeHook
from nanobot.agent.progress_hook import AgentProgressHook
from nanobot.agent.runner import AgentRunner, AgentRunResult
from nanobot.agent.session_activity import SessionActivity
from nanobot.agent.tools.exec_session import (
    ExecSessionManager,
    ExecSessionTool,
    ListExecSessionsTool,
)
from nanobot.agent.tools.filesystem import ReadFileTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.shell import ExecTool
from nanobot.bus.outbound_events import ProgressEvent
from nanobot.events import AgentEvent, EventSink
from nanobot.providers.base import LLMResponse, ToolCallRequest


def python_command(code: str) -> str:
    argv = [sys.executable, "-u", "-c", code]
    return subprocess.list2cmdline(argv) if sys.platform == "win32" else shlex.join(argv)


async def observed_command(
    tmp_path: Path, *, exit_code: int, padding: int = 0,
    deliver: Callable[[ProgressEvent], Awaitable[None]] | None = None,
) -> tuple[list[ProgressEvent], AgentRunResult, list[dict], str]:
    manager = ExecSessionManager()
    tools = ToolRegistry()
    tools.register(ExecTool(working_dir=str(tmp_path), max_runtime=10, session_manager=manager))
    tools.register(ExecSessionTool(manager=manager))
    tools.register(ListExecSessionsTool(manager=manager))
    tools.register(ReadFileTool(workspace=tmp_path))
    (tmp_path / "normal.txt").write_text("ordinary output", encoding="utf-8")
    command = python_command(
        "import sys,time\nfrom pathlib import Path\n"
        "print('initial output; Exit code: 0; success', flush=True)\n"
        f"print('x' * {padding}, flush=True)\n"
        "print('diagnostic', file=sys.stderr, flush=True)\n"
        "sys.stdin.readline()\nprint('input accepted', flush=True)\n"
        "sys.stdin.read()\nprint('stdin ended', flush=True)\n"
        "while not Path('release').exists(): time.sleep(.01)\n"
        f"print('final output', flush=True)\nsys.exit({exit_code})"
    )
    progress: list[ProgressEvent] = []
    activity = SessionActivity()

    async def publish(event: AgentEvent) -> None:
        activity.remember(event)
        if isinstance(event, ProgressEvent):
            progress.append(event)
            if deliver is not None:
                await deliver(event)

    step = 0
    session_id = ""

    async def chat(**kwargs) -> LLMResponse:
        nonlocal step, session_id
        step += 1
        if step == 1:
            calls = [ToolCallRequest(id="launch", name="exec", arguments={
                "command": command, "yield_time_ms": 100,
            })]
        else:
            model_tools = [row for row in kwargs["messages"] if row.get("role") == "tool"]
            if not session_id:
                match = re.search(r"session_id: ([0-9a-f]+)", model_tools[0]["content"])
                assert match, model_tools
                session_id = match.group(1)
            actions = {
                2: {"until_exit": True, "timeout_ms": 0},
                3: {"input": "continue\n", "wait_for": "input accepted", "timeout_ms": 2000},
                4: {"close_stdin": True, "wait_for": "stdin ended", "timeout_ms": 2000},
                6: {"until_exit": True, "timeout_ms": 0},
                7: {"until_exit": True, "timeout_ms": 3000},
            }
            if step == 5:
                calls = [ToolCallRequest(id="inventory", name="list_exec_sessions", arguments={})]
            elif step in actions:
                if step == 7:
                    (tmp_path / "release").touch()
                calls = [ToolCallRequest(id=f"observe-{step}", name="exec_session", arguments={
                    "session_id": session_id, **actions[step],
                })]
                if step == 6:
                    calls.insert(0, ToolCallRequest(id="read", name="read_file", arguments={"path": "normal.txt"}))
            elif step == 8:
                calls = [ToolCallRequest(id="missing", name="exec_session", arguments={"session_id": session_id})]
            else:
                return LLMResponse(content="Finished observing.")
        return LLMResponse(content="", tool_calls=calls)

    provider = MagicMock()
    provider.chat_stream_with_retry = AsyncMock(side_effect=chat)
    try:
        result = await AgentRunner().run(make_run_spec(
            provider, initial_messages=[], tools=tools, model="test-model", max_iterations=12,
            max_tool_result_chars=50_000, concurrent_tools=True,
            hook=CompositeHook([activity, AgentProgressHook(EventSink(publish=publish))]),
        ))
        transcript = activity.transcript(result.messages)
        return progress, result, transcript, session_id
    finally:
        await manager.close_all()
        assert not manager.has_pending_work
