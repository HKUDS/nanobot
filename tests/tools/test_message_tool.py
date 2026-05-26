import os

import pytest

from nanobot.agent.tools.message import MessageTool
from nanobot.bus.events import OutboundMessage
from nanobot.config.paths import get_workspace_path


@pytest.mark.asyncio
async def test_message_tool_returns_error_when_no_target_context() -> None:
    tool = MessageTool()
    result = await tool.execute(content="test")
    assert result == "Error: No target channel/chat specified"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        "not a list",
        [["ok"], "row-not-a-list"],
        [["ok", 42]],
        [[None]],
    ],
)
async def test_message_tool_rejects_malformed_buttons(bad) -> None:
    """``buttons`` must be ``list[list[str]]``; the tool validates the shape
    up front so a malformed LLM payload errors visibly instead of slipping
    into the channel layer where Telegram would silently reject the frame."""
    tool = MessageTool()
    result = await tool.execute(
        content="hi",
        channel="telegram",
        chat_id="1",
        buttons=bad,
    )
    assert result == "Error: buttons must be a list of list of strings"


@pytest.mark.asyncio
async def test_message_tool_marks_channel_delivery_only_when_enabled() -> None:
    sent: list[OutboundMessage] = []

    async def _send(msg: OutboundMessage) -> None:
        sent.append(msg)

    tool = MessageTool(send_callback=_send)

    await tool.execute(content="normal", channel="telegram", chat_id="1")
    token = tool.set_record_channel_delivery(True)
    try:
        await tool.execute(content="cron", channel="telegram", chat_id="1")
    finally:
        tool.reset_record_channel_delivery(token)

    assert sent[0].metadata == {}
    assert sent[1].metadata == {"_record_channel_delivery": True}


@pytest.mark.asyncio
async def test_message_tool_records_media_deliveries() -> None:
    sent: list[OutboundMessage] = []

    async def _send(msg: OutboundMessage) -> None:
        sent.append(msg)

    tool = MessageTool(send_callback=_send)

    await tool.execute(
        content="image",
        channel="websocket",
        chat_id="chat-1",
        media=["/tmp/generated.png"],
    )

    assert sent[0].metadata == {"_record_channel_delivery": True}


@pytest.mark.asyncio
async def test_message_tool_inherits_metadata_for_same_target() -> None:
    sent: list[OutboundMessage] = []

    async def _send(msg: OutboundMessage) -> None:
        sent.append(msg)

    tool = MessageTool(send_callback=_send)
    slack_meta = {"slack": {"thread_ts": "111.222", "channel_type": "channel"}}
    from nanobot.agent.tools.context import RequestContext

    tool.set_context(RequestContext(channel="slack", chat_id="C123", metadata=slack_meta))

    await tool.execute(content="thread reply")

    assert sent[0].metadata == slack_meta


@pytest.mark.asyncio
async def test_message_tool_clears_metadata_when_context_has_none() -> None:
    sent: list[OutboundMessage] = []

    async def _send(msg: OutboundMessage) -> None:
        sent.append(msg)

    tool = MessageTool(send_callback=_send)
    from nanobot.agent.tools.context import RequestContext

    tool.set_context(
        RequestContext(
            channel="slack",
            chat_id="C123",
            metadata={"slack": {"thread_ts": "111.222", "channel_type": "channel"}},
        ),
    )
    tool.set_context(RequestContext(channel="slack", chat_id="C123", metadata={}))

    await tool.execute(content="plain reply")

    assert sent[0].metadata == {}


@pytest.mark.asyncio
async def test_message_tool_does_not_inherit_metadata_for_cross_target() -> None:
    sent: list[OutboundMessage] = []

    async def _send(msg: OutboundMessage) -> None:
        sent.append(msg)

    tool = MessageTool(send_callback=_send)
    from nanobot.agent.tools.context import RequestContext

    tool.set_context(
        RequestContext(
            channel="slack",
            chat_id="C123",
            metadata={"slack": {"thread_ts": "111.222", "channel_type": "channel"}},
        ),
    )

    await tool.execute(content="channel reply", channel="slack", chat_id="C999")

    assert sent[0].metadata == {}


@pytest.mark.asyncio
async def test_message_tool_resolves_relative_media_paths() -> None:
    sent: list[OutboundMessage] = []

    async def _send(msg: OutboundMessage) -> None:
        sent.append(msg)

    tool = MessageTool(send_callback=_send)

    await tool.execute(
        content="see attached",
        channel="telegram",
        chat_id="1",
        media=["output/image.png"],
    )

    expected = str(get_workspace_path() / "output/image.png")
    assert sent[0].media == [expected]


@pytest.mark.asyncio
async def test_message_tool_resolves_relative_media_paths_from_active_workspace(tmp_path) -> None:
    sent: list[OutboundMessage] = []

    async def _send(msg: OutboundMessage) -> None:
        sent.append(msg)

    workspace = tmp_path / "workspace"
    tool = MessageTool(send_callback=_send, workspace=workspace)

    await tool.execute(
        content="see attached",
        channel="telegram",
        chat_id="1",
        media=["output/image.png"],
    )

    assert sent[0].media == [str(workspace / "output/image.png")]


@pytest.mark.asyncio
async def test_message_tool_rejects_outside_workspace_absolute_media_when_restricted(
    tmp_path,
) -> None:
    sent: list[OutboundMessage] = []

    async def _send(msg: OutboundMessage) -> None:
        sent.append(msg)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    tool = MessageTool(send_callback=_send, workspace=workspace, restrict_to_workspace=True)

    result = await tool.execute(
        content="see attached",
        channel="telegram",
        chat_id="1",
        media=[str(outside)],
    )

    assert result.startswith("Error: media path is not allowed:")
    assert "outside allowed directory" in result
    assert sent == []


@pytest.mark.asyncio
async def test_message_tool_allows_workspace_absolute_media_when_restricted(tmp_path) -> None:
    sent: list[OutboundMessage] = []

    async def _send(msg: OutboundMessage) -> None:
        sent.append(msg)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    image = workspace / "image.png"
    image.write_text("image", encoding="utf-8")
    tool = MessageTool(send_callback=_send, workspace=workspace, restrict_to_workspace=True)

    result = await tool.execute(
        content="see attached",
        channel="telegram",
        chat_id="1",
        media=[str(image)],
    )

    assert result == "Message sent to telegram:1 with 1 attachments"
    assert sent[0].media == [str(image.resolve())]


@pytest.mark.asyncio
async def test_message_tool_passes_through_absolute_media_paths() -> None:
    sent: list[OutboundMessage] = []

    async def _send(msg: OutboundMessage) -> None:
        sent.append(msg)

    tool = MessageTool(send_callback=_send)

    abs_path = os.path.abspath(os.path.join(os.sep, "tmp", "abs_image.png"))

    await tool.execute(
        content="see attached",
        channel="telegram",
        chat_id="1",
        media=[abs_path],
    )

    assert sent[0].media == [abs_path]


@pytest.mark.asyncio
async def test_message_tool_passes_through_url_media_paths() -> None:
    sent: list[OutboundMessage] = []

    async def _send(msg: OutboundMessage) -> None:
        sent.append(msg)

    tool = MessageTool(send_callback=_send)

    url = "https://example.com/image.png"

    await tool.execute(
        content="see attached",
        channel="telegram",
        chat_id="1",
        media=[url],
    )

    assert sent[0].media == [url]


@pytest.mark.asyncio
async def test_message_tool_resolves_mixed_media_paths() -> None:
    sent: list[OutboundMessage] = []

    async def _send(msg: OutboundMessage) -> None:
        sent.append(msg)

    tool = MessageTool(send_callback=_send)

    abs_path = os.path.abspath(os.path.join(os.sep, "tmp", "absolute.png"))

    await tool.execute(
        content="see attached",
        channel="telegram",
        chat_id="1",
        media=[
            "output/relative.png",
            abs_path,
            "https://example.com/url.png",
            "http://example.com/http.png",
        ],
    )

    expected_relative = str(get_workspace_path() / "output/relative.png")
    assert sent[0].media == [
        expected_relative,
        abs_path,
        "https://example.com/url.png",
        "http://example.com/http.png",
    ]


@pytest.mark.asyncio
async def test_message_tool_tracks_turn_media_for_same_target(tmp_path) -> None:
    sent: list[OutboundMessage] = []

    async def _send(msg: OutboundMessage) -> None:
        sent.append(msg)

    tool = MessageTool(send_callback=_send)
    from nanobot.agent.tools.context import RequestContext

    tool.set_context(RequestContext(channel="websocket", chat_id="chat-1", metadata={}))
    tool.start_turn()
    f = tmp_path / "doc.md"
    f.write_text("hello", encoding="utf-8")
    await tool.execute(content="see file", channel="websocket", chat_id="chat-1", media=[str(f)])

    assert tool.turn_delivered_media_paths() == [str(f.resolve())]


@pytest.mark.asyncio
async def test_message_tool_start_turn_clears_tracked_media(tmp_path) -> None:
    async def _send(msg: OutboundMessage) -> None:
        pass

    tool = MessageTool(send_callback=_send)
    from nanobot.agent.tools.context import RequestContext

    tool.set_context(RequestContext(channel="websocket", chat_id="chat-1", metadata={}))
    tool.start_turn()
    f = tmp_path / "doc.md"
    f.write_text("hello", encoding="utf-8")
    await tool.execute(content="see file", media=[str(f)])
    tool.start_turn()
    assert tool.turn_delivered_media_paths() == []


@pytest.mark.asyncio
async def test_message_tool_cross_target_does_not_track_turn_media(tmp_path) -> None:
    async def _send(msg: OutboundMessage) -> None:
        pass

    tool = MessageTool(send_callback=_send)
    from nanobot.agent.tools.context import RequestContext

    tool.set_context(RequestContext(channel="websocket", chat_id="chat-1", metadata={}))
    f = tmp_path / "doc.md"
    f.write_text("hello", encoding="utf-8")
    await tool.execute(
        content="see file",
        channel="telegram",
        chat_id="tg-other",
        media=[str(f)],
    )
    assert tool.turn_delivered_media_paths() == []


@pytest.mark.asyncio
async def test_message_tool_rejects_wrong_explicit_ws_chat_id(tmp_path) -> None:
    sent: list[OutboundMessage] = []

    async def _send(msg: OutboundMessage) -> None:
        sent.append(msg)

    tool = MessageTool(send_callback=_send)
    from nanobot.agent.tools.context import RequestContext

    conv = "550e8400-e29b-41d4-a716-446655440000"
    tool.set_context(RequestContext(channel="websocket", chat_id=conv, metadata={}))
    f = tmp_path / "doc.md"
    f.write_text("hello", encoding="utf-8")
    result = await tool.execute(
        content="see file",
        channel="websocket",
        chat_id="anon-deadbeefcafe",
        media=[str(f)],
    )
    assert result.startswith("Error: chat_id does not match")
    assert sent == []


@pytest.mark.asyncio
async def test_message_tool_allows_ws_explicit_when_matches_context(tmp_path) -> None:
    sent: list[OutboundMessage] = []

    async def _send(msg: OutboundMessage) -> None:
        sent.append(msg)

    tool = MessageTool(send_callback=_send)
    from nanobot.agent.tools.context import RequestContext

    conv = "550e8400-e29b-41d4-a716-446655440000"
    tool.set_context(RequestContext(channel="websocket", chat_id=conv, metadata={}))
    f = tmp_path / "doc.md"
    f.write_text("hello", encoding="utf-8")
    result = await tool.execute(
        content="see file",
        channel="websocket",
        chat_id=conv,
        media=[str(f)],
    )
    assert result.startswith("Message sent")
    assert sent[0].chat_id == conv


@pytest.mark.asyncio
async def test_message_tool_cli_context_may_target_other_ws_chat(tmp_path) -> None:
    """Cron / CLI handlers keep non-websocket defaults; explicit websocket + uuid remains valid."""
    sent: list[OutboundMessage] = []

    async def _send(msg: OutboundMessage) -> None:
        sent.append(msg)

    tool = MessageTool(send_callback=_send)
    from nanobot.agent.tools.context import RequestContext

    target = "550e8400-e29b-41d4-a716-446655440000"
    tool.set_context(RequestContext(channel="cli", chat_id="direct", metadata={}))
    f = tmp_path / "doc.md"
    f.write_text("hello", encoding="utf-8")
    result = await tool.execute(
        content="ping",
        channel="websocket",
        chat_id=target,
        media=[str(f)],
    )
    assert result.startswith("Message sent")
    assert sent[0].channel == "websocket"
    assert sent[0].chat_id == target
