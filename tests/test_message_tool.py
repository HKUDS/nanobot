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


@pytest.mark.asyncio
async def test_message_tool_stamps_force_send() -> None:
    """Message tool sends are always intentional; force_send=True bypasses
    channel-level auto-reply suppression."""
    sent: list = []

    async def cb(msg):
        sent.append(msg)

    tool = MessageTool(
        send_callback=cb,
        default_channel="telegram",
        default_chat_id="12345",
    )

    await tool.execute(content="hi", chat_id="12345")
    assert sent[0].metadata.get("force_send") is True


def test_description_lists_fs_peers_when_configured() -> None:
    tool = MessageTool(fs_peers=["Iroh", "Peewee"])
    assert "'Iroh'" in tool.description
    assert "'Peewee'" in tool.description


def test_description_omits_fs_hint_when_no_peers() -> None:
    tool = MessageTool()
    assert "channel='fs'" not in tool.description


@pytest.mark.asyncio
async def test_fs_rate_limit_blocks_rapid_resends() -> None:
    sent: list = []

    async def cb(msg):
        sent.append(msg)

    tool = MessageTool(
        send_callback=cb,
        default_channel="telegram",
        default_chat_id="12345",
        fs_peers=["Iroh"],
        fs_min_send_interval_seconds=1.0,
    )

    first = await tool.execute(content="one", channel="fs", chat_id="Iroh")
    assert first.startswith("Message sent")
    second = await tool.execute(content="two", channel="fs", chat_id="Iroh")
    assert "rate-limited" in second
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_fs_rate_limit_is_per_peer() -> None:
    sent: list = []

    async def cb(msg):
        sent.append(msg)

    tool = MessageTool(
        send_callback=cb,
        default_channel="telegram",
        default_chat_id="12345",
        fs_peers=["Iroh", "Peewee"],
        fs_min_send_interval_seconds=1.0,
    )

    await tool.execute(content="hi I", channel="fs", chat_id="Iroh")
    # Sending to a different peer is not rate-limited.
    result = await tool.execute(content="hi P", channel="fs", chat_id="Peewee")
    assert result.startswith("Message sent")
    assert len(sent) == 2
