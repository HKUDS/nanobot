"""Tests for QQ channel ack_message feature.

Covers the four verification points from the PR:
1. C2C message: ack appears instantly
2. Group message: ack appears instantly
3. ack_message set to "": no ack sent
4. Custom ack_message text: correct text delivered
Each test also verifies that normal message processing is not blocked.
"""

from types import SimpleNamespace

import pytest

try:
    from nanobot.channels import qq

    QQ_AVAILABLE = getattr(qq, "QQ_AVAILABLE", False)
except ImportError:
    QQ_AVAILABLE = False

if not QQ_AVAILABLE:
    pytest.skip("QQ dependencies not installed (qq-botpy)", allow_module_level=True)

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
async def test_ack_sent_on_c2c_message() -> None:
    """Ack is sent immediately for C2C messages, then normal processing continues."""
    channel = QQChannel(
        QQConfig(
            app_id="app",
            secret="secret",
            allow_from=["*"],
            ack_message="⏳ Processing...",
        ),
        MessageBus(),
    )
    channel._client = _FakeClient()

    data = SimpleNamespace(
        id="msg1",
        content="hello",
        author=SimpleNamespace(user_openid="user1"),
        attachments=[],
    )
    await channel._on_message(data, is_group=False)

    assert len(channel._client.api.c2c_calls) >= 1
    ack_call = channel._client.api.c2c_calls[0]
    assert ack_call["content"] == "⏳ Processing..."
    assert ack_call["openid"] == "user1"
    assert ack_call["msg_id"] == "msg1"
    assert ack_call["msg_type"] == 0

    msg = await channel.bus.consume_inbound()
    assert msg.content == "hello"
    assert msg.sender_id == "user1"


@pytest.mark.asyncio
async def test_ack_sent_on_group_message() -> None:
    """Ack is sent immediately for group messages, then normal processing continues."""
    channel = QQChannel(
        QQConfig(
            app_id="app",
            secret="secret",
            allow_from=["*"],
            ack_message="⏳ Processing...",
        ),
        MessageBus(),
    )
    channel._client = _FakeClient()

    data = SimpleNamespace(
        id="msg2",
        content="hello group",
        group_openid="group123",
        author=SimpleNamespace(member_openid="user1"),
        attachments=[],
    )
    await channel._on_message(data, is_group=True)

    assert len(channel._client.api.group_calls) >= 1
    ack_call = channel._client.api.group_calls[0]
    assert ack_call["content"] == "⏳ Processing..."
    assert ack_call["group_openid"] == "group123"
    assert ack_call["msg_id"] == "msg2"
    assert ack_call["msg_type"] == 0

    msg = await channel.bus.consume_inbound()
    assert msg.content == "hello group"
    assert msg.chat_id == "group123"


@pytest.mark.asyncio
async def test_no_ack_when_ack_message_empty() -> None:
    """Setting ack_message to empty string disables the ack entirely."""
    channel = QQChannel(
        QQConfig(
            app_id="app",
            secret="secret",
            allow_from=["*"],
            ack_message="",
        ),
        MessageBus(),
    )
    channel._client = _FakeClient()

    data = SimpleNamespace(
        id="msg3",
        content="hello",
        author=SimpleNamespace(user_openid="user1"),
        attachments=[],
    )
    await channel._on_message(data, is_group=False)

    assert len(channel._client.api.c2c_calls) == 0
    assert len(channel._client.api.group_calls) == 0

    msg = await channel.bus.consume_inbound()
    assert msg.content == "hello"


@pytest.mark.asyncio
async def test_custom_ack_message_text() -> None:
    """Custom Chinese ack_message text is delivered correctly."""
    custom = "正在处理中，请稍候..."
    channel = QQChannel(
        QQConfig(
            app_id="app",
            secret="secret",
            allow_from=["*"],
            ack_message=custom,
        ),
        MessageBus(),
    )
    channel._client = _FakeClient()

    data = SimpleNamespace(
        id="msg4",
        content="test input",
        author=SimpleNamespace(user_openid="user1"),
        attachments=[],
    )
    await channel._on_message(data, is_group=False)

    assert len(channel._client.api.c2c_calls) >= 1
    ack_call = channel._client.api.c2c_calls[0]
    assert ack_call["content"] == custom

    msg = await channel.bus.consume_inbound()
    assert msg.content == "test input"
