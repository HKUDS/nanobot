import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

# Check optional QQ dependencies before running tests
try:
    from nanobot.channels import qq
    QQ_AVAILABLE = getattr(qq, "QQ_AVAILABLE", False)
except ImportError:
    QQ_AVAILABLE = False

if not QQ_AVAILABLE:
    pytest.skip("QQ dependencies not installed (qq-botpy)", allow_module_level=True)

import aiohttp

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.qq import QQChannel, QQConfig


class _FakeApi:
    def __init__(self) -> None:
        self.c2c_calls: list[dict] = []
        self.group_calls: list[dict] = []

    async def post_c2c_message(self, **kwargs) -> None:
        self.c2c_calls.append(kwargs)

    async def post_group_message(self, **kwargs) -> None:
        self.group_calls.append(kwargs)


class _FakeClient:
    def __init__(self) -> None:
        self.api = _FakeApi()


@pytest.mark.asyncio
async def test_on_group_message_routes_to_group_chat_id() -> None:
    channel = QQChannel(QQConfig(app_id="app", secret="secret", allow_from=["user1"]), MessageBus())

    data = SimpleNamespace(
        id="msg1",
        content="hello",
        group_openid="group123",
        author=SimpleNamespace(member_openid="user1"),
        attachments=[],
    )

    await channel._on_message(data, is_group=True)

    msg = await channel.bus.consume_inbound()
    assert msg.sender_id == "user1"
    assert msg.chat_id == "group123"


@pytest.mark.asyncio
async def test_send_group_message_uses_plain_text_group_api_with_msg_seq() -> None:
    channel = QQChannel(QQConfig(app_id="app", secret="secret", allow_from=["*"]), MessageBus())
    channel._client = _FakeClient()
    channel._chat_type_cache["group123"] = "group"

    await channel.send(
        OutboundMessage(
            channel="qq",
            chat_id="group123",
            content="hello",
            metadata={"message_id": "msg1"},
        )
    )

    assert len(channel._client.api.group_calls) == 1
    call = channel._client.api.group_calls[0]
    assert call == {
        "group_openid": "group123",
        "msg_type": 0,
        "content": "hello",
        "msg_id": "msg1",
        "msg_seq": 2,
    }
    assert not channel._client.api.c2c_calls


@pytest.mark.asyncio
async def test_send_c2c_message_uses_plain_text_c2c_api_with_msg_seq() -> None:
    channel = QQChannel(QQConfig(app_id="app", secret="secret", allow_from=["*"]), MessageBus())
    channel._client = _FakeClient()

    await channel.send(
        OutboundMessage(
            channel="qq",
            chat_id="user123",
            content="hello",
            metadata={"message_id": "msg1"},
        )
    )

    assert len(channel._client.api.c2c_calls) == 1
    call = channel._client.api.c2c_calls[0]
    assert call == {
        "openid": "user123",
        "msg_type": 0,
        "content": "hello",
        "msg_id": "msg1",
        "msg_seq": 2,
    }
    assert not channel._client.api.group_calls


@pytest.mark.asyncio
async def test_send_group_message_uses_markdown_when_configured() -> None:
    channel = QQChannel(
        QQConfig(app_id="app", secret="secret", allow_from=["*"], msg_format="markdown"),
        MessageBus(),
    )
    channel._client = _FakeClient()
    channel._chat_type_cache["group123"] = "group"

    await channel.send(
        OutboundMessage(
            channel="qq",
            chat_id="group123",
            content="**hello**",
            metadata={"message_id": "msg1"},
        )
    )

    assert len(channel._client.api.group_calls) == 1
    call = channel._client.api.group_calls[0]
    assert call == {
        "group_openid": "group123",
        "msg_type": 2,
        "markdown": {"content": "**hello**"},
        "msg_id": "msg1",
        "msg_seq": 2,
    }


@pytest.mark.asyncio
async def test_read_media_bytes_local_path() -> None:
    channel = QQChannel(QQConfig(app_id="app", secret="secret"), MessageBus())

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"\x89PNG\r\n")
        tmp_path = f.name

    data, filename = await channel._read_media_bytes(tmp_path)
    assert data == b"\x89PNG\r\n"
    assert filename == Path(tmp_path).name


@pytest.mark.asyncio
async def test_read_media_bytes_file_uri() -> None:
    channel = QQChannel(QQConfig(app_id="app", secret="secret"), MessageBus())

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        f.write(b"JFIF")
        tmp_path = f.name

    data, filename = await channel._read_media_bytes(f"file://{tmp_path}")
    assert data == b"JFIF"
    assert filename == Path(tmp_path).name


@pytest.mark.asyncio
async def test_read_media_bytes_missing_file() -> None:
    channel = QQChannel(QQConfig(app_id="app", secret="secret"), MessageBus())

    data, filename = await channel._read_media_bytes("/nonexistent/path/image.png")
    assert data is None
    assert filename is None


# -------------------------------------------------------
# Tests for _send_media exception handling
# -------------------------------------------------------

def _make_channel_with_local_file(suffix: str = ".png", content: bytes = b"\x89PNG\r\n"):
    """Create a QQChannel with a fake client and a temp file for media."""
    channel = QQChannel(
        QQConfig(app_id="app", secret="secret", allow_from=["*"]),
        MessageBus(),
    )
    channel._client = _FakeClient()
    channel._chat_type_cache["user1"] = "c2c"

    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.write(content)
    tmp.close()
    return channel, tmp.name


@pytest.mark.asyncio
async def test_send_media_network_error_propagates() -> None:
    """aiohttp.ClientError (network/transport) should re-raise, not return False."""
    channel, tmp_path = _make_channel_with_local_file()

    # Make the base64 upload raise a network error
    channel._client.api._http = SimpleNamespace()
    channel._client.api._http.request = AsyncMock(
        side_effect=aiohttp.ServerDisconnectedError("connection lost"),
    )

    with pytest.raises(aiohttp.ServerDisconnectedError):
        await channel._send_media(
            chat_id="user1",
            media_ref=tmp_path,
            msg_id="msg1",
            is_group=False,
        )


@pytest.mark.asyncio
async def test_send_media_client_connector_error_propagates() -> None:
    """aiohttp.ClientConnectorError (DNS/connection refused) should re-raise."""
    channel, tmp_path = _make_channel_with_local_file()

    from aiohttp.client_reqrep import ConnectionKey
    conn_key = ConnectionKey("api.qq.com", 443, True, None, None, None, None)
    connector_error = aiohttp.ClientConnectorError(
        connection_key=conn_key,
        os_error=OSError("Connection refused"),
    )

    channel._client.api._http = SimpleNamespace()
    channel._client.api._http.request = AsyncMock(
        side_effect=connector_error,
    )

    with pytest.raises(aiohttp.ClientConnectorError):
        await channel._send_media(
            chat_id="user1",
            media_ref=tmp_path,
            msg_id="msg1",
            is_group=False,
        )


@pytest.mark.asyncio
async def test_send_media_oserror_propagates() -> None:
    """OSError (low-level I/O) should re-raise for retry."""
    channel, tmp_path = _make_channel_with_local_file()

    channel._client.api._http = SimpleNamespace()
    channel._client.api._http.request = AsyncMock(
        side_effect=OSError("Network is unreachable"),
    )

    with pytest.raises(OSError):
        await channel._send_media(
            chat_id="user1",
            media_ref=tmp_path,
            msg_id="msg1",
            is_group=False,
        )


@pytest.mark.asyncio
async def test_send_media_api_error_returns_false() -> None:
    """API-level errors (botpy RuntimeError subclasses) should return False, not raise."""
    channel, tmp_path = _make_channel_with_local_file()

    # Simulate a botpy API error (e.g. ServerError is a RuntimeError subclass)
    from botpy.errors import ServerError

    channel._client.api._http = SimpleNamespace()
    channel._client.api._http.request = AsyncMock(
        side_effect=ServerError("internal server error"),
    )

    result = await channel._send_media(
        chat_id="user1",
        media_ref=tmp_path,
        msg_id="msg1",
        is_group=False,
    )
    assert result is False


@pytest.mark.asyncio
async def test_send_media_generic_runtime_error_returns_false() -> None:
    """Generic RuntimeError (not network) should return False."""
    channel, tmp_path = _make_channel_with_local_file()

    channel._client.api._http = SimpleNamespace()
    channel._client.api._http.request = AsyncMock(
        side_effect=RuntimeError("some API error"),
    )

    result = await channel._send_media(
        chat_id="user1",
        media_ref=tmp_path,
        msg_id="msg1",
        is_group=False,
    )
    assert result is False


@pytest.mark.asyncio
async def test_send_media_value_error_returns_false() -> None:
    """ValueError (bad API response data) should return False."""
    channel, tmp_path = _make_channel_with_local_file()

    channel._client.api._http = SimpleNamespace()
    channel._client.api._http.request = AsyncMock(
        side_effect=ValueError("bad response data"),
    )

    result = await channel._send_media(
        chat_id="user1",
        media_ref=tmp_path,
        msg_id="msg1",
        is_group=False,
    )
    assert result is False


@pytest.mark.asyncio
async def test_send_media_timeout_error_propagates() -> None:
    """asyncio.TimeoutError inherits from Exception but not ClientError/OSError.
    However, aiohttp.ServerTimeoutError IS a ClientError subclass, so that propagates.
    For a plain TimeoutError (which is also OSError in Python 3.11+), it should propagate."""
    channel, tmp_path = _make_channel_with_local_file()

    channel._client.api._http = SimpleNamespace()
    channel._client.api._http.request = AsyncMock(
        side_effect=aiohttp.ServerTimeoutError("request timed out"),
    )

    with pytest.raises(aiohttp.ServerTimeoutError):
        await channel._send_media(
            chat_id="user1",
            media_ref=tmp_path,
            msg_id="msg1",
            is_group=False,
        )


@pytest.mark.asyncio
async def test_send_fallback_text_on_api_error() -> None:
    """When _send_media returns False (API error), send() should emit fallback text."""
    channel, tmp_path = _make_channel_with_local_file()

    from botpy.errors import ServerError

    channel._client.api._http = SimpleNamespace()
    channel._client.api._http.request = AsyncMock(
        side_effect=ServerError("internal server error"),
    )

    await channel.send(
        OutboundMessage(
            channel="qq",
            chat_id="user1",
            content="",
            media=[tmp_path],
            metadata={"message_id": "msg1"},
        )
    )

    # Should have sent a fallback text message
    assert len(channel._client.api.c2c_calls) == 1
    fallback_content = channel._client.api.c2c_calls[0]["content"]
    assert "Attachment send failed" in fallback_content


@pytest.mark.asyncio
async def test_send_propagates_network_error_no_fallback() -> None:
    """When _send_media raises a network error, send() should NOT silently fallback."""
    channel, tmp_path = _make_channel_with_local_file()

    channel._client.api._http = SimpleNamespace()
    channel._client.api._http.request = AsyncMock(
        side_effect=aiohttp.ServerDisconnectedError("connection lost"),
    )

    with pytest.raises(aiohttp.ServerDisconnectedError):
        await channel.send(
            OutboundMessage(
                channel="qq",
                chat_id="user1",
                content="hello",
                media=[tmp_path],
                metadata={"message_id": "msg1"},
            )
        )

    # No fallback text should have been sent
    assert len(channel._client.api.c2c_calls) == 0
