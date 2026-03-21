import asyncio
import json

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.napcat import NapCatChannel, NapCatConfig
from nanobot.channels.registry import discover_all


class _FakeWebSocket:
    def __init__(self, incoming: list[str] | None = None) -> None:
        self.incoming = list(incoming or [])
        self.sent: list[str] = []
        self.closed = False

    async def send(self, payload: str) -> None:
        self.sent.append(payload)

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.incoming:
            return self.incoming.pop(0)
        raise StopAsyncIteration


class _FakeConnect:
    def __init__(self, ws: _FakeWebSocket, capture: dict) -> None:
        self.ws = ws
        self.capture = capture

    async def __aenter__(self):
        return self.ws

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _make_channel(**kwargs) -> NapCatChannel:
    return NapCatChannel(NapCatConfig(allow_from=["*"], **kwargs), MessageBus())


def test_napcat_is_discoverable_and_has_defaults() -> None:
    channels = discover_all()
    assert "napcat" in channels
    assert channels["napcat"].default_config()["url"] == "ws://127.0.0.1:3001/"


def test_inbound_private_message_routes_to_bus() -> None:
    async def run() -> None:
        channel = _make_channel()
        await channel._handle_ws_message(json.dumps({
            "post_type": "message",
            "self_id": 10001,
            "message_type": "private",
            "message_id": 123,
            "user_id": 20002,
            "message": [{"type": "text", "data": {"text": "hello"}}],
        }))
        msg = await channel.bus.consume_inbound()
        assert msg.sender_id == "20002"
        assert msg.chat_id == "20002"
        assert msg.content == "hello"
        assert msg.metadata["message_id"] == "123"

    asyncio.run(run())


def test_inbound_group_message_open_policy_routes() -> None:
    async def run() -> None:
        channel = _make_channel(group_policy="open")
        await channel._handle_ws_message(json.dumps({
            "post_type": "message",
            "self_id": 10001,
            "message_type": "group",
            "message_id": 123,
            "user_id": 20002,
            "group_id": 30003,
            "message": [{"type": "text", "data": {"text": "hello group"}}],
        }))
        msg = await channel.bus.consume_inbound()
        assert msg.sender_id == "20002"
        assert msg.chat_id == "30003"
        assert msg.content == "hello group"
        assert msg.metadata["is_group"] is True

    asyncio.run(run())


def test_inbound_group_message_mention_policy_ignores_non_mentions() -> None:
    async def run() -> None:
        channel = _make_channel(group_policy="mention")
        await channel._handle_ws_message(json.dumps({
            "post_type": "message",
            "self_id": 10001,
            "message_type": "group",
            "message_id": 123,
            "user_id": 20002,
            "group_id": 30003,
            "message": [{"type": "text", "data": {"text": "hello group"}}],
        }))
        assert channel.bus.inbound_size == 0

    asyncio.run(run())


def test_inbound_group_message_mention_policy_accepts_at_self() -> None:
    async def run() -> None:
        channel = _make_channel(group_policy="mention")
        await channel._handle_ws_message(json.dumps({
            "post_type": "message",
            "self_id": 10001,
            "message_type": "group",
            "message_id": 123,
            "user_id": 20002,
            "group_id": 30003,
            "message": [
                {"type": "at", "data": {"qq": "10001"}},
                {"type": "text", "data": {"text": "hello bot"}},
            ],
        }))
        msg = await channel.bus.consume_inbound()
        assert msg.chat_id == "30003"
        assert msg.content == "hello bot"

    asyncio.run(run())


def test_image_receive_populates_local_media_and_preserves_text(monkeypatch) -> None:
    async def run() -> None:
        channel = _make_channel()
        async def fake_download(url: str, message_id: str, index: int) -> str:
            assert url == "https://example.com/a.png"
            assert message_id == "123"
            assert index == 1
            return "/tmp/napcat_123_1.png"
        monkeypatch.setattr(channel, "_download_image", fake_download)
        await channel._handle_ws_message(json.dumps({
            "post_type": "message",
            "self_id": 10001,
            "message_type": "private",
            "message_id": 123,
            "user_id": 20002,
            "message": [
                {"type": "text", "data": {"text": "look"}},
                {"type": "image", "data": {"url": "https://example.com/a.png"}},
            ],
        }))
        msg = await channel.bus.consume_inbound()
        assert msg.content == "look"
        assert msg.media == ["/tmp/napcat_123_1.png"]

    asyncio.run(run())


def test_outbound_private_message_sends_send_private_msg() -> None:
    async def run() -> None:
        channel = _make_channel()
        channel._ws = _FakeWebSocket()
        await channel.send(OutboundMessage(channel="napcat", chat_id="20002", content="hello"))
        payload = json.loads(channel._ws.sent[0])
        assert payload["action"] == "send_private_msg"
        assert payload["params"] == {"user_id": "20002", "message": "hello"}
        assert payload["echo"].startswith("nanobot:")

    asyncio.run(run())


def test_outbound_group_message_sends_send_group_msg() -> None:
    async def run() -> None:
        channel = _make_channel()
        channel._ws = _FakeWebSocket()
        await channel.send(OutboundMessage(
            channel="napcat",
            chat_id="30003",
            content="hello group",
            metadata={"is_group": True},
        ))
        payload = json.loads(channel._ws.sent[0])
        assert payload["action"] == "send_group_msg"
        assert payload["params"] == {"group_id": "30003", "message": "hello group"}

    asyncio.run(run())


def test_access_token_is_added_to_websocket_headers(monkeypatch) -> None:
    async def run() -> None:
        capture = {}
        ws = _FakeWebSocket()
        channel = _make_channel(access_token="secret")

        def fake_connect(url, additional_headers=None):
            capture["url"] = url
            capture["headers"] = additional_headers
            return _FakeConnect(ws, capture)

        monkeypatch.setattr("nanobot.channels.napcat.websockets.connect", fake_connect)
        await channel._run_connection()
        assert capture["url"] == "ws://127.0.0.1:3001/"
        assert capture["headers"] == {"Authorization": "Bearer secret"}

    asyncio.run(run())


def test_reconnect_path_sleeps_after_connection_error(monkeypatch) -> None:
    async def run() -> None:
        channel = _make_channel(reconnect_delay_s=0.25)
        calls = {"count": 0}
        sleeps: list[float] = []

        async def fake_run_connection():
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("boom")
            channel._running = False

        async def fake_sleep(delay: float):
            sleeps.append(delay)

        monkeypatch.setattr(channel, "_run_connection", fake_run_connection)
        monkeypatch.setattr("nanobot.channels.napcat.asyncio.sleep", fake_sleep)
        await channel.start()
        assert sleeps == [0.25]
        assert calls["count"] == 2

    asyncio.run(run())


def test_self_sent_message_is_ignored() -> None:
    async def run() -> None:
        channel = _make_channel()
        await channel._handle_ws_message(json.dumps({
            "post_type": "message",
            "self_id": 10001,
            "message_type": "private",
            "message_id": 123,
            "user_id": 10001,
            "message": [{"type": "text", "data": {"text": "loop"}}],
        }))
        assert channel.bus.inbound_size == 0

    asyncio.run(run())
