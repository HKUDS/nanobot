import pytest

from nanobot.agent.tools.session_messages import SendSessionMessageTool, SessionMessageError
from nanobot.bus.queue import MessageBus
from nanobot.session.manager import SessionManager
from nanobot.session.session_handles import SessionHandleResolver


async def test_session_send_rejects_commands_and_delivers_normal_input(tmp_path):
    manager = SessionManager(tmp_path)
    bus = MessageBus()
    tool = SendSessionMessageTool(sessions=manager, bus=bus)
    try:
        await manager.state.get("websocket:source")
        await manager.state.get("websocket:target")
        handles = SessionHandleResolver(manager)
        target = await handles.ahandle_for_session("websocket:target")
        assert target is not None
        for content in ("/stop", "  /stop", "\n\t/restart", "/restart"):
            with pytest.raises(SessionMessageError, match="slash commands"):
                await tool.enqueue(source_session_key="websocket:source", target_handle=target.name,
                                   content=content, expect_reply=False)
            assert bus.inbound_size == 0
        await tool.enqueue(source_session_key="websocket:source", target_handle=target.name,
                           content="Please review /restart", expect_reply=False)
        message = await bus.consume_inbound()
        assert message.content == "Please review /restart"
        assert message.session_key == "websocket:target"
        assert bus.inbound_size == 0
    finally:
        await manager.state.aclose()
