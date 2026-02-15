import pytest

from nanobot.agent.tools.message import MessageTool
from nanobot.bus.events import OutboundMessage


@pytest.mark.asyncio
async def test_message_tool_sends_media_paths_with_default_context() -> None:
    sent: list[OutboundMessage] = []

    async def _send(msg: OutboundMessage) -> None:
        sent.append(msg)

    tool = MessageTool(
        send_callback=_send,
        default_channel="test-channel",
        default_chat_id="!room:example.org",
    )

    result = await tool.execute(
        content="Here is the file.",
        media=[" /tmp/test.txt ", "", "   ", "/tmp/report.pdf"],
    )

    assert result == "Message sent to test-channel:!room:example.org"
    assert len(sent) == 1
    assert sent[0].channel == "test-channel"
    assert sent[0].chat_id == "!room:example.org"
    assert sent[0].content == "Here is the file."
    assert sent[0].media == ["/tmp/test.txt", "/tmp/report.pdf"]


@pytest.mark.asyncio
async def test_message_tool_returns_error_when_no_target_context() -> None:
    tool = MessageTool()
    result = await tool.execute(content="test")
    assert result == "Error: No target channel/chat specified"
