from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.channels.discord import DiscordChannel, _split_message
from nanobot.config.schema import DiscordConfig
from nanobot.errors import DeliverySkippedError


class _Bus:
    async def publish_inbound(self, _msg) -> None:
        return None


def test_discord_split_message_branches() -> None:
    assert _split_message("") == []
    assert _split_message("abc", max_len=10) == ["abc"]
    chunks = _split_message("a b c d e", max_len=3)
    assert len(chunks) >= 2


async def test_discord_send_paths() -> None:
    ch = DiscordChannel(DiscordConfig(token="t"), _Bus())
    with pytest.raises(DeliverySkippedError):
        await ch.send(OutboundMessage(channel="discord", chat_id="1", content="x"))

    ch._http = SimpleNamespace()
    ch._send_payload = AsyncMock(return_value=True)  # type: ignore[method-assign]
    ch._stop_typing = AsyncMock()  # type: ignore[method-assign]
    msg = OutboundMessage(channel="discord", chat_id="1", content="hello world", reply_to="r1")
    await ch.send(msg)
    assert ch._send_payload.await_count == 1


async def test_discord_send_payload_retry_and_fail() -> None:
    ch = DiscordChannel(DiscordConfig(token="t"), _Bus())

    class _Resp429:
        status_code = 429

        @staticmethod
        def json() -> dict[str, float]:
            return {"retry_after": 0.0}

        @staticmethod
        def raise_for_status() -> None:
            return None

    class _RespOK:
        status_code = 200

        @staticmethod
        def json() -> dict[str, object]:
            return {}

        @staticmethod
        def raise_for_status() -> None:
            return None

    seq = [_Resp429(), _RespOK()]

    async def _post(*_args, **_kwargs):
        return seq.pop(0)

    ch._http = SimpleNamespace(post=_post)
    assert await ch._send_payload("u", {}, {"a": 1}) is True

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("x")

    ch._http = SimpleNamespace(post=_boom)
    with pytest.raises(RuntimeError):
        await ch._send_payload("u", {}, {"a": 1})


async def test_discord_gateway_loop_dispatches() -> None:
    ch = DiscordChannel(DiscordConfig(token="t"), _Bus())
    ch._running = True
    ch._start_heartbeat = AsyncMock()  # type: ignore[method-assign]
    ch._identify = AsyncMock()  # type: ignore[method-assign]
    ch._handle_message_create = AsyncMock()  # type: ignore[method-assign]

    class _Ws:
        def __init__(self, items: list[str]):
            self._items = items

        def __aiter__(self):
            self._it = iter(self._items)
            return self

        async def __anext__(self):
            try:
                return next(self._it)
            except StopIteration as e:
                raise StopAsyncIteration from e

    ch._ws = _Ws(
        [
            "{bad",
            json.dumps({"op": 10, "d": {"heartbeat_interval": 1}}),
            json.dumps({"op": 0, "t": "MESSAGE_CREATE", "d": {"id": "m"}}),
            json.dumps({"op": 7}),
        ]
    )
    await ch._gateway_loop()
    assert ch._identify.await_count == 1
    assert ch._handle_message_create.await_count == 1


async def test_discord_handle_message_create_with_attachments(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ch = DiscordChannel(DiscordConfig(), _Bus())
    ch._handle_message = AsyncMock()  # type: ignore[method-assign]
    ch._start_typing = AsyncMock()  # type: ignore[method-assign]
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    class _Resp:
        content = b"x"

        @staticmethod
        def raise_for_status() -> None:
            return None

    ch._http = SimpleNamespace(get=AsyncMock(return_value=_Resp()))

    payload = {
        "id": "m1",
        "author": {"id": "u1", "bot": False},
        "channel_id": "c1",
        "content": "hi",
        "attachments": [
            {"id": "a1", "url": "https://e.x/f", "filename": "f.txt", "size": 2},
            {"id": "a2", "url": "https://e.x/big", "filename": "b.bin", "size": 30 * 1024 * 1024},
        ],
    }
    await ch._handle_message_create(payload)
    assert ch._handle_message.await_count == 1
