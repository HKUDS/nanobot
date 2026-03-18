from __future__ import annotations

import asyncio

import pytest

from nanobot.agent.tools.cron import CronTool
from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.spawn import SpawnTool
from nanobot.cron.service import CronService


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
        tool.set_context("feishu", "chat-a")
        entered.set()
        await release.wait()
        return await tool.execute(content="one")

    async def task_two() -> str:
        await entered.wait()
        tool.set_context("email", "chat-b")
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
        async def spawn(self, *, task: str, label: str | None, origin_channel: str, origin_chat_id: str, session_key: str) -> str:
            seen.append((origin_channel, origin_chat_id, session_key))
            return f"{origin_channel}:{origin_chat_id}:{task}"

    tool = SpawnTool(_Manager())

    async def task_one() -> str:
        tool.set_context("whatsapp", "chat-a")
        entered.set()
        await release.wait()
        return await tool.execute(task="one")

    async def task_two() -> str:
        await entered.wait()
        tool.set_context("telegram", "chat-b")
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
        tool.set_context("feishu", "chat-a")
        entered.set()
        await release.wait()
        return await tool.execute(action="add", message="first", every_seconds=60)

    async def task_two() -> str:
        await entered.wait()
        tool.set_context("email", "chat-b")
        release.set()
        return await tool.execute(action="add", message="second", every_seconds=60)

    result_one, result_two = await asyncio.gather(task_one(), task_two())

    assert result_one.startswith("Created job")
    assert result_two.startswith("Created job")

    jobs = tool._cron.list_jobs()
    assert {job.payload.channel for job in jobs} == {"feishu", "email"}
    assert {job.payload.to for job in jobs} == {"chat-a", "chat-b"}
