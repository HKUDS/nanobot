import pytest

from nanobot.agent.tools.message import MessageTool
from nanobot.bus.events import OutboundMessage


def test_parameters_include_media_array() -> None:
    tool = MessageTool()
    media = tool.parameters["properties"]["media"]

    assert media["type"] == "array"
    assert media["items"] == {"type": "string"}


@pytest.mark.asyncio
async def test_execute_sends_trimmed_media_with_default_context() -> None:
    sent: list[OutboundMessage] = []

    async def callback(msg: OutboundMessage) -> None:
        sent.append(msg)

    tool = MessageTool(send_callback=callback, default_channel="telegram", default_chat_id="123")

    result = await tool.execute(
        content="hello",
        media=[" /tmp/a.png ", "", "   ", "/tmp/b.pdf"],
    )

    assert result == "Message sent to telegram:123"
    assert len(sent) == 1
    assert sent[0].channel == "telegram"
    assert sent[0].chat_id == "123"
    assert sent[0].content == "hello"
    assert sent[0].media == ["/tmp/a.png", "/tmp/b.pdf"]


@pytest.mark.asyncio
async def test_execute_uses_explicit_target_and_empty_media_default() -> None:
    sent: list[OutboundMessage] = []

    async def callback(msg: OutboundMessage) -> None:
        sent.append(msg)

    tool = MessageTool(send_callback=callback, default_channel="telegram", default_chat_id="123")

    result = await tool.execute(content="hi", channel="email", chat_id="alice@example.com")

    assert result == "Message sent to email:alice@example.com"
    assert len(sent) == 1
    assert sent[0].channel == "email"
    assert sent[0].chat_id == "alice@example.com"
    assert sent[0].media == []
