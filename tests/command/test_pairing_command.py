from unittest.mock import MagicMock

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.command.builtin import cmd_pairing
from nanobot.command.router import CommandContext
from nanobot.pairing import store
from nanobot.pairing.events import PairingChanged


@pytest.mark.asyncio
async def test_pairing_command_notifies_after_persistence_without_a_file_watcher(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_store_path", lambda: tmp_path / "pairing.json")
    code = store.generate_code("telegram", "alice")
    bus = MessageBus()
    approved = []
    bus.subscribe(lambda _event: approved.append(store.is_approved("telegram", "alice")), PairingChanged)
    loop = MagicMock(bus=bus)
    msg = InboundMessage(channel="cli", sender_id="owner", chat_id="direct", content=f"/pairing approve {code}")
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw=msg.content, args=f"approve {code}", loop=loop)
    result = await cmd_pairing(ctx)
    await bus.drain()
    assert "Approved" in result.content and approved == [True]
    ctx.args = "approve invalid"
    await cmd_pairing(ctx)
    ctx.args = "list"
    await cmd_pairing(ctx)
    await bus.drain()
    assert approved == [True]
