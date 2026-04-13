from __future__ import annotations

import pytest

# Check optional Slack dependencies before running tests
try:
    import slack_sdk  # noqa: F401
except ImportError:
    pytest.skip("Slack dependencies not installed (slack-sdk)", allow_module_level=True)

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.slack import SlackChannel
from nanobot.channels.slack import SlackConfig


class _FakeAsyncWebClient:
    def __init__(self) -> None:
        self.chat_post_calls: list[dict[str, object | None]] = []
        self.file_upload_calls: list[dict[str, object | None]] = []
        self.reactions_add_calls: list[dict[str, object | None]] = []
        self.reactions_remove_calls: list[dict[str, object | None]] = []

    async def chat_postMessage(
        self,
        *,
        channel: str,
        text: str,
        thread_ts: str | None = None,
    ) -> None:
        self.chat_post_calls.append(
            {
                "channel": channel,
                "text": text,
                "thread_ts": thread_ts,
            }
        )

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
    assert fake_web.chat_post_calls[0]["text"] == "hello\n"
    assert fake_web.chat_post_calls[0]["thread_ts"] == "1700000000.000100"
    assert len(fake_web.file_upload_calls) == 1
    assert fake_web.file_upload_calls[0]["thread_ts"] == "1700000000.000100"


@pytest.mark.asyncio
async def test_send_omits_thread_for_dm_messages() -> None:
    channel = SlackChannel(SlackConfig(enabled=True), MessageBus())
    fake_web = _FakeAsyncWebClient()
    channel._web_client = fake_web

    await channel.send(
        OutboundMessage(
            channel="slack",
            chat_id="D123",
            content="hello",
            media=["/tmp/demo.txt"],
            metadata={"slack": {"thread_ts": "1700000000.000100", "channel_type": "im"}},
        )
    )

    assert len(fake_web.chat_post_calls) == 1
    assert fake_web.chat_post_calls[0]["text"] == "hello\n"
    assert fake_web.chat_post_calls[0]["thread_ts"] is None
    assert len(fake_web.file_upload_calls) == 1
    assert fake_web.file_upload_calls[0]["thread_ts"] is None


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


def test_is_allowed_group_checks_user_allow_from() -> None:
    """Groups should check both group_allow_from and user-level allow_from."""
    channel = SlackChannel(
        SlackConfig(
            enabled=True,
            allow_from=["U123"],
            group_policy="allowlist",
            group_allow_from=["C456"],
        ),
        MessageBus(),
    )

    # User in allow_from, channel in group_allow_from - should succeed
    assert channel._is_allowed("U123", "C456", "channel") is True

    # User NOT in allow_from, but channel in group_allow_from - should fail
    assert channel._is_allowed("U999", "C456", "channel") is False

    # User in allow_from, channel NOT in group_allow_from - should fail
    assert channel._is_allowed("U123", "C999", "channel") is False


def test_is_allowed_group_wildcard_allows_all_users() -> None:
    """Groups with allow_from=['*'] should allow all users in whitelisted channels."""
    channel = SlackChannel(
        SlackConfig(
            enabled=True,
            allow_from=["*"],
            group_policy="allowlist",
            group_allow_from=["C456"],
        ),
        MessageBus(),
    )

    # Any user should be allowed in whitelisted channel
    assert channel._is_allowed("U123", "C456", "channel") is True
    assert channel._is_allowed("U999", "C456", "channel") is True


def test_is_allowed_group_empty_allow_from_denies_all() -> None:
    """Groups with empty allow_from should deny all users."""
    channel = SlackChannel(
        SlackConfig(
            enabled=True,
            allow_from=[],
            group_policy="allowlist",
            group_allow_from=["C456"],
        ),
        MessageBus(),
    )

    # Even in whitelisted channel, no user should be allowed
    assert channel._is_allowed("U123", "C456", "channel") is False


def test_is_allowed_group_open_policy_with_user_allow_from() -> None:
    """Groups with 'open' policy should still check user-level allow_from."""
    channel = SlackChannel(
        SlackConfig(
            enabled=True,
            allow_from=["U123"],
            group_policy="open",
        ),
        MessageBus(),
    )

    # User in allow_from - should succeed
    assert channel._is_allowed("U123", "C456", "channel") is True

    # User NOT in allow_from - should fail
    assert channel._is_allowed("U999", "C456", "channel") is False


def test_is_allowed_dm_uses_dm_config() -> None:
    """DMs should use dm.allow_from, not top-level allow_from."""
    channel = SlackChannel(
        SlackConfig(
            enabled=True,
            allow_from=["U123"],
            dm={"enabled": True, "policy": "allowlist", "allow_from": ["U456"]},
        ),
        MessageBus(),
    )

    # DM: user in dm.allow_from - should succeed
    assert channel._is_allowed("U456", "D123", "im") is True

    # DM: user NOT in dm.allow_from (but in top-level allow_from) - should fail
    assert channel._is_allowed("U123", "D123", "im") is False
