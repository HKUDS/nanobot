from __future__ import annotations

import asyncio
from contextlib import suppress
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.channels import whatsapp as whatsapp_module
from nanobot.channels.whatsapp import (
    WhatsAppChannel,
    _legacy_bridge_config_fields,
    _NeonizeAPI,
    _ReactionTarget,
)


class _Proto:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def HasField(self, name: str) -> bool:  # noqa: N802 - protobuf compatibility
        return _is_set(getattr(self, name, None))

    def ListFields(self):  # noqa: N802 - protobuf compatibility
        return [
            (SimpleNamespace(name=name), value)
            for name, value in self.__dict__.items()
            if _is_set(value)
        ]


def _is_set(value) -> bool:
    if value is None:
        return False
    if isinstance(value, (str, bytes, list, tuple, dict, set)):
        return bool(value)
    return True


def _jid(user: str, server: str) -> _Proto:
    return _Proto(User=user, Server=server, IsEmpty=False)


def _event(
    *,
    message: _Proto,
    message_id: str = "m1",
    chat: _Proto | None = None,
    sender: _Proto | None = None,
    sender_alt: _Proto | None = None,
    is_group: bool = False,
    timestamp: int = 1,
    is_from_me: bool = False,
) -> _Proto:
    source = _Proto(
        Chat=chat or _jid("15551234567", "s.whatsapp.net"),
        Sender=sender,
        SenderAlt=sender_alt,
        IsGroup=is_group,
        IsFromMe=is_from_me,
    )
    return _Proto(
        Info=_Proto(ID=message_id, Timestamp=timestamp, MessageSource=source),
        Message=message,
    )


def _make_channel(config: dict | None = None) -> WhatsAppChannel:
    merged = {"enabled": True, "allowFrom": ["*"]}
    if config:
        merged.update(config)
    ch = WhatsAppChannel(merged, MagicMock())
    ch._started_at = 0
    return ch


def _patch_neonize_api(monkeypatch) -> None:
    chat_presence = SimpleNamespace(
        CHAT_PRESENCE_COMPOSING="composing",
        CHAT_PRESENCE_PAUSED="paused",
    )
    chat_presence_media = SimpleNamespace(CHAT_PRESENCE_MEDIA_TEXT="text")
    monkeypatch.setattr(
        whatsapp_module,
        "_NEONIZE_API",
        _NeonizeAPI(
            NewAClient=object,
            ConnectedEv=object(),
            DisconnectedEv=object(),
            MessageEv=object(),
            PairStatusEv=object(),
            build_jid=lambda user, server="s.whatsapp.net": (user, server),
            ChatPresence=chat_presence,
            ChatPresenceMedia=chat_presence_media,
        ),
    )


class _FakeLoginClient:
    def __init__(self) -> None:
        self.handlers = {}
        self.me = _Proto(JID=_jid("bot", "s.whatsapp.net"), LID=_jid("BOTLID", "lid"))
        self.stop = AsyncMock()

    def event(self, event_type):
        def register(func):
            self.handlers[event_type] = func
            return func

        return register

    def qr(self, func):
        self.qr_handler = func
        return func

    async def connect(self) -> None:
        await self.handlers[whatsapp_module._NEONIZE_API.ConnectedEv](self, _Proto())


class _FailingConnectLoginClient(_FakeLoginClient):
    async def connect(self) -> asyncio.Task[None]:
        async def fail() -> None:
            raise RuntimeError("dial failed")

        return asyncio.create_task(fail())


def test_default_config_has_no_bridge_fields() -> None:
    config = WhatsAppChannel.default_config()

    assert "bridgeUrl" not in config
    assert "bridgeToken" not in config
    assert config["databasePath"] == ""


def test_legacy_bridge_config_fields_are_detected() -> None:
    assert _legacy_bridge_config_fields({"bridgeUrl": "ws://localhost:3001"}) == ["bridgeUrl"]
    assert _legacy_bridge_config_fields({"bridgeToken": "secret"}) == ["bridgeToken"]


@pytest.mark.asyncio
async def test_login_succeeds_when_connected(monkeypatch) -> None:
    _patch_neonize_api(monkeypatch)
    client = _FakeLoginClient()
    ch = _make_channel()
    ch._new_client = MagicMock(return_value=client)

    assert await ch.login() is True
    assert ch._self_jids == {"bot@s.whatsapp.net", "bot", "BOTLID@lid", "BOTLID"}
    client.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_login_fails_when_connect_task_fails(monkeypatch) -> None:
    _patch_neonize_api(monkeypatch)
    client = _FailingConnectLoginClient()
    ch = _make_channel()
    ch._new_client = MagicMock(return_value=client)

    assert await ch.login() is False
    client.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_text_uses_neonize_send_message(monkeypatch) -> None:
    _patch_neonize_api(monkeypatch)
    client = SimpleNamespace(
        send_message=AsyncMock(),
        send_image=AsyncMock(),
        send_video=AsyncMock(),
        send_audio=AsyncMock(),
        send_document=AsyncMock(),
    )
    ch = _make_channel()
    ch._client = client
    ch._connected = True

    await ch.send(OutboundMessage(channel="whatsapp", chat_id="12345@s.whatsapp.net", content="hi"))

    client.send_message.assert_awaited_once_with(("12345", "s.whatsapp.net"), "hi")


@pytest.mark.asyncio
async def test_send_text_passes_metadata_mentions_to_neonize(monkeypatch) -> None:
    _patch_neonize_api(monkeypatch)
    client = SimpleNamespace(
        send_message=AsyncMock(),
        send_image=AsyncMock(),
        send_video=AsyncMock(),
        send_audio=AsyncMock(),
        send_document=AsyncMock(),
    )
    ch = _make_channel()
    ch._client = client
    ch._connected = True

    await ch.send(
        OutboundMessage(
            channel="whatsapp",
            chat_id="12345@s.whatsapp.net",
            content="hi",
            metadata={
                "mentions": [
                    "+15551234567@s.whatsapp.net",
                    {"jid": "15557654321@s.whatsapp.net"},
                    "not-a-number",
                ]
            },
        )
    )

    client.send_message.assert_awaited_once_with(
        ("12345", "s.whatsapp.net"),
        "hi",
        ghost_mentions="@15551234567 @15557654321",
        mentions_are_lids=False,
    )


@pytest.mark.asyncio
async def test_send_text_passes_lid_mentions_to_neonize(monkeypatch) -> None:
    _patch_neonize_api(monkeypatch)
    client = SimpleNamespace(send_message=AsyncMock())
    ch = _make_channel()
    ch._client = client
    ch._connected = True

    await ch.send(
        OutboundMessage(
            channel="whatsapp",
            chat_id="12345@s.whatsapp.net",
            content="hi",
            metadata={"mentioned_jids": ["123456789012345@lid"]},
        )
    )

    client.send_message.assert_awaited_once_with(
        ("12345", "s.whatsapp.net"),
        "hi",
        ghost_mentions="@123456789012345",
        mentions_are_lids=True,
    )


@pytest.mark.asyncio
async def test_inbound_message_starts_typing_and_reaction(monkeypatch) -> None:
    _patch_neonize_api(monkeypatch)
    client = SimpleNamespace(
        download_any=AsyncMock(),
        send_chat_presence=AsyncMock(),
        build_reaction=AsyncMock(return_value="reaction-message"),
        send_message=AsyncMock(),
    )
    ch = _make_channel({"reactEmoji": "👀"})
    ch._client = client
    ch._connected = True
    ch._handle_message = AsyncMock()

    await ch._handle_neonize_message(
        client,
        _event(
            message=_Proto(conversation="hello"),
            message_id="wamid.1",
            chat=_jid("120363000", "g.us"),
            sender=_jid("LID99", "lid"),
            sender_alt=_jid("15559998888", "s.whatsapp.net"),
            is_group=True,
        ),
    )
    await asyncio.sleep(0)

    client.send_chat_presence.assert_any_await(
        ("120363000", "g.us"),
        "composing",
        "text",
    )
    client.build_reaction.assert_awaited_once_with(
        ("120363000", "g.us"),
        ("15559998888", "s.whatsapp.net"),
        "wamid.1",
        "👀",
    )
    assert call(("120363000", "g.us"), "reaction-message") in client.send_message.await_args_list
    assert ch._reaction_targets["120363000@g.us"] == _ReactionTarget(
        "wamid.1",
        "15559998888@s.whatsapp.net",
    )

    ch._stop_typing("120363000@g.us")


@pytest.mark.asyncio
async def test_final_send_stops_typing_and_removes_reaction(monkeypatch) -> None:
    _patch_neonize_api(monkeypatch)
    client = SimpleNamespace(
        send_message=AsyncMock(),
        send_chat_presence=AsyncMock(),
        build_reaction=AsyncMock(return_value="remove-reaction"),
    )
    ch = _make_channel()
    ch._client = client
    ch._connected = True
    chat_id = "12345@s.whatsapp.net"
    typing_task = asyncio.create_task(asyncio.sleep(60))
    ch._typing_tasks[chat_id] = typing_task
    ch._reaction_targets[chat_id] = _ReactionTarget("wamid.1", "15551234567@s.whatsapp.net")

    await ch.send(OutboundMessage(channel="whatsapp", chat_id=chat_id, content="done"))
    await asyncio.sleep(0)

    assert typing_task.cancelled()
    assert chat_id not in ch._typing_tasks
    assert chat_id not in ch._reaction_targets
    client.send_chat_presence.assert_awaited_once_with(
        ("12345", "s.whatsapp.net"),
        "paused",
        "text",
    )
    client.build_reaction.assert_awaited_once_with(
        ("12345", "s.whatsapp.net"),
        ("15551234567", "s.whatsapp.net"),
        "wamid.1",
        "",
    )
    client.send_message.assert_has_awaits(
        [
            call(("12345", "s.whatsapp.net"), "remove-reaction"),
            call(("12345", "s.whatsapp.net"), "done"),
        ]
    )


@pytest.mark.asyncio
async def test_progress_send_keeps_typing_and_reaction(monkeypatch) -> None:
    _patch_neonize_api(monkeypatch)
    client = SimpleNamespace(
        send_message=AsyncMock(),
        send_chat_presence=AsyncMock(),
        build_reaction=AsyncMock(return_value="remove-reaction"),
    )
    ch = _make_channel()
    ch._client = client
    ch._connected = True
    chat_id = "12345@s.whatsapp.net"
    typing_task = asyncio.create_task(asyncio.sleep(60))
    ch._typing_tasks[chat_id] = typing_task
    ch._reaction_targets[chat_id] = _ReactionTarget("wamid.1", "15551234567@s.whatsapp.net")

    await ch.send(
        OutboundMessage(
            channel="whatsapp",
            chat_id=chat_id,
            content="working",
            metadata={"_progress": True},
        )
    )

    assert ch._typing_tasks[chat_id] is typing_task
    assert ch._reaction_targets[chat_id] == _ReactionTarget(
        "wamid.1",
        "15551234567@s.whatsapp.net",
    )
    client.send_chat_presence.assert_not_awaited()
    client.build_reaction.assert_not_awaited()
    client.send_message.assert_awaited_once_with(("12345", "s.whatsapp.net"), "working")

    typing_task.cancel()
    with suppress(asyncio.CancelledError):
        await typing_task


@pytest.mark.asyncio
async def test_send_media_dispatches_by_mimetype(monkeypatch) -> None:
    _patch_neonize_api(monkeypatch)
    client = SimpleNamespace(
        send_message=AsyncMock(),
        send_image=AsyncMock(),
        send_video=AsyncMock(),
        send_audio=AsyncMock(),
        send_document=AsyncMock(),
    )
    ch = _make_channel()
    ch._client = client
    ch._connected = True

    await ch.send(
        OutboundMessage(
            channel="whatsapp",
            chat_id="12345@s.whatsapp.net",
            content="",
            media=["photo.jpg", "clip.mp4", "voice.ogg", "report.pdf"],
        )
    )

    jid = ("12345", "s.whatsapp.net")
    client.send_image.assert_awaited_once_with(jid, "photo.jpg")
    client.send_video.assert_awaited_once_with(jid, "clip.mp4")
    client.send_audio.assert_awaited_once_with(jid, "voice.ogg")
    client.send_document.assert_awaited_once_with(
        jid,
        "report.pdf",
        filename="report.pdf",
        mimetype="application/pdf",
    )


@pytest.mark.asyncio
async def test_send_when_disconnected_raises() -> None:
    ch = _make_channel()

    with pytest.raises(RuntimeError, match="not connected"):
        await ch.send(OutboundMessage(channel="whatsapp", chat_id="123", content="hi"))


@pytest.mark.asyncio
async def test_group_policy_mention_skips_unmentioned_group_message() -> None:
    ch = _make_channel({"groupPolicy": "mention"})
    ch._self_jids = {"bot@s.whatsapp.net", "bot"}
    ch._handle_message = AsyncMock()

    await ch._handle_neonize_message(
        SimpleNamespace(download_any=AsyncMock()),
        _event(
            message=_Proto(conversation="hello group"),
            chat=_jid("120363000", "g.us"),
            sender=_jid("SENDERLID", "lid"),
            is_group=True,
        ),
    )

    ch._handle_message.assert_not_called()


@pytest.mark.asyncio
async def test_group_policy_mention_accepts_mention_and_prefers_phone_sender() -> None:
    ch = _make_channel({"groupPolicy": "mention"})
    ch._self_jids = {"bot@s.whatsapp.net", "bot"}
    ch._handle_message = AsyncMock()
    context = _Proto(mentionedJID=["bot@s.whatsapp.net"])
    message = _Proto(extendedTextMessage=_Proto(text="hello @bot", contextInfo=context))

    await ch._handle_neonize_message(
        SimpleNamespace(download_any=AsyncMock()),
        _event(
            message=message,
            chat=_jid("120363000", "g.us"),
            sender=_jid("LID99", "lid"),
            sender_alt=_jid("15559998888", "s.whatsapp.net"),
            is_group=True,
        ),
    )

    kwargs = ch._handle_message.await_args.kwargs
    assert kwargs["sender_id"] == "15559998888"
    assert kwargs["chat_id"] == "120363000@g.us"
    assert kwargs["metadata"]["lid"] == "LID99"
    assert kwargs["metadata"]["phone"] == "15559998888"


@pytest.mark.asyncio
async def test_group_policy_mention_accepts_reply_to_bot() -> None:
    ch = _make_channel({"groupPolicy": "mention"})
    ch._self_jids = {"bot@s.whatsapp.net", "bot"}
    ch._handle_message = AsyncMock()
    context = _Proto(participant="bot@s.whatsapp.net")
    message = _Proto(extendedTextMessage=_Proto(text="reply", contextInfo=context))

    await ch._handle_neonize_message(
        SimpleNamespace(download_any=AsyncMock()),
        _event(
            message=message,
            chat=_jid("120363000", "g.us"),
            sender=_jid("SENDERLID", "lid"),
            is_group=True,
        ),
    )

    kwargs = ch._handle_message.await_args.kwargs
    assert kwargs["metadata"]["is_reply_to_bot"] is True


@pytest.mark.asyncio
async def test_group_sender_id_uses_participant_not_group_jid() -> None:
    ch = WhatsAppChannel({"enabled": True, "allowFrom": ["SENDERLID"]}, MagicMock())
    ch._started_at = 0
    ch._handle_message = AsyncMock()

    await ch._handle_neonize_message(
        SimpleNamespace(download_any=AsyncMock()),
        _event(
            message=_Proto(conversation="hi"),
            chat=_jid("120363000", "g.us"),
            sender=_jid("SENDERLID", "lid"),
            is_group=True,
        ),
    )

    kwargs = ch._handle_message.await_args.kwargs
    assert kwargs["sender_id"] == "SENDERLID"
    assert kwargs["metadata"]["participant"] == "SENDERLID@lid"


@pytest.mark.asyncio
async def test_lid_to_phone_cache_resolves_lid_only_messages() -> None:
    ch = _make_channel()
    ch._handle_message = AsyncMock()

    await ch._handle_neonize_message(
        SimpleNamespace(download_any=AsyncMock()),
        _event(
            message=_Proto(conversation="first"),
            message_id="c1",
            chat=_jid("LID99", "lid"),
            sender=_jid("LID99", "lid"),
            sender_alt=_jid("5559999", "s.whatsapp.net"),
        ),
    )
    await ch._handle_neonize_message(
        SimpleNamespace(download_any=AsyncMock()),
        _event(
            message=_Proto(conversation="second"),
            message_id="c2",
            chat=_jid("LID99", "lid"),
            sender=_jid("LID99", "lid"),
        ),
    )

    assert ch._handle_message.await_args_list[1].kwargs["sender_id"] == "5559999"


def test_lid_mappings_from_config() -> None:
    ch = WhatsAppChannel(
        {"enabled": True, "lidMappings": {"123456789012345": "15551234567"}},
        MagicMock(),
    )

    assert ch._lid_to_phone == {"123456789012345": "15551234567"}


@pytest.mark.asyncio
async def test_image_media_is_downloaded_and_forwarded(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(whatsapp_module, "get_media_dir", lambda channel: tmp_path / channel)
    ch = _make_channel()
    ch._handle_message = AsyncMock()
    client = SimpleNamespace(download_any=AsyncMock())
    message = _Proto(
        imageMessage=_Proto(
            caption="look",
            mimetype="image/jpeg",
        )
    )

    await ch._handle_neonize_message(
        client,
        _event(message=message, sender_alt=_jid("15551234567", "s.whatsapp.net")),
    )

    client.download_any.assert_awaited_once()
    kwargs = ch._handle_message.await_args.kwargs
    assert kwargs["content"].startswith("look\n[image: ")
    assert len(kwargs["media"]) == 1
    assert kwargs["media"][0].endswith(".jpg")


@pytest.mark.asyncio
async def test_voice_message_transcribes_and_drops_media_when_successful(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(whatsapp_module, "get_media_dir", lambda channel: tmp_path / channel)
    ch = _make_channel()
    ch._handle_message = AsyncMock()
    ch.transcribe_audio = AsyncMock(return_value="Hello from audio")
    client = SimpleNamespace(download_any=AsyncMock())
    message = _Proto(audioMessage=_Proto(mimetype="audio/ogg", PTT=True))

    await ch._handle_neonize_message(
        client,
        _event(message=message, sender_alt=_jid("15551234567", "s.whatsapp.net")),
    )

    ch.transcribe_audio.assert_awaited_once()
    kwargs = ch._handle_message.await_args.kwargs
    assert kwargs["content"] == "Hello from audio"
    assert kwargs["media"] == []


@pytest.mark.asyncio
async def test_unauthorized_voice_message_does_not_download_or_transcribe(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(whatsapp_module, "get_media_dir", lambda channel: tmp_path / channel)
    ch = WhatsAppChannel({"enabled": True, "allowFrom": ["allowed"]}, MagicMock())
    ch._started_at = 0
    ch._handle_message = AsyncMock()
    ch.transcribe_audio = AsyncMock(return_value="blocked audio")
    client = SimpleNamespace(download_any=AsyncMock())

    await ch._handle_neonize_message(
        client,
        _event(
            message=_Proto(audioMessage=_Proto(mimetype="audio/ogg", PTT=True)),
            chat=_jid("blocked", "s.whatsapp.net"),
            sender=_jid("blocked", "s.whatsapp.net"),
        ),
    )

    client.download_any.assert_not_awaited()
    ch.transcribe_audio.assert_not_awaited()
    ch._handle_message.assert_awaited_once()
    kwargs = ch._handle_message.await_args.kwargs
    assert kwargs["sender_id"] == "blocked"
    assert kwargs["content"] == ""
    assert kwargs["media"] == []
    assert kwargs["is_dm"] is True


@pytest.mark.asyncio
async def test_unauthorized_dm_uses_base_pairing_flow(monkeypatch) -> None:
    _patch_neonize_api(monkeypatch)
    monkeypatch.setattr("nanobot.channels.base.generate_code", lambda _ch, _sid: "ABCD-EFGH")
    monkeypatch.setattr("nanobot.channels.base.is_approved", lambda _ch, _sid: False)
    client = SimpleNamespace(send_message=AsyncMock(), download_any=AsyncMock())
    ch = WhatsAppChannel({"enabled": True, "allowFrom": []}, MagicMock())
    ch._client = client
    ch._connected = True
    ch._started_at = 0

    await ch._handle_neonize_message(
        client,
        _event(
            message=_Proto(conversation="hello"),
            chat=_jid("blocked", "s.whatsapp.net"),
            sender=_jid("blocked", "s.whatsapp.net"),
        ),
    )

    client.download_any.assert_not_awaited()
    client.send_message.assert_awaited_once()
    assert client.send_message.await_args.args[0] == ("blocked", "s.whatsapp.net")
    assert "ABCD-EFGH" in client.send_message.await_args.args[1]


def test_reset_database_removes_sqlite_sidecars(tmp_path) -> None:
    db = tmp_path / "neonize.db"
    wal = tmp_path / "neonize.db-wal"
    shm = tmp_path / "neonize.db-shm"
    for path in (db, wal, shm):
        path.write_text("x", encoding="utf-8")

    WhatsAppChannel._reset_database(db)

    assert not db.exists()
    assert not wal.exists()
    assert not shm.exists()
