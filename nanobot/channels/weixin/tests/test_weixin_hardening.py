from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock

import httpx
import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.outbound_events import ProgressEvent
from nanobot.bus.queue import MessageBus
from nanobot.channels.manager import ChannelManager
from nanobot.channels.weixin.manifest import SETUP_SPEC
from nanobot.channels.weixin.runtime import (
    ITEM_TOOL_CALL_RESULT,
    ITEM_TOOL_CALL_START,
    WEIXIN_MAX_MESSAGE_LEN,
    WeixinAPIError,
    WeixinAuthError,
    WeixinChannel,
    WeixinConfig,
    WeixinQuotaError,
    sanitize_weixin_markdown,
    split_weixin_message,
)
from nanobot.config.schema import Config


def _channel(**config: object) -> WeixinChannel:
    return WeixinChannel(
        WeixinConfig.model_validate(
            {"enabled": True, "allowFrom": ["*"], **config}
        ),
        MessageBus(),
    )


def _ready_channel(**config: object) -> WeixinChannel:
    channel = _channel(**config)
    channel._client = object()
    channel._token = "bot-token"
    channel._context_tokens["wx-user"] = "ctx-1"
    channel._context_token_at["wx-user"] = time.time()
    channel._typing_tickets["wx-user"] = {
        "ticket": "",
        "next_fetch_at": time.time() + 3600,
    }
    return channel


def test_weixin_defaults_protect_context_quota() -> None:
    config = WeixinConfig()

    assert WEIXIN_MAX_MESSAGE_LEN == 1800
    assert config.send_progress is False
    assert config.send_tool_hints is False
    assert config.reply_progress_messages is False
    assert config.context_message_budget == 8
    assert config.block_streaming is False


def test_weixin_webui_manifest_covers_runtime_configuration() -> None:
    runtime_fields = set(WeixinConfig().model_dump(mode="json", by_alias=True))

    assert set(SETUP_SPEC.fields) == runtime_fields - {"enabled"}


def test_reply_progress_opt_in_enables_progress_transport() -> None:
    config = WeixinConfig(reply_progress_messages=True)

    assert config.send_progress is True
    assert config.send_tool_hints is True


@pytest.mark.parametrize(
    ("section", "send_progress", "send_tool_hints"),
    [
        ({"enabled": True}, False, False),
        ({"enabled": True, "replyProgressMessages": True}, True, True),
        ({"enabled": True, "sendProgress": True, "sendToolHints": False}, True, False),
    ],
)
def test_channel_manager_preserves_weixin_quota_defaults(
    section: dict[str, object],
    send_progress: bool,
    send_tool_hints: bool,
) -> None:
    manager = ChannelManager.__new__(ChannelManager)
    manager.config = Config.model_validate({"channels": {"weixin": section}})
    manager.bus = MessageBus()

    channel = manager._build_channel("weixin", WeixinChannel, section)

    assert channel.send_progress is send_progress
    assert channel.send_tool_hints is send_tool_hints


@pytest.mark.asyncio
async def test_channel_manager_does_not_retry_permanent_weixin_error(monkeypatch) -> None:
    manager = ChannelManager.__new__(ChannelManager)
    manager.config = Config.model_validate({"channels": {"sendMaxRetries": 3}})
    manager.bus = MessageBus()
    channel = _channel()
    channel.send = AsyncMock(
        side_effect=WeixinAPIError(
            "sendmessage",
            errcode=-1,
            errmsg="business rejection",
            retryable=False,
        )
    )
    sleep = AsyncMock()
    monkeypatch.setattr("nanobot.channels.manager.asyncio.sleep", sleep)

    await manager._send_with_retry(
        channel,
        OutboundMessage(channel="weixin", chat_id="wx-user", content="test"),
    )

    channel.send.assert_awaited_once()
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_weixin_http_clients_ignore_system_proxy(tmp_path, monkeypatch) -> None:
    captured: list[dict[str, object]] = []

    class FakeClient:
        async def aclose(self) -> None:
            return None

    def make_client(**kwargs: object) -> FakeClient:
        captured.append(kwargs)
        return FakeClient()

    monkeypatch.setattr("nanobot.channels.weixin.runtime.httpx.AsyncClient", make_client)

    connect_channel = _channel(stateDir=str(tmp_path / "connect"))
    connect_channel.connect_open_client()
    await connect_channel.connect_close_client()

    login_channel = _channel(stateDir=str(tmp_path / "login"))
    login_channel._qr_login = AsyncMock(return_value=True)
    assert await login_channel.login() is True

    start_channel = _channel(token="configured-token", stateDir=str(tmp_path / "start"))

    async def stop_after_poll() -> None:
        start_channel._running = False

    start_channel._notify_lifecycle = AsyncMock()
    start_channel._poll_once = AsyncMock(side_effect=stop_after_poll)
    await start_channel.start()
    await start_channel.stop()

    assert len(captured) == 3
    assert all(kwargs["trust_env"] is False for kwargs in captured)


def test_markdown_sanitizer_preserves_code_and_escapes_bare_angles() -> None:
    content = "before <tag> `x<y>`\n```python\na<b\n```\n![drop](https://x.test/a.png)"

    sanitized = sanitize_weixin_markdown(content)

    assert "before ＜tag＞" in sanitized
    assert "`x<y>`" in sanitized
    assert "a<b" in sanitized
    assert "![drop]" not in sanitized


def test_markdown_split_balances_fences_and_stays_within_limit() -> None:
    chunks = split_weixin_message("```python\n" + ("x" * 4000) + "\n```")

    assert len(chunks) >= 3
    assert all(len(chunk) <= WEIXIN_MAX_MESSAGE_LEN for chunk in chunks)
    assert all(chunk.count("```") % 2 == 0 for chunk in chunks)


@pytest.mark.asyncio
async def test_qr_fetch_posts_known_local_tokens(tmp_path) -> None:
    state_dir = tmp_path / "weixin"
    state_dir.mkdir()
    (state_dir / "account.json").write_text(
        json.dumps({"token": "persisted-token"}),
        encoding="utf-8",
    )
    channel = _channel(stateDir=str(state_dir))
    channel._api_post = AsyncMock(
        return_value={"qrcode": "qr-1", "qrcode_img_content": "https://qr.test/1"}
    )

    assert await channel._fetch_qr_code() == ("qr-1", "https://qr.test/1")
    channel._api_post.assert_awaited_once_with(
        "ilink/bot/get_bot_qrcode?bot_type=3",
        {"local_token_list": ["persisted-token"]},
        auth=False,
        include_base_info=False,
    )


@pytest.mark.asyncio
async def test_qr_fetch_retries_without_rejected_local_tokens(tmp_path) -> None:
    state_dir = tmp_path / "weixin"
    state_dir.mkdir()
    (state_dir / "account.json").write_text(
        json.dumps({"token": "invalid-token"}),
        encoding="utf-8",
    )
    channel = _channel(stateDir=str(state_dir))
    channel._api_post = AsyncMock(
        side_effect=[
            {"ret": -3},
            {"ret": 0, "qrcode": "qr-1", "qrcode_img_content": "https://qr.test/1"},
        ]
    )

    assert await channel._fetch_qr_code() == ("qr-1", "https://qr.test/1")
    assert [call.args[1] for call in channel._api_post.await_args_list] == [
        {"local_token_list": ["invalid-token"]},
        {"local_token_list": []},
    ]


@pytest.mark.asyncio
async def test_qr_fetch_does_not_retry_invalid_request_without_local_tokens(tmp_path) -> None:
    channel = _channel(stateDir=str(tmp_path / "weixin"))
    channel._api_post = AsyncMock(return_value={"ret": -3})

    with pytest.raises(WeixinAPIError, match="get_bot_qrcode failed.*ret=-3"):
        await channel._fetch_qr_code()

    channel._api_post.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifecycle_notifications_are_best_effort() -> None:
    channel = _ready_channel()
    channel._api_post = AsyncMock(return_value={"ret": 0})

    await channel._notify_lifecycle("start")
    await channel._notify_lifecycle("stop")

    assert [call.args[0] for call in channel._api_post.await_args_list] == [
        "ilink/bot/msg/notifystart",
        "ilink/bot/msg/notifystop",
    ]


def test_business_errors_have_explicit_retry_contracts() -> None:
    channel = _channel()

    with pytest.raises(WeixinQuotaError) as quota:
        channel._raise_for_api_error("sendmessage", {"ret": -2})
    with pytest.raises(WeixinAuthError) as auth:
        channel._raise_for_api_error("getupdates", {"errcode": -14})
    with pytest.raises(WeixinAPIError) as rejected:
        channel._raise_for_api_error("sendmessage", {"ret": -100})

    assert channel.should_retry_send_error(quota.value) is False
    assert channel.should_retry_send_error(auth.value) is False
    assert channel.should_retry_send_error(rejected.value) is False
    assert channel.should_retry_send_error(httpx.ReadTimeout("slow")) is True

    request = httpx.Request("POST", "https://ilinkai.weixin.qq.com/send")
    for status_code in (408, 425, 429, 503):
        response = httpx.Response(status_code, request=request)
        error = httpx.HTTPStatusError(
            "retryable response",
            request=request,
            response=response,
        )
        assert channel.should_retry_send_error(error) is True

    rejected_response = httpx.Response(400, request=request)
    rejected_http = httpx.HTTPStatusError(
        "bad request",
        request=request,
        response=rejected_response,
    )
    assert channel.should_retry_send_error(rejected_http) is False


def test_error_classification_checks_ret_and_errcode_independently() -> None:
    channel = _channel()

    with pytest.raises(WeixinQuotaError):
        channel._raise_for_api_error(
            "sendmessage",
            {"ret": -2, "errcode": -100},
        )
    with pytest.raises(WeixinAuthError):
        channel._raise_for_api_error(
            "getupdates",
            {"ret": -14, "errcode": -100},
        )


@pytest.mark.asyncio
async def test_stop_cancels_inflight_long_poll() -> None:
    channel = _channel(token="configured-token")
    poll_started = asyncio.Event()
    poll_cancelled = asyncio.Event()

    class FakeClient:
        async def aclose(self) -> None:
            return None

    async def blocking_poll() -> None:
        poll_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            poll_cancelled.set()
            raise

    channel._new_http_client = lambda _timeout: FakeClient()  # type: ignore[method-assign]
    channel._notify_lifecycle = AsyncMock()
    channel._poll_once = blocking_poll  # type: ignore[method-assign]

    start_task = asyncio.create_task(channel.start())
    await asyncio.wait_for(poll_started.wait(), timeout=1)
    await asyncio.wait_for(channel.stop(), timeout=1)
    await asyncio.wait_for(start_task, timeout=1)

    assert poll_cancelled.is_set()
    assert channel._poll_task is None


@pytest.mark.asyncio
async def test_retry_reuses_client_id_and_skips_completed_chunks() -> None:
    channel = _ready_channel()
    request = httpx.Request("POST", "https://ilinkai.weixin.qq.com/ilink/bot/sendmessage")
    channel._api_post = AsyncMock(
        side_effect=[
            {"ret": 0},
            httpx.ReadTimeout("ambiguous timeout", request=request),
            {"ret": 0},
        ]
    )
    msg = OutboundMessage(
        channel="weixin",
        chat_id="wx-user",
        content="x" * (WEIXIN_MAX_MESSAGE_LEN + 200),
    )

    with pytest.raises(httpx.ReadTimeout):
        await channel.send(msg)
    await channel.send(msg)

    bodies = [call.args[1] for call in channel._api_post.await_args_list]
    client_ids = [body["msg"]["client_id"] for body in bodies]
    assert client_ids[0] != client_ids[1]
    assert client_ids[1] == client_ids[2]
    assert channel._context_send_counts["ctx-1"] == 2


@pytest.mark.asyncio
async def test_quota_rejection_defers_final_until_fresh_context() -> None:
    channel = _ready_channel()
    channel._api_post = AsyncMock(side_effect=[{"ret": -2}, {"ret": 0}])
    msg = OutboundMessage(
        channel="weixin",
        chat_id="wx-user",
        content="deferred answer",
    )

    with pytest.raises(WeixinQuotaError):
        await channel.send(msg)
    first_client_id = channel._api_post.await_args_list[0].args[1]["msg"]["client_id"]
    assert "wx-user" in channel._deferred_outbound

    channel._context_tokens["wx-user"] = "ctx-2"
    channel._context_token_at["wx-user"] = time.time()
    await channel._retry_deferred_messages("wx-user")

    second_client_id = channel._api_post.await_args_list[1].args[1]["msg"]["client_id"]
    assert second_client_id == first_client_id
    assert "wx-user" not in channel._deferred_outbound


@pytest.mark.asyncio
async def test_local_context_budget_stops_before_extra_api_call() -> None:
    channel = _ready_channel(contextMessageBudget=1)
    channel._api_post = AsyncMock(return_value={"ret": 0})

    await channel._send_text("wx-user", "one", "ctx-1")
    with pytest.raises(WeixinQuotaError, match="local safety budget"):
        await channel._send_text("wx-user", "two", "ctx-1")

    channel._api_post.assert_awaited_once()


@pytest.mark.asyncio
async def test_bounded_block_streaming_reserves_one_final_message() -> None:
    channel = _ready_channel(
        blockStreaming=True,
        blockStreamingMinChars=200,
        blockStreamingMaxMessages=3,
    )
    channel._send_text = AsyncMock()

    await channel.send_delta("wx-user", "a" * 250, stream_id="stream-1")
    await channel.send_delta("wx-user", "b" * 250, stream_id="stream-1")
    await channel.send_delta("wx-user", "c" * 250, stream_id="stream-1")
    await channel.send_delta("wx-user", "done", stream_id="stream-1", stream_end=True)

    assert channel._send_text.await_count == 3
    assert "stream-1" not in channel._stream_buffers
    assert "stream-1" not in channel._stream_sent_counts


@pytest.mark.asyncio
async def test_structured_progress_is_capped_and_uses_one_run_id() -> None:
    channel = _ready_channel(
        replyProgressMessages=True,
        replyProgressMaxMessages=2,
    )
    channel._send_message_item = AsyncMock()
    events = [
        {"phase": "start", "call_id": "call-1", "name": "read_file"},
        {"phase": "end", "call_id": "call-1", "name": "read_file"},
        {"phase": "start", "call_id": "call-2", "name": "exec"},
    ]

    await channel.send(
        OutboundMessage(
            channel="weixin",
            chat_id="wx-user",
            content="read_file",
            event=ProgressEvent(content="read_file", tool_hint=True, tool_events=events),
        )
    )

    assert channel._send_message_item.await_count == 2
    first = channel._send_message_item.await_args_list[0]
    second = channel._send_message_item.await_args_list[1]
    assert first.args[1]["type"] == ITEM_TOOL_CALL_START
    assert second.args[1]["type"] == ITEM_TOOL_CALL_RESULT
    assert first.kwargs["run_id"] == second.kwargs["run_id"]
