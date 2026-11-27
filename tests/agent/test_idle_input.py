from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.session_helpers import make_agent_loop
from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.tools.subagent import SubagentTool
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import GenerationSettings, LLMResponse
from nanobot.session.manager import SessionManager
from nanobot.session.recovery import PENDING_FOLLOWUP_ID_KEY, pending_followups
from nanobot.webui.recovery import RecoveryCoordinator


@pytest.fixture
async def loop(tmp_path):
    provider = MagicMock(aclose=AsyncMock(), generation=GenerationSettings())
    provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="answer"))
    workspace = tmp_path / "workspace"
    manager = SessionManager(workspace, sessions_root=tmp_path / "sessions")
    agent = make_agent_loop(bus=MessageBus(), provider=provider, workspace=workspace, model="test-model", session_manager=manager)
    try:
        yield agent
    finally:
        await agent.aclose()


def message(text="question"):
    return InboundMessage(channel="websocket", sender_id="webui", chat_id="test", content=text,
                          metadata={"webui": True, "webui_turn_id": text})


async def drain(loop):
    tasks = [task for group in loop._active_tasks.values() for task in group]
    if tasks:
        await asyncio.wait_for(asyncio.gather(*tasks), 10)


@pytest.mark.parametrize("lane", ["execution", "control"])
async def test_busy_session_does_not_run_preparation(loop, lane):
    msg = message()
    prepare = AsyncMock(return_value=True)
    owner = (loop._get_session_lock(msg.session_key) if lane == "execution"
             else loop._pending_queues.controlling(msg.session_key))
    async with owner:
        assert not await loop.enqueue_if_idle(msg, prepare)
    prepare.assert_not_awaited()


@pytest.mark.parametrize("admit", [True, False])
async def test_idle_input_and_racing_ordinary_input_share_fifo(loop, admit):
    entered, release = asyncio.Event(), asyncio.Event()
    idle, ordinary = message("prepared"), message("ordinary")
    loop._dispatch_one = AsyncMock()

    async def prepare():
        entered.set()
        await release.wait()
        return admit

    task = asyncio.create_task(loop.enqueue_if_idle(idle, prepare))
    async with asyncio.timeout(5):
        await entered.wait()
        followup = asyncio.create_task(loop._enqueue_session_message(ordinary))
        try:
            await asyncio.sleep(0)
            assert not followup.done()
            # Once preparation begins, disconnecting must not drop a committed input.
            task.cancel()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        await followup
        await drain(loop)
    assert [call.args[0].content for call in loop._dispatch_one.await_args_list] == (
        [idle.content, ordinary.content] if admit else [ordinary.content]
    )


async def test_shutdown_joins_preparation_and_restart_replays_its_journal(loop, tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.config.loader._current_config_path", tmp_path / "config.json")
    image = tmp_path / "original.gif"
    image.write_bytes(b"GIF89a" + bytes(16))
    msg = message()
    msg.media = [str(image)]
    committed, release = asyncio.Event(), asyncio.Event()

    async def prepare():
        msg.metadata[PENDING_FOLLOWUP_ID_KEY] = await loop.sessions.state.queue_followup(msg.session_key, msg)
        committed.set()
        await release.wait()
        return True

    loop.preserve_inflight_turns_on_shutdown()
    submission = asyncio.create_task(loop.enqueue_if_idle(msg, prepare))
    async with asyncio.timeout(5):
        await committed.wait()
        closing = asyncio.create_task(loop.aclose())
        try:
            await asyncio.sleep(0)
            assert not closing.done()
        finally:
            release.set()
        await asyncio.gather(submission, closing)
    reopened = SessionManager(loop.workspace, sessions_root=tmp_path / "sessions")
    bus = MessageBus()
    recovery = RecoveryCoordinator(reopened, bus)
    restarted = make_agent_loop(bus=bus, provider=loop.provider, model="test-model", workspace=loop.workspace,
                          session_manager=reopened, recovery_admission=recovery)
    try:
        await recovery.scan()
        replay = await asyncio.wait_for(bus.consume_inbound(), 5)
        assert (replay.content, replay.media, replay.timestamp) == (msg.content, msg.media, msg.timestamp)
        await restarted._enqueue_session_message(replay)
        await drain(restarted)
        restarted.provider.chat_stream_with_retry.assert_awaited_once()
        saved = await reopened.state.read(msg.session_key)
        assert saved.messages[0]["content"][0]["type"] == "image_attachment"
        assert saved.messages[-1]["content"] == "answer"
        assert not pending_followups(saved)
    finally:
        await restarted.aclose()


@pytest.mark.parametrize("arrival", ["during_reply", "after_reply"])
async def test_child_from_previous_generation_cannot_enter_next_prompt(loop, arrival):
    msg = message()
    source = await loop.sessions.state.get(msg.session_key)
    runtime = await loop.runtime_for_session(source)
    child_started, release_child, main_started = asyncio.Event(), asyncio.Event(), asyncio.Event()
    release_main = asyncio.Event()
    child_result = "OLD_CHILD_RESULT"
    main_prompts = []

    async def controlled_model(**kwargs):
        messages = kwargs["messages"]
        if str(messages[-1].get("content", "")).startswith("child task"):
            child_started.set()
            await release_child.wait()
            return LLMResponse(content=child_result)
        main_prompts.append(messages)
        main_started.set()
        if arrival == "during_reply":
            await release_main.wait()
        return LLMResponse(content="answer")

    async def reset():
        await loop.sessions.state.reset(msg.session_key)
        msg.session_generation = (await loop.sessions.state.get(msg.session_key)).generation
        return True

    loop.provider.chat_stream_with_retry.side_effect = controlled_model
    try:
        with request_context(RequestContext(
            channel=msg.channel, chat_id=msg.chat_id, session_key=source.key,
            session_generation=source.generation, turn_id="parent", runtime=runtime,
            can_receive_background_results=True,
        )):
            await SubagentTool(loop.subagents).execute(action="create", task="child task")
        await asyncio.wait_for(child_started.wait(), 5)
        assert await loop.enqueue_if_idle(msg, reset)
        await asyncio.wait_for(main_started.wait(), 5)
        if arrival == "after_reply":
            # The new turn must not wait for a child of the retired generation.
            await drain(loop)
        release_child.set()
        late = await asyncio.wait_for(loop.bus.consume_inbound(), 5)
        assert late.session_generation == source.generation
        assert child_result in late.content
        await loop._enqueue_session_message(late)
        release_main.set()
        await drain(loop)
        assert len(main_prompts) == 1
        assert child_result not in str(main_prompts)
        saved = await loop.sessions.state.read(source.key)
        assert child_result not in str(saved.messages)
    finally:
        release_child.set()
        release_main.set()
