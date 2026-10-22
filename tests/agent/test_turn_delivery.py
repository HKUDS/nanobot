from dataclasses import replace
from pathlib import Path

import pytest

from nanobot.agent.execution import ExecutionLifecycle
from nanobot.agent.turn_delivery import TurnDeliveryFactory
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.outbound_events import ContextCompactionEvent
from nanobot.bus.queue import MessageBus
from nanobot.bus.runtime_events import TurnCompleted
from nanobot.events import RetryStatusEvent
from nanobot.providers.base import LLMProvider, ProviderCallContext
from nanobot.session.keys import HEARTBEAT_SESSION_KEY
from nanobot.session.manager import SessionManager
from nanobot.session.turn_continuation import INTERNAL_CONTINUATION_META
from nanobot.session.webui_turns import WebuiTurnRoutePolicy
from nanobot.webui.metadata import (
    WEBSOCKET_TURN_OWNER_METADATA_KEY,
    WEBUI_TURN_METADATA_KEY,
)


@pytest.mark.parametrize("channel", ["telegram", "discord", "websocket", "cli", "custom"])
@pytest.mark.parametrize("legacy_route", [False, True])
@pytest.mark.parametrize("key", [HEARTBEAT_SESSION_KEY, "dream:20260602-155256"])
async def test_internal_compaction_never_reaches_its_result_destination(channel, legacy_route, key):
    factory = TurnDeliveryFactory(MessageBus())
    msg = InboundMessage(channel=channel, sender_id="user", chat_id="chat", content="check")
    delivery = factory.create(msg, key)
    metadata = {"_compaction_route": {"channel": channel, "chat_id": "chat"}} if legacy_route else {}
    idle_events = factory.session_events(key, metadata, generation="generation")
    for sink in (delivery.events, idle_events):
        assert not sink.accepts(ContextCompactionEvent)
        for phase in ("started", "succeeded", "failed", "cancelled"):
            await sink.emit(ContextCompactionEvent("internal-compact", phase))
    assert factory.bus.outbound.empty()

    delivery.remember_session_route(metadata)
    assert "_compaction_route" not in metadata

    # The same destination still receives the user's own compaction lifecycle.
    user_delivery = factory.create(msg, f"{channel}:chat")
    user_delivery.remember_session_route(metadata)
    for sink in (user_delivery.events, factory.session_events(f"{channel}:chat", metadata, generation="generation")):
        await sink.emit(ContextCompactionEvent("user-compact", "succeeded"))
        assert factory.bus.outbound.get_nowait().event == ContextCompactionEvent(
            "user-compact", "succeeded",
        )


@pytest.mark.parametrize("unified", [False, True])
@pytest.mark.parametrize(("key", "channel", "chat_id", "metadata"), [
    ("slack:C123:1700000000.000100", "slack", "C123",
     {"slack": {"thread_ts": "1700000000.000100"}}),
    ("telegram:-100123:topic:42", "telegram", "-100123", {"message_thread_id": 42}),
    ("discord:456:thread:777", "discord", "777", {}),
    ("mattermost:channel:root", "mattermost", "channel", {"mattermost": {"root_id": "root"}}),
    ("matrix:!room:example.org:thread:$root", "matrix", "!room:example.org",
     {"thread_root_event_id": "$root", "thread_reply_to_event_id": "$reply"}),
    ("feishu:chat:thread:root", "feishu", "chat",
     {"message_id": "reply", "thread_id": "root", "chat_type": "group"}),
    ("dingtalk:group:conversation:user", "dingtalk", "group:conversation", {}),
])
async def test_session_route_delivers_automatic_and_manual_compaction(
    key, channel, chat_id, metadata, unified,
) -> None:
    factory = TurnDeliveryFactory(MessageBus())
    automatic = ContextCompactionEvent(compaction_id="auto-1", phase="started")
    notified = ContextCompactionEvent(
        compaction_id="notified-1", phase="started", notify=True,
    )
    key = "unified:default" if unified else key
    msg = InboundMessage(
        channel=channel, sender_id="user", chat_id=chat_id, content="hello",
        metadata={
            "webui_turn_id": "turn-1", "sender_name": "User",
            "message_id": "received-1", "thread_id": "received-thread", **metadata,
        },
    )
    delivery = factory.create(msg, key)
    session_metadata = {}
    delivery.remember_session_route(session_metadata)

    sink = factory.session_events(key, session_metadata, generation="generation")
    assert sink.publish is not None
    await sink.emit(automatic)
    await sink.emit(notified)

    outbounds = [factory.bus.outbound.get_nowait() for _ in range(2)]
    assert [(outbound.channel, outbound.chat_id, outbound.metadata) for outbound in outbounds] == [
        (channel, chat_id, metadata),
    ] * 2
    assert [outbound.event for outbound in outbounds] == [automatic, notified]


async def test_idle_compaction_keeps_its_route_when_a_unified_session_moves() -> None:
    factory = TurnDeliveryFactory(MessageBus())
    key = "unified:default"
    session_metadata = {}
    original = InboundMessage(
        channel="slack", sender_id="user", chat_id="C123", content="hello",
        metadata={"slack": {"thread_ts": "1700000000.000100"}},
    )
    factory.create(original, key).remember_session_route(session_metadata)
    sink = factory.session_events(key, session_metadata, generation="generation")
    assert sink.publish is not None
    await sink.emit(ContextCompactionEvent("compact-1", "started", notify=True))

    latest = InboundMessage(
        channel="telegram", sender_id="user", chat_id="42", content="next question",
    )
    factory.create(latest, key).remember_session_route(session_metadata)
    await sink.emit(ContextCompactionEvent("compact-1", "succeeded", notify=True))

    events = [factory.bus.outbound.get_nowait() for _ in range(2)]
    assert [(msg.channel, msg.chat_id, msg.metadata) for msg in events] == [
        ("slack", "C123", {"slack": {"thread_ts": "1700000000.000100"}}),
    ] * 2


async def test_automatic_compaction_reaches_legacy_websocket_session() -> None:
    factory = TurnDeliveryFactory(MessageBus())
    event = ContextCompactionEvent(compaction_id="compact-1", phase="succeeded")
    sink = factory.session_events("websocket:chat", {}, generation="generation")
    assert sink.publish is not None
    await sink.emit(event)
    assert factory.bus.outbound.get_nowait().event is event


@pytest.mark.asyncio
async def test_retry_event_uses_scoped_channel_delivery() -> None:
    bus = MessageBus()
    msg = InboundMessage(
        channel="websocket",
        sender_id="user",
        chat_id="chat-a",
        content="hello",
        metadata={WEBUI_TURN_METADATA_KEY: "turn-1"},
    )
    delivery = TurnDeliveryFactory(bus).create(msg, msg.session_key)

    await delivery.events.emit(RetryStatusEvent(
        state="waiting",
        attempt=1,
        max_attempts=4,
        error_kind="connection",
        next_retry_at=123.5,
    ))

    assert bus.outbound_size == 1
    outbound = bus.outbound.get_nowait()
    assert isinstance(outbound.event, RetryStatusEvent)
    assert outbound.event.error_kind == "connection"
    assert outbound.event.next_retry_at == 123.5
    assert outbound.metadata[WEBUI_TURN_METADATA_KEY] == "turn-1"


@pytest.mark.asyncio
async def test_delivery_maps_model_error_to_failed_turn_completion() -> None:
    bus = MessageBus()
    seen: list[TurnCompleted] = []
    bus.subscribe(seen.append, TurnCompleted)
    msg = InboundMessage(
        channel="websocket",
        sender_id="user",
        chat_id="chat-a",
        content="hello",
    )
    delivery = TurnDeliveryFactory(bus).create(msg, msg.session_key)
    delivery.record_stop_reason("error", failure_error_kind="billing")

    await delivery.complete(
        OutboundMessage(
            channel="websocket",
            chat_id="chat-a",
            content="Sorry, I encountered an error calling the AI model.",
        ),
        publish_completion=True,
    )

    assert len(seen) == 1
    assert seen[0].outcome == "failed"
    assert seen[0].failure_kind == "model"
    assert seen[0].failure_error_kind == "billing"
    assert bus.outbound_size == 0


@pytest.mark.asyncio
async def test_delivery_keeps_model_error_message_for_ordinary_channels() -> None:
    bus = MessageBus()
    msg = InboundMessage(
        channel="telegram",
        sender_id="user",
        chat_id="chat-a",
        content="hello",
    )
    delivery = TurnDeliveryFactory(bus).create(msg, msg.session_key)
    delivery.record_stop_reason("error")
    response = OutboundMessage(
        channel="telegram",
        chat_id="chat-a",
        content="Sorry, I encountered an error calling the AI model.",
    )

    await delivery.complete(response, publish_completion=True)

    assert await bus.consume_outbound() is response


@pytest.mark.parametrize("channel", ["telegram", "cli", "websocket"])
async def test_background_retry_status_is_quiet(channel) -> None:
    factory = TurnDeliveryFactory(MessageBus())
    delivery = factory.create(InboundMessage(
        channel="system", sender_id="job", chat_id=f"{channel}:chat", content="",
    ), f"{channel}:chat")
    assert not delivery.events.accepts(RetryStatusEvent)
    await delivery.events.emit(RetryStatusEvent("waiting", 1, 4, "connection"))
    assert factory.bus.outbound.empty()


async def test_retry_completion_is_isolated_between_turns_in_one_session() -> None:
    bus = MessageBus()
    seen: list[TurnCompleted] = []
    bus.subscribe(seen.append, TurnCompleted)
    factory = TurnDeliveryFactory(bus)
    deliveries = [factory.create(InboundMessage(
        channel="websocket", sender_id="user", chat_id="chat", content="",
        metadata={WEBUI_TURN_METADATA_KEY: turn},
    ), "websocket:chat") for turn in ("first", "second")]
    await deliveries[0].events.emit(RetryStatusEvent("exhausted", 4, 4, "connection"))
    for delivery in reversed(deliveries):
        delivery.record_stop_reason("error")
        await delivery.complete(None, publish_completion=True)
    assert [(event.context.metadata[WEBUI_TURN_METADATA_KEY], event.failure_attempts)
            for event in seen] == [("second", None), ("first", 4)]


async def test_next_model_request_clears_exhaustion_within_the_same_turn() -> None:
    from unittest.mock import AsyncMock, patch

    from nanobot.providers.base import LLMResponse

    class Provider(LLMProvider):
        async def chat(self, **kwargs):
            return LLMResponse(content="payment required", finish_reason="error", error_status_code=402)

        def get_default_model(self):
            return "test"

    bus = MessageBus()
    completed: list[TurnCompleted] = []
    bus.subscribe(completed.append, TurnCompleted)
    msg = InboundMessage(channel="websocket", sender_id="user", chat_id="chat", content="")
    delivery = TurnDeliveryFactory(bus).create(msg, msg.session_key)
    await delivery.events.emit(RetryStatusEvent("exhausted", 4, 4, "connection"))
    with patch("nanobot.providers.base.asyncio.sleep", new_callable=AsyncMock):
        response = await Provider(provider_name="test").chat_stream_with_retry(
            [{"role": "user", "content": "continue"}],
            provider_context=ProviderCallContext(events=delivery.events),
        )
    delivery.record_stop_reason("error", failure_error_kind=LLMProvider.public_error_kind(response))
    await delivery.complete(None, publish_completion=True)
    assert completed[0].failure_error_kind == "billing"
    assert completed[0].failure_attempts is None


async def test_websocket_lifecycles_use_their_admitted_execution_owners(tmp_path: Path) -> None:
    bus = MessageBus()
    executions = ExecutionLifecycle(bus)
    factory = TurnDeliveryFactory(
        bus,
        route_policy=WebuiTurnRoutePolicy(SessionManager(tmp_path / "sessions")),
    )
    first_msg = InboundMessage(
        channel="websocket",
        sender_id="user",
        chat_id="chat-a",
        content="first",
        metadata={WEBSOCKET_TURN_OWNER_METADATA_KEY: "attacker-reused-owner"},
    )
    second_msg = InboundMessage(
        channel="websocket",
        sender_id="user",
        chat_id="chat-a",
        content="second",
        metadata={WEBSOCKET_TURN_OWNER_METADATA_KEY: "attacker-reused-owner"},
    )

    first_admission = await executions.admit(first_msg, first_msg.session_key)
    second_admission = await executions.admit(second_msg, second_msg.session_key)
    assert first_admission is not None
    assert second_admission is not None
    first = factory.create(first_msg, first_msg.session_key)
    second = factory.create(second_msg, second_msg.session_key)
    first_owner = first.lifecycle_message.metadata[WEBSOCKET_TURN_OWNER_METADATA_KEY]
    second_owner = second.lifecycle_message.metadata[WEBSOCKET_TURN_OWNER_METADATA_KEY]

    assert first_owner == first_admission.execution_id
    assert second_owner == second_admission.execution_id
    assert first_owner == first.delivery_message.metadata[WEBSOCKET_TURN_OWNER_METADATA_KEY]
    assert first_owner != second_owner
    assert WEBUI_TURN_METADATA_KEY not in first.lifecycle_message.metadata
    assert first_msg.metadata[WEBSOCKET_TURN_OWNER_METADATA_KEY] == first_owner
    assert second_msg.metadata[WEBSOCKET_TURN_OWNER_METADATA_KEY] == second_owner


async def test_internal_continuation_keeps_display_owner_with_a_new_execution(tmp_path: Path) -> None:
    bus = MessageBus()
    executions = ExecutionLifecycle(bus)
    factory = TurnDeliveryFactory(
        bus,
        route_policy=WebuiTurnRoutePolicy(SessionManager(tmp_path / "sessions")),
    )
    msg = InboundMessage(
        channel="websocket",
        sender_id="user",
        chat_id="chat-continuation",
        content="start",
        metadata={WEBUI_TURN_METADATA_KEY: "turn-continuation"},
    )
    first_admission = await executions.admit(msg, msg.session_key)
    assert first_admission is not None
    first = factory.create(msg, msg.session_key)
    continuation = replace(
        msg,
        sender_id="system:continuation",
        metadata={**msg.metadata, INTERNAL_CONTINUATION_META: True},
        execution_admission=None,
    )
    next_admission = await executions.admit(continuation, continuation.session_key)
    assert next_admission is not None
    assert next_admission.execution_id != first_admission.execution_id

    next_delivery = factory.create(continuation, continuation.session_key)

    assert first.route.metadata[WEBSOCKET_TURN_OWNER_METADATA_KEY] == first_admission.execution_id
    assert next_delivery.route.metadata[WEBSOCKET_TURN_OWNER_METADATA_KEY] == first_admission.execution_id
    assert next_delivery.lifecycle_message.metadata[WEBUI_TURN_METADATA_KEY] == "turn-continuation"
    assert continuation.metadata[WEBSOCKET_TURN_OWNER_METADATA_KEY] == first_admission.execution_id


async def test_internal_user_input_uses_the_persisted_webui_route(tmp_path: Path) -> None:
    sessions = SessionManager(tmp_path / "sessions")
    target = sessions.get_or_create("websocket:target")
    target.metadata["webui"] = True
    sessions.save(target)
    await sessions.state.read(target.key)
    factory = TurnDeliveryFactory(
        MessageBus(),
        route_policy=WebuiTurnRoutePolicy(sessions),
    )
    msg = InboundMessage(
        channel="system",
        sender_id="session",
        chat_id="websocket:target",
        content="Review this",
        session_key_override="websocket:target",
        input_role="user",
    )

    delivery = factory.create(msg, msg.session_key)

    assert (delivery.route.channel, delivery.route.chat_id) == ("websocket", "target")
    assert delivery.route.publish_lifecycle
    assert delivery.route.metadata["_wants_stream"] is True
    assert isinstance(delivery.route.metadata[WEBSOCKET_TURN_OWNER_METADATA_KEY], str)


async def test_late_subagent_route_requires_webui_owned_session(tmp_path: Path) -> None:
    sessions = SessionManager(tmp_path)
    factory = TurnDeliveryFactory(
        MessageBus(),
        route_policy=WebuiTurnRoutePolicy(sessions),
    )
    session_key = "websocket:chat-a"
    msg = InboundMessage(
        channel="system",
        sender_id="subagent",
        chat_id=session_key,
        content="Background research completed",
        session_key_override=session_key,
        metadata={
            "injected_event": "subagent_result",
            "subagent_task_id": "sub-1",
        },
    )

    hidden_route = factory.create(msg, session_key).route

    assert hidden_route.channel == "websocket"
    assert hidden_route.chat_id == "chat-a"
    assert hidden_route.metadata == {}
    assert hidden_route.publish_lifecycle is False

    session = sessions.get_or_create(session_key)
    session.metadata["webui"] = True
    sessions.save(session)
    await sessions.state.read(session_key)
    first_visible_route = factory.create(msg, session_key).route
    second_visible_route = factory.create(msg, session_key).route

    assert first_visible_route.publish_lifecycle is True
    assert set(first_visible_route.metadata) == {
        "webui",
        "_wants_stream",
        WEBSOCKET_TURN_OWNER_METADATA_KEY,
        WEBUI_TURN_METADATA_KEY,
    }
    assert first_visible_route.metadata["webui"] is True
    assert first_visible_route.metadata["_wants_stream"] is True
    first_turn_id = first_visible_route.metadata[WEBUI_TURN_METADATA_KEY]
    second_turn_id = second_visible_route.metadata[WEBUI_TURN_METADATA_KEY]
    assert first_turn_id.startswith("subagent:")
    assert second_turn_id.startswith("subagent:")
    assert first_turn_id != second_turn_id
    assert (
        first_visible_route.metadata[WEBSOCKET_TURN_OWNER_METADATA_KEY]
        != second_visible_route.metadata[WEBSOCKET_TURN_OWNER_METADATA_KEY]
    )
    assert msg.metadata == {
        "injected_event": "subagent_result",
        "subagent_task_id": "sub-1",
    }


@pytest.mark.asyncio
async def test_unified_display_route_admits_alias_generation_and_rejects_stale_lifetime(tmp_path):
    from nanobot.session.display_history import HISTORY_GENERATION_METADATA_KEY
    from nanobot.session.sqlite_store import SessionConflictError

    sessions = SessionManager(tmp_path)
    alias = await sessions.state.get_header("websocket:chat")
    source = await sessions.state.get_header("unified:default")
    policy = WebuiTurnRoutePolicy(sessions)
    factory = TurnDeliveryFactory(MessageBus(), route_policy=policy, route_admission=policy.admit)
    message = InboundMessage(channel="system", sender_id="cron", chat_id="websocket:chat", content="notice")
    delivery = factory.create(message, source.key)
    await delivery.bind_session_generation(source.generation)
    assert delivery.route.metadata[HISTORY_GENERATION_METADATA_KEY] == alias.generation
    assert delivery.delivery_message.session_generation == source.generation
    response = delivery.background_response("done", stop_reason="end_turn", streamed=False, latency_ms=1)
    assert response.metadata[HISTORY_GENERATION_METADATA_KEY] == alias.generation
    await sessions.state.delete(alias.key)
    replacement = await sessions.state.get_header(alias.key)
    stale = factory.create(InboundMessage(
        channel="websocket", sender_id="user", chat_id="chat", content="old queued input",
        metadata={HISTORY_GENERATION_METADATA_KEY: alias.generation},
    ), source.key)
    with pytest.raises(SessionConflictError):
        await stale.bind_session_generation(source.generation)
    assert replacement.generation != alias.generation
    await sessions.state.aclose()
