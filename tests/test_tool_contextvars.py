from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.agent.tools import Tool, ToolRegistry, ToolResult, current_tool_invocation_context
from nanobot.agent.tools.context import (
    RequestContext,
    request_context,
    tool_invocation_context,
)
from nanobot.agent.tools.cron import CronTool
from nanobot.agent.tools.execution import execute_tool_calls
from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.spawn import SpawnTool
from nanobot.cron.service import CronService
from nanobot.providers.base import GenerationSettings, LLMProvider, ToolCallRequest
from nanobot.runtime_context import RUNTIME_CONTEXT_INPUT_META, RuntimeContextBlock
from nanobot.session.keys import UNIFIED_SESSION_KEY
from nanobot.utils.llm_runtime import LLMRuntime


def _runtime(model: str = "test-model") -> LLMRuntime:
    provider = MagicMock(spec=LLMProvider)
    provider.generation = GenerationSettings()
    return LLMRuntime.capture(provider, model, context_window_tokens=128_000)


class _InvocationCaptureTool(Tool):
    def __init__(
        self,
        seen: dict[str, tuple[str, str | None]],
        *,
        barrier: asyncio.Event | None = None,
        fail: bool = False,
        return_error: bool = False,
    ) -> None:
        self._seen = seen
        self._barrier = barrier
        self._fail = fail
        self._return_error = return_error
        self._entered = 0
        self._lock = asyncio.Lock()

    @property
    def name(self) -> str:
        return "capture_invocation"

    @property
    def description(self) -> str:
        return "Capture the current tool invocation context."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"label": {"type": "string"}},
            "required": ["label"],
        }

    @property
    def concurrency_safe(self) -> bool:
        return True

    async def execute(self, label: str) -> str:
        invocation = current_tool_invocation_context()
        assert invocation is not None
        self._seen[label] = (invocation.tool_call_id, invocation.invocation_key)

        if self._barrier is not None:
            async with self._lock:
                self._entered += 1
                if self._entered == 2:
                    self._barrier.set()
            await self._barrier.wait()
            after_overlap = current_tool_invocation_context()
            assert after_overlap == invocation

        if self._fail:
            raise RuntimeError("boom")
        if self._return_error:
            return ToolResult.error("Error: rejected")
        return label


class _BlockingInvocationTool(Tool):
    def __init__(self, entered: asyncio.Event) -> None:
        self._entered = entered

    @property
    def name(self) -> str:
        return "blocking_invocation"

    @property
    def description(self) -> str:
        return "Block until cancelled."

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self) -> str:
        assert current_tool_invocation_context() is not None
        self._entered.set()
        await asyncio.Event().wait()
        return "unreachable"


class _InvocationRecordingHook(AgentHook):
    def __init__(self) -> None:
        super().__init__()
        self.before: tuple[str, str | None] | None = None
        self.after: tuple[str, str | None] | None = None
        self.error: tuple[str, str | None] | None = None

    @staticmethod
    def _current() -> tuple[str, str | None]:
        invocation = current_tool_invocation_context()
        assert invocation is not None
        return invocation.tool_call_id, invocation.invocation_key

    async def before_execute_tool(self, context, tool_call, tool, params) -> None:
        self.before = self._current()

    async def after_execute_tool(self, context, tool_call, tool, params, result) -> None:
        self.after = self._current()

    async def on_execute_tool_error(self, context, tool_call, tool, params, error) -> None:
        self.error = self._current()


async def _run_invocation_calls(
    registry: ToolRegistry,
    calls: list[ToolCallRequest],
    *,
    concurrent: bool = False,
    hook: AgentHook | None = None,
) -> tuple[list[Any], list[dict[str, str]]]:
    return await execute_tool_calls(
        registry,
        calls,
        concurrent=concurrent,
        external_lookup_counts={},
        workspace_violation_counts={},
        hook=hook or AgentHook(),
        context=AgentHookContext(iteration=1, messages=[]),
    )


def _invocation_call(call_id: str, label: str) -> ToolCallRequest:
    return ToolCallRequest(
        id=call_id,
        name="capture_invocation",
        arguments={"label": label},
    )


@pytest.mark.asyncio
async def test_message_tool_keeps_task_local_context() -> None:
    seen: list[tuple[str, str, str]] = []
    entered = asyncio.Event()
    release = asyncio.Event()

    async def send_callback(msg):
        seen.append((msg.channel, msg.chat_id, msg.content))
        return None

    tool = MessageTool(send_callback=send_callback)

    async def task_one() -> str:
        with request_context(RequestContext(channel="feishu", chat_id="chat-a")):
            entered.set()
            await release.wait()
            return await tool.execute(content="one")

    async def task_two() -> str:
        await entered.wait()
        with request_context(RequestContext(channel="email", chat_id="chat-b")):
            release.set()
            return await tool.execute(content="two")

    result_one, result_two = await asyncio.gather(task_one(), task_two())

    assert result_one == "Message sent to feishu:chat-a"
    assert result_two == "Message sent to email:chat-b"
    assert ("feishu", "chat-a", "one") in seen
    assert ("email", "chat-b", "two") in seen


@pytest.mark.asyncio
async def test_spawn_tool_keeps_task_local_context() -> None:
    seen: list[tuple[str, str, str]] = []
    entered = asyncio.Event()
    release = asyncio.Event()

    class _Manager:
        max_concurrent_subagents = 1

        def get_running_count(self) -> int:
            return 0

        async def spawn(
            self,
            *,
            task: str,
            runtime: LLMRuntime,
            label: str | None,
            origin_channel: str,
            origin_chat_id: str,
            session_key: str,
            origin_message_id: str | None = None,
            temperature: float | None = None,
            workspace_scope=None,
        ) -> str:
            seen.append((origin_channel, origin_chat_id, session_key))
            return f"{origin_channel}:{origin_chat_id}:{task}"

    tool = SpawnTool(_Manager())

    async def task_one() -> str:
        with request_context(RequestContext(
            channel="whatsapp",
            chat_id="chat-a",
            runtime=_runtime("model-a"),
        )):
            entered.set()
            await release.wait()
            return await tool.execute(task="one")

    async def task_two() -> str:
        await entered.wait()
        with request_context(RequestContext(
            channel="telegram",
            chat_id="chat-b",
            runtime=_runtime("model-b"),
        )):
            release.set()
            return await tool.execute(task="two")

    result_one, result_two = await asyncio.gather(task_one(), task_two())

    assert result_one == "whatsapp:chat-a:one"
    assert result_two == "telegram:chat-b:two"
    assert ("whatsapp", "chat-a", "whatsapp:chat-a") in seen
    assert ("telegram", "chat-b", "telegram:chat-b") in seen


@pytest.mark.asyncio
async def test_cron_tool_keeps_task_local_context(tmp_path) -> None:
    tool = CronTool(CronService(tmp_path / "jobs.json"))
    entered = asyncio.Event()
    release = asyncio.Event()

    async def task_one() -> str:
        with request_context(
            RequestContext(channel="feishu", chat_id="chat-a", session_key="feishu:chat-a")
        ):
            entered.set()
            await release.wait()
            return await tool.execute(action="add", message="first", every_seconds=60)

    async def task_two() -> str:
        await entered.wait()
        with request_context(
            RequestContext(channel="email", chat_id="chat-b", session_key="email:chat-b")
        ):
            release.set()
            return await tool.execute(action="add", message="second", every_seconds=60)

    result_one, result_two = await asyncio.gather(task_one(), task_two())

    assert result_one.startswith("Created job")
    assert result_two.startswith("Created job")

    jobs = tool._cron.list_jobs()
    assert {job.payload.session_key for job in jobs} == {"feishu:chat-a", "email:chat-b"}
    assert {(job.payload.origin_channel, job.payload.origin_chat_id) for job in jobs} == {
        ("feishu", "chat-a"),
        ("email", "chat-b"),
    }


# --- Basic single-task regression tests ---


@pytest.mark.asyncio
async def test_message_tool_basic_request_context_and_execute() -> None:
    """A bound request context should route a single execution correctly."""
    seen: list[tuple[str, str, str]] = []

    async def send_callback(msg):
        seen.append((msg.channel, msg.chat_id, msg.content))

    tool = MessageTool(send_callback=send_callback)
    with request_context(
        RequestContext(channel="telegram", chat_id="chat-123", message_id="msg-456")
    ):
        result = await tool.execute(content="hello")
    assert result == "Message sent to telegram:chat-123"
    assert seen == [("telegram", "chat-123", "hello")]


@pytest.mark.asyncio
async def test_message_tool_default_values_without_request_context() -> None:
    """Without a request context, constructor defaults should be used."""
    seen: list[tuple[str, str, str]] = []

    async def send_callback(msg):
        seen.append((msg.channel, msg.chat_id, msg.content))

    tool = MessageTool(
        send_callback=send_callback,
        default_channel="discord",
        default_chat_id="general",
    )

    result = await tool.execute(content="hi")
    assert result == "Message sent to discord:general"
    assert seen == [("discord", "general", "hi")]


@pytest.mark.asyncio
async def test_spawn_tool_basic_request_context_and_execute() -> None:
    """A bound request context should provide the correct origin."""
    seen: list[tuple[str, str, str]] = []

    class _Manager:
        max_concurrent_subagents = 1

        def get_running_count(self) -> int:
            return 0

        async def spawn(
            self,
            *,
            task,
            runtime,
            label,
            origin_channel,
            origin_chat_id,
            session_key,
            origin_message_id=None,
            temperature=None,
            workspace_scope=None,
        ):
            seen.append((origin_channel, origin_chat_id, session_key))
            return f"ok: {task}"

    tool = SpawnTool(_Manager())
    with request_context(RequestContext(
        channel="feishu",
        chat_id="chat-abc",
        runtime=_runtime(),
    )):
        result = await tool.execute(task="do something")
    assert result == "ok: do something"
    assert seen == [("feishu", "chat-abc", "feishu:chat-abc")]


@pytest.mark.asyncio
async def test_spawn_tool_rejects_missing_request_runtime() -> None:
    """Spawning cannot reconstruct a model runtime outside turn admission."""
    seen: list[tuple[str, str, str]] = []

    class _Manager:
        max_concurrent_subagents = 1

        def get_running_count(self) -> int:
            return 0

        async def spawn(
            self,
            *,
            task,
            runtime,
            label,
            origin_channel,
            origin_chat_id,
            session_key,
            origin_message_id=None,
            temperature=None,
            workspace_scope=None,
        ):
            seen.append((origin_channel, origin_chat_id, session_key))
            return "ok"

    tool = SpawnTool(_Manager())

    result = await tool.execute(task="test")
    assert result == "Error: spawn requires an active model runtime"
    assert result.is_error
    assert seen == []


@pytest.mark.asyncio
async def test_cron_tool_basic_request_context_and_execute(tmp_path) -> None:
    """A bound request context should provide the correct cron owner."""
    tool = CronTool(CronService(tmp_path / "jobs.json"))
    with request_context(
        RequestContext(channel="wechat", chat_id="user-789", session_key="wechat:user-789")
    ):
        result = await tool.execute(action="add", message="standup", every_seconds=300)
    assert result.startswith("Created job")

    jobs = tool._cron.list_jobs()
    assert len(jobs) == 1
    assert jobs[0].payload.session_key == "wechat:user-789"
    assert jobs[0].payload.origin_channel == "wechat"
    assert jobs[0].payload.origin_chat_id == "user-789"


@pytest.mark.asyncio
async def test_webui_cron_tool_uses_origin_session_when_unified_enabled(tmp_path) -> None:
    """WebUI-created cron jobs stay attached to the creating chat."""
    tool = CronTool(CronService(tmp_path / "jobs.json"))

    with request_context(
        RequestContext(
            channel="websocket",
            chat_id="chat-123",
            metadata={"webui": True},
            session_key=UNIFIED_SESSION_KEY,
        )
    ):
        result = await tool.execute(action="add", message="standup", every_seconds=300)
    assert result.startswith("Created job")

    jobs = tool._cron.list_jobs()
    assert len(jobs) == 1
    assert jobs[0].payload.session_key == "websocket:chat-123"
    assert jobs[0].payload.origin_channel == "websocket"
    assert jobs[0].payload.origin_chat_id == "chat-123"
    assert jobs[0].payload.origin_metadata == {"webui": True}


@pytest.mark.asyncio
async def test_cron_tool_snapshots_only_persistable_request_metadata(tmp_path) -> None:
    """Live runtime context must not poison a persisted WebUI cron job."""
    store_path = tmp_path / "jobs.json"
    service = CronService(store_path)
    tool = CronTool(service)
    await service.start()
    try:
        with request_context(
            RequestContext(
                channel="websocket",
                chat_id="chat-123",
                metadata={
                    "webui": True,
                    RUNTIME_CONTEXT_INPUT_META: [
                        RuntimeContextBlock(source="webui_quote", content="quoted reply")
                    ],
                    "opaque": object(),
                },
                session_key=UNIFIED_SESSION_KEY,
            )
        ):
            result = await tool.execute(action="add", message="standup", every_seconds=300)

        assert result.startswith("Created job")
        jobs = service.list_jobs()
        assert len(jobs) == 1
        assert jobs[0].payload.origin_metadata == {"webui": True}

        raw = json.loads(store_path.read_text(encoding="utf-8"))
        assert raw["jobs"][0]["payload"]["originMetadata"] == {"webui": True}
    finally:
        service.stop()


@pytest.mark.asyncio
async def test_cron_tool_preserves_thread_scoped_session_key(tmp_path) -> None:
    """Channel-provided thread session keys should remain the cron owner."""
    tool = CronTool(CronService(tmp_path / "jobs.json"))
    with request_context(
        RequestContext(
            channel="slack",
            chat_id="C123",
            metadata={"slack": {"thread_ts": "1700.42"}},
            session_key="slack:C123:1700.42",
        )
    ):
        result = await tool.execute(action="add", message="check thread", every_seconds=300)
    assert result.startswith("Created job")

    jobs = tool._cron.list_jobs()
    assert len(jobs) == 1
    assert jobs[0].payload.session_key == "slack:C123:1700.42"
    assert jobs[0].payload.origin_channel == "slack"
    assert jobs[0].payload.origin_chat_id == "C123"
    assert jobs[0].payload.origin_metadata == {"slack": {"thread_ts": "1700.42"}}


@pytest.mark.asyncio
async def test_cron_tool_no_context_returns_error(tmp_path) -> None:
    """Without a request context, add should fail with a clear error."""
    tool = CronTool(CronService(tmp_path / "jobs.json"))

    result = await tool.execute(action="add", message="test", every_seconds=60)
    assert result == "Error: scheduled cron jobs must be created from a chat session"


# --- Per-tool invocation context regression tests ---


@pytest.mark.asyncio
async def test_tool_invocation_context_exposes_current_call_identity() -> None:
    seen: dict[str, tuple[str, str | None]] = {}
    registry = ToolRegistry()
    registry.register(_InvocationCaptureTool(seen))

    with request_context(
        RequestContext(channel="test", chat_id="chat-1", session_key="test:chat-1")
    ):
        results, events = await _run_invocation_calls(
            registry,
            [_invocation_call("call-123", "one")],
        )

    assert results == ["one"]
    assert events[0]["status"] == "ok"
    tool_call_id, invocation_key = seen["one"]
    assert tool_call_id == "call-123"
    assert invocation_key is not None
    assert len(invocation_key) == 64
    assert current_tool_invocation_context() is None


@pytest.mark.asyncio
async def test_tool_invocation_key_is_stable_for_same_logical_call() -> None:
    seen: dict[str, tuple[str, str | None]] = {}
    registry = ToolRegistry()
    registry.register(_InvocationCaptureTool(seen))
    request = RequestContext(channel="test", chat_id="chat-1", session_key="test:chat-1")

    with request_context(request):
        await _run_invocation_calls(registry, [_invocation_call("call-stable", "first")])
    with request_context(request):
        await _run_invocation_calls(registry, [_invocation_call("call-stable", "second")])

    assert seen["first"][1] is not None
    assert seen["first"][1] == seen["second"][1]


@pytest.mark.asyncio
async def test_tool_invocation_keys_are_scoped_by_call_and_session() -> None:
    seen: dict[str, tuple[str, str | None]] = {}
    registry = ToolRegistry()
    registry.register(_InvocationCaptureTool(seen))

    with request_context(
        RequestContext(channel="test", chat_id="a", session_key="test:a")
    ):
        await _run_invocation_calls(
            registry,
            [
                _invocation_call("call-a", "call-a"),
                _invocation_call("call-b", "call-b"),
                _invocation_call("call-shared", "session-a"),
            ],
        )
    with request_context(
        RequestContext(channel="test", chat_id="b", session_key="test:b")
    ):
        await _run_invocation_calls(
            registry,
            [_invocation_call("call-shared", "session-b")],
        )

    assert seen["call-a"][1] != seen["call-b"][1]
    assert seen["session-a"][1] != seen["session-b"][1]


@pytest.mark.asyncio
async def test_parallel_tool_calls_keep_task_local_invocation_context() -> None:
    seen: dict[str, tuple[str, str | None]] = {}
    both_entered = asyncio.Event()
    registry = ToolRegistry()
    registry.register(_InvocationCaptureTool(seen, barrier=both_entered))

    with request_context(
        RequestContext(channel="test", chat_id="chat-1", session_key="test:chat-1")
    ):
        results, _events = await _run_invocation_calls(
            registry,
            [
                _invocation_call("call-a", "a"),
                _invocation_call("call-b", "b"),
            ],
            concurrent=True,
        )

    assert results == ["a", "b"]
    assert seen["a"][0] == "call-a"
    assert seen["b"][0] == "call-b"
    assert seen["a"][1] != seen["b"][1]
    assert current_tool_invocation_context() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("return_error", [False, True])
async def test_tool_invocation_context_is_reset_after_tool_failure(
    return_error: bool,
) -> None:
    seen: dict[str, tuple[str, str | None]] = {}
    registry = ToolRegistry()
    registry.register(
        _InvocationCaptureTool(
            seen,
            fail=not return_error,
            return_error=return_error,
        )
    )

    with request_context(
        RequestContext(channel="test", chat_id="chat-1", session_key="test:chat-1")
    ):
        results, events = await _run_invocation_calls(
            registry,
            [_invocation_call("call-fail", "failure")],
        )
        assert current_tool_invocation_context() is None

    assert events[0]["status"] == "error"
    assert "Error:" in str(results[0])
    assert seen["failure"][0] == "call-fail"


@pytest.mark.asyncio
async def test_tool_invocation_context_is_reset_after_cancellation() -> None:
    entered = asyncio.Event()
    cleanup_seen: list[object] = []
    registry = ToolRegistry()
    registry.register(_BlockingInvocationTool(entered))

    async def run() -> None:
        with request_context(
            RequestContext(channel="test", chat_id="chat-1", session_key="test:chat-1")
        ):
            try:
                await _run_invocation_calls(
                    registry,
                    [ToolCallRequest(id="call-cancel", name="blocking_invocation", arguments={})],
                )
            finally:
                cleanup_seen.append(current_tool_invocation_context())

    task = asyncio.create_task(run())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert cleanup_seen == [None]
    assert current_tool_invocation_context() is None


@pytest.mark.asyncio
async def test_tool_invocation_context_without_session_has_no_stable_key() -> None:
    seen: dict[str, tuple[str, str | None]] = {}
    registry = ToolRegistry()
    registry.register(_InvocationCaptureTool(seen))

    with request_context(
        RequestContext(channel="cli", chat_id="direct", session_key=None, turn_id="turn-1")
    ):
        await _run_invocation_calls(
            registry,
            [_invocation_call("call-ephemeral", "ephemeral")],
        )

    assert seen["ephemeral"] == ("call-ephemeral", None)


@pytest.mark.asyncio
async def test_tool_hooks_share_the_invocation_context() -> None:
    seen: dict[str, tuple[str, str | None]] = {}
    registry = ToolRegistry()
    registry.register(_InvocationCaptureTool(seen))
    hook = _InvocationRecordingHook()

    with request_context(
        RequestContext(channel="test", chat_id="chat-1", session_key="test:chat-1")
    ):
        await _run_invocation_calls(
            registry,
            [_invocation_call("call-hook", "hook")],
            hook=hook,
        )

    assert hook.before == seen["hook"]
    assert hook.after == seen["hook"]
    assert hook.error is None


@pytest.mark.asyncio
async def test_tool_error_hook_sees_invocation_context() -> None:
    seen: dict[str, tuple[str, str | None]] = {}
    registry = ToolRegistry()
    registry.register(_InvocationCaptureTool(seen, fail=True))
    hook = _InvocationRecordingHook()

    with request_context(
        RequestContext(channel="test", chat_id="chat-1", session_key="test:chat-1")
    ):
        await _run_invocation_calls(
            registry,
            [_invocation_call("call-error-hook", "error")],
            hook=hook,
        )

    assert hook.before == seen["error"]
    assert hook.error == seen["error"]
    assert hook.after is None


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["before", "after"])
async def test_tool_invocation_context_is_reset_after_hook_exception(phase: str) -> None:
    class _FailingHook(AgentHook):
        async def before_execute_tool(self, context, tool_call, tool, params) -> None:
            assert current_tool_invocation_context() is not None
            if phase == "before":
                raise RuntimeError("hook failed")

        async def after_execute_tool(self, context, tool_call, tool, params, result) -> None:
            assert current_tool_invocation_context() is not None
            if phase == "after":
                raise RuntimeError("hook failed")

    registry = ToolRegistry()
    registry.register(_InvocationCaptureTool({}))

    with request_context(
        RequestContext(channel="test", chat_id="chat-1", session_key="test:chat-1")
    ):
        with pytest.raises(RuntimeError, match="hook failed"):
            await _run_invocation_calls(
                registry,
                [_invocation_call("call-hook-fail", "hook-fail")],
                hook=_FailingHook(),
            )
        assert current_tool_invocation_context() is None


def test_nested_tool_invocation_context_restores_outer_identity() -> None:
    assert current_tool_invocation_context() is None

    with request_context(
        RequestContext(channel="test", chat_id="chat-1", session_key="test:chat-1")
    ):
        with tool_invocation_context("call-outer") as outer:
            assert current_tool_invocation_context() == outer
            with tool_invocation_context("call-inner") as inner:
                assert current_tool_invocation_context() == inner
                assert inner.invocation_key != outer.invocation_key
            assert current_tool_invocation_context() == outer

    assert current_tool_invocation_context() is None
