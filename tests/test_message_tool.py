import pytest

from nanobot.agent.tools.message import MessageTool


@pytest.mark.asyncio
async def test_message_tool_returns_error_when_no_target_context() -> None:
    tool = MessageTool()
    result = await tool.execute(content="test")
    assert result == "Error: No target channel/chat specified"


@pytest.mark.asyncio
async def test_explicit_channel_without_chat_id_is_rejected() -> None:
    sent: list = []

    async def cb(msg):
        sent.append(msg)

    tool = MessageTool(
        send_callback=cb,
        default_channel="telegram",
        default_chat_id="12345",
    )

    # LLM specifies channel but forgets chat_id; we must not silently reuse
    # the Telegram chat_id for an "fs" message.
    result = await tool.execute(content="hi", channel="fs")
    assert "chat_id is required" in result
    assert "'fs'" in result
    assert sent == []


@pytest.mark.asyncio
async def test_unknown_fs_peer_is_rejected() -> None:
    sent: list = []

    async def cb(msg):
        sent.append(msg)

    tool = MessageTool(
        send_callback=cb,
        default_channel="telegram",
        default_chat_id="12345",
        fs_peers=["Iroh", "Peewee"],
    )

    result = await tool.execute(content="hi", channel="fs", chat_id="nobody")
    assert "unknown fs peer" in result
    assert "Iroh" in result and "Peewee" in result
    assert sent == []


@pytest.mark.asyncio
async def test_known_fs_peer_is_sent() -> None:
    sent: list = []

    async def cb(msg):
        sent.append(msg)

    tool = MessageTool(
        send_callback=cb,
        default_channel="telegram",
        default_chat_id="12345",
        fs_peers=["Iroh"],
    )

    result = await tool.execute(content="hi", channel="fs", chat_id="Iroh")
    assert result.startswith("Message sent to fs:Iroh")
    assert len(sent) == 1
    assert sent[0].channel == "fs"
    assert sent[0].chat_id == "Iroh"


def test_description_lists_fs_peers_when_configured() -> None:
    tool = MessageTool(fs_peers=["Iroh", "Peewee"])
    assert "'Iroh'" in tool.description
    assert "'Peewee'" in tool.description


def test_description_omits_fs_hint_when_no_peers() -> None:
    tool = MessageTool()
    assert "channel='fs'" not in tool.description
