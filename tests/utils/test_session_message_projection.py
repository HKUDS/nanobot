from unittest.mock import AsyncMock

import pytest

from nanobot.bus.queue import MessageBus
from nanobot.bus.runtime_events import RuntimeEventContext, UserInputAccepted
from nanobot.session.manager import SessionManager
from nanobot.session.session_messages import SESSION_MESSAGE_METADATA_KEY
from nanobot.session.webui_turns import WebuiTurnCoordinator
from nanobot.webui.history import record_from_fact


@pytest.fixture
async def sessions(tmp_path):
    manager = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "sessions")
    try:
        yield manager
    finally:
        await manager.state.aclose()


def _input(generation=None):
    return UserInputAccepted(
        context=RuntimeEventContext(
            channel="system", chat_id="websocket:target", session_key="websocket:target",
            session_generation=generation,
            metadata={SESSION_MESSAGE_METADATA_KEY: {
                "message_id": "message-1", "created_at_ms": 123, "expect_reply": False,
                "source_handle": "luma", "source_session_key": "websocket:source",
                "target_session_key": "websocket:target",
            }},
        ),
        content="Review this",
    )


def _coordinator(sessions):
    bus = MessageBus()
    bus.publish_outbound = AsyncMock()
    return WebuiTurnCoordinator(
        bus=bus, sessions=sessions, schedule_background=lambda coro: coro.close(),
    ), bus


@pytest.mark.asyncio
@pytest.mark.parametrize("bound", [False, True], ids=["unbound-event", "bound-event"])
async def test_projection_persists_before_publishing(sessions, bound):
    target = await sessions.state.get("websocket:target")
    await sessions.state.mutate_metadata(target.key, lambda metadata: metadata.update(webui=True))
    coordinator, bus = _coordinator(sessions)

    async def verify_committed(outbound):
        records = await sessions.state.project_history(
            target.key,
            lambda reader: [record_from_fact(fact, target.key) for fact in reader.all_facts()],
        )
        assert len(records) == 1
        assert records[0]["text"] == "Review this"
        assert records[0]["session_message"] == outbound.event.provenance["session_message"]
        assert records[0]["session_message"]["session"]["name"] == "luma"

    bus.publish_outbound.side_effect = verify_committed
    await coordinator._handle_user_input_accepted(_input(target.generation if bound else None))

    bus.publish_outbound.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing", "stale", "deleted", "replaced", "write-error"])
async def test_failed_projection_does_not_write_or_notify(sessions, monkeypatch, failure):
    target = await sessions.state.get("websocket:target")
    await sessions.state.mutate_metadata(target.key, lambda metadata: metadata.update(webui=True))
    generation = None
    if failure in {"missing", "stale"}:
        await sessions.state.delete(target.key)
        if failure == "stale":
            await sessions.state.get(target.key)
            await sessions.state.mutate_metadata(target.key, lambda metadata: metadata.update(webui=True))
            generation = target.generation
    else:
        append = sessions.state.append_history

        async def race_or_fail(key, facts, *, expected_generation):
            assert expected_generation == target.generation
            if failure == "write-error":
                raise OSError("test write failure")
            await sessions.state.delete(key)
            if failure == "replaced":
                await sessions.state.get(key)
            await append(key, facts, expected_generation=expected_generation)

        monkeypatch.setattr(sessions.state, "append_history", race_or_fail)
    coordinator, bus = _coordinator(sessions)

    await coordinator._handle_user_input_accepted(_input(generation))

    bus.publish_outbound.assert_not_awaited()
    revision, facts = await sessions.state.project_history(
        target.key, lambda reader: (reader.revision, list(reader.all_facts())),
    )
    assert facts == []
    if failure in {"missing", "deleted"}:
        assert revision is None
    elif failure in {"stale", "replaced"}:
        assert revision[0] != target.generation
