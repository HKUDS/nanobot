from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

discord = pytest.importorskip("discord")

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.discord import (
    MAX_MESSAGE_LEN,
    DiscordBotClient,
    DiscordChannel,
    DiscordConfig,
)
from nanobot.command.builtin import build_help_text


# Minimal Discord client test double used to control startup/readiness behavior.
class _FakeDiscordClient:
    instances: list["_FakeDiscordClient"] = []
    start_error: Exception | None = None

    def __init__(self, owner, *, intents, proxy=None, proxy_auth=None) -> None:
        self.owner = owner
        self.intents = intents
        self.proxy = proxy
        self.proxy_auth = proxy_auth
        self.closed = False
        self.ready = True
        self.channels: dict[int, object] = {}
        self.user = SimpleNamespace(id=999)
        self.__class__.instances.append(self)

    async def start(self, token: str) -> None:
        self.token = token
        if self.__class__.start_error is not None:
            raise self.__class__.start_error

    async def close(self) -> None:
        self.closed = True

    def is_closed(self) -> bool:
        return self.closed

    def is_ready(self) -> bool:
        return self.ready

    def get_channel(self, channel_id: int):
        return self.channels.get(channel_id)

    async def send_outbound(self, msg: OutboundMessage) -> None:
        channel = self.get_channel(int(msg.chat_id))
        if channel is None:
            return
        await channel.send(content=msg.content)


class _FakeAttachment:
    # Attachment double that can simulate successful or failing save() calls.
    def __init__(
        self, attachment_id: int, filename: str, *, size: int = 1, fail: bool = False
    ) -> None:
        self.id = attachment_id
        self.filename = filename
        self.size = size
        self._fail = fail

    async def save(self, path: str | Path) -> None:
        if self._fail:
            raise RuntimeError("save failed")
        Path(path).write_bytes(b"attachment")


class _FakePartialMessage:
    # Lightweight stand-in for Discord partial message references used in replies.
    def __init__(self, message_id: int) -> None:
        self.id = message_id


class _FakeSentMessage:
    # Sent-message double supporting edit() for streaming tests.
    def __init__(self, channel, content: str) -> None:
        self.channel = channel
        self.content = content
        self.edits: list[dict] = []

    async def edit(self, **kwargs) -> None:
        self.edits.append(dict(kwargs))
        if "content" in kwargs:
            self.content = kwargs["content"]


class _FakeChannel:
    # Channel double that records outbound payloads and typing activity.
    def __init__(
        self,
        channel_id: int = 123,
        parent_id: int | None = None,
        parent: object | None = None,
    ) -> None:
        self.id = channel_id
        self.parent_id = parent_id
        self.parent = parent
        self.sent_payloads: list[dict] = []
        self.sent_messages: list[_FakeSentMessage] = []
        self.trigger_typing_calls = 0
        self.typing_enter_hook = None

    async def send(self, **kwargs) -> None:
        payload = dict(kwargs)
        if "file" in payload:
            payload["file_name"] = payload["file"].filename
            del payload["file"]
        self.sent_payloads.append(payload)
        message = _FakeSentMessage(self, payload.get("content", ""))
        self.sent_messages.append(message)
        return message

    def get_partial_message(self, message_id: int) -> _FakePartialMessage:
        return _FakePartialMessage(message_id)

    def typing(self):
        channel = self

        class _TypingContext:
            async def __aenter__(self):
                channel.trigger_typing_calls += 1
                if channel.typing_enter_hook is not None:
                    await channel.typing_enter_hook()

            async def __aexit__(self, exc_type, exc, tb):
                return False

        return _TypingContext()


class _FakeInteractionResponse:
    def __init__(self) -> None:
        self.messages: list[dict] = []
        self._done = False

    async def send_message(self, content: str, *, ephemeral: bool = False) -> None:
        self.messages.append({"content": content, "ephemeral": ephemeral})
        self._done = True

    def is_done(self) -> bool:
        return self._done


def _make_interaction(
    *,
    user_id: int = 123,
    channel_id: int | None = 456,
    channel=None,
    guild_id: int | None = None,
    interaction_id: int = 999,
):
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id),
        channel_id=channel_id,
        channel=channel,
        guild_id=guild_id,
        id=interaction_id,
        command=SimpleNamespace(qualified_name="new"),
        response=_FakeInteractionResponse(),
    )


def _make_message(
    *,
    author_id: int = 123,
    author_bot: bool = False,
    channel_id: int = 456,
    parent_channel_id: int | None = None,
    message_id: int = 789,
    content: str = "hello",
    guild_id: int | None = None,
    mentions: list[object] | None = None,
    attachments: list[object] | None = None,
    reply_to: int | None = None,
    reply_author_id: int | None = None,
    message_type=None,
):
    # Factory for incoming Discord message objects with optional guild/reply/attachments.
    guild = SimpleNamespace(id=guild_id) if guild_id is not None else None
    referenced_message = (
        SimpleNamespace(author=SimpleNamespace(id=reply_author_id))
        if reply_author_id is not None
        else None
    )
    reference = (
        SimpleNamespace(message_id=reply_to, resolved=referenced_message)
        if reply_to is not None
        else None
    )
    return SimpleNamespace(
        author=SimpleNamespace(id=author_id, bot=author_bot),
        channel=_FakeChannel(channel_id, parent_channel_id),
        content=content,
        guild=guild,
        mentions=mentions or [],
        raw_mentions=[],
        attachments=attachments or [],
        reference=reference,
        id=message_id,
        type=message_type or discord.MessageType.default,
    )


@pytest.mark.asyncio
async def test_start_returns_when_token_missing() -> None:
    # If no token is configured, startup should no-op and leave channel stopped.
    channel = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), MessageBus())

    await channel.start()

    assert channel.is_running is False
    assert channel._client is None


@pytest.mark.asyncio
async def test_start_returns_when_discord_dependency_missing(monkeypatch) -> None:
    channel = DiscordChannel(
        DiscordConfig(enabled=True, token="token", allow_from=["*"]),
        MessageBus(),
    )
    monkeypatch.setattr("nanobot.channels.discord.DISCORD_AVAILABLE", False)

    await channel.start()

    assert channel.is_running is False
    assert channel._client is None


@pytest.mark.asyncio
async def test_start_handles_client_construction_failure(monkeypatch) -> None:
    # Construction errors from the Discord client should be swallowed and keep state clean.
    channel = DiscordChannel(
        DiscordConfig(enabled=True, token="token", allow_from=["*"]),
        MessageBus(),
    )

    def _boom(owner, *, intents, proxy=None, proxy_auth=None):
        raise RuntimeError("bad client")

    monkeypatch.setattr("nanobot.channels.discord.DiscordBotClient", _boom)

    await channel.start()

    assert channel.is_running is False
    assert channel._client is None


@pytest.mark.asyncio
async def test_start_handles_client_start_failure(monkeypatch) -> None:
    # If client.start fails, the partially created client should be closed and detached.
    channel = DiscordChannel(
        DiscordConfig(enabled=True, token="token", allow_from=["*"]),
        MessageBus(),
    )

    _FakeDiscordClient.instances.clear()
    _FakeDiscordClient.start_error = RuntimeError("connect failed")
    monkeypatch.setattr("nanobot.channels.discord.DiscordBotClient", _FakeDiscordClient)

    await channel.start()

    assert channel.is_running is False
    assert channel._client is None
    assert _FakeDiscordClient.instances[0].intents.value == channel.config.intents
    assert _FakeDiscordClient.instances[0].closed is True

    _FakeDiscordClient.start_error = None


@pytest.mark.asyncio
async def test_stop_is_safe_after_partial_start(monkeypatch) -> None:
    # stop() should close/discard the client even when startup was only partially completed.
    channel = DiscordChannel(
        DiscordConfig(enabled=True, token="token", allow_from=["*"]),
        MessageBus(),
    )
    client = _FakeDiscordClient(channel, intents=None)
    channel._client = client
    channel._running = True

    await channel.stop()

    assert channel.is_running is False
    assert client.closed is True
    assert channel._client is None


@pytest.mark.asyncio
async def test_on_message_ignores_self_messages() -> None:
    # Self-loop guard: messages from this bot's own account must be dropped (#3217).
    channel = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), MessageBus())
    channel._bot_user_id = "999"  # simulate bot identity populated in on_ready()
    handled: list[dict] = []
    channel._handle_message = lambda **kwargs: handled.append(kwargs)  # type: ignore[method-assign]

    await channel._on_message(_make_message(author_id=999, author_bot=True))

    assert handled == []


@pytest.mark.asyncio
async def test_on_message_accepts_messages_from_other_bots() -> None:
    # Multi-agent setups: messages from OTHER bots must be processed, not dropped (#3217).
    channel = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), MessageBus())
    channel._bot_user_id = "999"
    handled: list[dict] = []

    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = capture_handle  # type: ignore[method-assign]

    await channel._on_message(_make_message(author_id=123, author_bot=True))

    assert len(handled) == 1
    assert handled[0]["sender_id"] == "123"


@pytest.mark.asyncio
async def test_on_message_stops_typing_on_handle_exception() -> None:
    # If inbound handling raises, typing should be stopped for that channel.
    channel = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), MessageBus())

    async def fail_handle(**kwargs) -> None:
        raise RuntimeError("boom")

    channel._handle_message = fail_handle  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="boom"):
        await channel._on_message(_make_message(author_id=123, channel_id=456))

    assert channel._typing_tasks == {}


@pytest.mark.asyncio
async def test_on_message_accepts_allowlisted_dm() -> None:
    # Allowed direct messages should be forwarded with normalized metadata.
    channel = DiscordChannel(DiscordConfig(enabled=True, allow_from=["123"]), MessageBus())
    handled: list[dict] = []

    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = capture_handle  # type: ignore[method-assign]

    await channel._on_message(_make_message(author_id=123, channel_id=456, message_id=789))

    assert len(handled) == 1
    assert handled[0]["chat_id"] == "456"
    assert handled[0]["metadata"] == {"message_id": "789", "guild_id": None, "reply_to": None}


@pytest.mark.asyncio
async def test_on_message_accepts_when_channel_in_allow_channels() -> None:
    # When allow_channels is set, messages from listed channels should be forwarded.
    channel = DiscordChannel(
        DiscordConfig(enabled=True, allow_from=["*"], allow_channels=["456"]),
        MessageBus(),
    )
    handled: list[dict] = []

    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = capture_handle  # type: ignore[method-assign]

    await channel._on_message(_make_message(author_id=123, channel_id=456))

    assert len(handled) == 1
    assert handled[0]["chat_id"] == "456"


@pytest.mark.asyncio
async def test_on_message_accepts_thread_when_parent_channel_in_allow_channels() -> None:
    # Discord threads have independent channel IDs, but inherit allowlist access
    # from their parent channel.
    channel = DiscordChannel(
        DiscordConfig(
            enabled=True,
            allow_from=["*"],
            allow_channels=["456"],
            group_policy="mention",
        ),
        MessageBus(),
    )
    channel._bot_user_id = "999"
    handled: list[dict] = []

    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = capture_handle  # type: ignore[method-assign]

    await channel._on_message(
        _make_message(
            channel_id=777,
            parent_channel_id=456,
            guild_id=1,
            mentions=[SimpleNamespace(id=999)],
        )
    )

    assert len(handled) == 1
    assert handled[0]["chat_id"] == "777"
    assert handled[0]["metadata"]["context_chat_id"] == "456"
    assert handled[0]["metadata"]["thread_id"] == "777"
    assert handled[0]["session_key"] == "discord:456:thread:777"


@pytest.mark.asyncio
async def test_on_message_accepts_thread_reply_to_bot_under_allowed_parent() -> None:
    channel = DiscordChannel(
        DiscordConfig(
            enabled=True,
            allow_from=["*"],
            allow_channels=["456"],
            group_policy="mention",
        ),
        MessageBus(),
    )
    channel._bot_user_id = "999"
    handled: list[dict] = []

    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = capture_handle  # type: ignore[method-assign]

    await channel._on_message(
        _make_message(
            channel_id=777,
            parent_channel_id=456,
            guild_id=1,
            content="follow up",
            reply_to=111,
            reply_author_id=999,
        )
    )

    assert len(handled) == 1
    assert handled[0]["chat_id"] == "777"
    assert handled[0]["metadata"]["reply_to"] == "111"
    assert handled[0]["metadata"]["context_chat_id"] == "456"
    assert handled[0]["session_key"] == "discord:456:thread:777"


@pytest.mark.asyncio
async def test_on_message_ignores_thread_lifecycle_messages() -> None:
    channel = DiscordChannel(
        DiscordConfig(
            enabled=True,
            allow_from=["*"],
            allow_channels=["456"],
            group_policy="open",
        ),
        MessageBus(),
    )
    handled: list[dict] = []

    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = capture_handle  # type: ignore[method-assign]

    await channel._on_message(
        _make_message(
            channel_id=777,
            parent_channel_id=456,
            guild_id=1,
            content="",
            message_type=discord.MessageType.thread_created,
        )
    )
    await channel._on_message(
        _make_message(
            channel_id=777,
            parent_channel_id=456,
            guild_id=1,
            content="",
            message_type=discord.MessageType.thread_starter_message,
        )
    )
    await channel._on_message(
        _make_message(
            channel_id=777,
            parent_channel_id=456,
            guild_id=1,
            content="",
            message_type=discord.MessageType.pins_add,
        )
    )

    assert handled == []


@pytest.mark.asyncio
async def test_on_message_drops_thread_when_neither_thread_nor_parent_allowed() -> None:
    channel = DiscordChannel(
        DiscordConfig(enabled=True, allow_from=["*"], allow_channels=["999"]),
        MessageBus(),
    )
    handled: list[dict] = []

    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = capture_handle  # type: ignore[method-assign]

    await channel._on_message(_make_message(channel_id=777, parent_channel_id=456))

    assert handled == []


@pytest.mark.asyncio
async def test_on_message_drops_when_channel_not_in_allow_channels() -> None:
    # When allow_channels is set and incoming channel is not listed, drop silently.
    channel = DiscordChannel(
        DiscordConfig(enabled=True, allow_from=["*"], allow_channels=["999"]),
        MessageBus(),
    )
    handled: list[dict] = []

    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = capture_handle  # type: ignore[method-assign]

    await channel._on_message(_make_message(author_id=123, channel_id=456))

    assert handled == []


@pytest.mark.asyncio
async def test_on_message_ignores_unmentioned_guild_message() -> None:
    # With mention-only group policy, guild messages without a bot mention are dropped.
    channel = DiscordChannel(
        DiscordConfig(enabled=True, allow_from=["*"], group_policy="mention"),
        MessageBus(),
    )
    channel._bot_user_id = "999"
    handled: list[dict] = []

    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = capture_handle  # type: ignore[method-assign]

    await channel._on_message(_make_message(guild_id=1, content="hello everyone"))

    assert handled == []


@pytest.mark.asyncio
async def test_on_message_accepts_mentioned_guild_message() -> None:
    # Mentioned guild messages should be accepted and preserve reply threading metadata.
    channel = DiscordChannel(
        DiscordConfig(enabled=True, allow_from=["*"], group_policy="mention"),
        MessageBus(),
    )
    channel._bot_user_id = "999"
    handled: list[dict] = []

    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = capture_handle  # type: ignore[method-assign]

    await channel._on_message(
        _make_message(
            guild_id=1,
            content="<@999> hello",
            mentions=[SimpleNamespace(id=999)],
            reply_to=321,
        )
    )

    assert len(handled) == 1
    assert handled[0]["metadata"]["reply_to"] == "321"


@pytest.mark.asyncio
async def test_on_message_downloads_attachments(tmp_path, monkeypatch) -> None:
    # Attachment downloads should be saved and referenced in forwarded content/media.
    channel = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), MessageBus())
    handled: list[dict] = []

    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = capture_handle  # type: ignore[method-assign]
    monkeypatch.setattr("nanobot.channels.discord.get_media_dir", lambda _name: tmp_path)

    await channel._on_message(
        _make_message(
            attachments=[_FakeAttachment(12, "photo.png")],
            content="see file",
        )
    )

    assert len(handled) == 1
    assert handled[0]["media"] == [str(tmp_path / "12_photo.png")]
    assert "[attachment:" in handled[0]["content"]


@pytest.mark.asyncio
async def test_on_message_marks_failed_attachment_download(tmp_path, monkeypatch) -> None:
    # Failed attachment downloads should emit a readable placeholder and no media path.
    channel = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), MessageBus())
    handled: list[dict] = []

    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = capture_handle  # type: ignore[method-assign]
    monkeypatch.setattr("nanobot.channels.discord.get_media_dir", lambda _name: tmp_path)

    await channel._on_message(
        _make_message(
            attachments=[_FakeAttachment(12, "photo.png", fail=True)],
            content="",
        )
    )

    assert len(handled) == 1
    assert handled[0]["media"] == []
    assert handled[0]["content"] == "[attachment: photo.png - download failed]"


@pytest.mark.asyncio
async def test_send_warns_when_client_not_ready() -> None:
    # Sending without a running/ready client should be a safe no-op.
    channel = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), MessageBus())

    await channel.send(OutboundMessage(channel="discord", chat_id="123", content="hello"))

    assert channel._typing_tasks == {}


@pytest.mark.asyncio
async def test_send_skips_when_channel_not_cached() -> None:
    # Outbound sends should be skipped when the destination channel is not resolvable.
    owner = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), MessageBus())
    client = DiscordBotClient(owner, intents=discord.Intents.none())
    fetch_calls: list[int] = []

    async def fetch_channel(channel_id: int):
        fetch_calls.append(channel_id)
        raise RuntimeError("not found")

    client.fetch_channel = fetch_channel  # type: ignore[method-assign]

    await client.send_outbound(OutboundMessage(channel="discord", chat_id="123", content="hello"))

    assert client.get_channel(123) is None
    assert fetch_calls == [123]


@pytest.mark.asyncio
async def test_send_fetches_channel_when_not_cached() -> None:
    owner = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), MessageBus())
    client = DiscordBotClient(owner, intents=discord.Intents.none())
    target = _FakeChannel(channel_id=123)

    async def fetch_channel(channel_id: int):
        return target if channel_id == 123 else None

    client.fetch_channel = fetch_channel  # type: ignore[method-assign]

    await client.send_outbound(OutboundMessage(channel="discord", chat_id="123", content="hello"))

    assert target.sent_payloads == [{"content": "hello"}]


@pytest.mark.asyncio
async def test_send_uses_seen_thread_channel_when_client_cannot_resolve_it() -> None:
    owner = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), MessageBus())
    client = DiscordBotClient(owner, intents=discord.Intents.none())
    target = _FakeChannel(channel_id=777, parent_id=456)
    owner._known_channels["777"] = target
    client.get_channel = lambda channel_id: None  # type: ignore[method-assign]

    async def fetch_channel(channel_id: int):
        raise RuntimeError("not found")

    client.fetch_channel = fetch_channel  # type: ignore[method-assign]

    await client.send_outbound(OutboundMessage(channel="discord", chat_id="777", content="hello"))

    assert target.sent_payloads == [{"content": "hello"}]


def test_supports_streaming_enabled_by_default() -> None:
    channel = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), MessageBus())

    assert channel.supports_streaming is True


@pytest.mark.asyncio
async def test_send_delta_streams_by_editing_message(monkeypatch) -> None:
    owner = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), MessageBus())
    client = _FakeDiscordClient(owner, intents=None)
    owner._client = client
    owner._running = True
    target = _FakeChannel(channel_id=123)
    client.channels[123] = target

    times = iter([1.0, 3.0, 5.0])
    monkeypatch.setattr("nanobot.channels.discord.time.monotonic", lambda: next(times, 5.0))

    await owner.send_delta("123", "hel", {"_stream_delta": True, "_stream_id": "s1"})
    await owner.send_delta("123", "lo", {"_stream_delta": True, "_stream_id": "s1"})
    await owner.send_delta("123", "", {"_stream_end": True, "_stream_id": "s1"})

    assert target.sent_payloads[0] == {"content": "hel"}
    assert target.sent_messages[0].edits == [{"content": "hello"}, {"content": "hello"}]
    assert owner._stream_bufs == {}


@pytest.mark.asyncio
async def test_send_delta_stream_end_splits_oversized_reply(monkeypatch) -> None:
    owner = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), MessageBus())
    client = _FakeDiscordClient(owner, intents=None)
    owner._client = client
    owner._running = True
    target = _FakeChannel(channel_id=123)
    client.channels[123] = target

    prefix = "a" * (MAX_MESSAGE_LEN - 100)
    suffix = "b" * 150
    full_text = prefix + suffix
    chunks = DiscordBotClient._build_chunks(full_text, [], False)
    assert len(chunks) == 2

    times = iter([1.0, 3.0])
    monkeypatch.setattr("nanobot.channels.discord.time.monotonic", lambda: next(times, 3.0))

    await owner.send_delta("123", prefix, {"_stream_delta": True, "_stream_id": "s1"})
    await owner.send_delta("123", suffix, {"_stream_delta": True, "_stream_id": "s1"})
    await owner.send_delta("123", "", {"_stream_end": True, "_stream_id": "s1"})

    assert target.sent_payloads == [{"content": prefix}, {"content": chunks[1]}]
    assert target.sent_messages[0].edits == [{"content": chunks[0]}, {"content": chunks[0]}]
    assert owner._stream_bufs == {}


@pytest.mark.asyncio
async def test_slash_new_forwards_when_user_is_allowlisted() -> None:
    channel = DiscordChannel(DiscordConfig(enabled=True, allow_from=["123"]), MessageBus())
    handled: list[dict] = []

    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = capture_handle  # type: ignore[method-assign]
    client = DiscordBotClient(channel, intents=discord.Intents.none())
    interaction = _make_interaction(user_id=123, channel_id=456, interaction_id=321)

    new_cmd = client.tree.get_command("new")
    assert new_cmd is not None
    await new_cmd.callback(interaction)

    assert interaction.response.messages == [{"content": "Processing /new...", "ephemeral": True}]
    assert len(handled) == 1
    assert handled[0]["content"] == "/new"
    assert handled[0]["sender_id"] == "123"
    assert handled[0]["chat_id"] == "456"
    assert handled[0]["metadata"]["interaction_id"] == "321"
    assert handled[0]["metadata"]["is_slash_command"] is True


@pytest.mark.asyncio
async def test_slash_new_accepts_thread_when_parent_channel_in_allow_channels() -> None:
    channel = DiscordChannel(
        DiscordConfig(enabled=True, allow_from=["*"], allow_channels=["456"]),
        MessageBus(),
    )
    handled: list[dict] = []

    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = capture_handle  # type: ignore[method-assign]
    client = DiscordBotClient(channel, intents=discord.Intents.none())
    thread = _FakeChannel(channel_id=777, parent_id=456)
    interaction = _make_interaction(
        user_id=123,
        channel_id=777,
        channel=thread,
        guild_id=1,
        interaction_id=321,
    )

    new_cmd = client.tree.get_command("new")
    assert new_cmd is not None
    await new_cmd.callback(interaction)

    assert interaction.response.messages == [{"content": "Processing /new...", "ephemeral": True}]
    assert len(handled) == 1
    assert handled[0]["chat_id"] == "777"
    assert handled[0]["metadata"]["context_chat_id"] == "456"
    assert handled[0]["metadata"]["thread_id"] == "777"
    assert handled[0]["session_key"] == "discord:456:thread:777"
    assert channel._known_channels["777"] is thread


@pytest.mark.asyncio
async def test_slash_new_blocks_channel_not_in_allow_channels() -> None:
    channel = DiscordChannel(
        DiscordConfig(enabled=True, allow_from=["*"], allow_channels=["999"]),
        MessageBus(),
    )
    handled: list[dict] = []

    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = capture_handle  # type: ignore[method-assign]
    client = DiscordBotClient(channel, intents=discord.Intents.none())
    interaction = _make_interaction(
        user_id=123,
        channel_id=777,
        channel=_FakeChannel(channel_id=777, parent_id=456),
        guild_id=1,
    )

    new_cmd = client.tree.get_command("new")
    assert new_cmd is not None
    await new_cmd.callback(interaction)

    assert interaction.response.messages == [
        {"content": "This channel is not allowed for this bot.", "ephemeral": True}
    ]
    assert handled == []


@pytest.mark.asyncio
async def test_slash_new_is_blocked_for_disallowed_user() -> None:
    channel = DiscordChannel(DiscordConfig(enabled=True, allow_from=["999"]), MessageBus())
    handled: list[dict] = []

    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = capture_handle  # type: ignore[method-assign]
    client = DiscordBotClient(channel, intents=discord.Intents.none())
    interaction = _make_interaction(user_id=123, channel_id=456)

    new_cmd = client.tree.get_command("new")
    assert new_cmd is not None
    await new_cmd.callback(interaction)

    assert interaction.response.messages == [
        {"content": "You are not allowed to use this bot.", "ephemeral": True}
    ]
    assert handled == []


@pytest.mark.parametrize("slash_name", ["stop", "restart", "status", "history"])
@pytest.mark.asyncio
async def test_slash_commands_forward_via_handle_message(slash_name: str) -> None:
    channel = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), MessageBus())
    handled: list[dict] = []

    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = capture_handle  # type: ignore[method-assign]
    client = DiscordBotClient(channel, intents=discord.Intents.none())
    interaction = _make_interaction()
    interaction.command.qualified_name = slash_name

    cmd = client.tree.get_command(slash_name)
    assert cmd is not None
    await cmd.callback(interaction)

    assert interaction.response.messages == [
        {"content": f"Processing /{slash_name}...", "ephemeral": True}
    ]
    assert len(handled) == 1
    assert handled[0]["content"] == f"/{slash_name}"
    assert handled[0]["metadata"]["is_slash_command"] is True


@pytest.mark.asyncio
async def test_slash_help_returns_ephemeral_help_text() -> None:
    channel = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), MessageBus())
    handled: list[dict] = []

    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = capture_handle  # type: ignore[method-assign]
    client = DiscordBotClient(channel, intents=discord.Intents.none())
    interaction = _make_interaction()
    interaction.command.qualified_name = "help"

    help_cmd = client.tree.get_command("help")
    assert help_cmd is not None
    await help_cmd.callback(interaction)

    assert interaction.response.messages == [{"content": build_help_text(), "ephemeral": True}]
    assert handled == []


@pytest.mark.asyncio
async def test_slash_help_respects_allow_channels() -> None:
    channel = DiscordChannel(
        DiscordConfig(enabled=True, allow_from=["*"], allow_channels=["999"]),
        MessageBus(),
    )
    client = DiscordBotClient(channel, intents=discord.Intents.none())
    interaction = _make_interaction(
        channel_id=777,
        channel=_FakeChannel(channel_id=777, parent_id=456),
        guild_id=1,
    )
    interaction.command.qualified_name = "help"

    help_cmd = client.tree.get_command("help")
    assert help_cmd is not None
    await help_cmd.callback(interaction)

    assert interaction.response.messages == [
        {"content": "This channel is not allowed for this bot.", "ephemeral": True}
    ]


@pytest.mark.asyncio
async def test_thread_delete_and_archive_remove_known_channel() -> None:
    channel = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), MessageBus())
    client = DiscordBotClient(channel, intents=discord.Intents.none())
    thread = _FakeChannel(channel_id=777, parent_id=456)

    channel._remember_channel(thread)
    await client.on_thread_delete(thread)
    assert "777" not in channel._known_channels

    channel._remember_channel(thread)
    archived_thread = SimpleNamespace(id=777, parent_id=456, archived=True)
    await client.on_thread_update(thread, archived_thread)
    assert "777" not in channel._known_channels


@pytest.mark.asyncio
async def test_client_send_outbound_chunks_text_replies_and_uploads_files(tmp_path) -> None:
    # Outbound payloads should upload files, attach reply references, and chunk long text.
    owner = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), MessageBus())
    client = DiscordBotClient(owner, intents=discord.Intents.none())
    target = _FakeChannel(channel_id=123)
    client.get_channel = lambda channel_id: target if channel_id == 123 else None  # type: ignore[method-assign]

    file_path = tmp_path / "demo.txt"
    file_path.write_text("hi")

    await client.send_outbound(
        OutboundMessage(
            channel="discord",
            chat_id="123",
            content="a" * 2100,
            reply_to="55",
            media=[str(file_path)],
        )
    )

    assert len(target.sent_payloads) == 3
    assert target.sent_payloads[0]["file_name"] == "demo.txt"
    assert target.sent_payloads[0]["reference"].id == 55
    assert target.sent_payloads[1]["content"] == "a" * 2000
    assert target.sent_payloads[2]["content"] == "a" * 100


@pytest.mark.asyncio
async def test_client_send_outbound_reports_failed_attachments_when_no_text(tmp_path) -> None:
    # If all attachment sends fail and no text exists, emit a failure placeholder message.
    owner = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), MessageBus())
    client = DiscordBotClient(owner, intents=discord.Intents.none())
    target = _FakeChannel(channel_id=123)
    client.get_channel = lambda channel_id: target if channel_id == 123 else None  # type: ignore[method-assign]

    missing_file = tmp_path / "missing.txt"

    await client.send_outbound(
        OutboundMessage(
            channel="discord",
            chat_id="123",
            content="",
            media=[str(missing_file)],
        )
    )

    assert target.sent_payloads == [{"content": "[attachment: missing.txt - send failed]"}]


@pytest.mark.asyncio
async def test_send_stops_typing_after_send() -> None:
    # Active typing indicators should be cancelled/cleared after a successful send.
    channel = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), MessageBus())
    client = _FakeDiscordClient(channel, intents=None)
    channel._client = client
    channel._running = True

    start = asyncio.Event()
    release = asyncio.Event()

    async def slow_typing() -> None:
        start.set()
        await release.wait()

    typing_channel = _FakeChannel(channel_id=123)
    typing_channel.typing_enter_hook = slow_typing

    await channel._start_typing(typing_channel)
    await asyncio.wait_for(start.wait(), timeout=1.0)

    await channel.send(OutboundMessage(channel="discord", chat_id="123", content="hello"))
    release.set()
    await asyncio.sleep(0)

    assert channel._typing_tasks == {}

    # Progress messages should keep typing active until a final (non-progress) send.
    start = asyncio.Event()
    release = asyncio.Event()

    async def slow_typing_progress() -> None:
        start.set()
        await release.wait()

    typing_channel = _FakeChannel(channel_id=123)
    typing_channel.typing_enter_hook = slow_typing_progress

    await channel._start_typing(typing_channel)
    await asyncio.wait_for(start.wait(), timeout=1.0)

    await channel.send(
        OutboundMessage(
            channel="discord",
            chat_id="123",
            content="progress",
            metadata={"_progress": True},
        )
    )

    assert "123" in channel._typing_tasks

    await channel.send(OutboundMessage(channel="discord", chat_id="123", content="final"))
    release.set()
    await asyncio.sleep(0)

    assert channel._typing_tasks == {}


@pytest.mark.asyncio
async def test_start_typing_uses_typing_context_when_trigger_typing_missing() -> None:
    channel = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), MessageBus())
    channel._running = True

    entered = asyncio.Event()
    release = asyncio.Event()

    class _TypingCtx:
        async def __aenter__(self):
            entered.set()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _NoTriggerChannel:
        def __init__(self, channel_id: int = 123) -> None:
            self.id = channel_id

        def typing(self):
            async def _waiter():
                await release.wait()

            # Hold the loop so task remains active until explicitly stopped.
            class _Ctx(_TypingCtx):
                async def __aenter__(self):
                    await super().__aenter__()
                    await _waiter()

            return _Ctx()

    typing_channel = _NoTriggerChannel(channel_id=123)
    await channel._start_typing(typing_channel)  # type: ignore[arg-type]
    await asyncio.wait_for(entered.wait(), timeout=1.0)

    assert "123" in channel._typing_tasks

    await channel._stop_typing("123")
    release.set()
    await asyncio.sleep(0)

    assert channel._typing_tasks == {}


def test_config_accepts_proxy_fields() -> None:
    config = DiscordConfig(
        enabled=True,
        token="token",
        allow_from=["*"],
        proxy="http://127.0.0.1:7890",
        proxy_username="user",
        proxy_password="pass",
    )
    assert config.proxy == "http://127.0.0.1:7890"
    assert config.proxy_username == "user"
    assert config.proxy_password == "pass"


def test_config_proxy_defaults_to_none() -> None:
    config = DiscordConfig(enabled=True, token="token", allow_from=["*"])
    assert config.proxy is None
    assert config.proxy_username is None
    assert config.proxy_password is None


@pytest.mark.asyncio
async def test_start_passes_proxy_to_client(monkeypatch) -> None:
    _FakeDiscordClient.instances.clear()
    channel = DiscordChannel(
        DiscordConfig(
            enabled=True,
            token="token",
            allow_from=["*"],
            proxy="http://127.0.0.1:7890",
        ),
        MessageBus(),
    )
    monkeypatch.setattr("nanobot.channels.discord.DiscordBotClient", _FakeDiscordClient)

    await channel.start()

    assert channel.is_running is False
    assert len(_FakeDiscordClient.instances) == 1
    assert _FakeDiscordClient.instances[0].proxy == "http://127.0.0.1:7890"
    assert _FakeDiscordClient.instances[0].proxy_auth is None


@pytest.mark.asyncio
async def test_start_passes_proxy_auth_when_credentials_provided(monkeypatch) -> None:
    aiohttp = pytest.importorskip("aiohttp")
    _FakeDiscordClient.instances.clear()
    channel = DiscordChannel(
        DiscordConfig(
            enabled=True,
            token="token",
            allow_from=["*"],
            proxy="http://127.0.0.1:7890",
            proxy_username="user",
            proxy_password="pass",
        ),
        MessageBus(),
    )
    monkeypatch.setattr("nanobot.channels.discord.DiscordBotClient", _FakeDiscordClient)

    await channel.start()

    assert channel.is_running is False
    assert len(_FakeDiscordClient.instances) == 1
    assert _FakeDiscordClient.instances[0].proxy == "http://127.0.0.1:7890"
    assert _FakeDiscordClient.instances[0].proxy_auth is not None
    assert isinstance(_FakeDiscordClient.instances[0].proxy_auth, aiohttp.BasicAuth)
    assert _FakeDiscordClient.instances[0].proxy_auth.login == "user"
    assert _FakeDiscordClient.instances[0].proxy_auth.password == "pass"


@pytest.mark.asyncio
async def test_start_no_proxy_auth_when_only_username(monkeypatch) -> None:
    _FakeDiscordClient.instances.clear()
    channel = DiscordChannel(
        DiscordConfig(
            enabled=True,
            token="token",
            allow_from=["*"],
            proxy="http://127.0.0.1:7890",
            proxy_username="user",
        ),
        MessageBus(),
    )
    monkeypatch.setattr("nanobot.channels.discord.DiscordBotClient", _FakeDiscordClient)

    await channel.start()

    assert channel.is_running is False
    assert _FakeDiscordClient.instances[0].proxy_auth is None


@pytest.mark.asyncio
async def test_start_no_proxy_auth_when_only_password(monkeypatch) -> None:
    _FakeDiscordClient.instances.clear()
    channel = DiscordChannel(
        DiscordConfig(
            enabled=True,
            token="token",
            allow_from=["*"],
            proxy="http://127.0.0.1:7890",
            proxy_password="pass",
        ),
        MessageBus(),
    )
    monkeypatch.setattr("nanobot.channels.discord.DiscordBotClient", _FakeDiscordClient)

    await channel.start()

    assert channel.is_running is False
    assert _FakeDiscordClient.instances[0].proxy == "http://127.0.0.1:7890"
    assert _FakeDiscordClient.instances[0].proxy_auth is None


# ---------------------------------------------------------------------------
# Tests for the send() exception propagation fix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_re_raises_network_error() -> None:
    """Network errors during send must propagate so ChannelManager can retry."""
    channel = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), MessageBus())
    client = _FakeDiscordClient(channel, intents=None)
    channel._client = client
    channel._running = True

    async def _failing_send_outbound(msg: OutboundMessage) -> None:
        raise ConnectionError("network unreachable")

    client.send_outbound = _failing_send_outbound  # type: ignore[method-assign]

    with pytest.raises(ConnectionError, match="network unreachable"):
        await channel.send(OutboundMessage(channel="discord", chat_id="123", content="hello"))


@pytest.mark.asyncio
async def test_send_re_raises_generic_exception() -> None:
    """Any exception from send_outbound must propagate, not be swallowed."""
    channel = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), MessageBus())
    client = _FakeDiscordClient(channel, intents=None)
    channel._client = client
    channel._running = True

    async def _failing_send_outbound(msg: OutboundMessage) -> None:
        raise RuntimeError("discord API failure")

    client.send_outbound = _failing_send_outbound  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="discord API failure"):
        await channel.send(OutboundMessage(channel="discord", chat_id="123", content="hello"))


@pytest.mark.asyncio
async def test_send_still_stops_typing_on_error() -> None:
    """Typing cleanup must still run in the finally block even when send raises."""
    channel = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), MessageBus())
    client = _FakeDiscordClient(channel, intents=None)
    channel._client = client
    channel._running = True

    # Start a typing task so we can verify it gets cleaned up
    start = asyncio.Event()
    release = asyncio.Event()

    async def slow_typing() -> None:
        start.set()
        await release.wait()

    typing_channel = _FakeChannel(channel_id=123)
    typing_channel.typing_enter_hook = slow_typing
    await channel._start_typing(typing_channel)
    await asyncio.wait_for(start.wait(), timeout=1.0)

    async def _failing_send_outbound(msg: OutboundMessage) -> None:
        raise ConnectionError("timeout")

    client.send_outbound = _failing_send_outbound  # type: ignore[method-assign]

    with pytest.raises(ConnectionError, match="timeout"):
        await channel.send(OutboundMessage(channel="discord", chat_id="123", content="hello"))

    release.set()
    await asyncio.sleep(0)

    # Typing should have been cleaned up by the finally block
    assert channel._typing_tasks == {}


@pytest.mark.asyncio
async def test_send_succeeds_normally() -> None:
    """Successful sends should work without raising."""
    channel = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), MessageBus())
    client = _FakeDiscordClient(channel, intents=None)
    channel._client = client
    channel._running = True

    sent_messages: list[OutboundMessage] = []

    async def _capture_send_outbound(msg: OutboundMessage) -> None:
        sent_messages.append(msg)

    client.send_outbound = _capture_send_outbound  # type: ignore[method-assign]

    msg = OutboundMessage(channel="discord", chat_id="123", content="hello world")
    await channel.send(msg)

    assert len(sent_messages) == 1
    assert sent_messages[0].content == "hello world"
    assert sent_messages[0].chat_id == "123"


# ---------------------------------------------------------------------------
# Interactive components (buttons, selects, modals)
# ---------------------------------------------------------------------------


class _FakeInteractionResponseFull(_FakeInteractionResponse):
    """Extends the slash-command response double with defer() and send_modal()."""

    def __init__(self) -> None:
        super().__init__()
        self.deferred = False
        self.modal = None

    async def defer(self) -> None:
        self.deferred = True
        self._done = True

    async def send_modal(self, modal) -> None:
        self.modal = modal
        self._done = True


def _component_message_double(
    *,
    components: list[object] | None = None,
    message_id: int = 12345,
):
    """Stand-in for interaction.message; carries action rows for label resolution."""
    return SimpleNamespace(id=message_id, components=components or [])


def _make_component_interaction(
    *,
    custom_id: str,
    component_type: int,
    values: list[str] | None = None,
    user_id: int = 123,
    channel_id: int = 456,
    channel=None,
    guild_id: int | None = None,
    interaction_id: int = 999,
    message=None,
):
    data: dict[str, object] = {"custom_id": custom_id, "component_type": component_type}
    if values is not None:
        data["values"] = values
    return SimpleNamespace(
        type=discord.InteractionType.component,
        data=data,
        user=SimpleNamespace(id=user_id),
        channel_id=channel_id,
        channel=channel,
        guild_id=guild_id,
        id=interaction_id,
        response=_FakeInteractionResponseFull(),
        message=message,
    )


def _make_modal_submit_interaction(
    *,
    modal_custom_id: str,
    components: list[dict],
    user_id: int = 123,
    channel_id: int = 456,
    channel=None,
    interaction_id: int = 1000,
    message=None,
):
    return SimpleNamespace(
        type=discord.InteractionType.modal_submit,
        data={"custom_id": modal_custom_id, "components": components},
        user=SimpleNamespace(id=user_id),
        channel_id=channel_id,
        channel=channel,
        guild_id=None,
        id=interaction_id,
        response=_FakeInteractionResponseFull(),
        message=message,
    )


@pytest.mark.asyncio
async def test_components_plain_string_buttons_attach_to_last_chunk() -> None:
    owner = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), MessageBus())
    client = DiscordBotClient(owner, intents=discord.Intents.none())
    target = _FakeChannel(channel_id=123)
    client.get_channel = lambda channel_id: target if channel_id == 123 else None  # type: ignore[method-assign]

    await client.send_outbound(
        OutboundMessage(
            channel="discord",
            chat_id="123",
            content="pick one",
            buttons=[["Yes", "No"]],
        )
    )

    assert len(target.sent_payloads) == 1
    payload = target.sent_payloads[0]
    assert payload["content"] == "pick one"
    view = payload["view"]
    assert isinstance(view, discord.ui.View)
    children = list(view.children)
    assert [child.label for child in children] == ["Yes", "No"]
    assert all(child.style == discord.ButtonStyle.primary for child in children)
    # Custom IDs are auto-assigned to nb:<seed>:0:0 etc.
    assert all(child.custom_id and child.custom_id.startswith("nb:") for child in children)


@pytest.mark.asyncio
async def test_components_view_only_on_last_chunk_when_text_overflows() -> None:
    owner = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), MessageBus())
    client = DiscordBotClient(owner, intents=discord.Intents.none())
    target = _FakeChannel(channel_id=123)
    client.get_channel = lambda channel_id: target if channel_id == 123 else None  # type: ignore[method-assign]

    await client.send_outbound(
        OutboundMessage(
            channel="discord",
            chat_id="123",
            content="a" * 2100,
            buttons=[["Ok"]],
        )
    )

    assert len(target.sent_payloads) == 2
    assert "view" not in target.sent_payloads[0]
    assert isinstance(target.sent_payloads[1]["view"], discord.ui.View)


@pytest.mark.asyncio
async def test_components_styled_button_via_dict() -> None:
    owner = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), MessageBus())
    client = DiscordBotClient(owner, intents=discord.Intents.none())
    target = _FakeChannel(channel_id=123)
    client.get_channel = lambda channel_id: target if channel_id == 123 else None  # type: ignore[method-assign]

    await client.send_outbound(
        OutboundMessage(
            channel="discord",
            chat_id="123",
            content="confirm",
            metadata={
                "_components": [
                    [{"type": "button", "label": "Approve", "style": "success", "custom_id": "ok"}]
                ]
            },
        )
    )

    view = target.sent_payloads[0]["view"]
    button = list(view.children)[0]
    assert button.style == discord.ButtonStyle.success
    assert button.label == "Approve"
    assert button.custom_id == "ok"


@pytest.mark.asyncio
async def test_components_link_button_has_no_custom_id() -> None:
    owner = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), MessageBus())
    client = DiscordBotClient(owner, intents=discord.Intents.none())
    target = _FakeChannel(channel_id=123)
    client.get_channel = lambda channel_id: target if channel_id == 123 else None  # type: ignore[method-assign]

    await client.send_outbound(
        OutboundMessage(
            channel="discord",
            chat_id="123",
            content="see docs",
            metadata={
                "_components": [[{"type": "link", "label": "Docs", "url": "https://example.com"}]]
            },
        )
    )

    view = target.sent_payloads[0]["view"]
    button = list(view.children)[0]
    assert button.style == discord.ButtonStyle.link
    assert button.url == "https://example.com"
    assert button.custom_id is None


@pytest.mark.asyncio
async def test_components_select_row_renders_select() -> None:
    owner = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), MessageBus())
    client = DiscordBotClient(owner, intents=discord.Intents.none())
    target = _FakeChannel(channel_id=123)
    client.get_channel = lambda channel_id: target if channel_id == 123 else None  # type: ignore[method-assign]

    await client.send_outbound(
        OutboundMessage(
            channel="discord",
            chat_id="123",
            content="priority?",
            metadata={
                "_components": [
                    [
                        {
                            "type": "select",
                            "custom_id": "pri",
                            "placeholder": "Pick one",
                            "options": [
                                {"label": "High", "value": "high"},
                                {"label": "Low", "value": "low"},
                            ],
                        }
                    ]
                ]
            },
        )
    )

    view = target.sent_payloads[0]["view"]
    children = list(view.children)
    assert len(children) == 1
    select = children[0]
    assert isinstance(select, discord.ui.Select)
    assert [opt.label for opt in select.options] == ["High", "Low"]
    assert select.custom_id == "pri"


@pytest.mark.asyncio
async def test_components_button_row_autorewraps_when_over_five() -> None:
    owner = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), MessageBus())
    client = DiscordBotClient(owner, intents=discord.Intents.none())
    target = _FakeChannel(channel_id=123)
    client.get_channel = lambda channel_id: target if channel_id == 123 else None  # type: ignore[method-assign]

    eight = [f"opt{i}" for i in range(8)]
    await client.send_outbound(
        OutboundMessage(
            channel="discord",
            chat_id="123",
            content="pick",
            buttons=[eight],
        )
    )

    view = target.sent_payloads[0]["view"]
    rows: dict[int, list[object]] = {}
    for child in view.children:
        rows.setdefault(child.row, []).append(child)
    assert sorted(rows.keys()) == [0, 1]
    assert len(rows[0]) == 5
    assert len(rows[1]) == 3


@pytest.mark.asyncio
async def test_components_select_truncates_options_over_25() -> None:
    owner = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), MessageBus())
    client = DiscordBotClient(owner, intents=discord.Intents.none())
    target = _FakeChannel(channel_id=123)
    client.get_channel = lambda channel_id: target if channel_id == 123 else None  # type: ignore[method-assign]

    options = [{"label": f"o{i}", "value": str(i)} for i in range(30)]
    await client.send_outbound(
        OutboundMessage(
            channel="discord",
            chat_id="123",
            content="pick",
            metadata={"_components": [[{"type": "select", "custom_id": "x", "options": options}]]},
        )
    )

    view = target.sent_payloads[0]["view"]
    select = list(view.children)[0]
    assert len(select.options) == 25


@pytest.mark.asyncio
async def test_components_empty_content_uses_zero_width_space_carrier() -> None:
    owner = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), MessageBus())
    client = DiscordBotClient(owner, intents=discord.Intents.none())
    target = _FakeChannel(channel_id=123)
    client.get_channel = lambda channel_id: target if channel_id == 123 else None  # type: ignore[method-assign]

    await client.send_outbound(
        OutboundMessage(
            channel="discord",
            chat_id="123",
            content="",
            buttons=[["Ack"]],
        )
    )

    assert len(target.sent_payloads) == 1
    payload = target.sent_payloads[0]
    assert payload["content"] == "​"  # zero-width space
    assert isinstance(payload["view"], discord.ui.View)


@pytest.mark.asyncio
async def test_components_button_click_dispatches_inbound() -> None:
    bus = MessageBus()
    owner = DiscordChannel(DiscordConfig(enabled=True, allow_from=["123"]), bus)
    client = DiscordBotClient(owner, intents=discord.Intents.none())
    channel_obj = _FakeChannel(channel_id=456)
    owner._remember_channel(channel_obj)

    button_child = SimpleNamespace(custom_id="nb:abc:0:0", label="Yes")
    action_row = SimpleNamespace(children=[button_child])
    interaction = _make_component_interaction(
        custom_id="nb:abc:0:0",
        component_type=2,
        channel=channel_obj,
        message=_component_message_double(components=[action_row]),
    )

    await client.on_interaction(interaction)

    assert interaction.response.deferred is True
    msg = bus.inbound.get_nowait()
    assert msg.content == "Yes"
    assert msg.metadata["is_callback"] is True
    assert msg.metadata["interaction_type"] == "button"
    assert msg.metadata["custom_id"] == "nb:abc:0:0"
    assert msg.metadata["button_label"] == "Yes"


@pytest.mark.asyncio
async def test_components_select_submit_dispatches_with_values_and_labels() -> None:
    bus = MessageBus()
    owner = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), bus)
    client = DiscordBotClient(owner, intents=discord.Intents.none())
    channel_obj = _FakeChannel(channel_id=456)
    owner._remember_channel(channel_obj)

    select_child = SimpleNamespace(
        custom_id="pri",
        options=[
            SimpleNamespace(label="High", value="high"),
            SimpleNamespace(label="Low", value="low"),
        ],
    )
    interaction = _make_component_interaction(
        custom_id="pri",
        component_type=3,
        values=["high", "low"],
        channel=channel_obj,
        message=_component_message_double(components=[SimpleNamespace(children=[select_child])]),
    )

    await client.on_interaction(interaction)

    msg = bus.inbound.get_nowait()
    assert msg.metadata["interaction_type"] == "select"
    assert msg.metadata["values"] == ["high", "low"]
    assert msg.metadata["labels"] == ["High", "Low"]
    assert msg.content == "High, Low"


@pytest.mark.asyncio
async def test_components_button_with_modal_opens_modal_and_submission_dispatches() -> None:
    bus = MessageBus()
    owner = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), bus)
    client = DiscordBotClient(owner, intents=discord.Intents.none())
    channel_obj = _FakeChannel(channel_id=456)
    owner._remember_channel(channel_obj)

    # First send the button-with-modal so the spec is cached.
    target = _FakeChannel(channel_id=456)
    client.get_channel = lambda channel_id: target if channel_id == 456 else None  # type: ignore[method-assign]
    await client.send_outbound(
        OutboundMessage(
            channel="discord",
            chat_id="456",
            content="open",
            metadata={
                "_components": [
                    [
                        {
                            "type": "button",
                            "label": "Open",
                            "custom_id": "btn-1",
                            "modal": {
                                "title": "Notes",
                                "inputs": [
                                    {
                                        "label": "Comment",
                                        "custom_id": "comment",
                                        "style": "paragraph",
                                    }
                                ],
                            },
                        }
                    ]
                ]
            },
        )
    )
    assert "btn-1" in owner._modal_specs
    assert owner._modal_to_button["btn-1:m"] == "btn-1"

    # Click the button -> bot opens modal, no inbound dispatched yet.
    click = _make_component_interaction(
        custom_id="btn-1",
        component_type=2,
        channel=channel_obj,
        message=_component_message_double(),
    )
    await client.on_interaction(click)
    assert click.response.modal is not None
    assert isinstance(click.response.modal, discord.ui.Modal)
    assert bus.inbound_size == 0

    # Submit the modal -> inbound message keyed by the originating button's custom_id.
    submit = _make_modal_submit_interaction(
        modal_custom_id="btn-1:m",
        components=[
            {"components": [{"custom_id": "comment", "value": "looks good"}]},
        ],
        channel=channel_obj,
    )
    await client.on_interaction(submit)
    msg = bus.inbound.get_nowait()
    assert msg.metadata["interaction_type"] == "modal_submit"
    assert msg.metadata["custom_id"] == "btn-1"
    assert msg.metadata["form_values"] == {"comment": "looks good"}
    assert "Comment: looks good" in msg.content


@pytest.mark.asyncio
async def test_components_modal_button_after_restart_falls_back_to_click() -> None:
    bus = MessageBus()
    owner = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), bus)
    client = DiscordBotClient(owner, intents=discord.Intents.none())
    channel_obj = _FakeChannel(channel_id=456)
    owner._remember_channel(channel_obj)
    # Simulate post-restart: caches empty.
    assert not owner._modal_specs

    button_child = SimpleNamespace(custom_id="btn-1", label="Open")
    interaction = _make_component_interaction(
        custom_id="btn-1",
        component_type=2,
        channel=channel_obj,
        message=_component_message_double(components=[SimpleNamespace(children=[button_child])]),
    )
    await client.on_interaction(interaction)

    msg = bus.inbound.get_nowait()
    assert msg.metadata["interaction_type"] == "button"
    assert msg.content == "Open"


@pytest.mark.asyncio
async def test_components_modal_submit_unknown_cid_emits_expired_message() -> None:
    bus = MessageBus()
    owner = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), bus)
    client = DiscordBotClient(owner, intents=discord.Intents.none())
    channel_obj = _FakeChannel(channel_id=456)
    owner._remember_channel(channel_obj)

    submit = _make_modal_submit_interaction(
        modal_custom_id="ghost:m",
        components=[],
        channel=channel_obj,
    )
    await client.on_interaction(submit)

    assert bus.inbound_size == 0
    assert any("expired" in m["content"] for m in submit.response.messages)


@pytest.mark.asyncio
async def test_components_unauthorized_user_is_blocked() -> None:
    bus = MessageBus()
    owner = DiscordChannel(DiscordConfig(enabled=True, allow_from=["999"]), bus)  # not 123
    client = DiscordBotClient(owner, intents=discord.Intents.none())
    channel_obj = _FakeChannel(channel_id=456)
    owner._remember_channel(channel_obj)

    interaction = _make_component_interaction(
        custom_id="x",
        component_type=2,
        user_id=123,
        channel=channel_obj,
        message=_component_message_double(),
    )
    await client.on_interaction(interaction)

    assert bus.inbound_size == 0
    assert any("not allowed" in m["content"] for m in interaction.response.messages)


@pytest.mark.asyncio
async def test_components_disallowed_channel_is_blocked() -> None:
    bus = MessageBus()
    owner = DiscordChannel(
        DiscordConfig(enabled=True, allow_from=["*"], allow_channels=["999"]),
        bus,
    )
    client = DiscordBotClient(owner, intents=discord.Intents.none())
    channel_obj = _FakeChannel(channel_id=456)
    owner._remember_channel(channel_obj)

    interaction = _make_component_interaction(
        custom_id="x",
        component_type=2,
        channel=channel_obj,
        message=_component_message_double(),
    )
    await client.on_interaction(interaction)

    assert bus.inbound_size == 0
    assert any("not allowed" in m["content"] for m in interaction.response.messages)


def test_modal_spec_cache_evicts_oldest_at_cap() -> None:
    channel = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), MessageBus())
    from nanobot.channels.discord import MODAL_SPEC_CAP

    for i in range(MODAL_SPEC_CAP + 5):
        channel._record_modal_spec(f"btn-{i}", {"title": "t", "inputs": []})

    assert len(channel._modal_specs) == MODAL_SPEC_CAP
    assert "btn-0" not in channel._modal_specs
    assert "btn-4" not in channel._modal_specs
    assert f"btn-{MODAL_SPEC_CAP + 4}" in channel._modal_specs
    assert "btn-0:m" not in channel._modal_to_button


# ---------------------------------------------------------------------------
# Modal v2: select / radio / checkbox inputs (discord.py 2.6+ Label wrapping)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_modal_select_input_wraps_select_in_label() -> None:
    """A modal spec with a select input opens a Modal containing a Label
    whose inner component is a discord.ui.Select. Pins the v2 dispatch
    path that the type='select' branch in _build_modal must produce."""
    bus = MessageBus()
    owner = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), bus)
    client = DiscordBotClient(owner, intents=discord.Intents.none())
    channel_obj = _FakeChannel(channel_id=456)
    owner._remember_channel(channel_obj)

    target = _FakeChannel(channel_id=456)
    client.get_channel = lambda channel_id: target if channel_id == 456 else None  # type: ignore[method-assign]
    await client.send_outbound(
        OutboundMessage(
            channel="discord",
            chat_id="456",
            content="open",
            metadata={
                "_components": [
                    [
                        {
                            "type": "button",
                            "label": "Open",
                            "custom_id": "btn-sel",
                            "modal": {
                                "title": "Pick",
                                "inputs": [
                                    {
                                        "type": "select",
                                        "label": "Priority",
                                        "custom_id": "pri",
                                        "options": [
                                            {"label": "High", "value": "high"},
                                            {"label": "Low", "value": "low"},
                                        ],
                                    }
                                ],
                            },
                        }
                    ]
                ]
            },
        )
    )

    click = _make_component_interaction(
        custom_id="btn-sel",
        component_type=2,
        channel=channel_obj,
        message=_component_message_double(),
    )
    await client.on_interaction(click)

    modal = click.response.modal
    assert isinstance(modal, discord.ui.Modal)
    children = list(modal.children)
    assert len(children) == 1
    label = children[0]
    assert isinstance(label, discord.ui.Label)
    inner = getattr(label, "component", None)
    assert isinstance(inner, discord.ui.Select)
    assert inner.custom_id == "pri"
    assert [opt.value for opt in inner.options] == ["high", "low"]


@pytest.mark.asyncio
async def test_modal_submit_label_shape_with_list_values() -> None:
    """Modal submits from select/checkbox inputs nest leaves under a Label
    envelope (`component`, not `components`) and carry list `values`. The
    payload walker must flatten those and join with ', '."""
    bus = MessageBus()
    owner = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), bus)
    client = DiscordBotClient(owner, intents=discord.Intents.none())
    channel_obj = _FakeChannel(channel_id=456)
    owner._remember_channel(channel_obj)
    owner._record_modal_spec(
        "btn-sel",
        {
            "title": "Pick",
            "inputs": [
                {
                    "type": "select",
                    "label": "Priority",
                    "custom_id": "pri",
                    "options": [
                        {"label": "High", "value": "high"},
                        {"label": "Low", "value": "low"},
                    ],
                }
            ],
        },
    )

    submit = _make_modal_submit_interaction(
        modal_custom_id="btn-sel:m",
        components=[
            {"component": {"custom_id": "pri", "values": ["high", "low"]}},
        ],
        channel=channel_obj,
    )
    await client.on_interaction(submit)

    msg = bus.inbound.get_nowait()
    assert msg.metadata["interaction_type"] == "modal_submit"
    assert msg.metadata["custom_id"] == "btn-sel"
    assert msg.metadata["form_values"] == {"pri": "high, low"}
    assert "Priority: high, low" in msg.content


@pytest.mark.asyncio
async def test_modal_submit_legacy_actionrow_shape_still_works() -> None:
    """The walker must keep handling the pre-2.6 ActionRow envelope
    (`components` list nesting) so existing TextInput-only modals don't
    regress when the v2 dispatch ships."""
    bus = MessageBus()
    owner = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), bus)
    client = DiscordBotClient(owner, intents=discord.Intents.none())
    channel_obj = _FakeChannel(channel_id=456)
    owner._remember_channel(channel_obj)
    owner._record_modal_spec(
        "btn-old",
        {
            "title": "Notes",
            "inputs": [
                {"label": "Comment", "custom_id": "comment", "style": "paragraph"},
            ],
        },
    )

    submit = _make_modal_submit_interaction(
        modal_custom_id="btn-old:m",
        components=[
            {"components": [{"custom_id": "comment", "value": "looks good"}]},
        ],
        channel=channel_obj,
    )
    await client.on_interaction(submit)

    msg = bus.inbound.get_nowait()
    assert msg.metadata["interaction_type"] == "modal_submit"
    assert msg.metadata["custom_id"] == "btn-old"
    assert msg.metadata["form_values"] == {"comment": "looks good"}
    assert "Comment: looks good" in msg.content
