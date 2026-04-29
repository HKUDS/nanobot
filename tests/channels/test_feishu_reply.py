"""Tests for Feishu message reply (quote) feature."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Check optional Feishu dependencies before running tests
try:
    from nanobot.channels import feishu
    FEISHU_AVAILABLE = getattr(feishu, "FEISHU_AVAILABLE", False)
except ImportError:
    FEISHU_AVAILABLE = False

if not FEISHU_AVAILABLE:
    pytest.skip("Feishu dependencies not installed (lark-oapi)", allow_module_level=True)

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.feishu import FeishuChannel, FeishuConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_feishu_channel(reply_to_message: bool = False, group_policy: str = "mention") -> FeishuChannel:
    config = FeishuConfig(
        enabled=True,
        app_id="cli_test",
        app_secret="secret",
        allow_from=["*"],
        reply_to_message=reply_to_message,
        group_policy=group_policy,
    )
    channel = FeishuChannel(config, MessageBus())
    channel._client = MagicMock()
    # _loop is only used by the WebSocket thread bridge; not needed for unit tests
    channel._loop = None
    return channel


def _make_feishu_event(
    *,
    message_id: str = "om_001",
    chat_id: str = "oc_abc",
    chat_type: str = "p2p",
    msg_type: str = "text",
    content: str = '{"text": "hello"}',
    sender_open_id: str = "ou_alice",
    parent_id: str | None = None,
    root_id: str | None = None,
):
    message = SimpleNamespace(
        message_id=message_id,
        chat_id=chat_id,
        chat_type=chat_type,
        message_type=msg_type,
        content=content,
        parent_id=parent_id,
        root_id=root_id,
        mentions=[],
    )
    sender = SimpleNamespace(
        sender_type="user",
        sender_id=SimpleNamespace(open_id=sender_open_id),
    )
    return SimpleNamespace(event=SimpleNamespace(message=message, sender=sender))


def _make_get_message_response(text: str, msg_type: str = "text", success: bool = True):
    """Build a fake im.v1.message.get response object."""
    body = SimpleNamespace(content=json.dumps({"text": text}))
    item = SimpleNamespace(msg_type=msg_type, body=body)
    data = SimpleNamespace(items=[item])
    resp = MagicMock()
    resp.success.return_value = success
    resp.data = data
    resp.code = 0
    resp.msg = "ok"
    return resp


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------

def test_feishu_config_reply_to_message_defaults_false() -> None:
    assert FeishuConfig().reply_to_message is False


def test_feishu_config_reply_to_message_can_be_enabled() -> None:
    config = FeishuConfig(reply_to_message=True)
    assert config.reply_to_message is True


# ---------------------------------------------------------------------------
# _get_message_content_sync tests
# ---------------------------------------------------------------------------

def test_get_message_content_sync_returns_reply_prefix() -> None:
    channel = _make_feishu_channel()
    channel._client.im.v1.message.get.return_value = _make_get_message_response("what time is it?")

    result = channel._get_message_content_sync("om_parent")

    assert result == "[Reply to: what time is it?]"


def test_get_message_content_sync_truncates_long_text() -> None:
    channel = _make_feishu_channel()
    long_text = "x" * (FeishuChannel._REPLY_CONTEXT_MAX_LEN + 50)
    channel._client.im.v1.message.get.return_value = _make_get_message_response(long_text)

    result = channel._get_message_content_sync("om_parent")

    assert result is not None
    assert result.endswith("...]")
    inner = result[len("[Reply to: ") : -1]
    assert len(inner) == FeishuChannel._REPLY_CONTEXT_MAX_LEN + len("...")


def test_get_message_content_sync_returns_none_on_api_failure() -> None:
    channel = _make_feishu_channel()
    resp = MagicMock()
    resp.success.return_value = False
    resp.code = 230002
    resp.msg = "bot not in group"
    channel._client.im.v1.message.get.return_value = resp

    result = channel._get_message_content_sync("om_parent")

    assert result is None


def test_get_message_content_sync_returns_none_for_non_text_type() -> None:
    channel = _make_feishu_channel()
    body = SimpleNamespace(content=json.dumps({"image_key": "img_1"}))
    item = SimpleNamespace(msg_type="image", body=body)
    data = SimpleNamespace(items=[item])
    resp = MagicMock()
    resp.success.return_value = True
    resp.data = data
    channel._client.im.v1.message.get.return_value = resp

    result = channel._get_message_content_sync("om_parent")

    assert result is None


def test_get_message_content_sync_returns_none_when_empty_text() -> None:
    channel = _make_feishu_channel()
    channel._client.im.v1.message.get.return_value = _make_get_message_response("   ")

    result = channel._get_message_content_sync("om_parent")

    assert result is None


# ---------------------------------------------------------------------------
# _reply_message_sync tests
# ---------------------------------------------------------------------------

def test_reply_message_sync_returns_true_on_success() -> None:
    channel = _make_feishu_channel()
    resp = MagicMock()
    resp.success.return_value = True
    channel._client.im.v1.message.reply.return_value = resp

    ok = channel._reply_message_sync("om_parent", "text", '{"text":"hi"}')

    assert ok is True
    channel._client.im.v1.message.reply.assert_called_once()


def test_reply_message_sync_returns_false_on_api_error() -> None:
    channel = _make_feishu_channel()
    resp = MagicMock()
    resp.success.return_value = False
    resp.code = 400
    resp.msg = "bad request"
    resp.get_log_id.return_value = "log_x"
    channel._client.im.v1.message.reply.return_value = resp

    ok = channel._reply_message_sync("om_parent", "text", '{"text":"hi"}')

    assert ok is False


def test_reply_message_sync_returns_false_on_exception() -> None:
    channel = _make_feishu_channel()
    channel._client.im.v1.message.reply.side_effect = RuntimeError("network error")

    ok = channel._reply_message_sync("om_parent", "text", '{"text":"hi"}')

    assert ok is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "expected_msg_type"),
    [
        ("voice.opus", "audio"),
        ("clip.mp4", "media"),
        ("report.pdf", "file"),
    ],
)
async def test_send_uses_expected_feishu_msg_type_for_uploaded_files(
    tmp_path: Path, filename: str, expected_msg_type: str
) -> None:
    channel = _make_feishu_channel()
    file_path = tmp_path / filename
    file_path.write_bytes(b"demo")

    send_calls: list[tuple[str, str, str, str]] = []

    def _record_send(receive_id_type: str, receive_id: str, msg_type: str, content: str) -> None:
        send_calls.append((receive_id_type, receive_id, msg_type, content))

    with patch.object(channel, "_upload_file_sync", return_value="file-key"), patch.object(
        channel, "_send_message_sync", side_effect=_record_send
    ):
        await channel.send(
            OutboundMessage(
                channel="feishu",
                chat_id="oc_test",
                content="",
                media=[str(file_path)],
                metadata={},
            )
        )

    assert len(send_calls) == 1
    receive_id_type, receive_id, msg_type, content = send_calls[0]
    assert receive_id_type == "chat_id"
    assert receive_id == "oc_test"
    assert msg_type == expected_msg_type
    assert json.loads(content) == {"file_key": "file-key"}


# ---------------------------------------------------------------------------
# send() — reply routing tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_uses_reply_api_when_configured() -> None:
    channel = _make_feishu_channel(reply_to_message=True)

    reply_resp = MagicMock()
    reply_resp.success.return_value = True
    channel._client.im.v1.message.reply.return_value = reply_resp

    await channel.send(OutboundMessage(
        channel="feishu",
        chat_id="oc_abc",
        content="hello",
        metadata={"message_id": "om_001"},
    ))

    channel._client.im.v1.message.reply.assert_called_once()
    channel._client.im.v1.message.create.assert_not_called()


@pytest.mark.asyncio
async def test_send_uses_create_api_when_reply_disabled() -> None:
    channel = _make_feishu_channel(reply_to_message=False)

    create_resp = MagicMock()
    create_resp.success.return_value = True
    channel._client.im.v1.message.create.return_value = create_resp

    await channel.send(OutboundMessage(
        channel="feishu",
        chat_id="oc_abc",
        content="hello",
        metadata={"message_id": "om_001"},
    ))

    channel._client.im.v1.message.create.assert_called_once()
    channel._client.im.v1.message.reply.assert_not_called()


@pytest.mark.asyncio
async def test_send_uses_create_api_when_no_message_id() -> None:
    channel = _make_feishu_channel(reply_to_message=True)

    create_resp = MagicMock()
    create_resp.success.return_value = True
    channel._client.im.v1.message.create.return_value = create_resp

    await channel.send(OutboundMessage(
        channel="feishu",
        chat_id="oc_abc",
        content="hello",
        metadata={},
    ))

    channel._client.im.v1.message.create.assert_called_once()
    channel._client.im.v1.message.reply.assert_not_called()


@pytest.mark.asyncio
async def test_send_skips_reply_for_progress_messages() -> None:
    channel = _make_feishu_channel(reply_to_message=True)

    create_resp = MagicMock()
    create_resp.success.return_value = True
    channel._client.im.v1.message.create.return_value = create_resp

    await channel.send(OutboundMessage(
        channel="feishu",
        chat_id="oc_abc",
        content="thinking...",
        metadata={"message_id": "om_001", "_progress": True},
    ))

    channel._client.im.v1.message.create.assert_called_once()
    channel._client.im.v1.message.reply.assert_not_called()


@pytest.mark.asyncio
async def test_send_fallback_to_create_when_reply_fails() -> None:
    channel = _make_feishu_channel(reply_to_message=True)

    reply_resp = MagicMock()
    reply_resp.success.return_value = False
    reply_resp.code = 400
    reply_resp.msg = "error"
    reply_resp.get_log_id.return_value = "log_x"
    channel._client.im.v1.message.reply.return_value = reply_resp

    create_resp = MagicMock()
    create_resp.success.return_value = True
    channel._client.im.v1.message.create.return_value = create_resp

    await channel.send(OutboundMessage(
        channel="feishu",
        chat_id="oc_abc",
        content="hello",
        metadata={"message_id": "om_001"},
    ))

    # reply attempted first, then falls back to create
    channel._client.im.v1.message.reply.assert_called_once()
    channel._client.im.v1.message.create.assert_called_once()


# ---------------------------------------------------------------------------
# _on_message — parent_id / root_id metadata tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_on_message_captures_parent_and_root_id_in_metadata() -> None:
    channel = _make_feishu_channel()
    channel._processed_message_ids.clear()
    channel._client.im.v1.message.react.return_value = MagicMock(success=lambda: True)

    captured = []

    async def _capture(**kwargs):
        captured.append(kwargs)

    channel._handle_message = _capture

    with patch.object(channel, "_add_reaction", return_value=None):
        await channel._on_message(
            _make_feishu_event(
                parent_id="om_parent",
                root_id="om_root",
            )
        )

    assert len(captured) == 1
    meta = captured[0]["metadata"]
    assert meta["parent_id"] == "om_parent"
    assert meta["root_id"] == "om_root"
    assert meta["message_id"] == "om_001"


@pytest.mark.asyncio
async def test_on_message_parent_and_root_id_none_when_absent() -> None:
    channel = _make_feishu_channel()
    channel._processed_message_ids.clear()

    captured = []

    async def _capture(**kwargs):
        captured.append(kwargs)

    channel._handle_message = _capture

    with patch.object(channel, "_add_reaction", return_value=None):
        await channel._on_message(_make_feishu_event())

    assert len(captured) == 1
    meta = captured[0]["metadata"]
    assert meta["parent_id"] is None
    assert meta["root_id"] is None


@pytest.mark.asyncio
async def test_on_message_prepends_reply_context_when_parent_id_present() -> None:
    channel = _make_feishu_channel()
    channel._processed_message_ids.clear()
    channel._client.im.v1.message.get.return_value = _make_get_message_response("original question")

    captured = []

    async def _capture(**kwargs):
        captured.append(kwargs)

    channel._handle_message = _capture

    with patch.object(channel, "_add_reaction", return_value=None):
        await channel._on_message(
            _make_feishu_event(
                content='{"text": "my answer"}',
                parent_id="om_parent",
            )
        )

    assert len(captured) == 1
    content = captured[0]["content"]
    assert content.startswith("[Reply to: original question]")
    assert "my answer" in content


@pytest.mark.asyncio
async def test_on_message_no_extra_api_call_when_no_parent_id() -> None:
    channel = _make_feishu_channel()
    channel._processed_message_ids.clear()

    captured = []

    async def _capture(**kwargs):
        captured.append(kwargs)

    channel._handle_message = _capture

    with patch.object(channel, "_add_reaction", return_value=None):
        await channel._on_message(_make_feishu_event())

    channel._client.im.v1.message.get.assert_not_called()
    assert len(captured) == 1


# ---------------------------------------------------------------------------
# Session key derivation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_key_group_with_root_id_is_thread_scoped() -> None:
    """Group message with root_id gets a thread-scoped session key."""
    channel = _make_feishu_channel(group_policy="open")
    bus_spy = []
    original_publish = channel.bus.publish_inbound

    async def capture(msg):
        bus_spy.append(msg)
        await original_publish(msg)

    channel.bus.publish_inbound = capture
    channel._download_and_save_media = AsyncMock(return_value=(None, ""))
    channel.transcribe_audio = AsyncMock(return_value="")
    channel._add_reaction = AsyncMock(return_value=None)

    event = _make_feishu_event(
        chat_type="group",
        content='{"text": "hello"}',
        root_id="om_root123",
        message_id="om_child456",
    )
    await channel._on_message(event)

    assert len(bus_spy) == 1
    assert bus_spy[0].session_key == "feishu:oc_abc:om_root123"


@pytest.mark.asyncio
async def test_session_key_group_no_root_id_uses_message_id() -> None:
    """Group message without root_id gets session keyed by message_id (per-message session)."""
    channel = _make_feishu_channel(group_policy="open")
    bus_spy = []
    original_publish = channel.bus.publish_inbound

    async def capture(msg):
        bus_spy.append(msg)
        await original_publish(msg)

    channel.bus.publish_inbound = capture
    channel._download_and_save_media = AsyncMock(return_value=(None, ""))
    channel.transcribe_audio = AsyncMock(return_value="")
    channel._add_reaction = AsyncMock(return_value=None)

    event = _make_feishu_event(
        chat_type="group",
        content='{"text": "hello"}',
        root_id=None,
        message_id="om_001",
    )
    await channel._on_message(event)

    assert len(bus_spy) == 1
    assert bus_spy[0].session_key == "feishu:oc_abc:om_001"


@pytest.mark.asyncio
async def test_session_key_private_chat_no_override() -> None:
    """Private chat never overrides session key (consistent with Telegram/Slack)."""
    channel = _make_feishu_channel()
    bus_spy = []
    original_publish = channel.bus.publish_inbound

    async def capture(msg):
        bus_spy.append(msg)
        await original_publish(msg)

    channel.bus.publish_inbound = capture
    channel._download_and_save_media = AsyncMock(return_value=(None, ""))
    channel.transcribe_audio = AsyncMock(return_value="")
    channel._add_reaction = AsyncMock(return_value=None)

    event = _make_feishu_event(
        chat_type="p2p",
        content='{"text": "hello"}',
        root_id=None,
        message_id="om_001",
    )
    await channel._on_message(event)

    assert len(bus_spy) == 1
    assert bus_spy[0].session_key_override is None


# ---------------------------------------------------------------------------
# reply_in_thread tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reply_uses_reply_in_thread_when_enabled() -> None:
    """When reply_to_message is True, reply includes reply_in_thread=True."""
    channel = _make_feishu_channel(reply_to_message=True)

    reply_resp = MagicMock()
    reply_resp.success.return_value = True
    channel._client.im.v1.message.reply.return_value = reply_resp

    await channel.send(OutboundMessage(
        channel="feishu",
        chat_id="oc_abc",
        content="hello",
        metadata={"message_id": "om_001"},
    ))

    channel._client.im.v1.message.reply.assert_called_once()
    call_args = channel._client.im.v1.message.reply.call_args
    request = call_args[0][0]
    assert request.request_body.reply_in_thread is True


@pytest.mark.asyncio
async def test_reply_without_reply_in_thread_when_disabled() -> None:
    """When reply_to_message is False, reply does NOT use reply_in_thread."""
    channel = _make_feishu_channel(reply_to_message=False)

    create_resp = MagicMock()
    create_resp.success.return_value = True
    channel._client.im.v1.message.create.return_value = create_resp

    await channel.send(OutboundMessage(
        channel="feishu",
        chat_id="oc_abc",
        content="hello",
    ))

    # No message_id in metadata → no reply attempt, direct create
    channel._client.im.v1.message.create.assert_called_once()


@pytest.mark.asyncio
async def test_reply_keeps_fallback_when_reply_fails() -> None:
    """Even with reply_to_message=True, fallback to create on reply failure."""
    channel = _make_feishu_channel(reply_to_message=True)

    reply_resp = MagicMock()
    reply_resp.success.return_value = False
    reply_resp.code = 99991400
    reply_resp.msg = "rate limited"
    channel._client.im.v1.message.reply.return_value = reply_resp

    create_resp = MagicMock()
    create_resp.success.return_value = True
    channel._client.im.v1.message.create.return_value = create_resp

    await channel.send(OutboundMessage(
        channel="feishu",
        chat_id="oc_abc",
        content="hello",
        metadata={"message_id": "om_001"},
    ))

    channel._client.im.v1.message.reply.assert_called()
    channel._client.im.v1.message.create.assert_called()


@pytest.mark.asyncio
async def test_reply_no_reply_in_thread_for_p2p_chat() -> None:
    """reply_in_thread should NOT be set for p2p chats (identified by chat_type)."""
    channel = _make_feishu_channel(reply_to_message=True)

    reply_resp = MagicMock()
    reply_resp.success.return_value = True
    channel._client.im.v1.message.reply.return_value = reply_resp

    await channel.send(OutboundMessage(
        channel="feishu",
        chat_id="oc_abc",  # p2p chats also use oc_ prefix
        content="hello",
        metadata={"message_id": "om_001", "chat_type": "p2p"},
    ))

    channel._client.im.v1.message.reply.assert_called_once()
    call_args = channel._client.im.v1.message.reply.call_args
    request = call_args[0][0]
    assert request.request_body.reply_in_thread is not True


@pytest.mark.asyncio
async def test_reply_uses_reply_in_thread_for_group_chat() -> None:
    """reply_in_thread should be True for group chats (identified by chat_type)."""
    channel = _make_feishu_channel(reply_to_message=True)

    reply_resp = MagicMock()
    reply_resp.success.return_value = True
    channel._client.im.v1.message.reply.return_value = reply_resp

    await channel.send(OutboundMessage(
        channel="feishu",
        chat_id="oc_abc",
        content="hello",
        metadata={"message_id": "om_001", "chat_type": "group"},
    ))

    channel._client.im.v1.message.reply.assert_called_once()
    call_args = channel._client.im.v1.message.reply.call_args
    request = call_args[0][0]
    assert request.request_body.reply_in_thread is True


@pytest.mark.asyncio
async def test_reply_targets_message_id_when_in_topic() -> None:
    """When inbound message is inside a topic (root_id != message_id),
    the reply should target the inbound message_id (not root_id).
    The Feishu Reply API keeps the response in the same topic
    automatically when the target message is already inside a topic."""
    channel = _make_feishu_channel(reply_to_message=True)

    reply_resp = MagicMock()
    reply_resp.success.return_value = True
    channel._client.im.v1.message.reply.return_value = reply_resp

    await channel.send(OutboundMessage(
        channel="feishu",
        chat_id="oc_abc",
        content="hello",
        metadata={
            "message_id": "om_child456",
            "chat_type": "group",
            "root_id": "om_root123",
        },
    ))

    channel._client.im.v1.message.reply.assert_called_once()
    call_args = channel._client.im.v1.message.reply.call_args
    request = call_args[0][0]
    # Should reply to the inbound message_id, not the root
    assert request.message_id == "om_child456"
    assert request.request_body.reply_in_thread is True


def test_on_reaction_added_stores_reaction_id() -> None:
    """_on_reaction_added stores the returned reaction_id in _reaction_ids."""
    channel = _make_feishu_channel()
    loop = asyncio.new_event_loop()
    try:
        task = loop.create_task(asyncio.sleep(0, result="reaction_abc"))
        loop.run_until_complete(task)
        channel._on_reaction_added("om_001", task)
    finally:
        loop.close()

    assert channel._reaction_ids["om_001"] == "reaction_abc"


def test_on_reaction_added_skips_none_result() -> None:
    """_on_reaction_added does not store None results."""
    channel = _make_feishu_channel()
    loop = asyncio.new_event_loop()
    try:
        task = loop.create_task(asyncio.sleep(0, result=None))
        loop.run_until_complete(task)
        channel._on_reaction_added("om_001", task)
    finally:
        loop.close()

    assert "om_001" not in channel._reaction_ids


def test_on_background_task_done_removes_from_set() -> None:
    """_on_background_task_done removes task from tracking set."""
    channel = _make_feishu_channel()
    loop = asyncio.new_event_loop()
    try:
        async def _fail():
            raise RuntimeError("test failure")

        task = loop.create_task(_fail())
        channel._background_tasks.add(task)
        try:
            loop.run_until_complete(task)
        except RuntimeError:
            pass  # expected
        channel._on_background_task_done(task)
    finally:
        loop.close()

    assert task not in channel._background_tasks
