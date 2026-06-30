from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.command.builtin import build_help_text, register_builtin_commands
from nanobot.command.router import CommandContext, CommandRouter
from nanobot.triggers.local_store import LocalTriggerStore


@pytest.mark.asyncio
async def test_trigger_command_creates_session_bound_local_trigger(tmp_path: Path) -> None:
    router = CommandRouter()
    register_builtin_commands(router)
    store = LocalTriggerStore(tmp_path)
    loop = SimpleNamespace(workspace=tmp_path, local_trigger_store=store)
    msg = InboundMessage(
        channel="websocket",
        sender_id="user",
        chat_id="chat-1",
        content="/trigger@nanobot_bot PR review",
        metadata={"webui": True},
    )
    ctx = CommandContext(
        msg=msg,
        session=None,
        key="websocket:chat-1",
        raw="/trigger@nanobot_bot PR review",
        loop=loop,
    )

    assert router.is_dispatchable_command("/trigger@nanobot_bot PR review") is True
    response = await router.dispatch(ctx)

    assert response is not None
    assert "Trigger created: PR review" in response.content
    trigger = store.list_for_session("websocket:chat-1")[0]
    assert trigger.name == "PR review"
    assert trigger.channel == "websocket"
    assert trigger.chat_id == "chat-1"
    assert trigger.session_key == "websocket:chat-1"
    assert f"nanobot trigger {trigger.id} \"message\"" in response.content


@pytest.mark.asyncio
async def test_trigger_command_without_name_returns_usage_only(tmp_path: Path) -> None:
    router = CommandRouter()
    register_builtin_commands(router)
    store = LocalTriggerStore(tmp_path)
    loop = SimpleNamespace(workspace=tmp_path, local_trigger_store=store)
    msg = InboundMessage(
        channel="websocket",
        sender_id="user",
        chat_id="chat-1",
        content="/trigger@nanobot_bot",
        metadata={"webui": True},
    )
    ctx = CommandContext(
        msg=msg,
        session=None,
        key="websocket:chat-1",
        raw="/trigger@nanobot_bot",
        loop=loop,
    )

    response = await router.dispatch(ctx)

    assert response is not None
    assert "Usage: /trigger <name>" in response.content
    assert store.list_for_session("websocket:chat-1") == []


def test_trigger_command_is_in_help_text() -> None:
    assert "/trigger <name>" in build_help_text()
