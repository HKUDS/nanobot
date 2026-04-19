"""Tests for Feishu reaction add/remove and auto-cleanup on stream end."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.bus.queue import MessageBus
from nanobot.channels.feishu import FeishuChannel, FeishuConfig, _FeishuStreamBuf


def _make_channel() -> FeishuChannel:
    config = FeishuConfig(
        enabled=True,
        app_id="cli_test",
        app_secret="secret",
        allow_from=["*"],
    )
    ch = FeishuChannel(config, MessageBus())
    ch._client = MagicMock()
    ch._loop = None
    return ch


def _mock_reaction_create_response(reaction_id: str = "reaction_001", success: bool = True):
    resp = MagicMock()
    resp.success.return_value = success
    resp.code = 0 if success else 99999
    resp.msg = "ok" if success else "error"
    if success:
        resp.data = SimpleNamespace(reaction_id=reaction_id)
    else:
        resp.data = None
    return resp


# ── _add_reaction_sync ──────────────────────────────────────────────────────


class TestAddReactionSync:
    def test_returns_reaction_id_on_success(self):
        ch = _make_channel()
        ch._client.im.v1.message_reaction.create.return_value = _mock_reaction_create_response("rx_42")
        result = ch._add_reaction_sync("om_001", "THUMBSUP")
        assert result == "rx_42"

    def test_returns_none_when_response_fails(self):
        ch = _make_channel()
        ch._client.im.v1.message_reaction.create.return_value = _mock_reaction_create_response(success=False)
        assert ch._add_reaction_sync("om_001", "THUMBSUP") is None

    def test_returns_none_when_response_data_is_none(self):
        ch = _make_channel()
        resp = MagicMock()
        resp.success.return_value = True
        resp.data = None
        ch._client.im.v1.message_reaction.create.return_value = resp
        assert ch._add_reaction_sync("om_001", "THUMBSUP") is None

    def test_returns_none_on_exception(self):
        ch = _make_channel()
        ch._client.im.v1.message_reaction.create.side_effect = RuntimeError("network error")
        assert ch._add_reaction_sync("om_001", "THUMBSUP") is None


# ── _add_reaction (async) ───────────────────────────────────────────────────


class TestAddReactionAsync:
    @pytest.mark.asyncio
    async def test_returns_reaction_id(self):
        ch = _make_channel()
        ch._add_reaction_sync = MagicMock(return_value="rx_99")
        result = await ch._add_reaction("om_001", "EYES")
        assert result == "rx_99"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_client(self):
        ch = _make_channel()
        ch._client = None
        result = await ch._add_reaction("om_001", "THUMBSUP")
        assert result is None


# ── _remove_reaction_sync ───────────────────────────────────────────────────


class TestRemoveReactionSync:
    def test_calls_delete_on_success(self):
        ch = _make_channel()
        resp = MagicMock()
        resp.success.return_value = True
        ch._client.im.v1.message_reaction.delete.return_value = resp

        ch._remove_reaction_sync("om_001", "rx_42")

        ch._client.im.v1.message_reaction.delete.assert_called_once()

    def test_handles_failure_gracefully(self):
        ch = _make_channel()
        resp = MagicMock()
        resp.success.return_value = False
        resp.code = 99999
        resp.msg = "not found"
        ch._client.im.v1.message_reaction.delete.return_value = resp

        # Should not raise
        ch._remove_reaction_sync("om_001", "rx_42")

    def test_handles_exception_gracefully(self):
        ch = _make_channel()
        ch._client.im.v1.message_reaction.delete.side_effect = RuntimeError("network error")

        # Should not raise
        ch._remove_reaction_sync("om_001", "rx_42")


# ── _remove_reaction (async) ────────────────────────────────────────────────


class TestRemoveReactionAsync:
    @pytest.mark.asyncio
    async def test_calls_sync_helper(self):
        ch = _make_channel()
        ch._remove_reaction_sync = MagicMock()

        await ch._remove_reaction("om_001", "rx_42")

        ch._remove_reaction_sync.assert_called_once_with("om_001", "rx_42")

    @pytest.mark.asyncio
    async def test_noop_when_no_client(self):
        ch = _make_channel()
        ch._client = None
        ch._remove_reaction_sync = MagicMock()

        await ch._remove_reaction("om_001", "rx_42")

        ch._remove_reaction_sync.assert_not_called()

    @pytest.mark.asyncio
    async def test_noop_when_reaction_id_is_empty(self):
        ch = _make_channel()
        ch._remove_reaction_sync = MagicMock()

        await ch._remove_reaction("om_001", "")

        ch._remove_reaction_sync.assert_not_called()

    @pytest.mark.asyncio
    async def test_noop_when_reaction_id_is_none(self):
        ch = _make_channel()
        ch._remove_reaction_sync = MagicMock()

        await ch._remove_reaction("om_001", None)

        ch._remove_reaction_sync.assert_not_called()


# ── send_delta stream end: reaction auto-cleanup ────────────────────────────


class TestStreamEndReactionCleanup:
    @pytest.mark.asyncio
    async def test_removes_reaction_on_stream_end(self):
        ch = _make_channel()
        ch._stream_bufs["oc_chat1"] = _FeishuStreamBuf(
            text="Done", card_id="card_1", sequence=3, last_edit=0.0,
        )
        ch._reaction_ids["om_001"] = "rx_42"
        ch._client.cardkit.v1.card_element.content.return_value = MagicMock(success=MagicMock(return_value=True))
        ch._client.cardkit.v1.card.settings.return_value = MagicMock(success=MagicMock(return_value=True))
        ch._remove_reaction = AsyncMock()

        await ch.send_delta(
            "oc_chat1", "",
            metadata={"_stream_end": True, "message_id": "om_001"},
        )

        ch._remove_reaction.assert_called_once_with("om_001", "rx_42")

    @pytest.mark.asyncio
    async def test_no_removal_when_message_id_missing(self):
        ch = _make_channel()
        ch._stream_bufs["oc_chat1"] = _FeishuStreamBuf(
            text="Done", card_id="card_1", sequence=3, last_edit=0.0,
        )
        ch._client.cardkit.v1.card_element.content.return_value = MagicMock(success=MagicMock(return_value=True))
        ch._client.cardkit.v1.card.settings.return_value = MagicMock(success=MagicMock(return_value=True))
        ch._remove_reaction = AsyncMock()

        await ch.send_delta(
            "oc_chat1", "",
            metadata={"_stream_end": True, "reaction_id": "rx_42"},
        )

        ch._remove_reaction.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_removal_when_reaction_id_missing(self):
        ch = _make_channel()
        ch._stream_bufs["oc_chat1"] = _FeishuStreamBuf(
            text="Done", card_id="card_1", sequence=3, last_edit=0.0,
        )
        ch._client.cardkit.v1.card_element.content.return_value = MagicMock(success=MagicMock(return_value=True))
        ch._client.cardkit.v1.card.settings.return_value = MagicMock(success=MagicMock(return_value=True))
        ch._remove_reaction = AsyncMock()

        await ch.send_delta(
            "oc_chat1", "",
            metadata={"_stream_end": True, "message_id": "om_001"},
        )

        ch._remove_reaction.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_removal_when_both_ids_missing(self):
        ch = _make_channel()
        ch._stream_bufs["oc_chat1"] = _FeishuStreamBuf(
            text="Done", card_id="card_1", sequence=3, last_edit=0.0,
        )
        ch._client.cardkit.v1.card_element.content.return_value = MagicMock(success=MagicMock(return_value=True))
        ch._client.cardkit.v1.card.settings.return_value = MagicMock(success=MagicMock(return_value=True))
        ch._remove_reaction = AsyncMock()

        await ch.send_delta("oc_chat1", "", metadata={"_stream_end": True})

        ch._remove_reaction.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_removal_when_not_stream_end(self):
        ch = _make_channel()
        ch._remove_reaction = AsyncMock()

        await ch.send_delta(
            "oc_chat1", "more text",
            metadata={"message_id": "om_001", "reaction_id": "rx_42"},
        )

        ch._remove_reaction.assert_not_called()
