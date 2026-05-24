from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

# Check optional Slack dependencies before running tests
try:
    import slack_sdk  # noqa: F401
except ImportError:
    pytest.skip("Slack dependencies not installed (slack-sdk)", allow_module_level=True)

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.slack import SLACK_MAX_MESSAGE_LEN, SlackChannel, SlackConfig


class _FakeAsyncWebClient:
    def __init__(self) -> None:
        self.chat_post_calls: list[dict[str, object | None]] = []
        self.file_upload_calls: list[dict[str, object | None]] = []
        self.reactions_add_calls: list[dict[str, object | None]] = []
        self.reactions_remove_calls: list[dict[str, object | None]] = []
        self.conversations_list_calls: list[dict[str, object | None]] = []
        self.conversations_replies_calls: list[dict[str, object | None]] = []
        self.users_list_calls: list[dict[str, object | None]] = []
        self.conversations_open_calls: list[dict[str, object | None]] = []
        self._conversations_pages: list[dict[str, object]] = []
        self._conversations_replies_response: dict[str, object] = {"messages": []}
        self._users_pages: list[dict[str, object]] = []
        self._open_dm_response: dict[str, object] = {"channel": {"id": "D_OPENED"}}

    async def chat_postMessage(  # noqa: N802 - mirrors Slack SDK method name
        self,
        *,
        channel: str,
        text: str,
        thread_ts: str | None = None,
        blocks: list[dict[str, object]] | None = None,
    ) -> None:
        call: dict[str, object | None] = {
            "channel": channel,
            "text": text,
            "thread_ts": thread_ts,
        }
        if blocks is not None:
            call["blocks"] = blocks
        self.chat_post_calls.append(call)

    async def files_upload_v2(
        self,
        *,
        channel: str,
        file: str,
        thread_ts: str | None = None,
    ) -> None:
        self.file_upload_calls.append(
            {
                "channel": channel,
                "file": file,
                "thread_ts": thread_ts,
            }
        )

    async def reactions_add(
        self,
        *,
        channel: str,
        name: str,
        timestamp: str,
    ) -> None:
        self.reactions_add_calls.append(
            {
                "channel": channel,
                "name": name,
                "timestamp": timestamp,
            }
        )

    async def reactions_remove(
        self,
        *,
        channel: str,
        name: str,
        timestamp: str,
    ) -> None:
        self.reactions_remove_calls.append(
            {
                "channel": channel,
                "name": name,
                "timestamp": timestamp,
            }
        )

    async def conversations_list(self, **kwargs):
        self.conversations_list_calls.append(kwargs)
        if self._conversations_pages:
            return self._conversations_pages.pop(0)
        return {"channels": [], "response_metadata": {"next_cursor": ""}}

    async def conversations_replies(self, **kwargs):
        self.conversations_replies_calls.append(kwargs)
        return self._conversations_replies_response

    async def users_list(self, **kwargs):
        self.users_list_calls.append(kwargs)
        if self._users_pages:
            return self._users_pages.pop(0)
        return {"members": [], "response_metadata": {"next_cursor": ""}}

    async def conversations_open(self, **kwargs):
        self.conversations_open_calls.append(kwargs)
        return self._open_dm_response


@pytest.mark.asyncio
async def test_send_uses_thread_for_channel_messages() -> None:
    channel = SlackChannel(SlackConfig(enabled=True), MessageBus())
    fake_web = _FakeAsyncWebClient()
    channel._web_client = fake_web

    await channel.send(
        OutboundMessage(
            channel="slack",
            chat_id="C123",
            content="hello",
            media=["/tmp/demo.txt"],
            metadata={"slack": {"thread_ts": "1700000000.000100", "channel_type": "channel"}},
        )
    )

    assert len(fake_web.chat_post_calls) == 1
    assert fake_web.chat_post_calls[0]["text"] == "hello"
    assert fake_web.chat_post_calls[0]["thread_ts"] == "1700000000.000100"
    assert len(fake_web.file_upload_calls) == 1
    assert fake_web.file_upload_calls[0]["thread_ts"] == "1700000000.000100"


@pytest.mark.asyncio
async def test_send_omits_thread_for_dm_root_messages() -> None:
    """DM root replies should not be threaded; metadata carries thread_ts=None."""
    channel = SlackChannel(SlackConfig(enabled=True), MessageBus())
    fake_web = _FakeAsyncWebClient()
    channel._web_client = fake_web

    await channel.send(
        OutboundMessage(
            channel="slack",
            chat_id="D123",
            content="hello",
            media=["/tmp/demo.txt"],
            metadata={"slack": {"thread_ts": None, "channel_type": "im"}},
        )
    )

    assert len(fake_web.chat_post_calls) == 1
    assert fake_web.chat_post_calls[0]["text"] == "hello"
    assert fake_web.chat_post_calls[0]["thread_ts"] is None
    assert len(fake_web.file_upload_calls) == 1
    assert fake_web.file_upload_calls[0]["thread_ts"] is None


@pytest.mark.asyncio
async def test_send_keeps_thread_for_dm_thread_messages() -> None:
    """When the user replies inside a DM thread, bot replies stay in the same thread."""
    channel = SlackChannel(SlackConfig(enabled=True), MessageBus())
    fake_web = _FakeAsyncWebClient()
    channel._web_client = fake_web

    await channel.send(
        OutboundMessage(
            channel="slack",
            chat_id="D123",
            content="hello",
            media=["/tmp/demo.txt"],
            metadata={
                "slack": {
                    "thread_ts": "1700000000.000100",
                    "channel_type": "im",
                    "event": {"channel": "D123"},
                }
            },
        )
    )

    assert len(fake_web.chat_post_calls) == 1
    assert fake_web.chat_post_calls[0]["thread_ts"] == "1700000000.000100"
    assert len(fake_web.file_upload_calls) == 1
    assert fake_web.file_upload_calls[0]["thread_ts"] == "1700000000.000100"


@pytest.mark.asyncio
async def test_send_splits_long_messages() -> None:
    channel = SlackChannel(SlackConfig(enabled=True), MessageBus())
    fake_web = _FakeAsyncWebClient()
    channel._web_client = fake_web

    await channel.send(
        OutboundMessage(
            channel="slack",
            chat_id="C123",
            content="x" * (SLACK_MAX_MESSAGE_LEN + 10),
        )
    )

    assert len(fake_web.chat_post_calls) == 2
    assert all(len(str(call["text"])) <= SLACK_MAX_MESSAGE_LEN for call in fake_web.chat_post_calls)


@pytest.mark.asyncio
async def test_send_renders_buttons_on_last_message_chunk() -> None:
    channel = SlackChannel(SlackConfig(enabled=True), MessageBus())
    fake_web = _FakeAsyncWebClient()
    channel._web_client = fake_web

    await channel.send(
        OutboundMessage(
            channel="slack",
            chat_id="C123",
            content="Choose one",
            buttons=[["Yes", "No"]],
        )
    )

    assert len(fake_web.chat_post_calls) == 1
    blocks = fake_web.chat_post_calls[0]["blocks"]
    assert isinstance(blocks, list)
    assert blocks[-1] == {
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Yes"},
                "value": "Yes",
                "action_id": "btn_Yes",
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "No"},
                "value": "No",
                "action_id": "btn_No",
            },
        ],
    }


@pytest.mark.asyncio
async def test_send_updates_reaction_when_final_response_sent() -> None:
    channel = SlackChannel(SlackConfig(enabled=True, react_emoji="eyes"), MessageBus())
    fake_web = _FakeAsyncWebClient()
    channel._web_client = fake_web

    await channel.send(
        OutboundMessage(
            channel="slack",
            chat_id="C123",
            content="done",
            metadata={
                "slack": {"event": {"ts": "1700000000.000100"}, "channel_type": "channel"},
            },
        )
    )

    assert fake_web.reactions_remove_calls == [
        {"channel": "C123", "name": "eyes", "timestamp": "1700000000.000100"}
    ]
    assert fake_web.reactions_add_calls == [
        {"channel": "C123", "name": "white_check_mark", "timestamp": "1700000000.000100"}
    ]


@pytest.mark.asyncio
async def test_send_resolves_channel_name_to_channel_id() -> None:
    channel = SlackChannel(SlackConfig(enabled=True), MessageBus())
    fake_web = _FakeAsyncWebClient()
    fake_web._conversations_pages = [
        {
            "channels": [{"id": "C999", "name": "channel_x"}],
            "response_metadata": {"next_cursor": ""},
        }
    ]
    channel._web_client = fake_web

    await channel.send(
        OutboundMessage(
            channel="slack",
            chat_id="#channel_x",
            content="hello",
        )
    )

    assert fake_web.chat_post_calls == [
        {"channel": "C999", "text": "hello", "thread_ts": None}
    ]
    assert len(fake_web.conversations_list_calls) == 1


@pytest.mark.asyncio
async def test_send_resolves_user_handle_to_dm_channel() -> None:
    channel = SlackChannel(SlackConfig(enabled=True), MessageBus())
    fake_web = _FakeAsyncWebClient()
    fake_web._users_pages = [
        {
            "members": [
                {
                    "id": "U234",
                    "name": "alice",
                    "profile": {"display_name": "Alice"},
                }
            ],
            "response_metadata": {"next_cursor": ""},
        }
    ]
    fake_web._open_dm_response = {"channel": {"id": "D234"}}
    channel._web_client = fake_web

    await channel.send(
        OutboundMessage(
            channel="slack",
            chat_id="@alice",
            content="hello",
        )
    )

    assert fake_web.conversations_open_calls == [{"users": "U234"}]
    assert fake_web.chat_post_calls == [
        {"channel": "D234", "text": "hello", "thread_ts": None}
    ]


@pytest.mark.asyncio
async def test_send_updates_reaction_on_origin_channel_for_cross_channel_send() -> None:
    channel = SlackChannel(SlackConfig(enabled=True, react_emoji="eyes"), MessageBus())
    fake_web = _FakeAsyncWebClient()
    fake_web._conversations_pages = [
        {
            "channels": [{"id": "C999", "name": "channel_x"}],
            "response_metadata": {"next_cursor": ""},
        }
    ]
    channel._web_client = fake_web

    await channel.send(
        OutboundMessage(
            channel="slack",
            chat_id="channel_x",
            content="done",
            metadata={
                "slack": {
                    "event": {"ts": "1700000000.000100", "channel": "D_ORIGIN"},
                    "channel_type": "im",
                },
            },
        )
    )

    assert fake_web.chat_post_calls == [
        {"channel": "C999", "text": "done", "thread_ts": None}
    ]
    assert fake_web.reactions_remove_calls == [
        {"channel": "D_ORIGIN", "name": "eyes", "timestamp": "1700000000.000100"}
    ]
    assert fake_web.reactions_add_calls == [
        {"channel": "D_ORIGIN", "name": "white_check_mark", "timestamp": "1700000000.000100"}
    ]


@pytest.mark.asyncio
async def test_send_does_not_reuse_origin_thread_ts_for_cross_channel_send() -> None:
    channel = SlackChannel(SlackConfig(enabled=True), MessageBus())
    fake_web = _FakeAsyncWebClient()
    fake_web._conversations_pages = [
        {
            "channels": [{"id": "C999", "name": "channel_x"}],
            "response_metadata": {"next_cursor": ""},
        }
    ]
    channel._web_client = fake_web

    await channel.send(
        OutboundMessage(
            channel="slack",
            chat_id="channel_x",
            content="done",
            metadata={
                "slack": {
                    "event": {"ts": "1700000000.000100", "channel": "C_ORIGIN"},
                    "thread_ts": "1700000000.000200",
                    "channel_type": "channel",
                },
            },
        )
    )

    assert fake_web.chat_post_calls == [
        {"channel": "C999", "text": "done", "thread_ts": None}
    ]


@pytest.mark.asyncio
async def test_send_raises_when_named_target_cannot_be_resolved() -> None:
    channel = SlackChannel(SlackConfig(enabled=True), MessageBus())
    fake_web = _FakeAsyncWebClient()
    channel._web_client = fake_web

    with pytest.raises(ValueError, match="was not found"):
        await channel.send(
            OutboundMessage(
                channel="slack",
                chat_id="#missing-channel",
                content="hello",
            )
        )


@pytest.mark.asyncio
async def test_with_thread_context_fetches_root_once() -> None:
    channel = SlackChannel(SlackConfig(enabled=True), MessageBus())
    channel._bot_user_id = "UBOT"
    fake_web = _FakeAsyncWebClient()
    fake_web._conversations_replies_response = {
        "messages": [
            {"ts": "111.000", "user": "UROOT", "text": "drink water"},
            {"ts": "112.000", "user": "U2", "text": "good idea"},
            {"ts": "112.500", "user": "UBOT", "text": "I'll remind you."},
            {"ts": "113.000", "user": "U3", "text": "<@UBOT> what did you see?"},
        ]
    }
    channel._web_client = fake_web

    content = await channel._with_thread_context(
        "what did you see?",
        chat_id="C123",
        channel_type="channel",
        thread_ts="111.000",
        raw_thread_ts="111.000",
        current_ts="113.000",
    )

    assert fake_web.conversations_replies_calls == [
        {"channel": "C123", "ts": "111.000", "limit": 20}
    ]
    assert "Slack thread context before this mention:" in content
    assert "- <@UROOT>: drink water" in content
    assert "- <@U2>: good idea" in content
    assert "- bot: I'll remind you." in content
    assert "U3" not in content
    assert content.endswith("Current message:\nwhat did you see?")

    second = await channel._with_thread_context(
        "again",
        chat_id="C123",
        channel_type="channel",
        thread_ts="111.000",
        raw_thread_ts="111.000",
        current_ts="114.000",
    )
    assert second == "again"
    assert len(fake_web.conversations_replies_calls) == 1


@pytest.mark.asyncio
async def test_with_thread_context_fetches_replies_in_dm_thread() -> None:
    """DM threads should also pull thread history (not only channel threads)."""
    channel = SlackChannel(SlackConfig(enabled=True), MessageBus())
    channel._bot_user_id = "UBOT"
    fake_web = _FakeAsyncWebClient()
    fake_web._conversations_replies_response = {
        "messages": [
            {"ts": "211.000", "user": "UA", "text": "here is the file"},
            {"ts": "212.000", "user": "UA", "text": "please read it"},
        ]
    }
    channel._web_client = fake_web

    content = await channel._with_thread_context(
        "what did you see?",
        chat_id="D123",
        channel_type="im",
        thread_ts="211.000",
        raw_thread_ts="211.000",
        current_ts="213.000",
    )

    assert fake_web.conversations_replies_calls == [
        {"channel": "D123", "ts": "211.000", "limit": 20}
    ]
    assert "Slack thread context before this mention:" in content
    assert "- <@UA>: here is the file" in content


@pytest.mark.asyncio
async def test_dm_root_message_has_no_thread_ts_and_no_thread_session() -> None:
    """A top-level DM should not synthesize a thread_ts and uses the default session."""
    channel = SlackChannel(SlackConfig(enabled=True), MessageBus())
    channel._bot_user_id = "UBOT"
    channel._web_client = _FakeAsyncWebClient()
    channel._handle_message = AsyncMock()  # type: ignore[method-assign]
    client = SimpleNamespace(send_socket_mode_response=AsyncMock())
    req = SimpleNamespace(
        type="events_api",
        envelope_id="env-dm-root",
        payload={
            "event": {
                "type": "message",
                "user": "U1",
                "channel": "D123",
                "channel_type": "im",
                "text": "hello",
                "ts": "1700000000.000100",
            }
        },
    )

    await channel._on_socket_request(client, req)

    channel._handle_message.assert_awaited_once()
    kwargs = channel._handle_message.await_args.kwargs
    assert kwargs["session_key"] is None
    assert kwargs["metadata"]["slack"]["thread_ts"] is None


@pytest.mark.asyncio
async def test_dm_thread_message_keeps_thread_ts_and_threaded_session() -> None:
    """A DM message inside a real thread should preserve thread_ts and isolate the session."""
    channel = SlackChannel(SlackConfig(enabled=True), MessageBus())
    channel._bot_user_id = "UBOT"
    channel._web_client = _FakeAsyncWebClient()
    channel._handle_message = AsyncMock()  # type: ignore[method-assign]
    channel._with_thread_context = AsyncMock(return_value="hello")  # type: ignore[method-assign]
    client = SimpleNamespace(send_socket_mode_response=AsyncMock())
    req = SimpleNamespace(
        type="events_api",
        envelope_id="env-dm-thread",
        payload={
            "event": {
                "type": "message",
                "user": "U1",
                "channel": "D123",
                "channel_type": "im",
                "text": "hello",
                "ts": "1700000000.000200",
                "thread_ts": "1700000000.000100",
            }
        },
    )

    await channel._on_socket_request(client, req)

    channel._handle_message.assert_awaited_once()
    kwargs = channel._handle_message.await_args.kwargs
    assert kwargs["session_key"] == "slack:D123:1700000000.000100"
    assert kwargs["metadata"]["slack"]["thread_ts"] == "1700000000.000100"


@pytest.mark.asyncio
async def test_slack_slash_command_skips_thread_context() -> None:
    channel = SlackChannel(SlackConfig(enabled=True, allow_from=[]), MessageBus())
    channel._bot_user_id = "UBOT"
    channel._with_thread_context = AsyncMock(return_value="wrapped")  # type: ignore[method-assign]
    channel._handle_message = AsyncMock()  # type: ignore[method-assign]
    client = SimpleNamespace(send_socket_mode_response=AsyncMock())
    req = SimpleNamespace(
        type="events_api",
        envelope_id="env-1",
        payload={
            "event": {
                "type": "app_mention",
                "user": "U1",
                "channel": "C123",
                "text": "<@UBOT> /restart",
                "thread_ts": "111.000",
                "ts": "112.000",
            }
        },
    )

    await channel._on_socket_request(client, req)

    channel._with_thread_context.assert_not_awaited()
    channel._handle_message.assert_awaited_once()
    assert channel._handle_message.await_args.kwargs["content"] == "/restart"


@pytest.mark.asyncio
async def test_slack_file_share_downloads_media_and_reaches_agent() -> None:
    channel = SlackChannel(SlackConfig(enabled=True, bot_token="xoxb-test"), MessageBus())
    channel._bot_user_id = "UBOT"
    channel._web_client = _FakeAsyncWebClient()
    channel._handle_message = AsyncMock()  # type: ignore[method-assign]
    channel._download_slack_file = AsyncMock(  # type: ignore[method-assign]
        return_value=("/tmp/report.pdf", "[file: report.pdf]")
    )
    client = SimpleNamespace(send_socket_mode_response=AsyncMock())
    req = SimpleNamespace(
        type="events_api",
        envelope_id="env-file",
        payload={
            "event": {
                "type": "message",
                "subtype": "file_share",
                "user": "U1",
                "channel": "D123",
                "channel_type": "im",
                "text": "please read this",
                "ts": "1700000000.000100",
                "files": [
                    {
                        "id": "F123",
                        "name": "report.pdf",
                        "mimetype": "application/pdf",
                        "url_private_download": "https://files.slack.com/report.pdf",
                    }
                ],
            }
        },
    )

    await channel._on_socket_request(client, req)

    channel._download_slack_file.assert_awaited_once()
    channel._handle_message.assert_awaited_once()
    kwargs = channel._handle_message.await_args.kwargs
    assert kwargs["content"] == "please read this\n[file: report.pdf]"
    assert kwargs["media"] == ["/tmp/report.pdf"]


def test_slack_download_rejects_login_html() -> None:
    html_response = httpx.Response(
        200,
        headers={"content-type": "text/html; charset=utf-8"},
        content=b"<!doctype html><html><title>Sign in to Slack</title>",
    )
    markdown_response = httpx.Response(
        200,
        headers={"content-type": "text/markdown"},
        content=b"# PR Extraction Guide\n",
    )

    assert SlackChannel._looks_like_html_download(html_response) is True
    assert SlackChannel._looks_like_html_download(markdown_response) is False


def test_slack_download_failure_marker_is_actionable() -> None:
    marker = SlackChannel._download_failure_marker("image", "screenshot.png", "download failed")

    assert "not available to nanobot" in marker
    assert "files:read" in marker
    assert "reinstall the Slack app" in marker


def test_slack_channel_uses_channel_aware_allow_policy() -> None:
    channel = SlackChannel(SlackConfig(enabled=True, allow_from=[]), MessageBus())
    assert channel.is_allowed("U1") is True
    assert channel._is_allowed("U1", "C123", "channel") is True
