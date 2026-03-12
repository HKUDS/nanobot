from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nanobot.channels import feishu as fs_mod
from nanobot.channels.feishu import FeishuChannel
from nanobot.channels.retry import ChannelHealth


def _channel() -> FeishuChannel:
    ch = object.__new__(FeishuChannel)
    ch.config = SimpleNamespace(
        app_id="app", app_secret="secret", encrypt_key="", verification_token=""
    )
    ch._client = None
    ch._ws_client = None
    ch._ws_thread = None
    ch._processed_message_ids = {}
    ch._loop = None
    ch._running = False
    ch.bus = SimpleNamespace()
    ch._handle_message = AsyncMock()
    ch._health = ChannelHealth()
    return ch


@pytest.mark.asyncio
async def test_start_stop_validation_paths(monkeypatch: pytest.MonkeyPatch):
    ch = _channel()

    monkeypatch.setattr(fs_mod, "FEISHU_AVAILABLE", False)
    await ch.start()

    monkeypatch.setattr(fs_mod, "FEISHU_AVAILABLE", True)
    ch.config.app_id = ""
    await ch.start()

    ch.config.app_id = "app"

    class _Builder:
        def app_id(self, _):
            return self

        def app_secret(self, _):
            return self

        def log_level(self, _):
            return self

        def build(self):
            return SimpleNamespace(im=SimpleNamespace(v1=SimpleNamespace()))

    class _DispatchBuilder:
        def register_p2_im_message_receive_v1(self, _fn):
            return self

        def build(self):
            return object()

    class _WsClient:
        def __init__(self, *args, **kwargs):
            self.start_calls = 0

        def start(self):
            self.start_calls += 1
            raise RuntimeError("ws boom")

        def stop(self):
            return None

    fake_lark = SimpleNamespace(
        Client=SimpleNamespace(builder=lambda: _Builder()),
        EventDispatcherHandler=SimpleNamespace(builder=lambda *_a: _DispatchBuilder()),
        ws=SimpleNamespace(Client=_WsClient),
        LogLevel=SimpleNamespace(INFO=1),
    )
    monkeypatch.setattr(fs_mod, "lark", fake_lark)

    original_sleep = asyncio.sleep

    async def _sleep_once(_s: float):
        ch._running = False
        await original_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", _sleep_once)

    await ch.start()
    await ch.stop()


@pytest.mark.asyncio
async def test_add_reaction_and_on_message_sync(monkeypatch: pytest.MonkeyPatch):
    ch = _channel()
    ch._client = SimpleNamespace(
        im=SimpleNamespace(
            v1=SimpleNamespace(
                message_reaction=SimpleNamespace(
                    create=lambda req: SimpleNamespace(success=lambda: True, code=0, msg=""),
                )
            )
        )
    )

    class _ReqB:
        def message_id(self, _):
            return self

        def request_body(self, _):
            return self

        def build(self):
            return object()

    class _ReqBodyB:
        def reaction_type(self, _):
            return self

        def build(self):
            return object()

    monkeypatch.setattr(
        fs_mod, "CreateMessageReactionRequest", SimpleNamespace(builder=lambda: _ReqB())
    )
    monkeypatch.setattr(
        fs_mod, "CreateMessageReactionRequestBody", SimpleNamespace(builder=lambda: _ReqBodyB())
    )
    monkeypatch.setattr(
        fs_mod,
        "Emoji",
        SimpleNamespace(
            builder=lambda: SimpleNamespace(
                emoji_type=lambda _e: SimpleNamespace(build=lambda: object())
            )
        ),
    )

    ch._add_reaction_sync("m1", "THUMBSUP")
    await ch._add_reaction("m1")

    calls = {"n": 0}

    def _run_coro(coro, loop):
        calls["n"] += 1
        coro.close()
        return None

    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", _run_coro)
    ch._loop = SimpleNamespace(is_running=lambda: True)
    ch._on_message_sync(SimpleNamespace(event=SimpleNamespace()))
    assert calls["n"] == 1
