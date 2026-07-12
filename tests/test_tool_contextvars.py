from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.tools.cron import CronTool
from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.spawn import SpawnTool
from nanobot.cron.service import CronService
from nanobot.providers.base import GenerationSettings, LLMProvider
from nanobot.session.keys import UNIFIED_SESSION_KEY
from nanobot.utils.llm_runtime import LLMRuntime


def _runtime(model: str = "test-model") -> LLMRuntime:
    provider = MagicMock(spec=LLMProvider)
    provider.generation = GenerationSettings()
    return LLMRuntime.capture(provider, model, context_window_tokens=128_000)


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
