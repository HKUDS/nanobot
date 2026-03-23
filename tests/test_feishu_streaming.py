"""Tests for Feishu streaming (send_delta) via interactive card PATCH."""
import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from nanobot.bus.queue import MessageBus
from nanobot.channels.feishu import FeishuChannel, FeishuConfig, _FeishuStreamBuf


def _make_channel(streaming: bool = True) -> FeishuChannel:
    config = FeishuConfig(
        enabled=True,
        app_id="cli_test",
        app_secret="secret",
        allow_from=["*"],
        streaming=streaming,
    )
    ch = FeishuChannel(config, MessageBus())
    ch._client = MagicMock()
    ch._loop = None
    return ch


def _mock_create_response(message_id: str = "om_stream_001"):
    resp = MagicMock()
    resp.success.return_value = True
    resp.data = SimpleNamespace(message_id=message_id)
    return resp


def _mock_patch_response(success: bool = True):
    resp = MagicMock()
    resp.success.return_value = success
    resp.code = 0 if success else 99999
    resp.msg = "ok" if success else "error"
    return resp


class TestFeishuStreamingConfig:
    def test_streaming_default_true(self):
        assert FeishuConfig().streaming is True

    def test_supports_streaming_when_enabled(self):
        ch = _make_channel(streaming=True)
        assert ch.supports_streaming is True

    def test_supports_streaming_disabled(self):
        ch = _make_channel(streaming=False)
        assert ch.supports_streaming is False


class TestStreamingCard:
    def test_card_with_cursor(self):
        card = FeishuChannel._streaming_card("Hello")
        assert card["config"]["update_multi"] is True
        assert "`▍`" in card["elements"][0]["content"]

    def test_card_without_cursor(self):
        card = FeishuChannel._streaming_card("Done", streaming=False)
        assert "`▍`" not in card["elements"][0]["content"]
        assert "Done" in card["elements"][0]["content"]


class TestSendDelta:
    @pytest.mark.asyncio
    async def test_first_delta_creates_card(self):
        ch = _make_channel()
        ch._client.im.v1.message.create.return_value = _mock_create_response("om_new")

        await ch.send_delta("oc_chat1", "Hello ")

        assert "oc_chat1" in ch._stream_bufs
        buf = ch._stream_bufs["oc_chat1"]
        assert buf.text == "Hello "
        assert buf.message_id == "om_new"
        ch._client.im.v1.message.create.assert_called_once()
        call_args = ch._client.im.v1.message.create.call_args
        assert call_args is not None

    @pytest.mark.asyncio
    async def test_second_delta_within_interval_skips_patch(self):
        ch = _make_channel()
        buf = _FeishuStreamBuf(text="Hello ", message_id="om_1", last_edit=time.monotonic())
        ch._stream_bufs["oc_chat1"] = buf

        await ch.send_delta("oc_chat1", "world")

        assert buf.text == "Hello world"
        ch._client.im.v1.message.patch.assert_not_called()

    @pytest.mark.asyncio
    async def test_delta_after_interval_patches_card(self):
        ch = _make_channel()
        buf = _FeishuStreamBuf(text="Hello ", message_id="om_1", last_edit=time.monotonic() - 1.0)
        ch._stream_bufs["oc_chat1"] = buf

        ch._client.im.v1.message.patch.return_value = _mock_patch_response()
        await ch.send_delta("oc_chat1", "world")

        assert buf.text == "Hello world"
        ch._client.im.v1.message.patch.assert_called_once()

    @pytest.mark.asyncio
    async def test_stream_end_pops_buf_and_patches_final(self):
        ch = _make_channel()
        ch._stream_bufs["oc_chat1"] = _FeishuStreamBuf(
            text="Final content", message_id="om_1", last_edit=0.0,
        )
        ch._client.im.v1.message.patch.return_value = _mock_patch_response()

        await ch.send_delta("oc_chat1", "", metadata={"_stream_end": True})

        assert "oc_chat1" not in ch._stream_bufs
        ch._client.im.v1.message.patch.assert_called_once()

    @pytest.mark.asyncio
    async def test_stream_end_without_buf_is_noop(self):
        ch = _make_channel()
        await ch.send_delta("oc_chat1", "", metadata={"_stream_end": True})
        ch._client.im.v1.message.patch.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_delta_skips_send(self):
        ch = _make_channel()
        await ch.send_delta("oc_chat1", "   ")

        assert "oc_chat1" in ch._stream_bufs
        ch._client.im.v1.message.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_client_returns_early(self):
        ch = _make_channel()
        ch._client = None
        await ch.send_delta("oc_chat1", "text")
        assert "oc_chat1" not in ch._stream_bufs


class TestSendMessageReturnsId:
    def test_returns_message_id_on_success(self):
        ch = _make_channel()
        ch._client.im.v1.message.create.return_value = _mock_create_response("om_abc")
        result = ch._send_message_sync("chat_id", "oc_chat1", "text", '{"text":"hi"}')
        assert result == "om_abc"

    def test_returns_none_on_failure(self):
        ch = _make_channel()
        resp = MagicMock()
        resp.success.return_value = False
        resp.code = 99999
        resp.msg = "error"
        resp.get_log_id.return_value = "log1"
        ch._client.im.v1.message.create.return_value = resp
        result = ch._send_message_sync("chat_id", "oc_chat1", "text", '{"text":"hi"}')
        assert result is None


class TestPatchCard:
    def test_patch_success(self):
        ch = _make_channel()
        ch._client.im.v1.message.patch.return_value = _mock_patch_response(True)
        assert ch._patch_card_sync("om_1", {"elements": []}) is True

    def test_patch_failure(self):
        ch = _make_channel()
        ch._client.im.v1.message.patch.return_value = _mock_patch_response(False)
        assert ch._patch_card_sync("om_1", {"elements": []}) is False

    def test_patch_exception(self):
        ch = _make_channel()
        ch._client.im.v1.message.patch.side_effect = RuntimeError("network")
        assert ch._patch_card_sync("om_1", {"elements": []}) is False
