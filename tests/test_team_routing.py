from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse


class DummyProvider:
    def __init__(self):
        self.generation = SimpleNamespace(temperature=0.1, max_tokens=512, reasoning_effort=None)

    def get_default_model(self) -> str:
        return "test-model"

    async def chat(self, **kwargs):
        return LLMResponse(content="ok")

    async def chat_with_retry(self, **kwargs):
        return LLMResponse(content="ok")


def _make_loop(tmp_path):
    return AgentLoop(
        bus=MessageBus(),
        provider=DummyProvider(),
        workspace=tmp_path,
        cron_service=None,
    )


@pytest.mark.asyncio
async def test_team_status_command_updates_session_metadata(tmp_path):
    loop = _make_loop(tmp_path)
    loop.team.status_text = MagicMock(return_value="team-status")
    loop.team.has_unfinished_run = MagicMock(return_value=True)

    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="room", content="/team status")
    out = await loop._process_message(msg)

    assert out is not None
    assert out.content == "team-status"
    session = loop.sessions.get_or_create("cli:room")
    assert session.metadata.get("nano_team_active") is True


@pytest.mark.asyncio
async def test_team_goal_command_starts_mode(tmp_path):
    loop = _make_loop(tmp_path)
    loop.team.start_or_route_goal = AsyncMock(return_value="started")
    loop.team.is_active = MagicMock(return_value=True)

    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="room", content="/team build a plan")
    out = await loop._process_message(msg)

    assert out is not None
    assert out.content == "started"
    session = loop.sessions.get_or_create("cli:room")
    assert session.metadata.get("nano_team_active") is True
    loop.team.start_or_route_goal.assert_awaited_once_with("cli:room", "build a plan")


@pytest.mark.asyncio
async def test_plain_message_is_rejected_when_team_mode_active(tmp_path):
    loop = _make_loop(tmp_path)
    loop.team.route_user_message = AsyncMock(return_value="routed")
    loop.team.is_active = MagicMock(return_value=True)

    session = loop.sessions.get_or_create("cli:room")
    session.metadata["nano_team_active"] = True
    loop.sessions.save(session)

    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="room", content="continue")
    out = await loop._process_message(msg)

    assert out is not None
    assert "Team mode is active" in out.content
    loop.team.route_user_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_cli_plain_message_handles_approval_reply(tmp_path):
    loop = _make_loop(tmp_path)
    loop.team.is_active = MagicMock(return_value=True)
    loop.team.has_pending_approval = MagicMock(return_value=True)
    loop.team.handle_approval_reply = MagicMock(return_value="Updated task t5 to in_progress")

    session = loop.sessions.get_or_create("telegram:room")
    session.metadata["nano_team_active"] = True
    loop.sessions.save(session)

    msg = InboundMessage(channel="telegram", sender_id="u1", chat_id="room", content="批准 t5")
    out = await loop._process_message(msg)

    assert out is not None
    assert out.content == "Updated task t5 to in_progress"
    loop.team.handle_approval_reply.assert_called_once_with("telegram:room", "批准 t5")


@pytest.mark.asyncio
async def test_teams_alias_works(tmp_path):
    loop = _make_loop(tmp_path)
    loop.team.start_or_route_goal = AsyncMock(return_value="started")
    loop.team.is_active = MagicMock(return_value=True)

    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="room", content="/teams write docs")
    out = await loop._process_message(msg)

    assert out is not None
    assert out.content == "started"
    loop.team.start_or_route_goal.assert_awaited_once_with("cli:room", "write docs")


@pytest.mark.asyncio
async def test_team_log_default_and_custom_count(tmp_path):
    loop = _make_loop(tmp_path)
    loop.team.log_text = MagicMock(return_value="logs")

    msg_default = InboundMessage(channel="cli", sender_id="u1", chat_id="room", content="/team log")
    out_default = await loop._process_message(msg_default)
    assert out_default is not None
    assert out_default.content == "logs"
    loop.team.log_text.assert_called_with("cli:room", n=20)

    msg_custom = InboundMessage(channel="cli", sender_id="u1", chat_id="room", content="/team log 50")
    out_custom = await loop._process_message(msg_custom)
    assert out_custom is not None
    assert out_custom.content == "logs"
    loop.team.log_text.assert_called_with("cli:room", n=50)


@pytest.mark.asyncio
async def test_btw_command_spawns_single_subagent(tmp_path):
    loop = _make_loop(tmp_path)
    loop.subagents.spawn = AsyncMock(return_value="spawned")

    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="room", content="/btw summarize logs")
    out = await loop._process_message(msg)

    assert out is not None
    assert out.content == "spawned"
    loop.subagents.spawn.assert_awaited_once()


@pytest.mark.asyncio
async def test_team_approve_reject_manual_commands(tmp_path):
    loop = _make_loop(tmp_path)
    loop.team.approve_for_session = MagicMock(return_value="approved")
    loop.team.reject_for_session = MagicMock(return_value="rejected")
    loop.team.request_changes_for_session = MagicMock(return_value="changed")

    out_approve = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="room", content="/team approve t5")
    )
    assert out_approve is not None and out_approve.content == "approved"
    loop.team.approve_for_session.assert_called_once_with("cli:room", "t5")

    out_reject = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="room", content="/team reject t5 needs context")
    )
    assert out_reject is not None and out_reject.content == "rejected"
    loop.team.reject_for_session.assert_called_once_with("cli:room", "t5", "needs context")

    out_manual = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="room", content="/team manual t5 clarify constraints")
    )
    assert out_manual is not None and out_manual.content == "changed"
    loop.team.request_changes_for_session.assert_called_once_with("cli:room", "t5", "clarify constraints")


@pytest.mark.asyncio
async def test_team_stop_in_cli_returns_final_snapshot(tmp_path):
    loop = _make_loop(tmp_path)
    loop.team.stop_mode = AsyncMock(return_value="final-board")

    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="room", content="/team stop")
    out = await loop._process_message(msg)

    assert out is not None
    assert out.content == "final-board"
    loop.team.stop_mode.assert_awaited_once_with("cli:room", with_snapshot=True)


@pytest.mark.asyncio
async def test_team_usage_lists_approval_commands(tmp_path):
    loop = _make_loop(tmp_path)
    out = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="room", content="/team")
    )
    assert out is not None
    assert "/team approve <task_id>" in out.content
    assert "/team reject <task_id> <reason>" in out.content
