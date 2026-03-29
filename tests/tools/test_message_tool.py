import pytest

from nanobot.agent.tools.message import MessageTool


@pytest.mark.asyncio
async def test_message_tool_returns_error_when_no_target_context() -> None:
    tool = MessageTool()
    result = await tool.execute(content="test")
    assert result == "Error: No target channel/chat specified"


@pytest.mark.asyncio
async def test_message_tool_passes_thread_id_to_outbound_message() -> None:
    """message_thread_id is forwarded to OutboundMessage and mentioned in return string."""
    sent = []

    async def capture(msg):
        sent.append(msg)

    tool = MessageTool(send_callback=capture, default_channel="telegram", default_chat_id="123")
    result = await tool.execute(content="hello", message_thread_id=42)

    assert len(sent) == 1
    assert sent[0].message_thread_id == 42
    assert "thread 42" in result


@pytest.mark.asyncio
async def test_message_tool_default_thread_id_from_set_context() -> None:
    """set_context with message_thread_id is used when none is passed at call time."""
    sent = []

    async def capture(msg):
        sent.append(msg)

    tool = MessageTool(send_callback=capture)
    tool.set_context(channel="telegram", chat_id="123", message_thread_id=7)
    result = await tool.execute(content="hello")

    assert sent[0].message_thread_id == 7
    assert "thread 7" in result


@pytest.mark.asyncio
async def test_message_tool_no_thread_id_omits_thread_info() -> None:
    """No message_thread_id means no thread info in return string and field is None."""
    sent = []

    async def capture(msg):
        sent.append(msg)

    tool = MessageTool(send_callback=capture, default_channel="telegram", default_chat_id="123")
    result = await tool.execute(content="hello")

    assert sent[0].message_thread_id is None
    assert "thread" not in result
