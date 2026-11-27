import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.memory import Consolidator
from nanobot.agent.runner import AgentRunResult
from nanobot.agent.subagent import SubagentManager
from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.tools.subagent import SubagentTool
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import GenerationSettings
from nanobot.utils.llm_runtime import LLMRuntime
from nanobot.utils.subagent_channel_display import scrub_subagent_announce_body


def manager_and_runtime(tmp_path):
    manager = SubagentManager(
        workspace=tmp_path, bus=MessageBus(), max_tool_result_chars=16000,
        consolidator=MagicMock(spec=Consolidator),
    )
    provider = MagicMock()
    provider.generation = GenerationSettings()
    return manager, LLMRuntime.capture(provider, "test", context_window_tokens=128000)


async def create(manager, runtime, task, *, owner="owner", turn="turn", message=None, wait=False):
    with request_context(RequestContext(
        channel="api", chat_id=owner, session_key=owner, runtime=runtime,
        turn_id=turn, message_id=message,
    )):
        return await SubagentTool(manager).execute(action="create", task=task, wait=wait)


@pytest.mark.parametrize(
    "owner,old_turn,new_turn,old_message,new_message,expected",
    [
        ("owner", "turn", "turn", "wire-a", "wire-b", 1),
        ("other-owner", "turn", "turn", None, None, 0),
        ("owner", "old", "new", "same-wire", "same-wire", 0),
        ("owner", None, None, "wire", "wire", 1),
        ("owner", None, None, "old-wire", "new-wire", 0),
        ("owner", None, None, None, None, 0),
        ("owner", "identity", None, None, "identity", 0),
    ],
)
async def test_pending_announcements_follow_request_owner_and_turn(
    tmp_path, owner, old_turn, new_turn, old_message, new_message, expected,
):
    manager, runtime = manager_and_runtime(tmp_path)
    started, release = asyncio.Event(), asyncio.Event()

    async def run(spec):
        task = spec.initial_messages[-1]["content"]
        if task == "older":
            started.set()
            await release.wait()
        return AgentRunResult(final_content=task, messages=[], stop_reason="completed")

    manager.runner.run = AsyncMock(side_effect=run)
    try:
        await create(manager, runtime, "older", owner=owner, turn=old_turn, message=old_message)
        await asyncio.wait_for(started.wait(), 5)
        await create(manager, runtime, "newer", turn=new_turn, message=new_message)
        result = await asyncio.wait_for(manager.bus.consume_inbound(), 5)
        assert result.metadata["subagent_remaining_count"] == expected
        assert ("Other results for this turn" in result.content) is bool(expected)
        assert "Other results for this turn" not in scrub_subagent_announce_body(result.content)
        assert result.metadata.get("origin_message_id") == new_message
        assert "newer" in scrub_subagent_announce_body(result.content)
    finally:
        release.set()
        await manager.close()


async def test_completed_sibling_is_pending_until_its_announcement(tmp_path):
    manager, runtime = manager_and_runtime(tmp_path)
    manager.runner.run = AsyncMock(return_value=AgentRunResult(
        final_content="finished", messages=[], stop_reason="completed",
    ))
    finished = {name: asyncio.Event() for name in ("first", "second")}
    release = {name: asyncio.Event() for name in finished}
    original_finish = manager._finish

    async def finish(record, cleanup_error=None):
        outcome = await original_finish(record, cleanup_error)
        name = record.status.task_description
        finished[name].set()
        await release[name].wait()
        return outcome

    manager._finish = finish
    try:
        await create(manager, runtime, "first")
        await create(manager, runtime, "second")
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in finished.values())), 5)
        assert all(status.state == "done" for status in manager.statuses_for_session("owner").values())
        release["first"].set()
        first = await asyncio.wait_for(manager.bus.consume_inbound(), 5)
        assert first.metadata["subagent_remaining_count"] == 1
        release["second"].set()
        second = await asyncio.wait_for(manager.bus.consume_inbound(), 5)
        assert second.metadata["subagent_remaining_count"] == 0
        assert "Other results for this turn" not in second.content
    finally:
        for event in release.values():
            event.set()
        await manager.close()


async def test_inline_result_does_not_owe_a_background_announcement(tmp_path):
    manager, runtime = manager_and_runtime(tmp_path)
    started, release = asyncio.Event(), asyncio.Event()

    async def run(spec):
        task = spec.initial_messages[-1]["content"]
        if task == "inline":
            started.set()
            await release.wait()
        return AgentRunResult(final_content=task, messages=[], stop_reason="completed")

    manager.runner.run = AsyncMock(side_effect=run)
    inline = asyncio.create_task(create(manager, runtime, "inline", wait=True))
    try:
        await asyncio.wait_for(started.wait(), 5)
        await create(manager, runtime, "background")
        result = await asyncio.wait_for(manager.bus.consume_inbound(), 5)
        assert result.metadata["subagent_remaining_count"] == 0
        release.set()
        assert await asyncio.wait_for(inline, 5) == "inline"
        assert manager.bus.inbound_size == 0
    finally:
        release.set()
        await manager.close()
        await asyncio.gather(inline, return_exceptions=True)


@pytest.mark.parametrize("failure", ["error", "cancel"])
async def test_unsuccessful_task_retires_its_announcement(tmp_path, failure):
    manager, runtime = manager_and_runtime(tmp_path)
    started = {name: asyncio.Event() for name in ("unsuccessful", "survivor")}
    release = {name: asyncio.Event() for name in started}

    async def run(spec):
        name = spec.initial_messages[-1]["content"]
        started[name].set()
        await release[name].wait()
        if name == "unsuccessful":
            raise RuntimeError("test failure")
        return AgentRunResult(final_content=name, messages=[], stop_reason="completed")

    manager.runner.run = AsyncMock(side_effect=run)
    try:
        await create(manager, runtime, "unsuccessful")
        await create(manager, runtime, "survivor")
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in started.values())), 5)
        if failure == "cancel":
            task_id = next(
                status.task_id for status in manager.statuses_for_session("owner").values()
                if status.task_description == "unsuccessful"
            )
            with request_context(RequestContext(channel="api", chat_id="owner", session_key="owner")):
                await SubagentTool(manager).execute(action="cancel", task_id=task_id)
        else:
            release["unsuccessful"].set()
        unsuccessful = await asyncio.wait_for(manager.bus.consume_inbound(), 5)
        assert unsuccessful.metadata["subagent_state"] == ("cancelled" if failure == "cancel" else "error")
        assert unsuccessful.metadata["subagent_remaining_count"] == 1
        release["survivor"].set()
        survivor = await asyncio.wait_for(manager.bus.consume_inbound(), 5)
        assert survivor.metadata["subagent_remaining_count"] == 0
    finally:
        for event in release.values():
            event.set()
        await manager.close()
