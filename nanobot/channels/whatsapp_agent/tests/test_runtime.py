"""Runtime contracts for the WhatsApp Agent Platform channel.

These exercise the paths that protect real invariants: ordered chunked sends,
cursor durability, dedup across a replayed batch, pacing, and retry safety.
"""

from __future__ import annotations

import asyncio
import base64
import gc
import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.outbound_events import ProgressEvent
from nanobot.bus.queue import MessageBus
from nanobot.channels.manager import ChannelManager
from nanobot.channels.whatsapp_agent import runtime as runtime_module
from nanobot.channels.whatsapp_agent.protocol import (
    APIError,
    WhatsAppAgentAPIError,
    WhatsAppAgentAuthError,
)
from nanobot.channels.whatsapp_agent.runtime import (
    CREATOR_CHAT_ID,
    WhatsAppAgentChannel,
    WhatsAppAgentConfig,
)


@pytest.fixture(autouse=True)
def _isolate_runtime_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("nanobot.config.loader._current_config_path", tmp_path / "config.json")


class _Bus(MessageBus):
    def __init__(self) -> None:
        super().__init__()
        self.inbound_messages: list[Any] = []

    async def publish_inbound(self, msg: Any) -> None:
        self.inbound_messages.append(msg)


def _channel(tmp_path: Path, **overrides: Any) -> WhatsAppAgentChannel:
    config = WhatsAppAgentConfig(
        enabled=True,
        token=overrides.pop("token", "test-token"),
        allow_from=["*"],
        state_dir=str(tmp_path),
        **overrides,
    )
    return WhatsAppAgentChannel(config, _Bus())


def _poll_body(messages: list[dict[str, Any]], next_offset: int = 10) -> dict[str, Any]:
    return {
        "object": "whatsapp_agent_platform",
        "entry": [
            {
                "id": "1",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": messages,
                            "statuses": [],
                        },
                    }
                ],
            }
        ],
        "next_offset": next_offset,
    }


def _text_message(wamid: str, body: str = "hi", sender: str = "user:55") -> dict[str, Any]:
    return {
        "from": sender,
        "id": wamid,
        "timestamp": "1736844652",
        "type": "text",
        "text": {"body": body},
    }


def _json_response(status: int, payload: Any) -> httpx.Response:
    return httpx.Response(status, json=payload)


# ----------------------------------------------------------------------
# Retry policy
# ----------------------------------------------------------------------


def test_confirmed_non_delivery_is_retried(tmp_path: Path):
    channel = _channel(tmp_path)

    assert channel.should_retry_send_error(
        WhatsAppAgentAPIError(APIError(429, 130429, "", "", ""))
    )
    assert channel.should_retry_send_error(
        WhatsAppAgentAPIError(APIError(503, 131016, "", "", ""))
    )


def test_ambiguous_and_fatal_outcomes_are_not_retried_by_default(tmp_path: Path):
    channel = _channel(tmp_path)

    # A 500 may already have delivered; a duplicate annoys more than a loss.
    assert channel.should_retry_send_error(
        WhatsAppAgentAPIError(APIError(500, 2, "", "", ""))
    ) is False
    # A plain 4xx fails identically until the request or token changes.
    assert channel.should_retry_send_error(
        WhatsAppAgentAPIError(APIError(400, 131009, "", "", ""))
    ) is False
    assert channel.should_retry_send_error(WhatsAppAgentAuthError("bad token")) is False


def test_ambiguous_retry_can_be_opted_in(tmp_path: Path):
    channel = _channel(tmp_path, retryAmbiguousSends=True)

    assert channel.should_retry_send_error(
        WhatsAppAgentAPIError(APIError(500, 2, "", "", ""))
    ) is True


def test_connection_failure_is_retried_because_nothing_was_written(tmp_path: Path):
    channel = _channel(tmp_path)

    assert channel.should_retry_send_error(httpx.ConnectError("refused")) is True


def test_progress_traffic_is_off_by_default(tmp_path: Path):
    channel = _channel(tmp_path)

    assert channel.progress_transport_defaults() == (False, False)
    assert channel.config.send_progress is False


# ----------------------------------------------------------------------
# Polling and durable cursor
# ----------------------------------------------------------------------


def test_empty_204_reuses_the_same_offset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    channel = _channel(tmp_path)
    channel._load_state()
    channel._state.accept_offset(77)
    seen_params: list[dict[str, Any]] = []

    async def fake_request(method, path, *, method_key, params=None, **kwargs):
        seen_params.append(dict(params or {}))
        return 204, None

    monkeypatch.setattr(channel, "_request", fake_request)
    channel._client = object()  # type: ignore[assignment]

    assert asyncio.run(channel._poll_once()) is None
    assert seen_params[0]["offset"] == 77


@pytest.mark.parametrize("poll_timeout", [0, 25])
def test_first_empty_poll_does_not_skip_traffic_between_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, poll_timeout: int,
):
    monkeypatch.setattr(runtime_module.time, "time", lambda: 1736844652)
    channel = _channel(tmp_path, pollTimeout=poll_timeout, markRead=False, typingIndicator=False)
    channel._load_state()
    messages: list[dict[str, Any]] = []

    async def fake_request(method, path, *, method_key, params=None, **kwargs):
        # Official semantics: omission resolves the head at each request.
        offset = params.get("offset", len(messages))
        pending = messages[offset:]
        return (200, _poll_body(pending, len(messages))) if pending else (204, None)

    monkeypatch.setattr(channel, "_request", fake_request)

    async def run():
        assert await channel._poll_once() is None
        messages.append(_text_message("wamid.between"))
        batch = await channel._poll_once()
        assert batch is not None
        assert [message.wamid for message in batch.messages] == ["wamid.between"]
        await channel._process_batch(batch)
        assert channel.bus.inbound_messages[0].content == "hi"

    asyncio.run(run())


def test_bootstrap_filters_history_across_pages_and_restarts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(runtime_module.time, "time", lambda: 100)
    channel = _channel(tmp_path, markRead=False, typingIndicator=False)
    channel._load_state()
    old = dict(_text_message("old"), timestamp="99")
    undated = dict(_text_message("undated"), timestamp=None)
    fresh = dict(_text_message("fresh"), timestamp="100")
    offsets: list[int] = []

    async def request(method, path, *, params, **kwargs):
        offsets.append(params["offset"])
        if params["offset"] == 0:
            return 200, _poll_body([old], 10)
        return 200, _poll_body([undated, fresh], 9007199254740993)

    monkeypatch.setattr(channel, "_request", request)

    async def run():
        batch = await channel._poll_once()
        assert batch is not None
        await channel._process_batch(batch)
        assert not channel.bus.inbound_messages
        # Restart while still scanning the backlog must retain the original
        # boundary, not skip a message sent since the first process started.
        monkeypatch.setattr(runtime_module.time, "time", lambda: 200)
        restarted = _channel(tmp_path, markRead=False, typingIndicator=False)
        restarted._load_state()
        monkeypatch.setattr(restarted, "_request", request)
        batch = await restarted._poll_once()
        assert batch is not None
        await restarted._process_batch(batch)
        await restarted._process_batch(batch)
        assert [m.metadata["message_id"] for m in restarted.bus.inbound_messages] == ["fresh"]
        assert restarted._state.offset == 9007199254740993

    asyncio.run(run())
    assert offsets == [0, 10]


def test_empty_bootstrap_retains_boundary_after_restart_and_backoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(runtime_module.time, "time", lambda: 100)
    first = _channel(tmp_path)
    first._load_state()
    monkeypatch.setattr(first, "_request", AsyncMock(return_value=(204, None)))
    asyncio.run(first._poll_once())

    monkeypatch.setattr(runtime_module.time, "time", lambda: 200)
    second = _channel(tmp_path, markRead=False, typingIndicator=False)
    second._load_state()
    request = AsyncMock(side_effect=[
        httpx.ConnectError("offline"),
        (200, _poll_body([dict(_text_message("between"), timestamp="150")], 42)),
    ])
    monkeypatch.setattr(second, "_request", request)

    async def run():
        with pytest.raises(httpx.ConnectError):
            await second._poll_once()
        batch = await second._poll_once()
        assert batch is not None
        await second._process_batch(batch)
        assert len(second.bus.inbound_messages) == 1

    asyncio.run(run())
    assert all(call.kwargs["params"]["offset"] == 0 for call in request.await_args_list)
    assert second._state.ignore_before == 100


def test_state_write_failure_stops_before_poll_or_acknowledgement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    from unittest.mock import AsyncMock

    channel = _channel(tmp_path)
    channel._load_state()
    request = AsyncMock()
    dispatch = AsyncMock()

    def fail_save(path):
        raise OSError("disk full")

    monkeypatch.setattr(channel._state, "save", fail_save)
    monkeypatch.setattr(channel, "_request", request)
    monkeypatch.setattr(channel, "_dispatch", dispatch)
    with pytest.raises(OSError, match="disk full"):
        asyncio.run(channel._poll_once())
    fresh = dict(_text_message("fresh"), timestamp=str(channel._state.ignore_before))
    with pytest.raises(OSError, match="disk full"):
        asyncio.run(channel._process_batch(_parse(_poll_body([fresh]))))
    request.assert_not_awaited()
    dispatch.assert_not_awaited()


def test_batch_advances_and_persists_the_cursor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    channel = _channel(tmp_path)
    channel._load_state()
    dispatched: list[Any] = []

    async def fake_dispatch(message):
        dispatched.append(message)

    monkeypatch.setattr(channel, "_dispatch", fake_dispatch)
    channel._client = object()  # type: ignore[assignment]

    asyncio.run(channel._process_batch(_parse(_poll_body([_text_message("wamid.1")], 4242))))

    assert [m.wamid for m in dispatched] == ["wamid.1"]
    assert channel._state.offset == 4242
    persisted = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert persisted["offset"] == 4242


def test_replayed_batch_does_not_dispatch_twice(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    channel = _channel(tmp_path)
    channel._load_state()
    dispatched: list[Any] = []

    async def fake_dispatch(message):
        dispatched.append(message.wamid)

    monkeypatch.setattr(channel, "_dispatch", fake_dispatch)
    channel._client = object()  # type: ignore[assignment]
    batch = _parse(_poll_body([_text_message("wamid.1")], 5))

    # Polling does not consume entries, so the same offset returns them again.
    asyncio.run(channel._process_batch(batch))
    channel._state.offset = 0
    asyncio.run(channel._process_batch(batch))

    assert dispatched == ["wamid.1"]


def test_failed_message_is_not_retried_as_a_duplicate_on_replay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    channel = _channel(tmp_path)
    channel._load_state()
    calls: list[str] = []

    async def fake_dispatch(message):
        calls.append(message.wamid)
        raise RuntimeError("boom")

    monkeypatch.setattr(channel, "_dispatch", fake_dispatch)
    channel._client = object()  # type: ignore[assignment]
    batch = _parse(_poll_body([_text_message("wamid.1")], 1))

    asyncio.run(channel._process_batch(batch))
    asyncio.run(channel._process_batch(batch))

    # The wamid is recorded before handling, so a crash cannot double-answer.
    assert calls == ["wamid.1"]


def _parse(body: dict[str, Any]):
    from nanobot.channels.whatsapp_agent.protocol import parse_poll_batch

    return parse_poll_batch(body)


# ----------------------------------------------------------------------
# Inbound routing
# ----------------------------------------------------------------------


def test_inbound_text_reaches_the_bus_with_quote_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    bus = _Bus()
    channel = WhatsAppAgentChannel(
        WhatsAppAgentConfig(enabled=True, token="t", allow_from=["*"], state_dir=str(tmp_path)),
        bus,
    )
    channel._load_state()

    async def no_ack(wamid: str) -> None:
        return None

    monkeypatch.setattr(channel, "_acknowledge", no_ack)
    asyncio.run(channel._dispatch(_message(_text_message("wamid.1", "hello"))))

    assert len(bus.inbound_messages) == 1
    inbound = bus.inbound_messages[0]
    assert inbound.channel == "whatsapp_agent"
    assert inbound.chat_id == CREATOR_CHAT_ID
    assert inbound.content == "hello"
    assert inbound.metadata["message_id"] == "wamid.1"
    assert channel._state.creator_id == "user:55"


@pytest.mark.parametrize("kind", ["reaction", "unknown"])
def test_non_replyable_messages_are_not_forwarded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str):
    bus = _Bus()
    channel = WhatsAppAgentChannel(
        WhatsAppAgentConfig(enabled=True, token="t", allow_from=["*"], state_dir=str(tmp_path)),
        bus,
    )
    channel._load_state()
    raw = {"from": "user:55", "id": "w1", "timestamp": "1", "type": kind}
    if kind == "reaction":
        raw["reaction"] = {"message_id": "x", "emoji": "👍"}

    asyncio.run(channel._dispatch(_message(raw)))

    assert bus.inbound_messages == []


def _message(raw: dict[str, Any]):
    from nanobot.channels.whatsapp_agent.protocol import parse_message

    parsed = parse_message(raw)
    assert parsed is not None
    return parsed


# ----------------------------------------------------------------------
# Outbound
# ----------------------------------------------------------------------


def test_text_is_chunked_to_the_api_limit_and_sent_in_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    channel = _channel(tmp_path)
    channel._state.note_creator("user:55")
    sent: list[dict[str, Any]] = []

    async def fake_request_ok(method, path, *, method_key, json_body=None, **kwargs):
        sent.append(json_body)
        return {"messages": [{"id": f"wamid.out{len(sent)}"}]}

    monkeypatch.setattr(channel, "_request_ok", fake_request_ok)

    body = "x" * 5000
    asyncio.run(
        channel.send(OutboundMessage(channel="whatsapp_agent", chat_id=CREATOR_CHAT_ID, content=body))
    )

    assert [len(chunk["text"]["body"]) for chunk in sent] == [4096, 904]
    # No inbound message id was supplied, so no quote is attached.
    assert all("context" not in chunk for chunk in sent)
    assert all(chunk["to"] == "user:55" for chunk in sent)


def test_reply_quotes_the_originating_message_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    channel = _channel(tmp_path)
    channel._state.note_creator("user:55")
    sent: list[dict[str, Any]] = []

    async def fake_request_ok(method, path, *, method_key, json_body=None, **kwargs):
        sent.append(json_body)
        return {"messages": [{"id": "wamid.out"}]}

    monkeypatch.setattr(channel, "_request_ok", fake_request_ok)

    asyncio.run(
        channel.send(
            OutboundMessage(
                channel="whatsapp_agent",
                chat_id=CREATOR_CHAT_ID,
                content="y" * 5000,
                metadata={"message_id": "wamid.in"},
            )
        )
    )

    assert sent[0]["context"] == {"message_id": "wamid.in"}
    assert "context" not in sent[1]


def test_send_without_a_known_creator_fails_loudly(tmp_path: Path):
    channel = _channel(tmp_path)

    with pytest.raises(WhatsAppAgentAPIError):
        asyncio.run(
            channel.send(OutboundMessage(channel="whatsapp_agent", chat_id=CREATOR_CHAT_ID, content="hi"))
        )


def test_outbound_wamid_is_remembered_for_receipts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    channel = _channel(tmp_path)
    channel._state.note_creator("user:55")

    async def fake_request_ok(method, path, *, method_key, json_body=None, **kwargs):
        return {"messages": [{"id": "wamid.sent"}]}

    monkeypatch.setattr(channel, "_request_ok", fake_request_ok)
    asyncio.run(
        channel.send(OutboundMessage(channel="whatsapp_agent", chat_id=CREATOR_CHAT_ID, content="hi"))
    )

    assert channel._state.last_status["wamid.sent"] == "sent"


def test_media_uses_the_matching_payload_object_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    channel = _channel(tmp_path)
    channel._state.note_creator("user:55")
    image = tmp_path / "chart.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    sent: list[dict[str, Any]] = []

    async def fake_request_ok(method, path, *, method_key, json_body=None, data=None, files=None, **kwargs):
        if path == "/media":
            return {"id": "MEDIA1"}
        sent.append(json_body)
        return {"messages": [{"id": "wamid.out"}]}

    monkeypatch.setattr(channel, "_request_ok", fake_request_ok)
    asyncio.run(
        channel.send(
            OutboundMessage(
                channel="whatsapp_agent",
                chat_id=CREATOR_CHAT_ID,
                content="",
                media=[str(image)],
            )
        )
    )

    assert sent[0]["type"] == "image"
    assert sent[0]["image"] == {"id": "MEDIA1"}
    # Extra payload objects are validated by the API, so none are included.
    assert set(sent[0]) == {"messaging_product", "to", "type", "image"}


def test_unsupported_media_format_is_sent_as_a_generic_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    from unittest.mock import AsyncMock

    channel = _channel(tmp_path)
    channel._state.note_creator("user:55")
    attachment = tmp_path / "chart.svg"
    attachment.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
    upload = AsyncMock(return_value="MEDIA1")
    request = AsyncMock(return_value={"messages": [{"id": "out"}]})
    monkeypatch.setattr(channel, "_upload_media", upload)
    monkeypatch.setattr(channel, "_request_ok", request)
    asyncio.run(channel.send(OutboundMessage(
        channel.name, "creator", "", media=[str(attachment)],
    )))
    upload.assert_awaited_once_with(attachment, "application/octet-stream")
    payload = request.call_args.kwargs["json_body"]
    assert payload["type"] == "document"
    assert payload["document"] == {"id": "MEDIA1", "filename": "chart.svg"}
    assert "image" not in payload


@pytest.mark.parametrize("max_mb,size_mb", [(1, 2), (16, 6)])
def test_oversized_media_is_skipped_before_upload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, max_mb: int, size_mb: int,
):
    channel = _channel(tmp_path, maxMediaMb=max_mb)
    channel._state.note_creator("user:55")
    big = tmp_path / "big.png"
    big.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * (size_mb * 1024 * 1024))
    calls: list[str] = []

    async def fake_request_ok(method, path, *, method_key, **kwargs):
        calls.append(path)
        return {}

    monkeypatch.setattr(channel, "_request_ok", fake_request_ok)
    asyncio.run(
        channel.send(
            OutboundMessage(
                channel="whatsapp_agent",
                chat_id=CREATOR_CHAT_ID,
                content="",
                media=[str(big)],
            )
        )
    )

    assert calls == []


@pytest.mark.parametrize("status,code", [(429, 130429), (503, 131016)])
def test_manager_retry_resumes_after_acknowledged_parts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: int, code: int,
):
    from nanobot.config.schema import Config

    channel = _channel(tmp_path)
    channel._state.note_creator("user:55")
    delivered: list[str] = []
    attempts = 0

    async def request(method, path, *, json_body=None, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            raise WhatsAppAgentAPIError(APIError(status, code, "not accepted", "", ""))
        delivered.append(json_body["text"]["body"])
        return {"messages": [{"id": str(attempts)}]}

    monkeypatch.setattr(channel, "_request_ok", request)
    monkeypatch.setattr("nanobot.channels.manager._SEND_RETRY_DELAYS", (0,))
    manager = object.__new__(ChannelManager)
    manager.config = Config()
    message = OutboundMessage(channel=channel.name, chat_id="creator", content="A" * 4096 + "B")
    asyncio.run(manager._send_with_retry(channel, message))
    assert delivered == ["A" * 4096, "B"]
    assert not channel._pending_sends


@pytest.mark.parametrize("retry_ambiguous", [False, True])
def test_media_failure_never_replays_accepted_text_or_attachments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, retry_ambiguous: bool,
):
    from nanobot.config.schema import Config

    channel = _channel(tmp_path, retryAmbiguousSends=retry_ambiguous)
    channel._state.note_creator("user:55")
    attachment = tmp_path / "document.txt"
    attachment.write_text("test", encoding="utf-8")
    sent: list[str] = []
    media_attempts = 0

    async def request(method, path, *, json_body=None, **kwargs):
        nonlocal media_attempts
        if path == "/media":
            return {"id": "MEDIA1"}
        if json_body["type"] == "document":
            media_attempts += 1
            if media_attempts == 2:
                raise WhatsAppAgentAPIError(APIError(500, 2, "unknown outcome", "", ""))
        sent.append(json_body["type"])
        return {"messages": [{"id": str(len(sent))}]}

    monkeypatch.setattr(channel, "_request_ok", request)
    monkeypatch.setattr("nanobot.channels.manager._SEND_RETRY_DELAYS", (0,))
    manager = object.__new__(ChannelManager)
    manager.config = Config()
    message = OutboundMessage(
        channel=channel.name, chat_id="creator", content="Files",
        media=[str(attachment), str(attachment)],
    )
    asyncio.run(manager._send_with_retry(channel, message))
    assert sent == ["text", "document"] + (["document"] if retry_ambiguous else [])
    assert media_attempts == (3 if retry_ambiguous else 2)
    assert not channel._pending_sends


def test_abandoned_or_cancelled_sends_release_retry_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    from unittest.mock import AsyncMock

    channel = _channel(tmp_path)
    channel._state.note_creator("user:55")
    request = AsyncMock(side_effect=WhatsAppAgentAPIError(APIError(429, 130429, "", "", "")))
    monkeypatch.setattr(channel, "_request_ok", request)

    async def abandon():
        # No successful retry follows; collecting the envelope must remove its
        # progress even when the failure was retryable.
        with pytest.raises(WhatsAppAgentAPIError):
            await channel.send(OutboundMessage(channel.name, "creator", "hello"))

    asyncio.run(abandon())
    request.reset_mock(side_effect=True)
    gc.collect()
    assert not channel._pending_sends

    request.side_effect = asyncio.CancelledError()
    message = OutboundMessage(channel.name, "creator", "hello")
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(channel.send(message))
    assert not channel._pending_sends


@pytest.mark.parametrize("options,expected", [
    ({}, []),
    ({"sendProgress": True}, ["Working"]),
    ({"sendToolHints": True}, ["Running tool"]),
    ({"sendProgress": True, "sendToolHints": True}, ["Working", "Running tool"]),
])
async def test_manager_dispatch_respects_progress_opt_ins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, options: dict, expected: list[str],
):
    from nanobot.config.schema import Config

    config = Config.model_validate({"channels": {
        "websocket": {"enabled": False},
        "whatsapp_agent": {"enabled": True, "token": "test-token", **options},
    }})
    manager = ChannelManager(config, MessageBus())
    channel = manager.channels["whatsapp_agent"]
    channel._state.note_creator("user:55")
    delivered: list[str] = []
    finished = asyncio.Event()

    async def request(method, path, *, json_body=None, **kwargs):
        body = json_body["text"]["body"]
        delivered.append(body)
        if body == "Done":
            finished.set()
        return {"messages": [{"id": str(len(delivered))}]}

    monkeypatch.setattr(channel, "_request_ok", request)
    dispatcher = asyncio.create_task(manager._dispatch_outbound())
    try:
        for content, event in (
            ("Working", ProgressEvent()),
            ("Running tool", ProgressEvent(tool_hint=True)),
            ("Done", None),
        ):
            await manager.bus.publish_outbound(OutboundMessage(
                channel.name, "creator", content, event=event,
            ))
        await asyncio.wait_for(finished.wait(), timeout=2)
        assert delivered == expected + ["Done"]
    finally:
        dispatcher.cancel()
        await asyncio.gather(dispatcher, return_exceptions=True)


# ----------------------------------------------------------------------
# Inbound media
# ----------------------------------------------------------------------


def test_inbound_media_is_downloaded_and_verified(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    channel = _channel(tmp_path)
    content = b"pdf-bytes"
    digest = base64.b64encode(hashlib.sha256(content).digest()).decode()
    raw = {
        "from": "user:55",
        "id": "wamid.m",
        "timestamp": "1",
        "type": "document",
        "document": {
            "id": "MEDIA1",
            "mime_type": "application/pdf",
            "sha256": digest,
            "filename": "report.pdf",
        },
    }

    async def fake_request_ok(method, path, *, method_key, **kwargs):
        return {"url": "https://lookaside.fbsbx.com/x/content"}

    async def fake_fetch(url, limit):
        return content

    monkeypatch.setattr(channel, "_request_ok", fake_request_ok)
    monkeypatch.setattr(channel, "_fetch_media_bytes", fake_fetch)
    paths, text = asyncio.run(channel._materialize(_message(raw)))

    assert len(paths) == 1
    assert Path(paths[0]).read_bytes() == content
    assert "report.pdf" in text


def test_media_with_a_mismatched_digest_is_discarded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    channel = _channel(tmp_path)
    raw = {
        "from": "user:55",
        "id": "wamid.m",
        "timestamp": "1",
        "type": "image",
        "image": {"id": "MEDIA1", "mime_type": "image/jpeg", "sha256": "AAAA"},
    }

    async def fake_request_ok(method, path, *, method_key, **kwargs):
        return {"url": "https://lookaside.fbsbx.com/x/content"}

    async def fake_fetch(url, limit):
        return b"tampered"

    monkeypatch.setattr(channel, "_request_ok", fake_request_ok)
    monkeypatch.setattr(channel, "_fetch_media_bytes", fake_fetch)
    paths, text = asyncio.run(channel._materialize(_message(raw)))

    # The bytes never reach the agent and no file is written.
    assert paths == []
    assert text == "[image]"


def test_internal_media_urls_are_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    channel = _channel(tmp_path)
    raw = {
        "from": "user:55",
        "id": "wamid.m",
        "timestamp": "1",
        "type": "image",
        "image": {"id": "MEDIA1", "mime_type": "image/jpeg"},
    }

    async def fake_request_ok(method, path, *, method_key, **kwargs):
        return {"url": "http://169.254.169.254/latest/meta-data"}

    monkeypatch.setattr(channel, "_request_ok", fake_request_ok)
    paths, _ = asyncio.run(channel._materialize(_message(raw)))

    assert paths == []


def test_voice_note_is_transcribed_when_a_provider_is_available(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    channel = _channel(tmp_path)
    raw = {
        "from": "user:55",
        "id": "wamid.v",
        "timestamp": "1",
        "type": "audio",
        "audio": {"id": "MEDIA1", "mime_type": "audio/ogg", "voice": True},
    }

    async def fake_request_ok(method, path, *, method_key, **kwargs):
        return {"url": "https://lookaside.fbsbx.com/x/content"}

    async def fake_fetch(url, limit):
        return b"ogg"

    async def fake_transcribe(path):
        return "remember to buy milk"

    monkeypatch.setattr(channel, "_request_ok", fake_request_ok)
    monkeypatch.setattr(channel, "_fetch_media_bytes", fake_fetch)
    monkeypatch.setattr(channel, "transcribe_audio", fake_transcribe)
    paths, text = asyncio.run(channel._materialize(_message(raw)))

    assert text == "remember to buy milk"
    assert len(paths) == 1


# ----------------------------------------------------------------------
# Lifecycle and pacing
# ----------------------------------------------------------------------


def test_start_requires_a_token(tmp_path: Path):
    channel = _channel(tmp_path, token="")

    with pytest.raises(WhatsAppAgentAuthError):
        asyncio.run(channel.start())


def test_start_error_message_is_actionable(tmp_path: Path):
    channel = _channel(tmp_path)

    message = channel.start_error_message(WhatsAppAgentAuthError("nope"))

    assert message is not None
    assert "API key" in message


def test_invalid_token_during_poll_stops_the_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    channel = _channel(tmp_path)
    entered = asyncio.Event()

    async def fake_poll_once():
        entered.set()
        raise WhatsAppAgentAuthError("bad")

    monkeypatch.setattr(channel, "_poll_once", fake_poll_once)
    monkeypatch.setattr(channel, "_new_http_client", lambda: _FakeClient())

    async def run() -> None:
        with pytest.raises(WhatsAppAgentAuthError):
            await channel.start()

    asyncio.run(run())
    assert entered.is_set()
    # An invalid token cannot recover by retrying, so the channel is not running.
    assert channel._running is False


def test_rolling_window_limiter_paces_a_method(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(runtime_module, "_RATE_WINDOW_SECONDS", 0.25)
    limiter = runtime_module._RollingWindowLimiter({"messages": 2}, margin=0)

    async def run() -> float:
        loop = asyncio.get_running_loop()
        start = loop.time()
        for _ in range(3):
            await limiter.acquire("messages")
        return loop.time() - start

    # The third call must wait for the window rather than exceed the cap.
    assert asyncio.run(run()) >= 0.24


def test_rolling_window_limiter_counts_each_method_separately(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(runtime_module, "_RATE_WINDOW_SECONDS", 0.25)
    limiter = runtime_module._RollingWindowLimiter({"messages": 1, "updates": 1}, margin=0)

    async def run() -> None:
        # A send must not consume the poll budget; both complete immediately.
        await asyncio.wait_for(limiter.acquire("messages"), timeout=0.2)
        await asyncio.wait_for(limiter.acquire("updates"), timeout=0.2)

    asyncio.run(run())


def test_restart_resumes_from_the_persisted_offset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # First process handles one message and advances the cursor.
    first = _channel(tmp_path)
    first._load_state()

    async def ok_dispatch(message):
        return None

    monkeypatch.setattr(first, "_dispatch", ok_dispatch)
    first._client = object()  # type: ignore[assignment]
    asyncio.run(first._process_batch(_parse(_poll_body([_text_message("wamid.1")], 500))))

    # A new process with the same token must resume, not restart the stream.
    second = _channel(tmp_path)
    second._load_state()
    seen: list[dict[str, Any]] = []

    async def fake_request(method, path, *, method_key, params=None, **kwargs):
        seen.append(dict(params or {}))
        return 204, None

    monkeypatch.setattr(second, "_request", fake_request)
    second._client = object()  # type: ignore[assignment]
    asyncio.run(second._poll_once())

    assert seen[0]["offset"] == 500
    # The dedup window also survives the restart.
    assert second._state.has_message("wamid.1") is True


def test_restart_with_a_new_token_does_not_reuse_the_old_cursor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    first = _channel(tmp_path)
    first._load_state()
    first._state.accept_offset(500)
    first._persist()

    replacement = _channel(tmp_path, token="a-different-agent-token")
    replacement._load_state()
    seen: list[dict[str, Any]] = []

    async def fake_request(method, path, *, method_key, params=None, **kwargs):
        seen.append(dict(params or {}))
        return 204, None

    monkeypatch.setattr(replacement, "_request", fake_request)
    replacement._client = object()  # type: ignore[assignment]
    asyncio.run(replacement._poll_once())

    # next_offset belongs to the agent that issued it, so it is not replayed.
    assert seen[0]["offset"] == 0


def test_the_token_never_appears_in_logs_or_persisted_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    secret = "EAAG-super-secret-agent-token"
    channel = _channel(tmp_path, token=secret)
    channel._load_state()
    channel._state.accept_offset(9)
    channel._persist()
    records: list[str] = []

    logger_id = logger.add(lambda message: records.append(message), level="DEBUG")
    try:
        # A failing poll exercises the error-logging path with a live token.
        async def failing_request(method, path, *, method_key, params=None, **kwargs):
            return 400, {"error": {"code": 100, "message": "(100) invalid"}}

        monkeypatch.setattr(channel, "_request", failing_request)
        channel._client = object()  # type: ignore[assignment]
        with pytest.raises(WhatsAppAgentAuthError):
            asyncio.run(channel._poll_once())
    finally:
        logger.remove(logger_id)

    assert secret not in "".join(records)
    assert secret not in (tmp_path / "state.json").read_text(encoding="utf-8")


def test_channel_does_not_regress_the_neonize_whatsapp_channel(tmp_path: Path):
    from nanobot.channels.registry import discover_plugins

    plugins = discover_plugins()

    assert "whatsapp" in plugins
    assert "whatsapp_agent" in plugins
    assert plugins["whatsapp"].runtime != plugins["whatsapp_agent"].runtime


class _FakeClient:
    async def aclose(self) -> None:
        return None
