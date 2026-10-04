from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.turn_delivery import TurnDeliveryFactory
from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.session.manager import SessionManager
from nanobot.session.recovery import RECOVERY_METADATA_KEY, RecoveryCoordinator
from nanobot.session.turn_continuation import INTERNAL_CONTINUATION_META


@pytest.mark.asyncio
async def test_recovery_continuation_runs_without_a_sustained_goal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = MessageBus()
    sessions = SessionManager(tmp_path)
    session = sessions.get_or_create("websocket:chat")
    session.metadata.update({
        "webui": True,
        RECOVERY_METADATA_KEY: {
            "status": "awaiting_user",
            "recovery_id": "recovery-1",
            "attempts": 0,
        },
    })
    sessions.save(session)
    recovery = RecoveryCoordinator(sessions, bus)

    loop = AgentLoop.__new__(AgentLoop)
    loop.sessions = sessions
    loop._unified_session = False
    loop._recovery_admission = recovery
    loop._session_locks = {}
    loop._concurrency_gate = None
    loop._automation_turn_coordinators = []
    loop._discarding_sessions = set()
    loop._preserve_inflight_turns_on_shutdown = False
    loop.turn_delivery_factory = TurnDeliveryFactory(bus)
    process_message = AsyncMock(return_value=OutboundMessage(
        channel="websocket",
        chat_id="chat",
        content="done",
    ))
    monkeypatch.setattr(loop, "_process_message", process_message)

    await recovery.handle_action(
        "continue",
        {"chat_id": "chat", "recovery_id": "recovery-1"},
    )
    continuation = bus.inbound.get_nowait()

    assert continuation.metadata[INTERNAL_CONTINUATION_META] is True
    await loop._dispatch_one(continuation, asyncio.Queue())

    process_message.assert_awaited_once()
