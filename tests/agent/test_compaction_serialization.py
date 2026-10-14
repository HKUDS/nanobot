"""Compaction and SDK turns settle against the same persisted transcript."""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from nanobot.nanobot import Nanobot
from nanobot.providers.base import LLMProvider, LLMResponse


class ControlledProvider(LLMProvider):
    def __init__(self):
        super().__init__(provider_name="test")
        self.turn_started = asyncio.Event()
        self.release_turn = asyncio.Event()
        self.summary_started = asyncio.Event()
        self.release_summary = asyncio.Event()
        self.summary_messages = []
        self.turn_messages = []

    def get_default_model(self):
        return "test-model"

    async def chat(self, messages, **kwargs):
        content = messages[-1]["content"]
        if content.startswith("new question"):
            self.turn_messages = messages
            self.turn_started.set()
            await self.release_turn.wait()
            return LLMResponse(content="new reply")
        if content.startswith("other question"):
            return LLMResponse(content="other reply")
        self.summary_messages = messages
        self.summary_started.set()
        await self.release_summary.wait()
        return LLMResponse(content="Shared transcript summary.")


@pytest.fixture
async def bot(loop_factory):
    provider = ControlledProvider()
    bot = Nanobot(loop_factory(provider=provider, session_ttl_minutes=1))
    try:
        yield bot, provider
    finally:
        provider.release_turn.set()
        provider.release_summary.set()
        await bot.aclose()


async def seed_history(bot, key):
    await bot.sessions.ingest(key, [
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old reply"},
    ])


async def schedule_idle_archive(bot):
    scheduled = []
    with patch("nanobot.agent.autocompact.datetime") as clock:
        clock.now.return_value = datetime.now() + timedelta(minutes=30)
        clock.fromisoformat.side_effect = datetime.fromisoformat
        await bot._loop.auto_compact.check_expired(scheduled.append, bot._loop.runtime_for_session)
    assert len(scheduled) == 1
    return scheduled[0]


async def assert_reply_and_summary(bot, key):
    snapshot = await bot.sessions.export(key)
    assert snapshot is not None
    assert ("assistant", "new reply") in [
        (message["role"], message["content"]) for message in snapshot.messages
    ]
    assert snapshot.metadata["_last_summary"]["text"] == "Shared transcript summary."


@pytest.mark.parametrize("trigger", ["compact_session", "compact_idle_session", "scheduled_idle"])
async def test_compaction_waits_for_active_sdk_turn_and_preserves_reply(
    bot, loop_factory, trigger,
):
    bot, provider = bot
    key = "sdk:shared"
    await seed_history(bot, key)
    idle_archive = await schedule_idle_archive(bot) if trigger == "scheduled_idle" else None
    compact_attempted = asyncio.Event()

    async def compact():
        compact_attempted.set()
        if idle_archive is not None:
            return await idle_archive
        if trigger == "compact_session":
            return await bot.runtime.compact_session(key)
        return await bot.runtime.compact_idle_session(key, max_suffix=4)

    turn = asyncio.create_task(bot.run("new question", session_key=key))
    tasks = [turn]
    try:
        await asyncio.wait_for(provider.turn_started.wait(), timeout=5)
        compaction = asyncio.create_task(compact())
        tasks.append(compaction)
        await asyncio.wait_for(compact_attempted.wait(), timeout=5)

        other = await asyncio.wait_for(bot.run("other question", session_key="sdk:other"), timeout=5)
        assert other.content == "other reply"
        summary_started_during_turn = provider.summary_started.is_set()

        provider.release_turn.set()
        result = await asyncio.wait_for(turn, timeout=5)
        assert result.content == "new reply"
        await asyncio.wait_for(provider.summary_started.wait(), timeout=5)
        provider.release_summary.set()
        compacted = await asyncio.wait_for(compaction, timeout=5)

        await assert_reply_and_summary(bot, key)
        assert summary_started_during_turn is False
        assert {"role": "assistant", "content": "new reply"} in provider.summary_messages
        if trigger == "compact_session":
            assert compacted.metadata["_last_summary"]["text"] == "Shared transcript summary."
            assert any(message["content"] == "new reply" for message in compacted.messages)
        elif trigger == "compact_idle_session":
            assert compacted == "Shared transcript summary."

        await bot.aclose()
        async with Nanobot(loop_factory(provider=ControlledProvider())) as restarted:
            await assert_reply_and_summary(restarted, key)
    finally:
        provider.release_turn.set()
        provider.release_summary.set()
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=5)
        if idle_archive is not None:
            idle_archive.close()


async def test_sdk_turn_waits_for_running_idle_archive_and_uses_its_summary(bot):
    bot, provider = bot
    key = "sdk:shared"
    await seed_history(bot, key)
    archive = asyncio.create_task(await schedule_idle_archive(bot))
    turn_attempted = asyncio.Event()

    async def run():
        turn_attempted.set()
        return await bot.run("new question", session_key=key)

    tasks = [archive]
    try:
        await asyncio.wait_for(provider.summary_started.wait(), timeout=5)
        turn = asyncio.create_task(run())
        tasks.append(turn)
        await asyncio.wait_for(turn_attempted.wait(), timeout=5)
        other = await asyncio.wait_for(bot.run("other question", session_key="sdk:other"), timeout=5)
        assert other.content == "other reply"
        assert provider.turn_started.is_set() is False

        provider.release_summary.set()
        await asyncio.wait_for(archive, timeout=5)
        await asyncio.wait_for(provider.turn_started.wait(), timeout=5)
        assert "Shared transcript summary." in provider.turn_messages[0]["content"]
        provider.release_turn.set()
        result = await asyncio.wait_for(turn, timeout=5)
        assert result.content == "new reply"
        await assert_reply_and_summary(bot, key)
    finally:
        provider.release_turn.set()
        provider.release_summary.set()
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=5)
