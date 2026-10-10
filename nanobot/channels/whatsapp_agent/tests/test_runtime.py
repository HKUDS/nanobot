"""Runtime contracts for the WhatsApp Agent Platform channel.

These exercise the paths that protect real invariants: ordered chunked sends,
cursor durability, dedup across a replayed batch, pacing, and retry safety.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
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


def test_first_poll_omits_offset_to_skip_the_backlog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    channel = _channel(tmp_path)
    channel._load_state()
    seen_params: list[dict[str, Any]] = []

    async def fake_request(method, path, *, method_key, params=None, **kwargs):
        seen_params.append(dict(params or {}))
        return 204, None

    monkeypatch.setattr(channel, "_request", fake_request)
    channel._client = object()  # type: ignore[assignment]

    asyncio.run(channel._poll_once())

    # Omitting ``offset`` resolves the head, so a first run never replays
    # up to 30 days of history into an auto-replying agent.
    assert "offset" not in seen_params[0]


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


def test_oversized_media_is_skipped_before_upload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    channel = _channel(tmp_path, maxMediaMb=1)
    channel._state.note_creator("user:55")
    big = tmp_path / "big.png"
    big.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * (6 * 1024 * 1024))
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
    assert "offset" not in seen[0]


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
