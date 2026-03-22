from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import discord
import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.discord import DiscordBotClient, DiscordChannel, DiscordConfig


# Minimal Discord client test double used to control startup/readiness behavior.
class _FakeDiscordClient:
    instances: list["_FakeDiscordClient"] = []
    start_error: Exception | None = None

    def __init__(self, owner, *, intents) -> None:
        self.owner = owner
        self.intents = intents
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
    def __init__(self, attachment_id: int, filename: str, *, size: int = 1, fail: bool = False) -> None:
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


class _FakeChannel:
    # Channel double that records outbound payloads and typing activity.
    def __init__(self, channel_id: int = 123) -> None:
        self.id = channel_id
        self.sent_payloads: list[dict] = []
        self.trigger_typing_calls = 0

    async def send(self, **kwargs) -> None:
        payload = dict(kwargs)
        if "file" in payload:
            payload["file_name"] = payload["file"].filename
            del payload["file"]
        self.sent_payloads.append(payload)

    def get_partial_message(self, message_id: int) -> _FakePartialMessage:
        return _FakePartialMessage(message_id)

    async def trigger_typing(self) -> None:
        self.trigger_typing_calls += 1


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
    guild_id: int | None = None,
    interaction_id: int = 999,
):
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id),
        channel_id=channel_id,
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
    message_id: int = 789,
    content: str = "hello",
    guild_id: int | None = None,
    mentions: list[object] | None = None,
    attachments: list[object] | None = None,
    reply_to: int | None = None,
):
    # Factory for incoming Discord message objects with optional guild/reply/attachments.
    guild = SimpleNamespace(id=guild_id) if guild_id is not None else None
    reference = SimpleNamespace(message_id=reply_to) if reply_to is not None else None
    return SimpleNamespace(
        author=SimpleNamespace(id=author_id, bot=author_bot),
        channel=_FakeChannel(channel_id),
        content=content,
        guild=guild,
        mentions=mentions or [],
        attachments=attachments or [],
        reference=reference,
        id=message_id,
    )


@pytest.mark.asyncio
async def test_start_returns_when_token_missing() -> None:
    # If no token is configured, startup should no-op and leave channel stopped.
    channel = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), MessageBus())

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

    def _boom(owner, *, intents):
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
async def test_on_message_ignores_bot_messages() -> None:
    # Incoming bot-authored messages must be ignored to prevent feedback loops.
    channel = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), MessageBus())
    handled: list[dict] = []
    channel._handle_message = lambda **kwargs: handled.append(kwargs)  # type: ignore[method-assign]

    await channel._on_message(_make_message(author_bot=True))

    assert handled == []


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

    await client.send_outbound(OutboundMessage(channel="discord", chat_id="123", content="hello"))

    assert client.get_channel(123) is None


@pytest.mark.asyncio
async def test_slash_new_forwards_when_user_is_allowlisted() -> None:
    channel = DiscordChannel(DiscordConfig(enabled=True, allow_from=["123"]), MessageBus())
    handled: list[dict] = []

    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = capture_handle  # type: ignore[method-assign]
    client = DiscordBotClient(channel, intents=discord.Intents.none())
    interaction = _make_interaction(user_id=123, channel_id=456, interaction_id=321)

    await client._handle_new_command(interaction)

    assert interaction.response.messages == [
        {"content": "Starting a new session...", "ephemeral": True}
    ]
    assert len(handled) == 1
    assert handled[0]["content"] == "/new"
    assert handled[0]["sender_id"] == "123"
    assert handled[0]["chat_id"] == "456"
    assert handled[0]["metadata"]["interaction_id"] == "321"
    assert handled[0]["metadata"]["is_slash_command"] is True


@pytest.mark.asyncio
async def test_slash_new_is_blocked_for_disallowed_user() -> None:
    channel = DiscordChannel(DiscordConfig(enabled=True, allow_from=["999"]), MessageBus())
    handled: list[dict] = []

    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = capture_handle  # type: ignore[method-assign]
    client = DiscordBotClient(channel, intents=discord.Intents.none())
    interaction = _make_interaction(user_id=123, channel_id=456)

    await client._handle_new_command(interaction)

    assert interaction.response.messages == [
        {"content": "You are not allowed to use this bot.", "ephemeral": True}
    ]
    assert handled == []


@pytest.mark.asyncio
async def test_slash_help_returns_command_list() -> None:
    owner = DiscordChannel(DiscordConfig(enabled=True, allow_from=["*"]), MessageBus())
    client = DiscordBotClient(owner, intents=discord.Intents.none())
    interaction = _make_interaction()
    interaction.command.qualified_name = "help"

    await client._handle_help_command(interaction)

    assert len(interaction.response.messages) == 1
    help_text = interaction.response.messages[0]["content"]
    assert "/new" in help_text
    assert "/help" in help_text
    assert "/restart" not in help_text


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
    typing_channel.trigger_typing = slow_typing

    await channel._start_typing(typing_channel)
    await start.wait()

    await channel.send(OutboundMessage(channel="discord", chat_id="123", content="hello"))
    release.set()
    await asyncio.sleep(0)

    assert channel._typing_tasks == {}
