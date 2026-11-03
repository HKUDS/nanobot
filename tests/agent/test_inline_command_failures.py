"""Inline command failures must not tear down the shared message consumer."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.bus.runtime_events import TurnCompleted
from nanobot.config.schema import Config, ModelPresetConfig
from nanobot.providers.base import GenerationSettings, LLMResponse
from nanobot.providers.factory import build_provider_snapshot
from nanobot.session.manager import SessionManager
from nanobot.session.model_selection import SESSION_MODEL_PRESET_METADATA_KEY


@pytest.fixture
async def loop(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = Config()
    config.model_presets["broken"] = ModelPresetConfig(provider="openai", model="gpt-4.1")
    provider = MagicMock(aclose=AsyncMock())
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings(max_tokens=100)
    provider.can_resume_conversation_state.return_value = False
    provider.estimate_prompt_tokens.return_value = (100, "test")
    agent = AgentLoop(
        bus=MessageBus(), provider=provider, workspace=workspace, model="test-model",
        session_manager=SessionManager(workspace, sessions_root=tmp_path / "sessions"),
        model_presets=config.model_presets,
        preset_snapshot_loader=lambda name: build_provider_snapshot(config, preset_name=name),
    )
    agent.tools.get_definitions = MagicMock(return_value=[])
    try:
        yield agent
    finally:
        await agent.aclose()


async def _reply(bus, chat_id):
    async with asyncio.timeout(3):
        while True:
            message = await bus.consume_outbound()
            if message.chat_id == chat_id and message.event is None:
                return message


@pytest.mark.parametrize("status_chat", ["idle", "busy"])
async def test_status_configuration_failure_preserves_other_work(loop, status_chat):
    model_started, release_model = asyncio.Event(), asyncio.Event()
    model_cancelled = asyncio.Event()
    completions = []
    loop.bus.subscribe(completions.append, TurnCompleted)

    async def chat(**kwargs):
        if not model_started.is_set():
            model_started.set()
            try:
                await release_model.wait()
            except asyncio.CancelledError:
                model_cancelled.set()
                raise
        return LLMResponse(content="still responsive")

    loop.provider.chat_stream_with_retry = chat
    run_task = asyncio.create_task(loop.run())
    try:
        await loop.bus.publish_inbound(InboundMessage(
            channel="telegram", sender_id="u", chat_id="busy", content="first",
        ))
        await asyncio.wait_for(model_started.wait(), timeout=3)
        # A selected preset can become unusable after its provider credentials change.
        await loop.sessions.state.update_metadata(
            f"telegram:{status_chat}", {SESSION_MODEL_PRESET_METADATA_KEY: "broken"},
            create_if_missing=True,
        )
        await loop.bus.publish_inbound(InboundMessage(
            channel="telegram", sender_id="u", chat_id=status_chat, content="/status",
            metadata={"message_id": "status-request", "thread_id": "status-thread"},
        ))
        failed = await _reply(loop.bus, status_chat)
        assert failed.content == "Sorry, I encountered an error."
        assert failed.metadata["message_id"] == "status-request"
        assert failed.metadata["thread_id"] == "status-thread"
        status_completions = [
            event for event in completions if event.context.chat_id == status_chat
        ]
        if status_chat == "idle":
            assert len(status_completions) == 1
            assert status_completions[0].outcome == "failed"
        else:
            assert status_completions == []

        await loop.bus.publish_inbound(InboundMessage(
            channel="telegram", sender_id="u", chat_id="other", content="hello",
        ))
        assert (await _reply(loop.bus, "other")).content == "still responsive"
        assert not run_task.done()
        assert not model_cancelled.is_set()
        loop.provider.aclose.assert_not_awaited()

        release_model.set()
        assert (await _reply(loop.bus, "busy")).content == "still responsive"
    finally:
        release_model.set()
        run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)


async def test_shutdown_cancellation_propagates_during_status(loop, monkeypatch):
    resolving = asyncio.Event()

    async def blocked_runtime(session):
        resolving.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(loop, "runtime_for_session", blocked_runtime)
    run_task = asyncio.create_task(loop.run())
    try:
        await loop.bus.publish_inbound(InboundMessage(
            channel="telegram", sender_id="u", chat_id="status", content="/status",
        ))
        await asyncio.wait_for(resolving.wait(), timeout=3)
        run_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(run_task, timeout=3)
        loop.provider.aclose.assert_awaited_once()
        assert loop.bus.outbound_size == 0
    finally:
        run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)
