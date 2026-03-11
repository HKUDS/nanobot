import json
from pathlib import Path

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.api import APIChannel
from nanobot.config.schema import ApiConfig


class _DummyRequest:
    def __init__(self, path: str, headers: dict[str, str] | None = None) -> None:
        self.path = path
        self.headers = headers or {}


class _DummyConnection:
    def __init__(self, path: str = "/chat", headers: dict[str, str] | None = None) -> None:
        self.request = _DummyRequest(path, headers)
        self.sent: list[str] = []

    async def send(self, payload: str) -> None:
        self.sent.append(payload)

    async def close(self, *args, **kwargs) -> None:
        return None


def _make_channel() -> APIChannel:
    return APIChannel(
        config=ApiConfig(enabled=True, path="/chat", token="", allow_from=["*"]),
        bus=MessageBus(),
        host="127.0.0.1",
        port=18790,
    )


def _make_channel_with_tmp_logs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> APIChannel:
    monkeypatch.setattr("nanobot.channels.api.get_logs_dir", lambda: tmp_path)
    return APIChannel(
        config=ApiConfig(enabled=True, path="/chat", token="", allow_from=["*"]),
        bus=MessageBus(),
        host="127.0.0.1",
        port=18790,
    )


def test_parse_chat_payload_uses_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    channel = _make_channel_with_tmp_logs(monkeypatch, tmp_path)
    parsed = channel._parse_chat_payload(
        {"senderId": "u1", "content": "hello", "requestId": "req-1"},
        {},
    )

    assert isinstance(parsed, dict)
    assert parsed["sender_id"] == "u1"
    assert parsed["chat_id"] == "u1"
    assert parsed["content"] == "hello"
    assert parsed["metadata"]["request_id"] == "req-1"


def test_parse_chat_payload_reads_query_values(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    channel = _make_channel_with_tmp_logs(monkeypatch, tmp_path)
    parsed = channel._parse_chat_payload(
        {"content": "hello"},
        {"senderId": ["u2"], "chatId": ["room-a"]},
    )

    assert isinstance(parsed, dict)
    assert parsed["sender_id"] == "u2"
    assert parsed["chat_id"] == "room-a"


def test_parse_chat_payload_rejects_invalid_media(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    channel = _make_channel_with_tmp_logs(monkeypatch, tmp_path)
    err = channel._parse_chat_payload(
        {"senderId": "u1", "content": "hello", "media": "bad"},
        {},
    )
    assert err == "media must be an array of strings."


def test_extract_token_prefers_query_over_header(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    channel = _make_channel_with_tmp_logs(monkeypatch, tmp_path)
    conn = _DummyConnection(
        path="/chat?token=query-token",
        headers={"Authorization": "Bearer header-token"},
    )
    _, query = channel._extract_request_info(conn)

    assert channel._extract_token(conn, query) == "query-token"


def test_build_outbound_payload_marks_progress_and_request_id() -> None:
    payload = APIChannel._build_outbound_payload(
        OutboundMessage(
            channel="api",
            chat_id="room-a",
            content="working",
            metadata={"_progress": True, "_tool_hint": True, "request_id": "r-1"},
        )
    )

    assert payload["type"] == "progress"
    assert payload["toolHint"] is True
    assert payload["requestId"] == "r-1"


@pytest.mark.asyncio
async def test_send_routes_message_to_bound_connection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    channel = _make_channel_with_tmp_logs(monkeypatch, tmp_path)
    conn = _DummyConnection()
    await channel._bind_connection("room-a", conn)

    await channel.send(
        OutboundMessage(channel="api", chat_id="room-a", content="hello", metadata={})
    )

    assert len(conn.sent) == 1
    payload = json.loads(conn.sent[0])
    assert payload["type"] == "message"
    assert payload["chatId"] == "room-a"
    assert payload["content"] == "hello"


@pytest.mark.asyncio
async def test_append_log_writes_jsonl(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    channel = _make_channel_with_tmp_logs(monkeypatch, tmp_path)

    await channel._append_log("inbound", sender_id="u1", chat_id="room-a")

    log_file = tmp_path / "api" / "chat_events.jsonl"
    assert log_file.exists()
    line = log_file.read_text(encoding="utf-8").strip().splitlines()[-1]
    record = json.loads(line)
    assert record["event"] == "inbound"
    assert record["sender_id"] == "u1"
    assert record["chat_id"] == "room-a"
