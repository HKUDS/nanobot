"""Manual context compaction command behavior."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.outbound_events import ContextCompactionEvent
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import GenerationSettings, LLMResponse, ProviderConversationState


@pytest.mark.asyncio
async def test_compact_emits_one_lifecycle_and_keeps_the_session(tmp_path) -> None:
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings(max_tokens=100)
    provider.can_resume_conversation_state.return_value = True
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="Portable checkpoint.",
        finish_reason="stop",
    ))
    loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        context_window_tokens=128_000,
    )
    loop.tools.get_definitions = MagicMock(return_value=[])
    session = loop.sessions.get_or_create("cli:test")
    session.add_message("user", "important question")
    session.add_message("assistant", "important answer")
    session.provider_state = ProviderConversationState(
        kind="openai_responses",
        provider="openai:test",
        model="test-model",
        version=1,
        payload={"items": []},
    )
    loop.sessions.save(session)

    try:
        response = await loop._process_message(
            InboundMessage(
                channel="cli",
                sender_id="user",
                chat_id="test",
                content="/compact",
            ),
            runtime=loop.llm_runtime(),
        )

        started = await bus.consume_outbound()
        assert response is not None
        assert isinstance(started.event, ContextCompactionEvent)
        assert isinstance(response.event, ContextCompactionEvent)
        assert started.event.phase == "started"
        assert response.event.phase == "succeeded"
        assert started.event.compaction_id == response.event.compaction_id
        assert response.event.checkpoint_source == "llm_summary"
        assert response.event.completes_command is True

        reloaded = loop.sessions.get_or_create("cli:test")
        assert reloaded.provider_state is None
        assert any(message.get("content") == "important answer" for message in reloaded.messages)
    finally:
        await loop.aclose()


@pytest.mark.asyncio
async def test_idle_compaction_routes_back_to_a_slack_thread() -> None:
    loop = MagicMock()
    loop.sessions.get_or_create.return_value = MagicMock(metadata={})
    loop.bus = MessageBus()
    event = ContextCompactionEvent(compaction_id="compact-1", phase="started")

    await AgentLoop._publish_idle_compaction(
        loop,
        "slack:C123:1700000000.000100",
        event,
    )

    outbound = await loop.bus.consume_outbound()
    assert outbound.channel == "slack"
    assert outbound.chat_id == "C123"
    assert outbound.metadata == {"slack": {"thread_ts": "1700000000.000100"}}
