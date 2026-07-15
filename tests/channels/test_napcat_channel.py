import asyncio

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.napcat import NapcatChannel, NapcatConfig


class _FakeWs:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, payload: str) -> None:
        self.sent.append(payload)

    async def close(self) -> None:
        pass


class _FakeContent:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def iter_chunked(self, _size: int):
        for chunk in self._chunks:
            yield chunk


class _FakeResponse:
    def __init__(self, status: int, chunks: list[bytes] | None = None) -> None:
        self.status = status
        self.content = _FakeContent(chunks or [])

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeHttp:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.calls: list[dict] = []

    def get(self, url: str, **kwargs):
        self.calls.append({"url": url, "kwargs": kwargs})
        return self.response


def _channel(config: NapcatConfig | None = None) -> NapcatChannel:
    return NapcatChannel(config or NapcatConfig(allow_from=["*"]), MessageBus())


@pytest.mark.asyncio
async def test_send_raises_while_websocket_is_not_connected() -> None:
    channel = _channel()

    with pytest.raises(RuntimeError, match="not connected"):
        await channel.send(
            OutboundMessage(channel="napcat", chat_id="private:123", content="hello")
        )


@pytest.mark.asyncio
async def test_group_message_requires_mention_by_default() -> None:
    channel = _channel(NapcatConfig(allow_from=["user1"], group_policy="mention"))
    channel._self_id = 42

    await channel._on_message(
        {
            "message_id": 1,
            "message_type": "group",
            "group_id": 100,
            "user_id": "user1",
            "sender": {"nickname": "Alice"},
            "message": [{"type": "text", "data": {"text": "hello"}}],
        }
    )

    assert channel.bus.inbound_size == 0


@pytest.mark.asyncio
async def test_group_mention_routes_with_sender_label() -> None:
    channel = _channel(NapcatConfig(allow_from=["user1"], group_policy="mention"))
    channel._self_id = 42

    await channel._on_message(
        {
            "message_id": 1,
            "message_type": "group",
            "group_id": 100,
            "user_id": "user1",
            "sender": {"card": "Alice"},
            "message": [
                {"type": "at", "data": {"qq": "42"}},
                {"type": "text", "data": {"text": "hello"}},
            ],
        }
    )

    msg = await channel.bus.consume_inbound()
    assert msg.sender_id == "user1"
    assert msg.chat_id == "group:100"
    assert msg.content == "Alice: hello"
    assert msg.metadata["message_id"] == 1


@pytest.mark.asyncio
async def test_call_action_raises_on_onebot_failure_and_clears_pending() -> None:
    channel = _channel()
    channel._ws = _FakeWs()

    task = asyncio.create_task(channel._call_action("send_msg", {"message": []}))
    while not channel._pending:
        await asyncio.sleep(0)
    fut = next(iter(channel._pending.values()))
    fut.set_result({"status": "failed", "retcode": 1400, "wording": "bad request"})

    with pytest.raises(RuntimeError, match="action send_msg failed"):
        await task
    assert channel._pending == {}


@pytest.mark.asyncio
async def test_notice_with_invalid_ids_is_ignored(monkeypatch) -> None:
    channel = _channel()

    async def fail_lookup(*_args, **_kwargs):
        raise AssertionError("lookup should not be called for invalid ids")

    monkeypatch.setattr(channel, "_lookup_member_name", fail_lookup)

    await channel._on_notice(
        {
            "notice_type": "group_increase",
            "group_id": "not-an-int",
            "user_id": "user1",
        }
    )

    assert channel.bus.inbound_size == 0


@pytest.mark.asyncio
async def test_download_image_rejects_redirects(tmp_path, monkeypatch) -> None:
    channel = _channel()
    channel._media_root = tmp_path
    channel._http = _FakeHttp(_FakeResponse(status=302))
    monkeypatch.setattr(
        "nanobot.channels.napcat.validate_url_target",
        lambda _url: (True, ""),
    )

    result = await channel._download_image({"url": "https://example.com/a.png", "file": "a.png"})

    assert result is None
    assert channel._http.calls == [
        {"url": "https://example.com/a.png", "kwargs": {"allow_redirects": False}}
    ]
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_dispatch_tracks_and_discards_background_tasks() -> None:
    channel = _channel()
    seen = asyncio.Event()

    async def fake_on_message(_payload):
        seen.set()

    channel._on_message = fake_on_message

    await channel._dispatch_frame(
        '{"post_type":"message","message_type":"private","user_id":"user1","message":"hi"}'
    )

    assert len(channel._background_tasks) == 1
    await asyncio.wait_for(seen.wait(), timeout=1)
    await asyncio.sleep(0)
    assert channel._background_tasks == set()
