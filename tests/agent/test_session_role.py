"""Tests for session role injection across context, loop, and session persistence."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.context import ContextBuilder
from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.session.manager import SessionManager


def _make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    return workspace


def _make_loop(tmp_path: Path) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    return AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path, model="test-model")


# ---------------------------------------------------------------------------
# ContextBuilder tests
# ---------------------------------------------------------------------------

def test_session_role_injected_into_system_prompt(tmp_path: Path) -> None:
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)
    prompt = builder.build_system_prompt(session_role="You are a pirate.")
    assert "# Session Role Context" in prompt
    assert "You are a pirate." in prompt


def test_session_role_not_injected_when_empty(tmp_path: Path) -> None:
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)
    prompt = builder.build_system_prompt()
    assert "# Session Role Context" not in prompt


def test_session_role_passed_via_build_messages(tmp_path: Path) -> None:
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)
    messages = builder.build_messages(
        history=[], current_message="hi",
        channel="cli", chat_id="direct",
        session_role="You are a wizard.",
    )
    assert "# Session Role Context" in messages[0]["content"]
    assert "You are a wizard." in messages[0]["content"]


# ---------------------------------------------------------------------------
# AgentLoop tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_message_syncs_session_role_to_session_metadata(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)
    loop._run_agent_loop = AsyncMock(return_value=(
        "ok",
        [],
        [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "ok"},
        ],
        "stop",
        False,
    ))  # type: ignore[method-assign]

    msg = InboundMessage(
        channel="feishu",
        sender_id="u1",
        chat_id="c1",
        content="hello",
        metadata={"session_role": "You are a pirate."},
    )
    result = await loop._process_message(msg)

    assert result is not None
    session = loop.sessions.get_or_create("feishu:c1")
    assert session.metadata.get("session_role") == "You are a pirate."


@pytest.mark.asyncio
async def test_process_message_updates_existing_session_role(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]
    loop._run_agent_loop = AsyncMock(return_value=(
        "ok",
        [],
        [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "ok"},
        ],
        "stop",
        False,
    ))  # type: ignore[method-assign]

    # Pre-seed an old role
    session = loop.sessions.get_or_create("feishu:c2")
    session.metadata["session_role"] = "You are a ninja."
    loop.sessions.save(session)

    msg = InboundMessage(
        channel="feishu",
        sender_id="u1",
        chat_id="c2",
        content="hello",
        metadata={"session_role": "You are a pirate."},
    )
    await loop._process_message(msg)

    session = loop.sessions.get_or_create("feishu:c2")
    assert session.metadata.get("session_role") == "You are a pirate."


@pytest.mark.asyncio
async def test_system_message_process_syncs_session_role(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]
    loop._run_agent_loop = AsyncMock(return_value=(
        "ok",
        [],
        [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "ok"},
        ],
        "stop",
        False,
    ))  # type: ignore[method-assign]

    msg = InboundMessage(
        channel="system",
        sender_id="subagent",
        chat_id="cli:direct",
        content="hello",
        metadata={"session_role": "You are a wizard."},
    )
    await loop._process_message(msg)

    session = loop.sessions.get_or_create("cli:direct")
    assert session.metadata.get("session_role") == "You are a wizard."


# ---------------------------------------------------------------------------
# Session persistence tests
# ---------------------------------------------------------------------------

def test_session_role_persisted_in_metadata(tmp_path: Path) -> None:
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("cli:test")
    session.metadata["session_role"] = "You are a pirate."
    manager.save(session)
    manager.invalidate("cli:test")

    restored = manager.get_or_create("cli:test")
    assert restored.metadata.get("session_role") == "You are a pirate."
