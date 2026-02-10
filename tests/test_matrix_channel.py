from types import SimpleNamespace

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.matrix import TYPING_NOTICE_TIMEOUT_MS, MatrixChannel
from nanobot.config.schema import MatrixConfig


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
        self.room_send_calls: list[dict[str, object]] = []
        self.typing_calls: list[tuple[str, bool, int]] = []
        self.raise_on_send = False
        self.raise_on_typing = False

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
        ignore_unverified_devices: bool,
    ) -> None:
        self.room_send_calls.append(
            {
                "room_id": room_id,
                "message_type": message_type,
                "content": content,
                "ignore_unverified_devices": ignore_unverified_devices,
            }
        )
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
    assert clients[0].load_store_called is False
    assert len(clients[0].response_callbacks) == 3

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
    event = SimpleNamespace(sender="@alice:matrix.org", body="Hello")

    await channel._on_message(room, event)

    assert handled == ["@alice:matrix.org"]
    assert client.typing_calls == [
        ("!room:matrix.org", True, TYPING_NOTICE_TIMEOUT_MS),
    ]


@pytest.mark.asyncio
async def test_on_message_skips_typing_for_self_message() -> None:
    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    room = SimpleNamespace(room_id="!room:matrix.org", display_name="Test room")
    event = SimpleNamespace(sender="@bot:matrix.org", body="Hello")

    await channel._on_message(room, event)

    assert client.typing_calls == []


@pytest.mark.asyncio
async def test_on_message_skips_typing_for_denied_sender() -> None:
    channel = MatrixChannel(_make_config(allow_from=["@bob:matrix.org"]), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    room = SimpleNamespace(room_id="!room:matrix.org", display_name="Test room")
    event = SimpleNamespace(sender="@alice:matrix.org", body="Hello")

    await channel._on_message(room, event)

    assert client.typing_calls == []


@pytest.mark.asyncio
async def test_send_clears_typing_after_send() -> None:
    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    await channel.send(
        OutboundMessage(channel="matrix", chat_id="!room:matrix.org", content="Hi")
    )

    assert len(client.room_send_calls) == 1
    assert client.typing_calls[-1] == ("!room:matrix.org", False, TYPING_NOTICE_TIMEOUT_MS)


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
