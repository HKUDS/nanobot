"""Tests for task_context ContextVar migration (PR A: pure refactor)."""

import asyncio
import pytest

from nanobot.agent.task_context import (
    current_channel,
    current_chat_id,
    current_message_id,
    message_sent_in_turn,
)


class TestContextVarIsolation:
    """Verify ContextVars are isolated across asyncio tasks."""

    @pytest.mark.asyncio
    async def test_different_tasks_see_own_values(self):
        results = {}

        async def worker(name: str, channel: str):
            current_channel.set(channel)
            await asyncio.sleep(0.01)  # yield to other task
            results[name] = current_channel.get()

        t1 = asyncio.create_task(worker("a", "feishu"))
        t2 = asyncio.create_task(worker("b", "slack"))
        await asyncio.gather(t1, t2)

        assert results["a"] == "feishu"
        assert results["b"] == "slack"

    @pytest.mark.asyncio
    async def test_default_values(self):
        """ContextVars return defaults when unset in a fresh context."""
        async def check():
            assert current_channel.get() == ""
            assert current_chat_id.get() == ""
            assert current_message_id.get() is None
            assert message_sent_in_turn.get() is False

        # Run in a new task to get a clean context copy
        await asyncio.create_task(check())

    @pytest.mark.asyncio
    async def test_sent_in_turn_isolated(self):
        results = {}

        async def worker(name: str, send: bool):
            message_sent_in_turn.set(send)
            await asyncio.sleep(0.01)
            results[name] = message_sent_in_turn.get()

        t1 = asyncio.create_task(worker("sender", True))
        t2 = asyncio.create_task(worker("quiet", False))
        await asyncio.gather(t1, t2)

        assert results["sender"] is True
        assert results["quiet"] is False


class TestMessageToolContextVar:
    """MessageTool reads from ContextVar with fallback to defaults."""

    @pytest.mark.asyncio
    async def test_contextvar_takes_precedence(self):
        from nanobot.agent.tools.message import MessageTool

        sent = []
        async def capture(msg):
            sent.append(msg)

        tool = MessageTool(send_callback=capture, default_channel="default_ch", default_chat_id="default_id")
        current_channel.set("feishu")
        current_chat_id.set("user123")

        await tool.execute(content="hello")
        assert sent[0].channel == "feishu"
        assert sent[0].chat_id == "user123"

    @pytest.mark.asyncio
    async def test_fallback_to_defaults(self):
        from nanobot.agent.tools.message import MessageTool

        sent = []
        async def capture(msg):
            sent.append(msg)

        # Run in fresh task so ContextVars are at defaults
        async def run():
            tool = MessageTool(send_callback=capture, default_channel="cli", default_chat_id="direct")
            await tool.execute(content="hello")
            assert sent[0].channel == "cli"
            assert sent[0].chat_id == "direct"

        await asyncio.create_task(run())

    @pytest.mark.asyncio
    async def test_sent_in_turn_property(self):
        from nanobot.agent.tools.message import MessageTool

        sent = []
        async def capture(msg):
            sent.append(msg)

        tool = MessageTool(send_callback=capture, default_channel="cli", default_chat_id="direct")
        current_channel.set("cli")
        current_chat_id.set("direct")

        tool.start_turn()
        assert tool.sent_in_turn is False
        await tool.execute(content="hi")
        assert tool.sent_in_turn is True


class TestSpawnToolContextVar:
    @pytest.mark.asyncio
    async def test_reads_from_contextvar(self):
        from unittest.mock import AsyncMock, MagicMock
        from nanobot.agent.tools.spawn import SpawnTool

        manager = MagicMock()
        manager.spawn = AsyncMock(return_value="spawned")
        tool = SpawnTool(manager)

        current_channel.set("telegram")
        current_chat_id.set("chat456")

        await tool.execute(task="do something")
        manager.spawn.assert_called_once_with(
            task="do something",
            label=None,
            origin_channel="telegram",
            origin_chat_id="chat456",
        )

    @pytest.mark.asyncio
    async def test_defaults_when_unset(self):
        from unittest.mock import AsyncMock, MagicMock
        from nanobot.agent.tools.spawn import SpawnTool

        manager = MagicMock()
        manager.spawn = AsyncMock(return_value="spawned")
        tool = SpawnTool(manager)

        async def run():
            await tool.execute(task="bg task")
            manager.spawn.assert_called_once_with(
                task="bg task",
                label=None,
                origin_channel="cli",
                origin_chat_id="direct",
            )

        await asyncio.create_task(run())


class TestCronToolContextVar:
    @pytest.mark.asyncio
    async def test_reads_from_contextvar(self):
        from unittest.mock import MagicMock
        from nanobot.agent.tools.cron import CronTool

        svc = MagicMock()
        tool = CronTool(svc)

        current_channel.set("discord")
        current_chat_id.set("guild789")

        result = await tool.execute(action="add", message="remind me", every_seconds=60)
        assert "Created job" in result
        svc.add_job.assert_called_once()
        call_kwargs = svc.add_job.call_args
        assert call_kwargs.kwargs.get("channel") or call_kwargs[1].get("channel") == "discord"

    @pytest.mark.asyncio
    async def test_error_when_no_context(self):
        from unittest.mock import MagicMock
        from nanobot.agent.tools.cron import CronTool

        svc = MagicMock()
        tool = CronTool(svc)

        async def run():
            result = await tool.execute(action="add", message="remind me", every_seconds=60)
            assert "Error" in result

        await asyncio.create_task(run())
