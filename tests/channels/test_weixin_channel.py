import asyncio
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

import nanobot.channels.weixin as weixin_mod
from nanobot.bus.queue import MessageBus
from nanobot.channels.weixin import (
    ITEM_IMAGE,
    ITEM_TEXT,
    MESSAGE_TYPE_BOT,
    WEIXIN_CHANNEL_VERSION,
    WeixinChannel,
    WeixinConfig,
    _decrypt_aes_ecb,
    _encrypt_aes_ecb,
)


def _make_channel() -> tuple[WeixinChannel, MessageBus]:
    bus = MessageBus()
    channel = WeixinChannel(
        WeixinConfig(
            enabled=True,
            allow_from=["*"],
            state_dir=tempfile.mkdtemp(prefix="nanobot-weixin-test-"),
        ),
        bus,
    )
    return channel, bus


def test_make_headers_includes_route_tag_when_configured() -> None:
    bus = MessageBus()
    channel = WeixinChannel(
        WeixinConfig(enabled=True, allow_from=["*"], route_tag=123),
        bus,
    )
    channel._token = "token"

    headers = channel._make_headers()

    assert headers["Authorization"] == "Bearer token"
    assert headers["SKRouteTag"] == "123"
    assert headers["iLink-App-Id"] == "bot"
    assert headers["iLink-App-ClientVersion"] == str((2 << 16) | (1 << 8) | 1)


def test_channel_version_matches_reference_plugin_version() -> None:
    assert WEIXIN_CHANNEL_VERSION == "2.1.1"


def test_save_and_load_state_persists_context_tokens(tmp_path) -> None:
    bus = MessageBus()
    channel = WeixinChannel(
        WeixinConfig(enabled=True, allow_from=["*"], state_dir=str(tmp_path)),
        bus,
    )
    channel._token = "token"
    channel._get_updates_buf = "cursor"
    channel._context_tokens = {"wx-user": "ctx-1"}

    channel._save_state()

    saved = json.loads((tmp_path / "account.json").read_text())
    assert saved["context_tokens"] == {"wx-user": "ctx-1"}

    restored = WeixinChannel(
        WeixinConfig(enabled=True, allow_from=["*"], state_dir=str(tmp_path)),
        bus,
    )

    assert restored._load_state() is True
    assert restored._context_tokens == {"wx-user": "ctx-1"}


@pytest.mark.asyncio
async def test_process_message_deduplicates_inbound_ids() -> None:
    channel, bus = _make_channel()
    msg = {
        "message_type": 1,
        "message_id": "m1",
        "from_user_id": "wx-user",
        "context_token": "ctx-1",
        "item_list": [
            {"type": ITEM_TEXT, "text_item": {"text": "hello"}},
        ],
    }

    await channel._process_message(msg)
    first = await asyncio.wait_for(bus.consume_inbound(), timeout=1.0)
    await channel._process_message(msg)

    assert first.sender_id == "wx-user"
    assert first.chat_id == "wx-user"
    assert first.content == "hello"
    assert bus.inbound_size == 0


@pytest.mark.asyncio
async def test_process_message_caches_context_token_and_send_uses_it() -> None:
    channel, _bus = _make_channel()
    channel._client = object()
    channel._token = "token"
    channel._send_text = AsyncMock()

    await channel._process_message(
        {
            "message_type": 1,
            "message_id": "m2",
            "from_user_id": "wx-user",
            "context_token": "ctx-2",
            "item_list": [
                {"type": ITEM_TEXT, "text_item": {"text": "ping"}},
            ],
        }
    )

    await channel.send(
        type("Msg", (), {"chat_id": "wx-user", "content": "pong", "media": [], "metadata": {}})()
    )

    channel._send_text.assert_awaited_once_with("wx-user", "pong", "ctx-2")


@pytest.mark.asyncio
async def test_process_message_ignores_unauthorized_sender_before_side_effects(tmp_path) -> None:
    bus = MessageBus()
    channel = WeixinChannel(
        WeixinConfig(enabled=True, allow_from=["allowed-user"], state_dir=str(tmp_path)),
        bus,
    )
    channel._download_media_item = AsyncMock(return_value="/tmp/test.jpg")
    channel._start_typing = AsyncMock()

    await channel._process_message(
        {
            "message_type": 1,
            "message_id": "m-unauthorized",
            "from_user_id": "blocked-user",
            "context_token": "ctx-blocked",
            "item_list": [
                {"type": ITEM_IMAGE, "image_item": {"media": {"encrypt_query_param": "x"}}},
            ],
        }
    )

    assert channel._context_tokens == {}
    channel._download_media_item.assert_not_awaited()
    channel._start_typing.assert_not_awaited()
    assert bus.inbound_size == 0


@pytest.mark.asyncio
async def test_process_message_persists_context_token_to_state_file(tmp_path) -> None:
    bus = MessageBus()
    channel = WeixinChannel(
        WeixinConfig(enabled=True, allow_from=["*"], state_dir=str(tmp_path)),
        bus,
    )

    await channel._process_message(
        {
            "message_type": 1,
            "message_id": "m2b",
            "from_user_id": "wx-user",
            "context_token": "ctx-2b",
            "item_list": [
                {"type": ITEM_TEXT, "text_item": {"text": "ping"}},
            ],
        }
    )

    saved = json.loads((tmp_path / "account.json").read_text())
    assert saved["context_tokens"] == {"wx-user": "ctx-2b"}


@pytest.mark.asyncio
async def test_process_message_extracts_media_and_preserves_paths() -> None:
    channel, bus = _make_channel()
    channel._download_media_item = AsyncMock(return_value="/tmp/test.jpg")

    await channel._process_message(
        {
            "message_type": 1,
            "message_id": "m3",
            "from_user_id": "wx-user",
            "context_token": "ctx-3",
            "item_list": [
                {"type": ITEM_IMAGE, "image_item": {"media": {"encrypt_query_param": "x"}}},
            ],
        }
    )

    inbound = await asyncio.wait_for(bus.consume_inbound(), timeout=1.0)

    assert "[image]" in inbound.content
    assert "/tmp/test.jpg" in inbound.content
    assert inbound.media == ["/tmp/test.jpg"]


@pytest.mark.asyncio
async def test_process_message_falls_back_to_referenced_media_when_no_top_level_media() -> None:
    channel, bus = _make_channel()
    channel._download_media_item = AsyncMock(return_value="/tmp/ref.jpg")

    await channel._process_message(
        {
            "message_type": 1,
            "message_id": "m3-ref-fallback",
            "from_user_id": "wx-user",
            "context_token": "ctx-3-ref-fallback",
            "item_list": [
                {
                    "type": ITEM_TEXT,
                    "text_item": {"text": "reply to image"},
                    "ref_msg": {
                        "message_item": {
                            "type": ITEM_IMAGE,
                            "image_item": {"media": {"encrypt_query_param": "ref-enc"}},
                        },
                    },
                },
            ],
        }
    )

    inbound = await asyncio.wait_for(bus.consume_inbound(), timeout=1.0)

    channel._download_media_item.assert_awaited_once_with(
        {"media": {"encrypt_query_param": "ref-enc"}},
        "image",
    )
    assert inbound.media == ["/tmp/ref.jpg"]
    assert "reply to image" in inbound.content
    assert "[image]" in inbound.content


@pytest.mark.asyncio
async def test_process_message_does_not_use_referenced_fallback_when_top_level_media_exists() -> None:
    channel, bus = _make_channel()
    channel._download_media_item = AsyncMock(side_effect=["/tmp/top.jpg", "/tmp/ref.jpg"])

    await channel._process_message(
        {
            "message_type": 1,
            "message_id": "m3-ref-no-fallback",
            "from_user_id": "wx-user",
            "context_token": "ctx-3-ref-no-fallback",
            "item_list": [
                {"type": ITEM_IMAGE, "image_item": {"media": {"encrypt_query_param": "top-enc"}}},
                {
                    "type": ITEM_TEXT,
                    "text_item": {"text": "has top-level media"},
                    "ref_msg": {
                        "message_item": {
                            "type": ITEM_IMAGE,
                            "image_item": {"media": {"encrypt_query_param": "ref-enc"}},
                        },
                    },
                },
            ],
        }
    )

    inbound = await asyncio.wait_for(bus.consume_inbound(), timeout=1.0)

    channel._download_media_item.assert_awaited_once_with(
        {"media": {"encrypt_query_param": "top-enc"}},
        "image",
    )
    assert inbound.media == ["/tmp/top.jpg"]
    assert "/tmp/ref.jpg" not in inbound.content


@pytest.mark.asyncio
async def test_process_message_does_not_fallback_when_top_level_media_exists_but_download_fails() -> None:
    channel, bus = _make_channel()
    # Top-level image download fails (None), referenced image would succeed if fallback were triggered.
    channel._download_media_item = AsyncMock(side_effect=[None, "/tmp/ref.jpg"])

    await channel._process_message(
        {
            "message_type": 1,
            "message_id": "m3-ref-no-fallback-on-failure",
            "from_user_id": "wx-user",
            "context_token": "ctx-3-ref-no-fallback-on-failure",
            "item_list": [
                {"type": ITEM_IMAGE, "image_item": {"media": {"encrypt_query_param": "top-enc"}}},
                {
                    "type": ITEM_TEXT,
                    "text_item": {"text": "quoted has media"},
                    "ref_msg": {
                        "message_item": {
                            "type": ITEM_IMAGE,
                            "image_item": {"media": {"encrypt_query_param": "ref-enc"}},
                        },
                    },
                },
            ],
        }
    )

    inbound = await asyncio.wait_for(bus.consume_inbound(), timeout=1.0)

    # Should only attempt top-level media item; reference fallback must not activate.
    channel._download_media_item.assert_awaited_once_with(
        {"media": {"encrypt_query_param": "top-enc"}},
        "image",
    )
    assert inbound.media == []
    assert "[image]" in inbound.content
    assert "/tmp/ref.jpg" not in inbound.content


@pytest.mark.asyncio
async def test_send_without_context_token_raises() -> None:
    channel, _bus = _make_channel()
    channel._client = object()
    channel._token = "token"
    channel._send_text = AsyncMock()

    with pytest.raises(RuntimeError, match="No context_token"):
        await channel.send(
            type("Msg", (), {"chat_id": "unknown-user", "content": "pong", "media": [], "metadata": {}})()
        )

    channel._send_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_raises_when_session_is_paused() -> None:
    channel, _bus = _make_channel()
    channel._client = object()
    channel._token = "token"
    channel._context_tokens["wx-user"] = "ctx-2"
    channel._pause_session(60)
    channel._send_text = AsyncMock()

    with pytest.raises(RuntimeError, match="session paused"):
        await channel.send(
            type("Msg", (), {"chat_id": "wx-user", "content": "pong", "media": [], "metadata": {}})()
        )

    channel._send_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_typing_ticket_fetches_and_caches_per_user() -> None:
    channel, _bus = _make_channel()
    channel._client = object()
    channel._token = "token"
    channel._api_post = AsyncMock(return_value={"ret": 0, "typing_ticket": "ticket-1"})

    first = await channel._get_typing_ticket("wx-user", "ctx-1")
    second = await channel._get_typing_ticket("wx-user", "ctx-2")

    assert first == "ticket-1"
    assert second == "ticket-1"
    channel._api_post.assert_awaited_once_with(
        "ilink/bot/getconfig",
        {"ilink_user_id": "wx-user", "context_token": "ctx-1", "base_info": weixin_mod.BASE_INFO},
    )


@pytest.mark.asyncio
async def test_send_uses_typing_start_and_cancel_when_ticket_available() -> None:
    channel, _bus = _make_channel()
    channel._client = object()
    channel._token = "token"
    channel._context_tokens["wx-user"] = "ctx-typing"
    channel._send_text = AsyncMock()
    channel._api_post = AsyncMock(
        side_effect=[
            {"ret": 0, "typing_ticket": "ticket-typing"},
            {"ret": 0},
            {"ret": 0},
        ]
    )

    await channel.send(
        type("Msg", (), {"chat_id": "wx-user", "content": "pong", "media": [], "metadata": {}})()
    )

    channel._send_text.assert_awaited_once_with("wx-user", "pong", "ctx-typing")
    assert channel._api_post.await_count == 3
    assert channel._api_post.await_args_list[0].args[0] == "ilink/bot/getconfig"
    assert channel._api_post.await_args_list[1].args[0] == "ilink/bot/sendtyping"
    assert channel._api_post.await_args_list[1].args[1]["status"] == 1
    assert channel._api_post.await_args_list[2].args[0] == "ilink/bot/sendtyping"
    assert channel._api_post.await_args_list[2].args[1]["status"] == 2


@pytest.mark.asyncio
async def test_send_still_sends_text_when_typing_ticket_missing() -> None:
    channel, _bus = _make_channel()
    channel._client = object()
    channel._token = "token"
    channel._context_tokens["wx-user"] = "ctx-no-ticket"
    channel._send_text = AsyncMock()
    channel._api_post = AsyncMock(return_value={"ret": 1, "errmsg": "no config"})

    await channel.send(
        type("Msg", (), {"chat_id": "wx-user", "content": "pong", "media": [], "metadata": {}})()
    )

    channel._send_text.assert_awaited_once_with("wx-user", "pong", "ctx-no-ticket")
    channel._api_post.assert_awaited_once()
    assert channel._api_post.await_args_list[0].args[0] == "ilink/bot/getconfig"


@pytest.mark.asyncio
async def test_poll_once_pauses_session_on_expired_errcode() -> None:
    channel, _bus = _make_channel()
    channel._client = SimpleNamespace(timeout=None)
    channel._token = "token"
    channel._api_post = AsyncMock(return_value={"ret": 0, "errcode": -14, "errmsg": "expired"})

    await channel._poll_once()

    assert channel._session_pause_remaining_s() > 0


@pytest.mark.asyncio
async def test_qr_login_refreshes_expired_qr_and_then_succeeds() -> None:
    channel, _bus = _make_channel()
    channel._running = True
    channel._save_state = lambda: None
    channel._print_qr_code = lambda url: None
    channel._api_get = AsyncMock(
        side_effect=[
            {"qrcode": "qr-1", "qrcode_img_content": "url-1"},
            {"qrcode": "qr-2", "qrcode_img_content": "url-2"},
        ]
    )
    channel._api_get_with_base = AsyncMock(
        side_effect=[
            {"status": "expired"},
            {
                "status": "confirmed",
                "bot_token": "token-2",
                "ilink_bot_id": "bot-2",
                "baseurl": "https://example.test",
                "ilink_user_id": "wx-user",
            },
        ]
    )

    ok = await channel._qr_login()

    assert ok is True
    assert channel._token == "token-2"
    assert channel.config.base_url == "https://example.test"


@pytest.mark.asyncio
async def test_qr_login_returns_false_after_too_many_expired_qr_codes() -> None:
    channel, _bus = _make_channel()
    channel._running = True
    channel._print_qr_code = lambda url: None
    channel._api_get = AsyncMock(
        side_effect=[
            {"qrcode": "qr-1", "qrcode_img_content": "url-1"},
            {"qrcode": "qr-2", "qrcode_img_content": "url-2"},
            {"qrcode": "qr-3", "qrcode_img_content": "url-3"},
            {"qrcode": "qr-4", "qrcode_img_content": "url-4"},
        ]
    )
    channel._api_get_with_base = AsyncMock(
        side_effect=[
            {"status": "expired"},
            {"status": "expired"},
            {"status": "expired"},
            {"status": "expired"},
        ]
    )

    ok = await channel._qr_login()

    assert ok is False


@pytest.mark.asyncio
async def test_qr_login_switches_polling_base_url_on_redirect_status() -> None:
    channel, _bus = _make_channel()
    channel._running = True
    channel._save_state = lambda: None
    channel._print_qr_code = lambda url: None
    channel._fetch_qr_code = AsyncMock(return_value=("qr-1", "url-1"))

    status_side_effect = [
        {"status": "scaned_but_redirect", "redirect_host": "idc.redirect.test"},
        {
            "status": "confirmed",
            "bot_token": "token-3",
            "ilink_bot_id": "bot-3",
            "baseurl": "https://example.test",
            "ilink_user_id": "wx-user",
        },
    ]
    channel._api_get = AsyncMock(side_effect=list(status_side_effect))
    channel._api_get_with_base = AsyncMock(side_effect=list(status_side_effect))

    ok = await channel._qr_login()

    assert ok is True
    assert channel._token == "token-3"
    assert channel._api_get_with_base.await_count == 2
    first_call = channel._api_get_with_base.await_args_list[0]
    second_call = channel._api_get_with_base.await_args_list[1]
    assert first_call.kwargs["base_url"] == "https://ilinkai.weixin.qq.com"
    assert second_call.kwargs["base_url"] == "https://idc.redirect.test"


@pytest.mark.asyncio
async def test_qr_login_redirect_without_host_keeps_current_polling_base_url() -> None:
    channel, _bus = _make_channel()
    channel._running = True
    channel._save_state = lambda: None
    channel._print_qr_code = lambda url: None
    channel._fetch_qr_code = AsyncMock(return_value=("qr-1", "url-1"))

    status_side_effect = [
        {"status": "scaned_but_redirect"},
        {
            "status": "confirmed",
            "bot_token": "token-4",
            "ilink_bot_id": "bot-4",
            "baseurl": "https://example.test",
            "ilink_user_id": "wx-user",
        },
    ]
    channel._api_get = AsyncMock(side_effect=list(status_side_effect))
    channel._api_get_with_base = AsyncMock(side_effect=list(status_side_effect))

    ok = await channel._qr_login()

    assert ok is True
    assert channel._token == "token-4"
    assert channel._api_get_with_base.await_count == 2
    first_call = channel._api_get_with_base.await_args_list[0]
    second_call = channel._api_get_with_base.await_args_list[1]
    assert first_call.kwargs["base_url"] == "https://ilinkai.weixin.qq.com"
    assert second_call.kwargs["base_url"] == "https://ilinkai.weixin.qq.com"


@pytest.mark.asyncio
async def test_qr_login_resets_redirect_base_url_after_qr_refresh() -> None:
    channel, _bus = _make_channel()
    channel._running = True
    channel._save_state = lambda: None
    channel._print_qr_code = lambda url: None
    channel._fetch_qr_code = AsyncMock(side_effect=[("qr-1", "url-1"), ("qr-2", "url-2")])

    channel._api_get_with_base = AsyncMock(
        side_effect=[
            {"status": "scaned_but_redirect", "redirect_host": "idc.redirect.test"},
            {"status": "expired"},
            {
                "status": "confirmed",
                "bot_token": "token-5",
                "ilink_bot_id": "bot-5",
                "baseurl": "https://example.test",
                "ilink_user_id": "wx-user",
            },
        ]
    )

    ok = await channel._qr_login()

    assert ok is True
    assert channel._token == "token-5"
    assert channel._api_get_with_base.await_count == 3
    first_call = channel._api_get_with_base.await_args_list[0]
    second_call = channel._api_get_with_base.await_args_list[1]
    third_call = channel._api_get_with_base.await_args_list[2]
    assert first_call.kwargs["base_url"] == "https://ilinkai.weixin.qq.com"
    assert second_call.kwargs["base_url"] == "https://idc.redirect.test"
    assert third_call.kwargs["base_url"] == "https://ilinkai.weixin.qq.com"


@pytest.mark.asyncio
async def test_process_message_skips_bot_messages() -> None:
    channel, bus = _make_channel()

    await channel._process_message(
        {
            "message_type": MESSAGE_TYPE_BOT,
            "message_id": "m4",
            "from_user_id": "wx-user",
            "item_list": [
                {"type": ITEM_TEXT, "text_item": {"text": "hello"}},
            ],
        }
    )

    assert bus.inbound_size == 0


@pytest.mark.asyncio
async def test_process_message_starts_typing_on_inbound() -> None:
    """Typing indicator fires immediately when user message arrives."""
    channel, _bus = _make_channel()
    channel._running = True
    channel._client = object()
    channel._token = "token"
    channel._start_typing = AsyncMock()

    await channel._process_message(
        {
            "message_type": 1,
            "message_id": "m-typing",
            "from_user_id": "wx-user",
            "context_token": "ctx-typing",
            "item_list": [
                {"type": ITEM_TEXT, "text_item": {"text": "hello"}},
            ],
        }
    )

    channel._start_typing.assert_awaited_once_with("wx-user", "ctx-typing")


@pytest.mark.asyncio
async def test_send_final_message_clears_typing_indicator() -> None:
    """Non-progress send should cancel typing status."""
    channel, _bus = _make_channel()
    channel._client = object()
    channel._token = "token"
    channel._context_tokens["wx-user"] = "ctx-2"
    channel._typing_tickets["wx-user"] = {"ticket": "ticket-2", "next_fetch_at": 9999999999}
    channel._send_text = AsyncMock()
    channel._api_post = AsyncMock(return_value={"ret": 0})

    await channel.send(
        type("Msg", (), {"chat_id": "wx-user", "content": "pong", "media": [], "metadata": {}})()
    )

    channel._send_text.assert_awaited_once_with("wx-user", "pong", "ctx-2")
    typing_cancel_calls = [
        c for c in channel._api_post.await_args_list
        if c.args[0] == "ilink/bot/sendtyping" and c.args[1]["status"] == 2
    ]
    assert len(typing_cancel_calls) >= 1


@pytest.mark.asyncio
async def test_send_progress_message_keeps_typing_indicator() -> None:
    """Progress messages must not cancel typing status."""
    channel, _bus = _make_channel()
    channel._client = object()
    channel._token = "token"
    channel._context_tokens["wx-user"] = "ctx-2"
    channel._typing_tickets["wx-user"] = {"ticket": "ticket-2", "next_fetch_at": 9999999999}
    channel._send_text = AsyncMock()
    channel._api_post = AsyncMock(return_value={"ret": 0})

    await channel.send(
        type(
            "Msg",
            (),
            {
                "chat_id": "wx-user",
                "content": "thinking",
                "media": [],
                "metadata": {"_progress": True},
            },
        )()
    )

    channel._send_text.assert_awaited_once_with("wx-user", "thinking", "ctx-2")
    typing_cancel_calls = [
        c for c in channel._api_post.await_args_list
        if c.args and c.args[0] == "ilink/bot/sendtyping" and c.args[1].get("status") == 2
    ]
    assert len(typing_cancel_calls) == 0


class _DummyHttpResponse:
    def __init__(self, *, headers: dict[str, str] | None = None, status_code: int = 200) -> None:
        self.headers = headers or {}
        self.status_code = status_code

    def raise_for_status(self) -> None:
        return None


@pytest.mark.asyncio
async def test_send_media_uses_upload_full_url_when_present(tmp_path) -> None:
    channel, _bus = _make_channel()

    media_file = tmp_path / "photo.jpg"
    media_file.write_bytes(b"hello-weixin")

    cdn_post = AsyncMock(return_value=_DummyHttpResponse(headers={"x-encrypted-param": "dl-param"}))
    channel._client = SimpleNamespace(post=cdn_post)
    channel._api_post = AsyncMock(
        side_effect=[
            {
                "upload_full_url": "https://upload-full.example.test/path?foo=bar",
                "upload_param": "should-not-be-used",
            },
            {"ret": 0},
        ]
    )

    await channel._send_media_file("wx-user", str(media_file), "ctx-1")

    # first POST call is CDN upload
    cdn_url = cdn_post.await_args_list[0].args[0]
    assert cdn_url == "https://upload-full.example.test/path?foo=bar"


@pytest.mark.asyncio
async def test_send_media_falls_back_to_upload_param_url(tmp_path) -> None:
    channel, _bus = _make_channel()

    media_file = tmp_path / "photo.jpg"
    media_file.write_bytes(b"hello-weixin")

    cdn_post = AsyncMock(return_value=_DummyHttpResponse(headers={"x-encrypted-param": "dl-param"}))
    channel._client = SimpleNamespace(post=cdn_post)
    channel._api_post = AsyncMock(
        side_effect=[
            {"upload_param": "enc-need-fallback"},
            {"ret": 0},
        ]
    )

    await channel._send_media_file("wx-user", str(media_file), "ctx-1")

    cdn_url = cdn_post.await_args_list[0].args[0]
    assert cdn_url.startswith(f"{channel.config.cdn_base_url}/upload?encrypted_query_param=enc-need-fallback")
    assert "&filekey=" in cdn_url


@pytest.mark.asyncio
async def test_send_media_voice_file_uses_voice_item_and_voice_upload_type(tmp_path) -> None:
    channel, _bus = _make_channel()

    media_file = tmp_path / "voice.mp3"
    media_file.write_bytes(b"voice-bytes")

    cdn_post = AsyncMock(return_value=_DummyHttpResponse(headers={"x-encrypted-param": "voice-dl-param"}))
    channel._client = SimpleNamespace(post=cdn_post)
    channel._api_post = AsyncMock(
        side_effect=[
            {"upload_full_url": "https://upload-full.example.test/voice?foo=bar"},
            {"ret": 0},
        ]
    )

    await channel._send_media_file("wx-user", str(media_file), "ctx-voice")

    getupload_body = channel._api_post.await_args_list[0].args[1]
    assert getupload_body["media_type"] == 4

    sendmessage_body = channel._api_post.await_args_list[1].args[1]
    item = sendmessage_body["msg"]["item_list"][0]
    assert item["type"] == 3
    assert "voice_item" in item
    assert "file_item" not in item
    assert item["voice_item"]["media"]["encrypt_query_param"] == "voice-dl-param"


@pytest.mark.asyncio
async def test_send_typing_uses_keepalive_until_send_finishes() -> None:
    channel, _bus = _make_channel()
    channel._client = object()
    channel._token = "token"
    channel._context_tokens["wx-user"] = "ctx-typing-loop"
    async def _api_post_side_effect(endpoint: str, _body: dict | None = None, *, auth: bool = True):
        if endpoint == "ilink/bot/getconfig":
            return {"ret": 0, "typing_ticket": "ticket-keepalive"}
        return {"ret": 0}

    channel._api_post = AsyncMock(side_effect=_api_post_side_effect)

    async def _slow_send_text(*_args, **_kwargs) -> None:
        await asyncio.sleep(0.03)

    channel._send_text = AsyncMock(side_effect=_slow_send_text)

    old_interval = weixin_mod.TYPING_KEEPALIVE_INTERVAL_S
    weixin_mod.TYPING_KEEPALIVE_INTERVAL_S = 0.01
    try:
        await channel.send(
            type("Msg", (), {"chat_id": "wx-user", "content": "pong", "media": [], "metadata": {}})()
        )
    finally:
        weixin_mod.TYPING_KEEPALIVE_INTERVAL_S = old_interval

    status_calls = [
        c.args[1]["status"]
        for c in channel._api_post.await_args_list
        if c.args and c.args[0] == "ilink/bot/sendtyping"
    ]
    assert status_calls.count(1) >= 2
    assert status_calls[-1] == 2


@pytest.mark.asyncio
async def test_get_typing_ticket_failure_uses_backoff_and_cached_ticket(monkeypatch) -> None:
    channel, _bus = _make_channel()
    channel._client = object()
    channel._token = "token"

    now = {"value": 1000.0}
    monkeypatch.setattr(weixin_mod.time, "time", lambda: now["value"])
    monkeypatch.setattr(weixin_mod.random, "random", lambda: 0.5)

    channel._api_post = AsyncMock(return_value={"ret": 0, "typing_ticket": "ticket-ok"})
    first = await channel._get_typing_ticket("wx-user", "ctx-1")
    assert first == "ticket-ok"

    # force refresh window reached
    now["value"] = now["value"] + (12 * 60 * 60) + 1
    channel._api_post = AsyncMock(return_value={"ret": 1, "errmsg": "temporary failure"})

    # On refresh failure, should still return cached ticket and apply backoff.
    second = await channel._get_typing_ticket("wx-user", "ctx-2")
    assert second == "ticket-ok"
    assert channel._api_post.await_count == 1

    # Before backoff expiry, no extra fetch should happen.
    now["value"] += 1
    third = await channel._get_typing_ticket("wx-user", "ctx-3")
    assert third == "ticket-ok"
    assert channel._api_post.await_count == 1


@pytest.mark.asyncio
async def test_qr_login_treats_temporary_connect_error_as_wait_and_recovers() -> None:
    channel, _bus = _make_channel()
    channel._running = True
    channel._save_state = lambda: None
    channel._print_qr_code = lambda url: None
    channel._fetch_qr_code = AsyncMock(return_value=("qr-1", "url-1"))

    request = httpx.Request("GET", "https://ilinkai.weixin.qq.com/ilink/bot/get_qrcode_status")
    channel._api_get_with_base = AsyncMock(
        side_effect=[
            httpx.ConnectError("temporary network", request=request),
            {
                "status": "confirmed",
                "bot_token": "token-net-ok",
                "ilink_bot_id": "bot-id",
                "baseurl": "https://example.test",
                "ilink_user_id": "wx-user",
            },
        ]
    )

    ok = await channel._qr_login()

    assert ok is True
    assert channel._token == "token-net-ok"


@pytest.mark.asyncio
async def test_qr_login_treats_5xx_gateway_response_error_as_wait_and_recovers() -> None:
    channel, _bus = _make_channel()
    channel._running = True
    channel._save_state = lambda: None
    channel._print_qr_code = lambda url: None
    channel._fetch_qr_code = AsyncMock(return_value=("qr-1", "url-1"))

    request = httpx.Request("GET", "https://ilinkai.weixin.qq.com/ilink/bot/get_qrcode_status")
    response = httpx.Response(status_code=524, request=request)
    channel._api_get_with_base = AsyncMock(
        side_effect=[
            httpx.HTTPStatusError("gateway timeout", request=request, response=response),
            {
                "status": "confirmed",
                "bot_token": "token-5xx-ok",
                "ilink_bot_id": "bot-id",
                "baseurl": "https://example.test",
                "ilink_user_id": "wx-user",
            },
        ]
    )

    ok = await channel._qr_login()

    assert ok is True
    assert channel._token == "token-5xx-ok"


def test_decrypt_aes_ecb_strips_valid_pkcs7_padding() -> None:
    key_b64 = "MDEyMzQ1Njc4OWFiY2RlZg=="  # base64("0123456789abcdef")
    plaintext = b"hello-weixin-padding"

    ciphertext = _encrypt_aes_ecb(plaintext, key_b64)
    decrypted = _decrypt_aes_ecb(ciphertext, key_b64)

    assert decrypted == plaintext


class _DummyDownloadResponse:
    def __init__(self, content: bytes, status_code: int = 200) -> None:
        self.content = content
        self.status_code = status_code

    def raise_for_status(self) -> None:
        return None


class _DummyErrorDownloadResponse(_DummyDownloadResponse):
    def __init__(self, url: str, status_code: int) -> None:
        super().__init__(content=b"", status_code=status_code)
        self._url = url

    def raise_for_status(self) -> None:
        request = httpx.Request("GET", self._url)
        response = httpx.Response(self.status_code, request=request)
        raise httpx.HTTPStatusError(
            f"download failed with status {self.status_code}",
            request=request,
            response=response,
        )


@pytest.mark.asyncio
async def test_download_media_item_uses_full_url_when_present(tmp_path) -> None:
    channel, _bus = _make_channel()
    weixin_mod.get_media_dir = lambda _name: tmp_path

    full_url = "https://cdn.example.test/download/full"
    channel._client = SimpleNamespace(
        get=AsyncMock(return_value=_DummyDownloadResponse(content=b"raw-image-bytes"))
    )

    item = {
        "media": {
            "full_url": full_url,
            "encrypt_query_param": "enc-fallback-should-not-be-used",
        },
    }
    saved_path = await channel._download_media_item(item, "image")

    assert saved_path is not None
    assert Path(saved_path).read_bytes() == b"raw-image-bytes"
    channel._client.get.assert_awaited_once_with(full_url)


@pytest.mark.asyncio
async def test_download_media_item_falls_back_when_full_url_returns_retryable_error(tmp_path) -> None:
    channel, _bus = _make_channel()
    weixin_mod.get_media_dir = lambda _name: tmp_path

    full_url = "https://cdn.example.test/download/full?taskid=123"
    channel._client = SimpleNamespace(
        get=AsyncMock(
            side_effect=[
                _DummyErrorDownloadResponse(full_url, 500),
                _DummyDownloadResponse(content=b"fallback-bytes"),
            ]
        )
    )

    item = {
        "media": {
            "full_url": full_url,
            "encrypt_query_param": "enc-fallback",
        },
    }
    saved_path = await channel._download_media_item(item, "image")

    assert saved_path is not None
    assert Path(saved_path).read_bytes() == b"fallback-bytes"
    assert channel._client.get.await_count == 2
    assert channel._client.get.await_args_list[0].args[0] == full_url
    fallback_url = channel._client.get.await_args_list[1].args[0]
    assert fallback_url.startswith(f"{channel.config.cdn_base_url}/download?encrypted_query_param=enc-fallback")


@pytest.mark.asyncio
async def test_download_media_item_falls_back_to_encrypt_query_param(tmp_path) -> None:
    channel, _bus = _make_channel()
    weixin_mod.get_media_dir = lambda _name: tmp_path

    channel._client = SimpleNamespace(
        get=AsyncMock(return_value=_DummyDownloadResponse(content=b"fallback-bytes"))
    )

    item = {"media": {"encrypt_query_param": "enc-fallback"}}
    saved_path = await channel._download_media_item(item, "image")

    assert saved_path is not None
    assert Path(saved_path).read_bytes() == b"fallback-bytes"
    called_url = channel._client.get.await_args_list[0].args[0]
    assert called_url.startswith(f"{channel.config.cdn_base_url}/download?encrypted_query_param=enc-fallback")


@pytest.mark.asyncio
async def test_download_media_item_does_not_retry_when_full_url_fails_without_fallback(tmp_path) -> None:
    channel, _bus = _make_channel()
    weixin_mod.get_media_dir = lambda _name: tmp_path

    full_url = "https://cdn.example.test/download/full"
    channel._client = SimpleNamespace(
        get=AsyncMock(return_value=_DummyErrorDownloadResponse(full_url, 500))
    )

    item = {"media": {"full_url": full_url}}
    saved_path = await channel._download_media_item(item, "image")

    assert saved_path is None
    channel._client.get.assert_awaited_once_with(full_url)


@pytest.mark.asyncio
async def test_download_media_item_non_image_requires_aes_key_even_with_full_url(tmp_path) -> None:
    channel, _bus = _make_channel()
    weixin_mod.get_media_dir = lambda _name: tmp_path

    full_url = "https://cdn.example.test/download/voice"
    channel._client = SimpleNamespace(
        get=AsyncMock(return_value=_DummyDownloadResponse(content=b"ciphertext-or-unknown"))
    )

    item = {
        "media": {
            "full_url": full_url,
        },
    }
    saved_path = await channel._download_media_item(item, "voice")

    assert saved_path is None
    channel._client.get.assert_not_awaited()


# ---------------------------------------------------------------------------
# Tests for media-send error classification (network vs non-network errors)
# ---------------------------------------------------------------------------


def _make_outbound_msg(chat_id: str = "wx-user", content: str = "", media: list | None = None):
    """Build a minimal OutboundMessage-like object for send() tests."""
    from nanobot.bus.events import OutboundMessage

    return OutboundMessage(
        channel="weixin",
        chat_id=chat_id,
        content=content,
        media=media or [],
        metadata={},
    )


@pytest.mark.asyncio
async def test_send_media_timeout_error_propagates_without_text_fallback() -> None:
    """httpx.TimeoutException during media send must re-raise immediately,
    NOT fall back to _send_text (which would also fail during network issues)."""
    channel, _bus = _make_channel()
    channel._client = object()
    channel._token = "token"
    channel._context_tokens["wx-user"] = "ctx-1"
    channel._send_media_file = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
    channel._send_text = AsyncMock()

    msg = _make_outbound_msg(chat_id="wx-user", media=["/tmp/photo.jpg"])

    with pytest.raises(httpx.TimeoutException, match="timed out"):
        await channel.send(msg)

    # _send_text must NOT have been called as a fallback
    channel._send_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_media_transport_error_propagates_without_text_fallback() -> None:
    """httpx.TransportError during media send must re-raise immediately."""
    channel, _bus = _make_channel()
    channel._client = object()
    channel._token = "token"
    channel._context_tokens["wx-user"] = "ctx-1"
    channel._send_media_file = AsyncMock(
        side_effect=httpx.TransportError("connection reset")
    )
    channel._send_text = AsyncMock()

    msg = _make_outbound_msg(chat_id="wx-user", media=["/tmp/photo.jpg"])

    with pytest.raises(httpx.TransportError, match="connection reset"):
        await channel.send(msg)

    channel._send_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_media_5xx_http_status_error_propagates_without_text_fallback() -> None:
    """httpx.HTTPStatusError with a 5xx status must re-raise immediately."""
    channel, _bus = _make_channel()
    channel._client = object()
    channel._token = "token"
    channel._context_tokens["wx-user"] = "ctx-1"

    fake_response = httpx.Response(
        status_code=503,
        request=httpx.Request("POST", "https://example.test/upload"),
    )
    channel._send_media_file = AsyncMock(
        side_effect=httpx.HTTPStatusError(
            "Service Unavailable", request=fake_response.request, response=fake_response
        )
    )
    channel._send_text = AsyncMock()

    msg = _make_outbound_msg(chat_id="wx-user", media=["/tmp/photo.jpg"])

    with pytest.raises(httpx.HTTPStatusError, match="Service Unavailable"):
        await channel.send(msg)

    channel._send_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_media_4xx_http_status_error_falls_back_to_text() -> None:
    """httpx.HTTPStatusError with a 4xx status should fall back to text, not re-raise."""
    channel, _bus = _make_channel()
    channel._client = object()
    channel._token = "token"
    channel._context_tokens["wx-user"] = "ctx-1"

    fake_response = httpx.Response(
        status_code=400,
        request=httpx.Request("POST", "https://example.test/upload"),
    )
    channel._send_media_file = AsyncMock(
        side_effect=httpx.HTTPStatusError(
            "Bad Request", request=fake_response.request, response=fake_response
        )
    )
    channel._send_text = AsyncMock()

    msg = _make_outbound_msg(chat_id="wx-user", media=["/tmp/photo.jpg"])

    # Should NOT raise — 4xx is a client error, non-retryable
    await channel.send(msg)

    # _send_text should have been called with the fallback message
    channel._send_text.assert_awaited_once_with(
        "wx-user", "[Failed to send: photo.jpg]", "ctx-1"
    )


@pytest.mark.asyncio
async def test_send_media_file_not_found_falls_back_to_text() -> None:
    """FileNotFoundError (a non-network error) should fall back to text."""
    channel, _bus = _make_channel()
    channel._client = object()
    channel._token = "token"
    channel._context_tokens["wx-user"] = "ctx-1"
    channel._send_media_file = AsyncMock(
        side_effect=FileNotFoundError("Media file not found: /tmp/missing.jpg")
    )
    channel._send_text = AsyncMock()

    msg = _make_outbound_msg(chat_id="wx-user", media=["/tmp/missing.jpg"])

    # Should NOT raise
    await channel.send(msg)

    channel._send_text.assert_awaited_once_with(
        "wx-user", "[Failed to send: missing.jpg]", "ctx-1"
    )


@pytest.mark.asyncio
async def test_send_media_value_error_falls_back_to_text() -> None:
    """ValueError (e.g. unsupported format) should fall back to text."""
    channel, _bus = _make_channel()
    channel._client = object()
    channel._token = "token"
    channel._context_tokens["wx-user"] = "ctx-1"
    channel._send_media_file = AsyncMock(
        side_effect=ValueError("Unsupported media format")
    )
    channel._send_text = AsyncMock()

    msg = _make_outbound_msg(chat_id="wx-user", media=["/tmp/file.xyz"])

    # Should NOT raise
    await channel.send(msg)

    channel._send_text.assert_awaited_once_with(
        "wx-user", "[Failed to send: file.xyz]", "ctx-1"
    )


@pytest.mark.asyncio
async def test_send_media_network_error_does_not_double_api_calls() -> None:
    """During network issues, media send should make exactly 1 API call attempt,
    not 2 (media + text fallback).  Verify total call count."""
    channel, _bus = _make_channel()
    channel._client = object()
    channel._token = "token"
    channel._context_tokens["wx-user"] = "ctx-1"
    channel._send_media_file = AsyncMock(
        side_effect=httpx.ConnectError("connection refused")
    )
    channel._send_text = AsyncMock()

    msg = _make_outbound_msg(chat_id="wx-user", content="hello", media=["/tmp/img.png"])

    with pytest.raises(httpx.ConnectError):
        await channel.send(msg)

    # _send_media_file called once, _send_text never called
    channel._send_media_file.assert_awaited_once()
    channel._send_text.assert_not_awaited()


# ---------------------------------------------------------------------------
# Tests for _send_text raising on API errors (previously silently swallowed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_text_raises_on_api_error() -> None:
    """_send_text must raise RuntimeError when the API returns a non-zero errcode,
    matching _send_media_file behavior. This ensures ChannelManager can retry."""
    channel, _bus = _make_channel()
    channel._client = httpx.AsyncClient()
    channel._token = "token"
    channel._api_post = AsyncMock(
        return_value={"errcode": -14, "errmsg": "session expired"}
    )

    with pytest.raises(RuntimeError, match="WeChat send text error.*-14"):
        await channel._send_text("wx-user", "hello", "ctx-expired")

    channel._api_post.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_text_succeeds_on_zero_errcode() -> None:
    """_send_text must NOT raise when errcode is 0."""
    channel, _bus = _make_channel()
    channel._client = httpx.AsyncClient()
    channel._token = "token"
    channel._api_post = AsyncMock(return_value={"errcode": 0})

    await channel._send_text("wx-user", "hello", "ctx-ok")

    channel._api_post.assert_awaited_once()
