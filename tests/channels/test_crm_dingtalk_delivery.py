from __future__ import annotations

from nanobot.bus.events import InboundMessage
from nanobot.command.builtin import register_builtin_commands
from nanobot.command.router import CommandContext, CommandRouter


async def test_crm_dingtalk_command_uses_existing_outbound_message_shape() -> None:
    router = CommandRouter()
    register_builtin_commands(router)
    msg = InboundMessage(
        channel="dingtalk",
        sender_id="synthetic-user",
        chat_id="group:synthetic-chat",
        content="/crm-daily 2026-01-15",
        metadata={"conversation_type": "group", "synthetic": True},
    )

    result = await router.dispatch(
        CommandContext(msg=msg, session=None, key=msg.session_key, raw=msg.content, loop=None)
    )

    assert result is not None
    assert result.channel == "dingtalk"
    assert result.chat_id == "group:synthetic-chat"
    assert result.metadata["render_as"] == "text"
    assert "Sales Daily Report" in result.content
