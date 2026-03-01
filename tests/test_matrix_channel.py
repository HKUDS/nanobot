import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

import nanobot.channels.matrix as matrix_module
from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.matrix import (
    MATRIX_HTML_FORMAT,
    TYPING_NOTICE_TIMEOUT_MS,
    MatrixChannel,
)
from nanobot.config.schema import MatrixConfig

_ROOM_SEND_UNSET = object()


class _DummyTask:
    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True

    def __await__(self):
        async def _done():
            return None

        return _done().__await__()


class _FakeAsyncClient:
    def __init__(self, homeserver, user, store_path, config) -> None:
        self.homeserver = homeserver
        self.user = user
        self.store_path = store_path
        self.config = config
        self.user_id: str | None = None
        self.access_token: str | None = None
        self.device_id: str | None = None
        self.load_store_called = False
        self.stop_sync_forever_called = False
        self.join_calls: list[str] = []
        self.callbacks: list[tuple[object, object]] = []
        self.response_callbacks: list[tuple[object, object]] = []
        self.rooms: dict[str, object] = {}
        self.room_send_calls: list[dict[str, object]] = []
        self.typing_calls: list[tuple[str, bool, int]] = []
        self.download_calls: list[dict[str, object]] = []
        self.upload_calls: list[dict[str, object]] = []
        self.download_response: object | None = None
        self.download_bytes: bytes = b"media"
        self.download_content_type: str = "application/octet-stream"
        self.download_filename: str | None = None
        self.upload_response: object | None = None
        self.content_repository_config_response: object = SimpleNamespace(upload_size=None)
        self.raise_on_send = False
        self.raise_on_typing = False
        self.raise_on_upload = False

    def add_event_callback(self, callback, event_type) -> None:
        self.callbacks.append((callback, event_type))

    def add_response_callback(self, callback, response_type) -> None:
        self.response_callbacks.append((callback, response_type))

    def load_store(self) -> None:
        self.load_store_called = True

    def stop_sync_forever(self) -> None:
        self.stop_sync_forever_called = True

    async def join(self, room_id: str) -> None:
        self.join_calls.append(room_id)

    async def room_send(
        self,
        room_id: str,
        message_type: str,
        content: dict[str, object],
        ignore_unverified_devices: object = _ROOM_SEND_UNSET,
    ) -> None:
        call: dict[str, object] = {
            "room_id": room_id,
            "message_type": message_type,
            "content": content,
        }
        if ignore_unverified_devices is not _ROOM_SEND_UNSET:
            call["ignore_unverified_devices"] = ignore_unverified_devices
        self.room_send_calls.append(call)
        if self.raise_on_send:
            raise RuntimeError("send failed")

    async def room_typing(
        self,
        room_id: str,
        typing_state: bool = True,
        timeout: int = 30_000,
    ) -> None:
        self.typing_calls.append((room_id, typing_state, timeout))
        if self.raise_on_typing:
            raise RuntimeError("typing failed")

    async def download(self, **kwargs):
        self.download_calls.append(kwargs)
        if self.download_response is not None:
            return self.download_response
        return matrix_module.MemoryDownloadResponse(
            body=self.download_bytes,
            content_type=self.download_content_type,
            filename=self.download_filename,
        )

    async def upload(
        self,
        data_provider,
        content_type: str | None = None,
        filename: str | None = None,
        filesize: int | None = None,
        encrypt: bool = False,
    ):
        if self.raise_on_upload:
            raise RuntimeError("upload failed")
        if isinstance(data_provider, (bytes, bytearray)):
            raise TypeError(
                f"data_provider type {type(data_provider)!r} is not of a usable type "
                "(Callable, IOBase)"
            )
        self.upload_calls.append(
            {
                "data_provider": data_provider,
                "content_type": content_type,
                "filename": filename,
                "filesize": filesize,
                "encrypt": encrypt,
            }
        )
        if self.upload_response is not None:
            return self.upload_response
        if encrypt:
            return (
                SimpleNamespace(content_uri="mxc://example.org/uploaded"),
                {
                    "v": "v2",
                    "iv": "iv",
                    "hashes": {"sha256": "hash"},
                    "key": {"alg": "A256CTR", "k": "key"},
                },
            )
        return SimpleNamespace(content_uri="mxc://example.org/uploaded"), None

    async def content_repository_config(self):
        return self.content_repository_config_response

    async def close(self) -> None:
        return None


def _make_config(**kwargs) -> MatrixConfig:
    return MatrixConfig(
        enabled=True,
        homeserver="https://matrix.org",
        access_token="token",
        user_id="@bot:matrix.org",
        **kwargs,
    )


@pytest.mark.asyncio
async def test_start_skips_load_store_when_device_id_missing(
    monkeypatch, tmp_path
) -> None:
    clients: list[_FakeAsyncClient] = []

    def _fake_client(*args, **kwargs) -> _FakeAsyncClient:
        client = _FakeAsyncClient(*args, **kwargs)
        clients.append(client)
        return client

    def _fake_create_task(coro):
        coro.close()
        return _DummyTask()

    monkeypatch.setattr("nanobot.channels.matrix.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "nanobot.channels.matrix.AsyncClientConfig",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr("nanobot.channels.matrix.AsyncClient", _fake_client)
    monkeypatch.setattr(
        "nanobot.channels.matrix.asyncio.create_task", _fake_create_task
    )

    channel = MatrixChannel(_make_config(device_id=""), MessageBus())
    await channel.start()

    assert len(clients) == 1
    assert clients[0].config.encryption_enabled is True
    assert clients[0].load_store_called is False
    assert len(clients[0].callbacks) == 3
    assert len(clients[0].response_callbacks) == 3

    await channel.stop()


@pytest.mark.asyncio
async def test_register_event_callbacks_uses_media_base_filter() -> None:
    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    channel._register_event_callbacks()

    assert len(client.callbacks) == 3
    assert client.callbacks[1][0] == channel._on_media_message
    assert client.callbacks[1][1] == matrix_module.MATRIX_MEDIA_EVENT_FILTER


def test_media_event_filter_does_not_match_text_events() -> None:
    assert not issubclass(matrix_module.RoomMessageText, matrix_module.MATRIX_MEDIA_EVENT_FILTER)


@pytest.mark.asyncio
async def test_start_disables_e2ee_when_configured(
    monkeypatch, tmp_path
) -> None:
    clients: list[_FakeAsyncClient] = []

    def _fake_client(*args, **kwargs) -> _FakeAsyncClient:
        client = _FakeAsyncClient(*args, **kwargs)
        clients.append(client)
        return client

    def _fake_create_task(coro):
        coro.close()
        return _DummyTask()

    monkeypatch.setattr("nanobot.channels.matrix.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "nanobot.channels.matrix.AsyncClientConfig",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr("nanobot.channels.matrix.AsyncClient", _fake_client)
    monkeypatch.setattr(
        "nanobot.channels.matrix.asyncio.create_task", _fake_create_task
    )

    channel = MatrixChannel(_make_config(device_id="", e2ee_enabled=False), MessageBus())
    await channel.start()

    assert len(clients) == 1
    assert clients[0].config.encryption_enabled is False

    await channel.stop()


@pytest.mark.asyncio
async def test_stop_stops_sync_forever_before_close(monkeypatch) -> None:
    channel = MatrixChannel(_make_config(device_id="DEVICE"), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    task = _DummyTask()

    channel.client = client
    channel._sync_task = task
    channel._running = True

    await channel.stop()

    assert channel._running is False
    assert client.stop_sync_forever_called is True
    assert task.cancelled is False


@pytest.mark.asyncio
async def test_room_invite_joins_when_allow_list_is_empty() -> None:
    channel = MatrixChannel(_make_config(allow_from=[]), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    room = SimpleNamespace(room_id="!room:matrix.org")
    event = SimpleNamespace(sender="@alice:matrix.org")

    await channel._on_room_invite(room, event)

    assert client.join_calls == ["!room:matrix.org"]


@pytest.mark.asyncio
async def test_room_invite_respects_allow_list_when_configured() -> None:
    channel = MatrixChannel(_make_config(allow_from=["@bob:matrix.org"]), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    room = SimpleNamespace(room_id="!room:matrix.org")
    event = SimpleNamespace(sender="@alice:matrix.org")

    await channel._on_room_invite(room, event)

    assert client.join_calls == []


@pytest.mark.asyncio
async def test_on_message_sets_typing_for_allowed_sender() -> None:
    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    handled: list[str] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs["sender_id"])

    channel._handle_message = _fake_handle_message  # type: ignore[method-assign]

    room = SimpleNamespace(room_id="!room:matrix.org", display_name="Test room")
    event = SimpleNamespace(sender="@alice:matrix.org", body="Hello", source={})

    await channel._on_message(room, event)

    assert handled == ["@alice:matrix.org"]
    assert client.typing_calls == [
        ("!room:matrix.org", True, TYPING_NOTICE_TIMEOUT_MS),
    ]


@pytest.mark.asyncio
async def test_typing_keepalive_refreshes_periodically(monkeypatch) -> None:
    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client
    channel._running = True

    monkeypatch.setattr(matrix_module, "TYPING_KEEPALIVE_INTERVAL_MS", 10)

    await channel._start_typing_keepalive("!room:matrix.org")
    await asyncio.sleep(0.03)
    await channel._stop_typing_keepalive("!room:matrix.org", clear_typing=True)

    true_updates = [call for call in client.typing_calls if call[1] is True]
    assert len(true_updates) >= 2
    assert client.typing_calls[-1] == ("!room:matrix.org", False, TYPING_NOTICE_TIMEOUT_MS)


@pytest.mark.asyncio
async def test_on_message_skips_typing_for_self_message() -> None:
    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    room = SimpleNamespace(room_id="!room:matrix.org", display_name="Test room")
    event = SimpleNamespace(sender="@bot:matrix.org", body="Hello", source={})

    await channel._on_message(room, event)

    assert client.typing_calls == []


@pytest.mark.asyncio
async def test_on_message_skips_typing_for_denied_sender() -> None:
    channel = MatrixChannel(_make_config(allow_from=["@bob:matrix.org"]), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    handled: list[str] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs["sender_id"])

    channel._handle_message = _fake_handle_message  # type: ignore[method-assign]

    room = SimpleNamespace(room_id="!room:matrix.org", display_name="Test room")
    event = SimpleNamespace(sender="@alice:matrix.org", body="Hello", source={})

    await channel._on_message(room, event)

    assert handled == []
    assert client.typing_calls == []


@pytest.mark.asyncio
async def test_on_message_mention_policy_requires_mx_mentions() -> None:
    channel = MatrixChannel(_make_config(group_policy="mention"), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    handled: list[str] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs["sender_id"])

    channel._handle_message = _fake_handle_message  # type: ignore[method-assign]

    room = SimpleNamespace(room_id="!room:matrix.org", display_name="Test room", member_count=3)
    event = SimpleNamespace(sender="@alice:matrix.org", body="Hello", source={"content": {}})

    await channel._on_message(room, event)

    assert handled == []
    assert client.typing_calls == []


@pytest.mark.asyncio
async def test_on_message_mention_policy_accepts_bot_user_mentions() -> None:
    channel = MatrixChannel(_make_config(group_policy="mention"), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    handled: list[str] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs["sender_id"])

    channel._handle_message = _fake_handle_message  # type: ignore[method-assign]

    room = SimpleNamespace(room_id="!room:matrix.org", display_name="Test room", member_count=3)
    event = SimpleNamespace(
        sender="@alice:matrix.org",
        body="Hello",
        source={"content": {"m.mentions": {"user_ids": ["@bot:matrix.org"]}}},
    )

    await channel._on_message(room, event)

    assert handled == ["@alice:matrix.org"]
    assert client.typing_calls == [("!room:matrix.org", True, TYPING_NOTICE_TIMEOUT_MS)]


@pytest.mark.asyncio
async def test_on_message_mention_policy_allows_direct_room_without_mentions() -> None:
    channel = MatrixChannel(_make_config(group_policy="mention"), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    handled: list[str] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs["sender_id"])

    channel._handle_message = _fake_handle_message  # type: ignore[method-assign]

    room = SimpleNamespace(room_id="!dm:matrix.org", display_name="DM", member_count=2)
    event = SimpleNamespace(sender="@alice:matrix.org", body="Hello", source={"content": {}})

    await channel._on_message(room, event)

    assert handled == ["@alice:matrix.org"]
    assert client.typing_calls == [("!dm:matrix.org", True, TYPING_NOTICE_TIMEOUT_MS)]


@pytest.mark.asyncio
async def test_on_message_allowlist_policy_requires_room_id() -> None:
    channel = MatrixChannel(
        _make_config(group_policy="allowlist", group_allow_from=["!allowed:matrix.org"]),
        MessageBus(),
    )
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    handled: list[str] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs["chat_id"])

    channel._handle_message = _fake_handle_message  # type: ignore[method-assign]

    denied_room = SimpleNamespace(room_id="!denied:matrix.org", display_name="Denied", member_count=3)
    event = SimpleNamespace(sender="@alice:matrix.org", body="Hello", source={"content": {}})
    await channel._on_message(denied_room, event)

    allowed_room = SimpleNamespace(
        room_id="!allowed:matrix.org",
        display_name="Allowed",
        member_count=3,
    )
    await channel._on_message(allowed_room, event)

    assert handled == ["!allowed:matrix.org"]
    assert client.typing_calls == [("!allowed:matrix.org", True, TYPING_NOTICE_TIMEOUT_MS)]


@pytest.mark.asyncio
async def test_on_message_room_mention_requires_opt_in() -> None:
    channel = MatrixChannel(_make_config(group_policy="mention"), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    handled: list[str] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs["sender_id"])

    channel._handle_message = _fake_handle_message  # type: ignore[method-assign]

    room = SimpleNamespace(room_id="!room:matrix.org", display_name="Test room", member_count=3)
    room_mention_event = SimpleNamespace(
        sender="@alice:matrix.org",
        body="Hello everyone",
        source={"content": {"m.mentions": {"room": True}}},
    )

    await channel._on_message(room, room_mention_event)
    assert handled == []
    assert client.typing_calls == []

    channel.config.allow_room_mentions = True
    await channel._on_message(room, room_mention_event)
    assert handled == ["@alice:matrix.org"]
    assert client.typing_calls == [("!room:matrix.org", True, TYPING_NOTICE_TIMEOUT_MS)]


@pytest.mark.asyncio
async def test_on_message_sets_thread_metadata_when_threaded_event() -> None:
    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    handled: list[dict[str, object]] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = _fake_handle_message  # type: ignore[method-assign]

    room = SimpleNamespace(room_id="!room:matrix.org", display_name="Test room", member_count=3)
    event = SimpleNamespace(
        sender="@alice:matrix.org",
        body="Hello",
        event_id="$reply1",
        source={
            "content": {
                "m.relates_to": {
                    "rel_type": "m.thread",
                    "event_id": "$root1",
                }
            }
        },
    )

    await channel._on_message(room, event)

    assert len(handled) == 1
    metadata = handled[0]["metadata"]
    assert metadata["thread_root_event_id"] == "$root1"
    assert metadata["thread_reply_to_event_id"] == "$reply1"
    assert metadata["event_id"] == "$reply1"


@pytest.mark.asyncio
async def test_on_media_message_downloads_attachment_and_sets_metadata(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr("nanobot.channels.matrix.get_data_dir", lambda: tmp_path)

    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    client.download_bytes = b"image"
    channel.client = client

    handled: list[dict[str, object]] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = _fake_handle_message  # type: ignore[method-assign]

    room = SimpleNamespace(room_id="!room:matrix.org", display_name="Test room", member_count=2)
    event = SimpleNamespace(
        sender="@alice:matrix.org",
        body="photo.png",
        url="mxc://example.org/mediaid",
        event_id="$event1",
        source={
            "content": {
                "msgtype": "m.image",
                "info": {"mimetype": "image/png", "size": 5},
            }
        },
    )

    await channel._on_media_message(room, event)

    assert len(client.download_calls) == 1
    assert len(handled) == 1
    assert client.typing_calls == [("!room:matrix.org", True, TYPING_NOTICE_TIMEOUT_MS)]

    media_paths = handled[0]["media"]
    assert isinstance(media_paths, list) and len(media_paths) == 1
    media_path = Path(media_paths[0])
    assert media_path.is_file()
    assert media_path.read_bytes() == b"image"

    metadata = handled[0]["metadata"]
    attachments = metadata["attachments"]
    assert isinstance(attachments, list) and len(attachments) == 1
    assert attachments[0]["type"] == "image"
    assert attachments[0]["mxc_url"] == "mxc://example.org/mediaid"
    assert attachments[0]["path"] == str(media_path)
    assert "[attachment: " in handled[0]["content"]


@pytest.mark.asyncio
async def test_on_media_message_sets_thread_metadata_when_threaded_event(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr("nanobot.channels.matrix.get_data_dir", lambda: tmp_path)

    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    client.download_bytes = b"image"
    channel.client = client

    handled: list[dict[str, object]] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = _fake_handle_message  # type: ignore[method-assign]

    room = SimpleNamespace(room_id="!room:matrix.org", display_name="Test room", member_count=2)
    event = SimpleNamespace(
        sender="@alice:matrix.org",
        body="photo.png",
        url="mxc://example.org/mediaid",
        event_id="$event1",
        source={
            "content": {
                "msgtype": "m.image",
                "info": {"mimetype": "image/png", "size": 5},
                "m.relates_to": {
                    "rel_type": "m.thread",
                    "event_id": "$root1",
                },
            }
        },
    )

    await channel._on_media_message(room, event)

    assert len(handled) == 1
    metadata = handled[0]["metadata"]
    assert metadata["thread_root_event_id"] == "$root1"
    assert metadata["thread_reply_to_event_id"] == "$event1"
    assert metadata["event_id"] == "$event1"


@pytest.mark.asyncio
async def test_on_media_message_respects_declared_size_limit(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr("nanobot.channels.matrix.get_data_dir", lambda: tmp_path)

    channel = MatrixChannel(_make_config(max_media_bytes=3), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    handled: list[dict[str, object]] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = _fake_handle_message  # type: ignore[method-assign]

    room = SimpleNamespace(room_id="!room:matrix.org", display_name="Test room", member_count=2)
    event = SimpleNamespace(
        sender="@alice:matrix.org",
        body="large.bin",
        url="mxc://example.org/large",
        event_id="$event2",
        source={"content": {"msgtype": "m.file", "info": {"size": 10}}},
    )

    await channel._on_media_message(room, event)

    assert client.download_calls == []
    assert len(handled) == 1
    assert handled[0]["media"] == []
    assert handled[0]["metadata"]["attachments"] == []
    assert "[attachment: large.bin - too large]" in handled[0]["content"]


@pytest.mark.asyncio
async def test_on_media_message_uses_server_limit_when_smaller_than_local_limit(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr("nanobot.channels.matrix.get_data_dir", lambda: tmp_path)

    channel = MatrixChannel(_make_config(max_media_bytes=10), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    client.content_repository_config_response = SimpleNamespace(upload_size=3)
    channel.client = client

    handled: list[dict[str, object]] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = _fake_handle_message  # type: ignore[method-assign]

    room = SimpleNamespace(room_id="!room:matrix.org", display_name="Test room", member_count=2)
    event = SimpleNamespace(
        sender="@alice:matrix.org",
        body="large.bin",
        url="mxc://example.org/large",
        event_id="$event2_server",
        source={"content": {"msgtype": "m.file", "info": {"size": 5}}},
    )

    await channel._on_media_message(room, event)

    assert client.download_calls == []
    assert len(handled) == 1
    assert handled[0]["media"] == []
    assert handled[0]["metadata"]["attachments"] == []
    assert "[attachment: large.bin - too large]" in handled[0]["content"]


@pytest.mark.asyncio
async def test_on_media_message_handles_download_error(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("nanobot.channels.matrix.get_data_dir", lambda: tmp_path)

    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    client.download_response = matrix_module.DownloadError("download failed")
    channel.client = client

    handled: list[dict[str, object]] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = _fake_handle_message  # type: ignore[method-assign]

    room = SimpleNamespace(room_id="!room:matrix.org", display_name="Test room", member_count=2)
    event = SimpleNamespace(
        sender="@alice:matrix.org",
        body="photo.png",
        url="mxc://example.org/mediaid",
        event_id="$event3",
        source={"content": {"msgtype": "m.image"}},
    )

    await channel._on_media_message(room, event)

    assert len(client.download_calls) == 1
    assert len(handled) == 1
    assert handled[0]["media"] == []
    assert handled[0]["metadata"]["attachments"] == []
    assert "[attachment: photo.png - download failed]" in handled[0]["content"]


@pytest.mark.asyncio
async def test_on_media_message_decrypts_encrypted_media(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("nanobot.channels.matrix.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        matrix_module,
        "decrypt_attachment",
        lambda ciphertext, key, sha256, iv: b"plain",
    )

    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    client.download_bytes = b"cipher"
    channel.client = client

    handled: list[dict[str, object]] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = _fake_handle_message  # type: ignore[method-assign]

    room = SimpleNamespace(room_id="!room:matrix.org", display_name="Test room", member_count=2)
    event = SimpleNamespace(
        sender="@alice:matrix.org",
        body="secret.txt",
        url="mxc://example.org/encrypted",
        event_id="$event4",
        key={"k": "key"},
        hashes={"sha256": "hash"},
        iv="iv",
        source={"content": {"msgtype": "m.file", "info": {"size": 6}}},
    )

    await channel._on_media_message(room, event)

    assert len(handled) == 1
    media_path = Path(handled[0]["media"][0])
    assert media_path.read_bytes() == b"plain"
    attachment = handled[0]["metadata"]["attachments"][0]
    assert attachment["encrypted"] is True
    assert attachment["size_bytes"] == 5


@pytest.mark.asyncio
async def test_on_media_message_handles_decrypt_error(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("nanobot.channels.matrix.get_data_dir", lambda: tmp_path)

    def _raise(*args, **kwargs):
        raise matrix_module.EncryptionError("boom")

    monkeypatch.setattr(matrix_module, "decrypt_attachment", _raise)

    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    client.download_bytes = b"cipher"
    channel.client = client

    handled: list[dict[str, object]] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = _fake_handle_message  # type: ignore[method-assign]

    room = SimpleNamespace(room_id="!room:matrix.org", display_name="Test room", member_count=2)
    event = SimpleNamespace(
        sender="@alice:matrix.org",
        body="secret.txt",
        url="mxc://example.org/encrypted",
        event_id="$event5",
        key={"k": "key"},
        hashes={"sha256": "hash"},
        iv="iv",
        source={"content": {"msgtype": "m.file"}},
    )

    await channel._on_media_message(room, event)

    assert len(handled) == 1
    assert handled[0]["media"] == []
    assert handled[0]["metadata"]["attachments"] == []
    assert "[attachment: secret.txt - download failed]" in handled[0]["content"]


@pytest.mark.asyncio
async def test_send_clears_typing_after_send() -> None:
    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    await channel.send(
        OutboundMessage(channel="matrix", chat_id="!room:matrix.org", content="Hi")
    )

    assert len(client.room_send_calls) == 1
    assert client.room_send_calls[0]["content"] == {
        "msgtype": "m.text",
        "body": "Hi",
        "m.mentions": {},
    }
    assert client.room_send_calls[0]["ignore_unverified_devices"] is True
    assert client.typing_calls[-1] == ("!room:matrix.org", False, TYPING_NOTICE_TIMEOUT_MS)


@pytest.mark.asyncio
async def test_send_uploads_media_and_sends_file_event(tmp_path) -> None:
    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    file_path = tmp_path / "test.txt"
    file_path.write_text("hello", encoding="utf-8")

    await channel.send(
        OutboundMessage(
            channel="matrix",
            chat_id="!room:matrix.org",
            content="Please review.",
            media=[str(file_path)],
        )
    )

    assert len(client.upload_calls) == 1
    assert not isinstance(client.upload_calls[0]["data_provider"], (bytes, bytearray))
    assert hasattr(client.upload_calls[0]["data_provider"], "read")
    assert client.upload_calls[0]["filename"] == "test.txt"
    assert client.upload_calls[0]["filesize"] == 5
    assert len(client.room_send_calls) == 2
    assert client.room_send_calls[0]["content"]["msgtype"] == "m.file"
    assert client.room_send_calls[0]["content"]["url"] == "mxc://example.org/uploaded"
    assert client.room_send_calls[1]["content"]["body"] == "Please review."


@pytest.mark.asyncio
async def test_send_adds_thread_relates_to_for_thread_metadata() -> None:
    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    metadata = {
        "thread_root_event_id": "$root1",
        "thread_reply_to_event_id": "$reply1",
    }
    await channel.send(
        OutboundMessage(
            channel="matrix",
            chat_id="!room:matrix.org",
            content="Hi",
            metadata=metadata,
        )
    )

    content = client.room_send_calls[0]["content"]
    assert content["m.relates_to"] == {
        "rel_type": "m.thread",
        "event_id": "$root1",
        "m.in_reply_to": {"event_id": "$reply1"},
        "is_falling_back": True,
    }


@pytest.mark.asyncio
async def test_send_uses_encrypted_media_payload_in_encrypted_room(tmp_path) -> None:
    channel = MatrixChannel(_make_config(e2ee_enabled=True), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    client.rooms["!encrypted:matrix.org"] = SimpleNamespace(encrypted=True)
    channel.client = client

    file_path = tmp_path / "secret.txt"
    file_path.write_text("topsecret", encoding="utf-8")

    await channel.send(
        OutboundMessage(
            channel="matrix",
            chat_id="!encrypted:matrix.org",
            content="",
            media=[str(file_path)],
        )
    )

    assert len(client.upload_calls) == 1
    assert client.upload_calls[0]["encrypt"] is True
    assert len(client.room_send_calls) == 1
    content = client.room_send_calls[0]["content"]
    assert content["msgtype"] == "m.file"
    assert "file" in content
    assert "url" not in content
    assert content["file"]["url"] == "mxc://example.org/uploaded"
    assert content["file"]["hashes"]["sha256"] == "hash"


@pytest.mark.asyncio
async def test_send_does_not_parse_attachment_marker_without_media(tmp_path) -> None:
    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    missing_path = tmp_path / "missing.txt"
    await channel.send(
        OutboundMessage(
            channel="matrix",
            chat_id="!room:matrix.org",
            content=f"[attachment: {missing_path}]",
        )
    )

    assert client.upload_calls == []
    assert len(client.room_send_calls) == 1
    assert client.room_send_calls[0]["content"]["body"] == f"[attachment: {missing_path}]"


@pytest.mark.asyncio
async def test_send_passes_thread_relates_to_to_attachment_upload(monkeypatch) -> None:
    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client
    channel._server_upload_limit_checked = True
    channel._server_upload_limit_bytes = None

    captured: dict[str, object] = {}

    async def _fake_upload_and_send_attachment(
        *,
        room_id: str,
        path: Path,
        limit_bytes: int,
        relates_to: dict[str, object] | None = None,
    ) -> str | None:
        captured["relates_to"] = relates_to
        return None

    monkeypatch.setattr(channel, "_upload_and_send_attachment", _fake_upload_and_send_attachment)

    metadata = {
        "thread_root_event_id": "$root1",
        "thread_reply_to_event_id": "$reply1",
    }
    await channel.send(
        OutboundMessage(
            channel="matrix",
            chat_id="!room:matrix.org",
            content="Hi",
            media=["/tmp/fake.txt"],
            metadata=metadata,
        )
    )

    assert captured["relates_to"] == {
        "rel_type": "m.thread",
        "event_id": "$root1",
        "m.in_reply_to": {"event_id": "$reply1"},
        "is_falling_back": True,
    }


@pytest.mark.asyncio
async def test_send_workspace_restriction_blocks_external_attachment(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    file_path = tmp_path / "external.txt"
    file_path.write_text("outside", encoding="utf-8")

    channel = MatrixChannel(
        _make_config(),
        MessageBus(),
        restrict_to_workspace=True,
        workspace=workspace,
    )
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    await channel.send(
        OutboundMessage(
            channel="matrix",
            chat_id="!room:matrix.org",
            content="",
            media=[str(file_path)],
        )
    )

    assert client.upload_calls == []
    assert len(client.room_send_calls) == 1
    assert client.room_send_calls[0]["content"]["body"] == "[attachment: external.txt - upload failed]"


@pytest.mark.asyncio
async def test_send_handles_upload_exception_and_reports_failure(tmp_path) -> None:
    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    client.raise_on_upload = True
    channel.client = client

    file_path = tmp_path / "broken.txt"
    file_path.write_text("hello", encoding="utf-8")

    await channel.send(
        OutboundMessage(
            channel="matrix",
            chat_id="!room:matrix.org",
            content="Please review.",
            media=[str(file_path)],
        )
    )

    assert len(client.upload_calls) == 0
    assert len(client.room_send_calls) == 1
    assert (
        client.room_send_calls[0]["content"]["body"]
        == "Please review.\n[attachment: broken.txt - upload failed]"
    )


@pytest.mark.asyncio
async def test_send_uses_server_upload_limit_when_smaller_than_local_limit(tmp_path) -> None:
    channel = MatrixChannel(_make_config(max_media_bytes=10), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    client.content_repository_config_response = SimpleNamespace(upload_size=3)
    channel.client = client

    file_path = tmp_path / "tiny.txt"
    file_path.write_text("hello", encoding="utf-8")

    await channel.send(
        OutboundMessage(
            channel="matrix",
            chat_id="!room:matrix.org",
            content="",
            media=[str(file_path)],
        )
    )

    assert client.upload_calls == []
    assert len(client.room_send_calls) == 1
    assert client.room_send_calls[0]["content"]["body"] == "[attachment: tiny.txt - too large]"


@pytest.mark.asyncio
async def test_send_blocks_all_outbound_media_when_limit_is_zero(tmp_path) -> None:
    channel = MatrixChannel(_make_config(max_media_bytes=0), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    file_path = tmp_path / "empty.txt"
    file_path.write_bytes(b"")

    await channel.send(
        OutboundMessage(
            channel="matrix",
            chat_id="!room:matrix.org",
            content="",
            media=[str(file_path)],
        )
    )

    assert client.upload_calls == []
    assert len(client.room_send_calls) == 1
    assert client.room_send_calls[0]["content"]["body"] == "[attachment: empty.txt - too large]"


@pytest.mark.asyncio
async def test_send_omits_ignore_unverified_devices_when_e2ee_disabled() -> None:
    channel = MatrixChannel(_make_config(e2ee_enabled=False), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    await channel.send(
        OutboundMessage(channel="matrix", chat_id="!room:matrix.org", content="Hi")
    )

    assert len(client.room_send_calls) == 1
    assert "ignore_unverified_devices" not in client.room_send_calls[0]


@pytest.mark.asyncio
async def test_send_stops_typing_keepalive_task() -> None:
    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client
    channel._running = True

    await channel._start_typing_keepalive("!room:matrix.org")
    assert "!room:matrix.org" in channel._typing_tasks

    await channel.send(
        OutboundMessage(channel="matrix", chat_id="!room:matrix.org", content="Hi")
    )

    assert "!room:matrix.org" not in channel._typing_tasks
    assert client.typing_calls[-1] == ("!room:matrix.org", False, TYPING_NOTICE_TIMEOUT_MS)


@pytest.mark.asyncio
async def test_send_progress_keeps_typing_keepalive_running() -> None:
    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client
    channel._running = True

    await channel._start_typing_keepalive("!room:matrix.org")
    assert "!room:matrix.org" in channel._typing_tasks

    await channel.send(
        OutboundMessage(
            channel="matrix",
            chat_id="!room:matrix.org",
            content="working...",
            metadata={"_progress": True, "_progress_kind": "reasoning"},
        )
    )

    assert "!room:matrix.org" in channel._typing_tasks
    assert client.typing_calls[-1] == ("!room:matrix.org", True, TYPING_NOTICE_TIMEOUT_MS)


@pytest.mark.asyncio
async def test_send_clears_typing_when_send_fails() -> None:
    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    client.raise_on_send = True
    channel.client = client

    with pytest.raises(RuntimeError, match="send failed"):
        await channel.send(
            OutboundMessage(channel="matrix", chat_id="!room:matrix.org", content="Hi")
        )

    assert client.typing_calls[-1] == ("!room:matrix.org", False, TYPING_NOTICE_TIMEOUT_MS)


@pytest.mark.asyncio
async def test_send_adds_formatted_body_for_markdown() -> None:
    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    markdown_text = "# Headline\n\n- [x] done\n\n| A | B |\n| - | - |\n| 1 | 2 |"
    await channel.send(
        OutboundMessage(channel="matrix", chat_id="!room:matrix.org", content=markdown_text)
    )

    content = client.room_send_calls[0]["content"]
    assert content["msgtype"] == "m.text"
    assert content["body"] == markdown_text
    assert content["m.mentions"] == {}
    assert content["format"] == MATRIX_HTML_FORMAT
    assert "<h1>Headline</h1>" in str(content["formatted_body"])
    assert "<table>" in str(content["formatted_body"])
    assert "<li>[x] done</li>" in str(content["formatted_body"])


@pytest.mark.asyncio
async def test_send_adds_formatted_body_for_inline_url_superscript_subscript() -> None:
    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    markdown_text = "Visit https://example.com and x^2^ plus H~2~O."
    await channel.send(
        OutboundMessage(channel="matrix", chat_id="!room:matrix.org", content=markdown_text)
    )

    content = client.room_send_calls[0]["content"]
    assert content["msgtype"] == "m.text"
    assert content["body"] == markdown_text
    assert content["m.mentions"] == {}
    assert content["format"] == MATRIX_HTML_FORMAT
    assert '<a href="https://example.com" rel="noopener noreferrer">' in str(
        content["formatted_body"]
    )
    assert "<sup>2</sup>" in str(content["formatted_body"])
    assert "<sub>2</sub>" in str(content["formatted_body"])


@pytest.mark.asyncio
async def test_send_sanitizes_disallowed_link_scheme() -> None:
    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    markdown_text = "[click](javascript:alert(1))"
    await channel.send(
        OutboundMessage(channel="matrix", chat_id="!room:matrix.org", content=markdown_text)
    )

    formatted_body = str(client.room_send_calls[0]["content"]["formatted_body"])
    assert "javascript:" not in formatted_body
    assert "<a" in formatted_body
    assert "href=" not in formatted_body


def test_matrix_html_cleaner_strips_event_handlers_and_script_tags() -> None:
    dirty_html = '<a href="https://example.com" onclick="evil()">x</a><script>alert(1)</script>'
    cleaned_html = matrix_module.MATRIX_HTML_CLEANER.clean(dirty_html)

    assert "<script" not in cleaned_html
    assert "onclick=" not in cleaned_html
    assert '<a href="https://example.com"' in cleaned_html


@pytest.mark.asyncio
async def test_send_keeps_only_mxc_image_sources() -> None:
    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    markdown_text = "![ok](mxc://example.org/mediaid) ![no](https://example.com/a.png)"
    await channel.send(
        OutboundMessage(channel="matrix", chat_id="!room:matrix.org", content=markdown_text)
    )

    formatted_body = str(client.room_send_calls[0]["content"]["formatted_body"])
    assert 'src="mxc://example.org/mediaid"' in formatted_body
    assert 'src="https://example.com/a.png"' not in formatted_body


@pytest.mark.asyncio
async def test_send_falls_back_to_plaintext_when_markdown_render_fails(monkeypatch) -> None:
    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    def _raise(text: str) -> str:
        raise RuntimeError("boom")

    monkeypatch.setattr(matrix_module, "MATRIX_MARKDOWN", _raise)
    markdown_text = "# Headline"
    await channel.send(
        OutboundMessage(channel="matrix", chat_id="!room:matrix.org", content=markdown_text)
    )

    content = client.room_send_calls[0]["content"]
    assert content == {"msgtype": "m.text", "body": markdown_text, "m.mentions": {}}


@pytest.mark.asyncio
async def test_send_keeps_plaintext_only_for_plain_text() -> None:
    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    text = "just a normal sentence without markdown markers"
    await channel.send(
        OutboundMessage(channel="matrix", chat_id="!room:matrix.org", content=text)
    )

    assert client.room_send_calls[0]["content"] == {
        "msgtype": "m.text",
        "body": text,
        "m.mentions": {},
    }
