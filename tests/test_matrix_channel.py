from types import SimpleNamespace

import pytest

from nanobot.bus.queue import MessageBus
from nanobot.channels.matrix import MatrixChannel
from nanobot.config.schema import MatrixConfig


class _DummyTask:
    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


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
        self.join_calls: list[str] = []
        self.callbacks: list[tuple[object, object]] = []

    def add_event_callback(self, callback, event_type) -> None:
        self.callbacks.append((callback, event_type))

    def load_store(self) -> None:
        self.load_store_called = True

    async def join(self, room_id: str) -> None:
        self.join_calls.append(room_id)

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

    await channel.stop()


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
