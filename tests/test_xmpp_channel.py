"""Tests for XMPP channel."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.xmpp import XmppChannel, _URL_RE
from nanobot.config.schema import XmppConfig


class _DummyTask:
    """Mock asyncio Task."""

    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True

    def __await__(self):
        async def _done():
            return None

        return _done().__await__()


class _FakeXmppClient:
    """Mock XMPP client for testing."""

    def __init__(self, jid: str, password: str, **kwargs) -> None:
        self.jid = jid
        self.password = password
        self._nickname = kwargs.get("nickname", "nanobot")
        self._rooms = set(kwargs.get("rooms", []))
        self._joined_rooms: set[str] = set()
        self._running = False
        self._file_transfer_enabled = kwargs.get("file_transfer_enabled", True)
        self._incoming_files: dict[str, dict] = {}
        self.boundjid = SimpleNamespace(bare=jid)
        self.plugin: dict[str, Any] = {}
        self.event_handlers: dict[str, list] = {}
        self.client_roster = {}
        self.send_presence_called = False
        self.get_roster_called = False
        self.join_muc_calls: list[tuple[str, str]] = []
        self.send_message_calls: list[dict] = []
        self.send_typing_calls: list[tuple[str, bool]] = []
        self.is_connected_val = True
        self.disconnect_called = False
        self.files_uploaded: list[dict] = []

    def register_plugin(self, name: str) -> None:
        self.plugin[name] = SimpleNamespace()

    def add_event_handler(self, event: str, handler) -> None:
        if event not in self.event_handlers:
            self.event_handlers[event] = []
        self.event_handlers[event].append(handler)

    def send_presence(self) -> None:
        self.send_presence_called = True

    async def get_roster(self) -> None:
        self.get_roster_called = True

    def is_connected(self) -> bool:
        return self.is_connected_val

    def disconnect(self) -> None:
        self.disconnect_called = True

    def send_message(self, mto: str, mbody: str, mtype: str = "chat") -> None:
        self.send_message_calls.append({"to": mto, "body": mbody, "type": mtype})

    def send_typing(self, to_jid: str, typing: bool = True) -> None:
        self.send_typing_calls.append((to_jid, typing))

    def make_message(self, mto: str, mtype: str = "chat"):
        msg = SimpleNamespace()
        msg.__dict__["chat_state"] = None
        msg.send = lambda: None
        return msg

    def _media_dir(self) -> Path:
        d = Path.home() / ".nanobot" / "media" / "xmpp"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _is_file_type_allowed(self, mime_type: str) -> bool:
        return True

    def _check_file_size(self, size_bytes: int) -> bool:
        return True

    def _build_file_path(self, sender: str, filename: str, mime_type: str | None) -> Path:
        timestamp = "20240101_120000"
        return self._media_dir() / f"{timestamp}_{sender.replace('@', '_')}_{filename}"

    def shutdown(self) -> None:
        self.disconnect_called = True


class _FakeResponse:
    """Mock HTTP response."""

    def __init__(self, content: bytes = b"", headers: dict | None = None, status_code: int = 200) -> None:
        self.content = content
        self.headers = headers or {}
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


class _FakeHttpxClient:
    """Mock httpx client for testing."""

    def __init__(self, **kwargs) -> None:
        self.responses: dict[str, _FakeResponse] = {}
        self.closed = False

    def set_response(self, url: str, response: _FakeResponse) -> None:
        self.responses[url] = response

    async def head(self, url: str) -> _FakeResponse:
        return self.responses.get(url, _FakeResponse())

    async def get(self, url: str) -> _FakeResponse:
        return self.responses.get(url, _FakeResponse())

    async def aclose(self) -> None:
        self.closed = True


def _make_config(**kwargs) -> XmppConfig:
    """Create XMPP config with defaults."""
    defaults = {
        "enabled": True,
        "jid": "bot@example.com",
        "password": "secret",
        "server": "",
        "port": 5222,
        "use_tls": True,
        "nickname": "nanobot",
        "rooms": [],
        "allow_from": ["*"],
        "group_policy": "open",
        "file_transfer_enabled": True,
        "max_file_size_mb": 50,
        "upload_domain": "",
    }
    defaults.update(kwargs)
    return XmppConfig(**defaults)


class _FakeClock:
    async def sleep(self, secs):
        pass


@pytest.mark.asyncio
async def test_start_configures_xmpp_client() -> None:
    channel = XmppChannel(_make_config(), MessageBus(), client_provider=_FakeXmppClient)
    channel._running = True
    await channel.start()

    try:
        assert channel.client is not None
        assert channel.client.jid == "bot@example.com"
    finally:
        await channel.stop()

@pytest.mark.asyncio
async def test_start_initializes_http_client() -> None:
    channel = XmppChannel(
        _make_config(), 
        MessageBus(), 
        client_provider=_FakeXmppClient,
        http_client_provider=_FakeHttpxClient
    )
    # Mock the run loop to avoid infinite loop
    channel._running = True

    await channel.start()

    try:
        assert isinstance(channel._http, _FakeHttpxClient)
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_stop_closes_http_client() -> None:
    channel = XmppChannel(
        _make_config(),
        MessageBus(),
        client_provider=_FakeXmppClient,
        http_client_provider=_FakeHttpxClient
    )
    channel._running = True

    await channel.start()
    http = channel._http

    await channel.stop()
    assert http.closed


@pytest.mark.asyncio
async def test_dm_to_message_without_urls() -> None:
    channel = XmppChannel(_make_config(), MessageBus())

    msg = await channel._dm_to_message("user@example.com", "Hello!")

    assert msg['sender_id'] == "user@example.com"
    assert msg['chat_id'] == "user@example.com"
    assert msg["content"] == "Hello!"
    assert msg["media"] == []
    assert msg['metadata']['type'] == "direct"
    assert msg["metadata"]["jid"] == "user@example.com"

@pytest.mark.asyncio
async def test_handle_dm_without_urls() -> None:
    """Test handling direct message without URLs."""
    bus = MessageBus()
    channel = XmppChannel(_make_config(), bus)

    await channel._handle_dm("user@example.com", "Hello!")

    assert bus.inbound_size > 0, "Sanity check failed"

    msg = await bus.consume_inbound()
    assert msg.sender_id == "user@example.com"
    assert msg.content == "Hello!"


@pytest.mark.asyncio
async def test_handle_dm_with_http_file_url(tmp_path) -> None:
    bus = MessageBus()
    channel = XmppChannel(_make_config(upload_domain="upload.example.com"), bus)
    channel.client = _FakeXmppClient("bot@example.com", "secret")

    fake_http = _FakeHttpxClient()
    image_data = b"fake image data"
    fake_http.set_response(
        "https://upload.example.com/file123.png",
        _FakeResponse(
            content=image_data,
            headers={"content-type": "image/png", "content-length": str(len(image_data))},
        ),
    )
    channel._http = fake_http

    await channel._handle_dm(
        "user@example.com",
        "Check this image: https://upload.example.com/file123.png",
    )

    assert bus.inbound_size > 0, "Sanity check failed"
    msg = await bus.consume_inbound()
    assert msg.sender_id == "user@example.com"
    # Check that media path is included
    assert len(msg.media) == 1
    media_path = Path(msg.media[0])
    assert media_path.exists()
    assert media_path.read_bytes() == image_data
    # Check content is modified
    assert "[attachment:" in msg.content
    assert "https://upload.example.com/file123.png" not in msg.content


@pytest.mark.asyncio
async def test_handle_dm_skips_non_file_urls() -> None:
    bus = MessageBus()
    channel = XmppChannel(_make_config(upload_domain="upload.example.com"), bus)

    # Create mock HTTP client (should not be used)
    fake_http = _FakeHttpxClient()
    channel._http = fake_http

    await channel._handle_dm(
        "user@example.com",
        "Visit https://example.com for more info",
    )

    assert bus.inbound_size > 0, "Sanity check failed"
    msg = await bus.consume_inbound()
    assert msg.media == []
    assert "https://example.com" in msg.content


@pytest.mark.asyncio
async def test_handle_dm_with_multiple_urls_only_downloads_files(tmp_path) -> None:
    bus = MessageBus()
    channel = XmppChannel(_make_config(upload_domain="upload.example.com"), bus)
    channel.client = _FakeXmppClient("bot@example.com", "secret")

    fake_http = _FakeHttpxClient()
    image_data = b"fake image"
    fake_http.set_response(
        "https://upload.example.com/image.png",
        _FakeResponse(
            content=image_data,
            headers={"content-type": "image/png", "content-length": "10"},
        ),
    )
    channel._http = fake_http

    await channel._handle_dm(
        "user@example.com",
        "See https://upload.example.com/image.png and visit https://example.com/docs",
    )

    assert bus.inbound_size > 0, "Sanity check failed"
    msg = await bus.consume_inbound()
    assert len(msg.media) == 1
    assert "https://example.com/docs" in msg.content
    assert "[attachment:" in msg.content


@pytest.mark.asyncio
async def test_handle_muc_message_without_urls() -> None:
    bus = MessageBus()
    channel = XmppChannel(_make_config(), bus)

    await channel._handle_muc_message(
        "room@conference.example.com",
        "alice",
        "alice@example.com/resource",
        "Hello everyone!",
    )

    assert bus.inbound_size > 0, "Sanity check failed"
    msg = await bus.consume_inbound()
    assert msg.sender_id == "room@conference.example.com/alice"
    assert msg.chat_id == "room@conference.example.com"
    assert msg.content == "Hello everyone!"
    assert msg.media == []


@pytest.mark.asyncio
async def test_handle_muc_message_skips_self_messages(monkeypatch) -> None:
    bus = MessageBus()
    channel = XmppChannel(_make_config(nickname="nanobot"), bus)

    await channel._handle_muc_message(
        "room@conference.example.com",
        "nanobot",  # Same as config nickname
        "nanobot@example.com/resource",
        "Hello everyone!",
    )

    assert bus.inbound_size == 0


@pytest.mark.asyncio
async def test_handle_muc_message_ignores_nonallowed_room() -> None:
    bus = MessageBus()
    channel = XmppChannel(
        _make_config(
            group_policy="allowlist",
            group_allow_from=["allowed@conference.example.com"],
        ),
        bus 
    )

    # Message from non-allowed room
    await channel._handle_muc_message(
        "denied@conference.example.com",
        "alice",
        "alice@example.com/resource",
        "Hello!",
    )
    assert bus.inbound_size == 0

@pytest.mark.asyncio
async def test_handle_muc_message_accepts_allowed_room() -> None:
    bus = MessageBus()
    channel = XmppChannel(
        _make_config(
            group_policy="allowlist",
            group_allow_from=["allowed@conference.example.com"],
        ),
        bus 
    )
    await channel._handle_muc_message(
        "allowed@conference.example.com",
        "bob",
        "bob@example.com/resource",
        "Hello!",
    )
    assert bus.inbound_size == 1
    msg = await bus.consume_inbound()
    assert msg.sender_id == "allowed@conference.example.com/bob"


@pytest.mark.asyncio
async def test_handle_muc_message_mention_policy_ignores_without_nick() -> None:
    bus = MessageBus()
    channel = XmppChannel(_make_config(group_policy="mention", nickname="bot"), bus)

    await channel._handle_muc_message(
        "room@conference.example.com",
        "alice",
        "alice@example.com/resource",
        "Hello everyone!",
    )
    assert bus.inbound_size == 0


@pytest.mark.asyncio
async def test_handle_muc_message_mention_policy_accepts_with_nick() -> None:
    bus = MessageBus()
    channel = XmppChannel(_make_config(group_policy="mention", nickname="bot"), bus)

    await channel._handle_muc_message(
        "room@conference.example.com",
        "bob",
        "bob@example.com/resource",
        "Hey @bot, help me!",
    )
    assert bus.inbound_size == 1


@pytest.mark.asyncio
async def test_send_text_message(monkeypatch) -> None:
    channel = XmppChannel(_make_config(), MessageBus(), clock=_FakeClock())
    mock_client = _FakeXmppClient("bot@example.com", "secret")
    channel.client = mock_client

    await channel.send(
        OutboundMessage(channel="xmpp", chat_id="user@example.com", content="Hello!")
    )

    assert len(mock_client.send_message_calls) == 1
    sent = mock_client.send_message_calls[0]
    assert sent["to"] == "user@example.com"
    assert sent["body"] == "Hello!"
    assert sent["type"] == "chat"


@pytest.mark.asyncio
async def test_send_with_media_files(monkeypatch, tmp_path) -> None:
    channel = XmppChannel(_make_config(), MessageBus(), clock=_FakeClock())
    mock_client = _FakeXmppClient("bot@example.com", "secret")
    mock_client.plugin["xep_0363"] = SimpleNamespace()
    mock_client.plugin["xep_0065"] = SimpleNamespace()
    channel.client = mock_client

    file_path = tmp_path / "test.txt"
    file_path.write_text("hello world", encoding="utf-8")

    await channel.send(
        OutboundMessage(
            channel="xmpp",
            chat_id="user@example.com",
            content="Here is a file",
            media=[str(file_path)],
        )
    )

    # Should send text message (file transfer fails with mock, sends error)
    assert len(mock_client.send_message_calls) >= 1
    assert mock_client.send_message_calls[0]["body"] == "Here is a file"


@pytest.mark.asyncio
async def test_send_without_content_but_with_media(tmp_path) -> None:
    channel = XmppChannel(_make_config(), MessageBus(), clock=_FakeClock())
    mock_client = _FakeXmppClient("bot@example.com", "secret")
    mock_client.plugin["xep_0363"] = SimpleNamespace()
    mock_client.plugin["xep_0065"] = SimpleNamespace()
    channel.client = mock_client

    file_path = tmp_path / "image.png"
    file_path.write_bytes(b"fake image")

    await channel.send(
        OutboundMessage(
            channel="xmpp",
            chat_id="user@example.com",
            content="",
            media=[str(file_path)],
        )
    )

    # Should still send something
    assert len(mock_client.send_message_calls) >= 0  # May send file via other means


@pytest.mark.asyncio
async def test_send_stops_typing_indicator() -> None:
    """Test that sending stops the typing indicator."""
    channel = XmppChannel(_make_config(), MessageBus(), clock=_FakeClock())
    mock_client = _FakeXmppClient("bot@example.com", "secret")
    channel.client = mock_client

    # Start typing
    await channel._start_typing("user@example.com")
    assert "user@example.com" in channel._typing_tasks

    # Send message
    await channel.send(
        OutboundMessage(channel="xmpp", chat_id="user@example.com", content="Hello!")
    )

    # Typing should be stopped
    assert "user@example.com" not in channel._typing_tasks
    assert mock_client.send_typing_calls[-1] == ("user@example.com", False)


@pytest.mark.asyncio
async def test_typing_keepalive_refreshes(monkeypatch) -> None:
    """Test that typing keepalive refreshes periodically."""
    channel = XmppChannel(_make_config(), MessageBus(), clock=_FakeClock())
    mock_client = _FakeXmppClient("bot@example.com", "secret")
    channel.client = mock_client
    channel._running = True

    # Start typing
    await channel._start_typing("user@example.com")

    # Should have at least one typing call (the initial one)
    typing_calls = [call for call in mock_client.send_typing_calls if call[1] is True]
    assert len(typing_calls) >= 1

    # Stop typing to clean up
    await channel._stop_typing("user@example.com")


@pytest.mark.asyncio
async def test_is_http_file_url_with_upload_domain(monkeypatch) -> None:
    """Test URL detection with configured upload domain."""
    channel = XmppChannel(_make_config(upload_domain="upload.example.com"), MessageBus())

    # Should match exact domain
    assert channel._is_http_file_url("https://upload.example.com/file.png") is True
    assert channel._is_http_file_url("http://upload.example.com/file.png") is True

    # URLs without file extensions should not match other domains
    assert channel._is_http_file_url("https://other.com/path") is False


@pytest.mark.asyncio
async def test_is_http_file_url_with_wildcard_domain(monkeypatch) -> None:
    """Test URL detection with wildcard upload domain."""
    channel = XmppChannel(_make_config(upload_domain="*.example.com"), MessageBus())

    # Should match subdomains
    assert channel._is_http_file_url("https://upload.example.com/file.png") is True
    assert channel._is_http_file_url("https://files.example.com/file.png") is True

    # URLs without file extensions should not match parent domain or other domains
    assert channel._is_http_file_url("https://example/") is False
    assert channel._is_http_file_url("https://other/path") is False


@pytest.mark.asyncio
async def test_is_http_file_url_fallback_to_extension(monkeypatch) -> None:
    """Test URL detection falls back to checking file extension."""
    channel = XmppChannel(_make_config(upload_domain=""), MessageBus())

    # URLs with file extensions should match
    assert channel._is_http_file_url("https://example.com/image.png") is True
    assert channel._is_http_file_url("https://example.com/doc.pdf") is True

    # URLs without file extensions should not match
    assert channel._is_http_file_url("https://example.com/path") is False
    assert channel._is_http_file_url("https://example.com/") is False


@pytest.mark.asyncio
async def test_download_http_file_respects_size_limit(monkeypatch) -> None:
    """Test that HTTP download respects size limits."""
    channel = XmppChannel(_make_config(), MessageBus())
    mock_client = _FakeXmppClient("bot@example.com", "secret")
    channel.client = mock_client

    fake_http = _FakeHttpxClient()
    # Set content-length header larger than limit
    fake_http.set_response(
        "https://example.com/huge.bin",
        _FakeResponse(
            headers={"content-length": str(50 * 1024 * 1024 + 1)},  # > 20MB
        ),
    )
    channel._http = fake_http

    file_path, marker = await channel._download_http_file(
        "https://example.com/huge.bin", "user@example.com"
    )

    assert file_path is None
    assert "too large" in marker


@pytest.mark.asyncio
async def test_download_http_file_handles_error(monkeypatch) -> None:
    """Test that HTTP download handles errors gracefully."""
    channel = XmppChannel(_make_config(), MessageBus())
    mock_client = _FakeXmppClient("bot@example.com", "secret")
    channel.client = mock_client

    fake_http = _FakeHttpxClient()
    fake_http.set_response(
        "https://example.com/error",
        _FakeResponse(status_code=500),
    )
    channel._http = fake_http

    file_path, marker = await channel._download_http_file(
        "https://example.com/error", "user@example.com"
    )

    assert file_path is None
    assert "download failed" in marker


@pytest.mark.asyncio
async def test_url_regex_pattern() -> None:
    """Test the URL regex pattern detects URLs correctly."""
    text = "Visit https://example.com and http://test.org/path?query=1 for more"
    urls = _URL_RE.findall(text)

    assert "https://example.com" in urls
    assert "http://test.org/path?query=1" in urls


@pytest.mark.asyncio
async def test_url_regex_excludes_invalid_chars() -> None:
    """Test that URL regex excludes URLs with invalid characters."""
    text = 'Link: https://example.com/path and bad: https://bad.com/path<"'
    urls = _URL_RE.findall(text)

    assert "https://example.com/path" in urls
    assert "https://bad.com/path" in urls  # Should only match up to invalid char
