"""Tests for the Signal channel implementation."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.signal import (
    SignalChannel,
    SignalConfig,
    SignalDMConfig,
    SignalGroupConfig,
)

# ---------------------------------------------------------------------------
# Fake HTTP client
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code: int = 200, body: dict | None = None) -> None:
        self.status_code = status_code
        self._body = body or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return self._body


class _FakeHTTPClient:
    """Minimal httpx.AsyncClient stand-in that records requests."""

    def __init__(self, *, default_response: dict | None = None) -> None:
        self.posts: list[dict] = []
        self.gets: list[str] = []
        self._response = _FakeResponse(body=default_response or {"result": {"timestamp": 123}})
        self.closed = False

    async def get(self, path: str) -> _FakeResponse:
        self.gets.append(path)
        return self._response

    async def post(self, path: str, *, json: dict) -> _FakeResponse:
        self.posts.append({"path": path, "json": json})
        return self._response

    async def aclose(self) -> None:
        self.closed = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_channel(
    *,
    phone_number: str = "+10000000000",
    dm_enabled: bool = True,
    dm_policy: str = "open",
    dm_allow_from: list[str] | None = None,
    group_enabled: bool = False,
    group_policy: str = "open",
    group_allow_from: list[str] | None = None,
    require_mention: bool = True,
    group_buffer_size: int = 20,
) -> SignalChannel:
    config = SignalConfig(
        enabled=True,
        phone_number=phone_number,
        dm=SignalDMConfig(
            enabled=dm_enabled,
            policy=dm_policy,
            allow_from=dm_allow_from or [],
        ),
        group=SignalGroupConfig(
            enabled=group_enabled,
            policy=group_policy,
            allow_from=group_allow_from or [],
            require_mention=require_mention,
        ),
        group_message_buffer_size=group_buffer_size,
    )
    return SignalChannel(config, MessageBus())


def _dm_envelope(
    *,
    source_number: str = "+19995550001",
    source_uuid: str | None = None,
    source_name: str | None = "Alice",
    message: str = "hello",
    attachments: list | None = None,
    reaction: dict | None = None,
    timestamp: int = 1000,
) -> dict:
    data_message: dict = {"message": message, "timestamp": timestamp}
    if attachments is not None:
        data_message["attachments"] = attachments
    if reaction is not None:
        data_message["reaction"] = reaction
    envelope: dict = {
        "sourceNumber": source_number,
        "sourceName": source_name,
        "dataMessage": data_message,
    }
    if source_uuid:
        envelope["sourceUuid"] = source_uuid
    return {"envelope": envelope}


def _group_envelope(
    *,
    source_number: str = "+19995550001",
    source_name: str = "Bob",
    group_id: str = "group123==",
    message: str = "hey group",
    mentions: list | None = None,
    timestamp: int = 2000,
    use_v2: bool = False,
) -> dict:
    group_obj = {"groupId": group_id}
    key = "groupV2" if use_v2 else "groupInfo"
    data_message: dict = {
        "message": message,
        "timestamp": timestamp,
        key: group_obj,
        "mentions": mentions or [],
    }
    return {
        "envelope": {
            "sourceNumber": source_number,
            "sourceName": source_name,
            "dataMessage": data_message,
        }
    }


# ---------------------------------------------------------------------------
# Static utility tests
# ---------------------------------------------------------------------------


class TestNormalizeSignalId:
    def test_phone_number_kept_and_stripped(self):
        result = SignalChannel._normalize_signal_id("+12345678901")
        assert "+12345678901" in result
        assert "12345678901" in result

    def test_digits_only_gets_plus_prefix(self):
        result = SignalChannel._normalize_signal_id("12345678901")
        assert "+12345678901" in result

    def test_lowercase_variant_added(self):
        result = SignalChannel._normalize_signal_id("SOME-UUID")
        assert "some-uuid" in result

    def test_empty_string_returns_empty(self):
        assert SignalChannel._normalize_signal_id("") == []

    def test_whitespace_stripped(self):
        result = SignalChannel._normalize_signal_id("  +1234  ")
        assert "+1234" in result


class TestCollectSenderIdParts:
    def test_collects_source_number(self):
        env = {"sourceNumber": "+15551234567"}
        parts = SignalChannel._collect_sender_id_parts(env)
        assert "+15551234567" in parts

    def test_collects_multiple_keys(self):
        env = {"sourceNumber": "+15551234567", "sourceUuid": "uuid-abc"}
        parts = SignalChannel._collect_sender_id_parts(env)
        assert "+15551234567" in parts
        assert "uuid-abc" in parts

    def test_deduplicates(self):
        env = {"sourceNumber": "+15551234567", "source": "+15551234567"}
        parts = SignalChannel._collect_sender_id_parts(env)
        assert parts.count("+15551234567") == 1

    def test_ignores_non_string_values(self):
        env = {"sourceNumber": 12345, "sourceUuid": None}
        parts = SignalChannel._collect_sender_id_parts(env)
        assert parts == []

    def test_empty_envelope_returns_empty(self):
        assert SignalChannel._collect_sender_id_parts({}) == []


class TestPrimarySenderId:
    def test_prefers_phone_number(self):
        assert SignalChannel._primary_sender_id(["+1234", "uuid-abc"]) == "+1234"

    def test_accepts_digit_only(self):
        assert SignalChannel._primary_sender_id(["1234567890", "uuid-abc"]) == "1234567890"

    def test_falls_back_to_first_part(self):
        assert SignalChannel._primary_sender_id(["uuid-abc", "other"]) == "uuid-abc"

    def test_empty_list_returns_empty(self):
        assert SignalChannel._primary_sender_id([]) == ""


class TestExtractGroupId:
    def test_extracts_from_group_info(self):
        gid = SignalChannel._extract_group_id({"groupId": "abc=="}, None)
        assert gid == "abc=="

    def test_extracts_from_group_v2(self):
        gid = SignalChannel._extract_group_id(None, {"id": "xyz=="})
        assert gid == "xyz=="

    def test_prefers_group_info_over_v2(self):
        gid = SignalChannel._extract_group_id({"groupId": "first"}, {"groupId": "second"})
        assert gid == "first"

    def test_returns_none_when_both_none(self):
        assert SignalChannel._extract_group_id(None, None) is None

    def test_returns_none_when_not_dicts(self):
        assert SignalChannel._extract_group_id("bad", 123) is None


class TestIsGroupChatId:
    def test_base64_with_equals_is_group(self):
        assert SignalChannel._is_group_chat_id("abc==") is True

    def test_long_id_without_dash_is_group(self):
        long_id = "a" * 41
        assert SignalChannel._is_group_chat_id(long_id) is True

    def test_phone_number_is_not_group(self):
        assert SignalChannel._is_group_chat_id("+12345678901") is False

    def test_uuid_with_dashes_is_not_group(self):
        assert SignalChannel._is_group_chat_id("550e8400-e29b-41d4-a716-446655440000") is False


class TestRecipientParams:
    def test_group_chat_uses_group_id(self):
        ch = _make_channel()
        params = ch._recipient_params("abc==")
        assert params == {"groupId": "abc=="}

    def test_dm_uses_recipient_list(self):
        ch = _make_channel()
        params = ch._recipient_params("+12345678901")
        assert params == {"recipient": ["+12345678901"]}


class TestMentionHelpers:
    def test_mention_id_candidates_extracts_number(self):
        mention = {"number": "+1234567890"}
        ids = SignalChannel._mention_id_candidates(mention)
        assert "+1234567890" in ids

    def test_mention_id_candidates_extracts_uuid(self):
        mention = {"uuid": "some-uuid"}
        ids = SignalChannel._mention_id_candidates(mention)
        assert "some-uuid" in ids

    def test_mention_span_valid(self):
        assert SignalChannel._mention_span({"start": 0, "length": 5}) == (0, 5)

    def test_mention_span_negative_start(self):
        assert SignalChannel._mention_span({"start": -1, "length": 5}) is None

    def test_mention_span_zero_length(self):
        assert SignalChannel._mention_span({"start": 0, "length": 0}) is None

    def test_mention_span_missing_keys(self):
        assert SignalChannel._mention_span({}) is None

    def test_leading_placeholder_ufffc(self):
        span = SignalChannel._leading_placeholder_span("￼ hello")
        assert span == (0, 1)

    def test_leading_placeholder_not_at_start(self):
        assert SignalChannel._leading_placeholder_span("hello ￼") is None

    def test_leading_placeholder_empty_string(self):
        assert SignalChannel._leading_placeholder_span("") is None

    def test_leading_placeholder_plain_text(self):
        assert SignalChannel._leading_placeholder_span("hello") is None


# ---------------------------------------------------------------------------
# Account ID alias / mention matching
# ---------------------------------------------------------------------------


class TestAccountIdAliases:
    def test_phone_number_alias_registered_on_init(self):
        ch = _make_channel(phone_number="+10000000000")
        assert ch._id_matches_account("+10000000000")

    def test_digit_only_variant_matches(self):
        ch = _make_channel(phone_number="+10000000000")
        assert ch._id_matches_account("10000000000")

    def test_remember_alias_adds_uuid(self):
        ch = _make_channel()
        ch._remember_account_id_alias("some-uuid-abc")
        assert ch._id_matches_account("some-uuid-abc")

    def test_non_matching_id_returns_false(self):
        ch = _make_channel(phone_number="+10000000000")
        assert not ch._id_matches_account("+19999999999")

    def test_none_and_non_string_return_false(self):
        ch = _make_channel()
        assert not ch._id_matches_account(None)


# ---------------------------------------------------------------------------
# _should_respond_in_group
# ---------------------------------------------------------------------------


class TestShouldRespondInGroup:
    def _make_group_channel(self, require_mention: bool = True) -> SignalChannel:
        return _make_channel(
            phone_number="+10000000000",
            group_enabled=True,
            require_mention=require_mention,
        )

    def test_no_require_mention_always_responds(self):
        ch = self._make_group_channel(require_mention=False)
        assert ch._should_respond_in_group("anything", []) is True

    def test_require_mention_with_no_mentions_returns_false(self):
        ch = self._make_group_channel(require_mention=True)
        assert ch._should_respond_in_group("hello", []) is False

    def test_require_mention_with_bot_number_mention(self):
        ch = self._make_group_channel(require_mention=True)
        mentions = [{"number": "+10000000000", "start": 0, "length": 12}]
        assert ch._should_respond_in_group("￼ hello", mentions) is True

    def test_require_mention_with_uuid_mention(self):
        ch = self._make_group_channel(require_mention=True)
        ch._remember_account_id_alias("bot-uuid-123")
        mentions = [{"uuid": "bot-uuid-123", "start": 0, "length": 8}]
        assert ch._should_respond_in_group("￼ hello", mentions) is True

    def test_identifier_less_leading_mention_accepted(self):
        ch = self._make_group_channel(require_mention=True)
        # Mention with no IDs but leading span — treated as bot mention
        mentions = [{"start": 0, "length": 1}]
        assert ch._should_respond_in_group("￼ hello", mentions) is True

    def test_identifier_less_non_leading_mention_rejected(self):
        ch = self._make_group_channel(require_mention=True)
        mentions = [{"start": 5, "length": 1}]
        assert ch._should_respond_in_group("hello ￼", mentions) is False

    def test_leading_placeholder_without_mentions_metadata(self):
        ch = self._make_group_channel(require_mention=True)
        assert ch._should_respond_in_group("￼ hello", []) is True

    def test_phone_number_in_text_triggers_response(self):
        ch = self._make_group_channel(require_mention=True)
        assert ch._should_respond_in_group("hey +10000000000 help", []) is True


# ---------------------------------------------------------------------------
# _strip_bot_mention
# ---------------------------------------------------------------------------


class TestStripBotMention:
    def _make_channel_with_number(self) -> SignalChannel:
        return _make_channel(phone_number="+10000000000")

    def test_strips_mention_by_phone(self):
        ch = self._make_channel_with_number()
        text = "￼ hello"
        mentions = [{"number": "+10000000000", "start": 0, "length": 1}]
        result = ch._strip_bot_mention(text, mentions)
        assert result == "hello"

    def test_strips_identifier_less_leading_mention(self):
        ch = self._make_channel_with_number()
        text = "￼ hello"
        mentions = [{"start": 0, "length": 1}]
        result = ch._strip_bot_mention(text, mentions)
        assert result == "hello"

    def test_strips_leading_placeholder_without_mention_metadata(self):
        ch = self._make_channel_with_number()
        text = "￼ hello"
        result = ch._strip_bot_mention(text, [])
        assert result == "hello"

    def test_non_bot_mention_mid_text_not_stripped(self):
        # A non-bot mention that is NOT a leading placeholder leaves the text alone.
        ch = self._make_channel_with_number()
        text = "hello ￼ world"
        mentions = [{"number": "+19999999999", "start": 6, "length": 1}]
        result = ch._strip_bot_mention(text, mentions)
        # Mid-text placeholder from a non-bot mention should be untouched
        assert "￼" in result

    def test_empty_text_returned_unchanged(self):
        ch = self._make_channel_with_number()
        assert ch._strip_bot_mention("", []) == ""


# ---------------------------------------------------------------------------
# Group message buffer
# ---------------------------------------------------------------------------


class TestGroupBuffer:
    def test_add_and_get_context(self):
        ch = _make_channel(group_buffer_size=5)
        ch._add_to_group_buffer("g1", "Alice", "+1111", "first msg", 1000)
        ch._add_to_group_buffer("g1", "Bob", "+2222", "second msg", 2000)
        # Only messages before the latest are returned as context
        ctx = ch._get_group_buffer_context("g1")
        assert "first msg" in ctx
        # The last message is not included (it's the "current" one)
        assert "second msg" not in ctx

    def test_empty_context_when_only_one_message(self):
        ch = _make_channel(group_buffer_size=5)
        ch._add_to_group_buffer("g1", "Alice", "+1111", "only msg", 1000)
        assert ch._get_group_buffer_context("g1") == ""

    def test_empty_context_when_group_unknown(self):
        ch = _make_channel()
        assert ch._get_group_buffer_context("unknown") == ""

    def test_buffer_respects_max_size(self):
        ch = _make_channel(group_buffer_size=3)
        for i in range(10):
            ch._add_to_group_buffer("g1", "Alice", "+1111", f"msg{i}", i)
        assert len(ch._group_buffers["g1"]) == 3

    def test_zero_buffer_size_does_not_add(self):
        ch = _make_channel(group_buffer_size=0)
        ch._add_to_group_buffer("g1", "Alice", "+1111", "msg", 1000)
        assert "g1" not in ch._group_buffers

    def test_context_limits_message_length(self):
        ch = _make_channel(group_buffer_size=5)
        long_msg = "x" * 500
        ch._add_to_group_buffer("g1", "Alice", "+1111", long_msg, 1000)
        ch._add_to_group_buffer("g1", "Bob", "+2222", "short", 2000)
        ctx = ch._get_group_buffer_context("g1")
        # Context is capped at 200 chars per message
        assert len(ctx.split("Alice: ", 1)[1]) <= 200


# ---------------------------------------------------------------------------
# _handle_data_message — DM routing
# ---------------------------------------------------------------------------


class TestHandleDataMessageDM:
    def _make_dm_channel(self, policy="open", allow_from=None) -> tuple[SignalChannel, list]:
        ch = _make_channel(dm_enabled=True, dm_policy=policy, dm_allow_from=allow_from or [])
        handled: list[dict] = []

        async def capture(**kwargs):
            handled.append(kwargs)

        ch._handle_message = capture  # type: ignore[method-assign]

        async def noop_typing(chat_id):
            pass

        ch._start_typing = noop_typing  # type: ignore[method-assign]
        return ch, handled

    @pytest.mark.asyncio
    async def test_dm_open_policy_accepted(self):
        ch, handled = self._make_dm_channel(policy="open")
        params = _dm_envelope(source_number="+19995550001", message="hi")
        await ch._handle_receive_notification(params)
        assert len(handled) == 1
        assert handled[0]["chat_id"] == "+19995550001"
        assert handled[0]["content"] == "hi"

    @pytest.mark.asyncio
    async def test_dm_allowlist_accepted(self):
        ch, handled = self._make_dm_channel(policy="allowlist", allow_from=["+19995550001"])
        params = _dm_envelope(source_number="+19995550001")
        await ch._handle_receive_notification(params)
        assert len(handled) == 1

    @pytest.mark.asyncio
    async def test_dm_allowlist_rejected(self):
        ch, handled = self._make_dm_channel(policy="allowlist", allow_from=["+10000000001"])
        params = _dm_envelope(source_number="+19995550002")
        await ch._handle_receive_notification(params)
        assert handled == []

    @pytest.mark.asyncio
    async def test_dm_disabled_rejected(self):
        ch = _make_channel(dm_enabled=False)
        handled: list[dict] = []

        async def capture(**kwargs):
            handled.append(kwargs)

        ch._handle_message = capture  # type: ignore[method-assign]

        async def noop_typing(chat_id):
            pass

        ch._start_typing = noop_typing  # type: ignore[method-assign]
        params = _dm_envelope(source_number="+19995550001")
        await ch._handle_receive_notification(params)
        assert handled == []

    @pytest.mark.asyncio
    async def test_reaction_message_ignored(self):
        ch, handled = self._make_dm_channel()
        params = _dm_envelope(reaction={"emoji": "👍", "targetTimestamp": 999})
        await ch._handle_receive_notification(params)
        assert handled == []

    @pytest.mark.asyncio
    async def test_empty_message_ignored(self):
        ch, handled = self._make_dm_channel()
        params = _dm_envelope(message="")
        await ch._handle_receive_notification(params)
        assert handled == []

    @pytest.mark.asyncio
    async def test_receipt_message_ignored(self):
        ch, handled = self._make_dm_channel()
        notification = {
            "envelope": {
                "sourceNumber": "+19995550001",
                "receiptMessage": {"when": 1234},
            }
        }
        await ch._handle_receive_notification(notification)
        assert handled == []

    @pytest.mark.asyncio
    async def test_typing_indicator_ignored(self):
        ch, handled = self._make_dm_channel()
        notification = {
            "envelope": {
                "sourceNumber": "+19995550001",
                "typingMessage": {"action": "STARTED"},
            }
        }
        await ch._handle_receive_notification(notification)
        assert handled == []

    @pytest.mark.asyncio
    async def test_missing_envelope_ignored(self):
        ch, handled = self._make_dm_channel()
        await ch._handle_receive_notification({})
        assert handled == []

    @pytest.mark.asyncio
    async def test_metadata_passed_to_handle(self):
        ch, handled = self._make_dm_channel()
        params = _dm_envelope(source_number="+19995550001", source_name="Alice", timestamp=9999)
        await ch._handle_receive_notification(params)
        meta = handled[0]["metadata"]
        assert meta["sender_name"] == "Alice"
        assert meta["timestamp"] == 9999
        assert meta["is_group"] is False

    @pytest.mark.asyncio
    async def test_sender_id_with_uuid_variant(self):
        ch, handled = self._make_dm_channel()
        params = _dm_envelope(source_number="+19995550001", source_uuid="uuid-abc")
        await ch._handle_receive_notification(params)
        assert len(handled) == 1
        # sender_id combines both parts
        assert "+19995550001" in handled[0]["sender_id"]
        assert "uuid-abc" in handled[0]["sender_id"]

    @pytest.mark.asyncio
    async def test_stop_typing_called_on_handle_error(self):
        ch = _make_channel(dm_enabled=True, dm_policy="open")
        typing_stopped: list[str] = []

        async def fail_handle(**kwargs):
            raise RuntimeError("boom")

        async def noop_typing(chat_id):
            pass

        async def record_stop(chat_id, **kwargs):
            typing_stopped.append(chat_id)

        ch._handle_message = fail_handle  # type: ignore[method-assign]
        ch._start_typing = noop_typing  # type: ignore[method-assign]
        ch._stop_typing = record_stop  # type: ignore[method-assign]

        # _handle_receive_notification swallows exceptions; the typing stop
        # still fires from _handle_data_message's except clause.
        params = _dm_envelope(source_number="+19995550001")
        await ch._handle_receive_notification(params)

        assert "+19995550001" in typing_stopped


# ---------------------------------------------------------------------------
# _handle_data_message — group routing
# ---------------------------------------------------------------------------


class TestHandleDataMessageGroup:
    def _make_group_channel(
        self,
        policy="open",
        allow_from=None,
        require_mention=True,
    ) -> tuple[SignalChannel, list]:
        ch = _make_channel(
            group_enabled=True,
            group_policy=policy,
            group_allow_from=allow_from or [],
            require_mention=require_mention,
        )
        handled: list[dict] = []

        async def capture(**kwargs):
            handled.append(kwargs)

        ch._handle_message = capture  # type: ignore[method-assign]

        async def noop_typing(chat_id):
            pass

        ch._start_typing = noop_typing  # type: ignore[method-assign]
        return ch, handled

    @pytest.mark.asyncio
    async def test_group_disabled_rejected(self):
        ch = _make_channel(group_enabled=False)
        handled: list[dict] = []
        ch._handle_message = lambda **kw: handled.append(kw)  # type: ignore[method-assign]
        params = _group_envelope(group_id="grp==", message="hi")
        await ch._handle_receive_notification(params)
        assert handled == []

    @pytest.mark.asyncio
    async def test_group_open_policy_no_mention_blocked_when_required(self):
        ch, handled = self._make_group_channel(require_mention=True)
        params = _group_envelope(group_id="grp==", message="hey everyone")
        await ch._handle_receive_notification(params)
        assert handled == []

    @pytest.mark.asyncio
    async def test_group_open_policy_no_mention_required(self):
        ch, handled = self._make_group_channel(require_mention=False)
        params = _group_envelope(group_id="grp==", message="hey everyone")
        await ch._handle_receive_notification(params)
        assert len(handled) == 1
        assert handled[0]["chat_id"] == "grp=="

    @pytest.mark.asyncio
    async def test_group_allowlist_accepted(self):
        ch, handled = self._make_group_channel(
            policy="allowlist", allow_from=["grp=="], require_mention=False
        )
        params = _group_envelope(group_id="grp==", message="hi")
        await ch._handle_receive_notification(params)
        assert len(handled) == 1

    @pytest.mark.asyncio
    async def test_group_allowlist_rejected(self):
        ch, handled = self._make_group_channel(policy="allowlist", allow_from=["other=="])
        params = _group_envelope(group_id="grp==", message="hi")
        await ch._handle_receive_notification(params)
        assert handled == []

    @pytest.mark.asyncio
    async def test_group_mention_triggers_response(self):
        ch, handled = self._make_group_channel(require_mention=True)
        ch._remember_account_id_alias("+10000000000")
        mentions = [{"number": "+10000000000", "start": 0, "length": 1}]
        params = _group_envelope(group_id="grp==", message="￼ hello", mentions=mentions)
        await ch._handle_receive_notification(params)
        assert len(handled) == 1

    @pytest.mark.asyncio
    async def test_group_v2_id_extracted(self):
        ch, handled = self._make_group_channel(require_mention=False)
        params = _group_envelope(group_id="grpV2==", message="hi", use_v2=True)
        await ch._handle_receive_notification(params)
        assert len(handled) == 1
        assert handled[0]["chat_id"] == "grpV2=="

    @pytest.mark.asyncio
    async def test_group_message_includes_sender_prefix(self):
        ch, handled = self._make_group_channel(require_mention=False)
        params = _group_envelope(group_id="grp==", source_name="Bob", message="hello")
        await ch._handle_receive_notification(params)
        assert "[Bob]:" in handled[0]["content"]

    @pytest.mark.asyncio
    async def test_group_message_context_prepended(self):
        ch, handled = self._make_group_channel(require_mention=False)
        # First message — adds to buffer but no context yet
        params1 = _group_envelope(group_id="grp==", source_name="Alice", message="msg1")
        await ch._handle_receive_notification(params1)
        # Second message — should include context from first
        params2 = _group_envelope(group_id="grp==", source_name="Bob", message="msg2")
        await ch._handle_receive_notification(params2)
        assert "[Recent group messages for context:]" in handled[1]["content"]
        assert "msg1" in handled[1]["content"]

    @pytest.mark.asyncio
    async def test_group_metadata_marks_is_group(self):
        ch, handled = self._make_group_channel(require_mention=False)
        params = _group_envelope(group_id="grp==", message="hi")
        await ch._handle_receive_notification(params)
        assert handled[0]["metadata"]["is_group"] is True
        assert handled[0]["metadata"]["group_id"] == "grp=="

    @pytest.mark.asyncio
    async def test_bot_account_alias_learned_from_incoming(self):
        ch, handled = self._make_group_channel(require_mention=False)
        # If the bot's own UUID appears in an envelope we learn it
        params = _dm_envelope(source_number="+10000000000", source_uuid="new-bot-uuid")
        # DMs from self are processed (learning alias), but DM policy is open
        ch._handle_message = lambda **kw: handled.append(kw)  # type: ignore[method-assign]
        ch._start_typing = lambda chat_id: None  # type: ignore[method-assign]
        await ch._handle_receive_notification(params)
        assert ch._id_matches_account("new-bot-uuid")


# ---------------------------------------------------------------------------
# Command handling
# ---------------------------------------------------------------------------


class TestCommandHandling:
    @pytest.mark.asyncio
    async def test_dm_command_forwarded_to_bus(self):
        """Slash commands in DMs are forwarded to the bus for AgentLoop to handle."""
        ch = _make_channel(dm_enabled=True, dm_policy="open")
        forwarded: list[dict] = []

        async def capture(**kw):
            forwarded.append(kw)

        ch._handle_message = capture  # type: ignore[method-assign]
        ch._start_typing = AsyncMock()

        params = _dm_envelope(source_number="+19995550001", message="/reset")
        await ch._handle_receive_notification(params)

        assert len(forwarded) == 1
        assert forwarded[0]["content"].strip() == "/reset"

    @pytest.mark.asyncio
    async def test_group_command_bypasses_mention_requirement(self):
        """Slash commands in groups bypass the mention requirement and reach the bus."""
        ch = _make_channel(
            group_enabled=True, group_policy="open", require_mention=True
        )
        forwarded: list[dict] = []

        async def capture(**kw):
            forwarded.append(kw)

        ch._handle_message = capture  # type: ignore[method-assign]
        ch._start_typing = AsyncMock()

        params = _group_envelope(source_number="+19995550001", group_id="grp==", message="/reset")
        await ch._handle_receive_notification(params)

        assert len(forwarded) == 1
        assert "/reset" in forwarded[0]["content"]

    @pytest.mark.asyncio
    async def test_command_denied_for_disallowed_dm_sender(self):
        """Commands from senders not on the DM allowlist are dropped."""
        ch = _make_channel(dm_enabled=False)
        forwarded: list[dict] = []

        async def capture(**kw):
            forwarded.append(kw)

        ch._handle_message = capture  # type: ignore[method-assign]

        params = _dm_envelope(source_number="+19995550001", message="/reset")
        await ch._handle_receive_notification(params)

        assert forwarded == []


# ---------------------------------------------------------------------------
# send() — outbound messages
# ---------------------------------------------------------------------------


class TestSend:
    def _make_send_channel(self) -> tuple[SignalChannel, _FakeHTTPClient]:
        ch = _make_channel()
        client = _FakeHTTPClient()
        ch._http = client  # type: ignore[assignment]
        return ch, client

    @pytest.mark.asyncio
    async def test_send_plain_text_posts_rpc(self):
        ch, client = self._make_send_channel()
        msg = OutboundMessage(channel="signal", chat_id="+19995550001", content="hello")
        await ch.send(msg)
        assert len(client.posts) == 1
        payload = client.posts[0]["json"]
        assert payload["method"] == "send"
        assert payload["params"]["message"] == "hello"

    @pytest.mark.asyncio
    async def test_send_with_markdown_includes_text_styles(self):
        ch, client = self._make_send_channel()
        msg = OutboundMessage(channel="signal", chat_id="+19995550001", content="**bold**")
        await ch.send(msg)
        params = client.posts[0]["json"]["params"]
        assert "textStyle" in params
        assert any("BOLD" in s for s in params["textStyle"])

    @pytest.mark.asyncio
    async def test_send_empty_content_skips_rpc(self):
        ch, client = self._make_send_channel()
        msg = OutboundMessage(channel="signal", chat_id="+19995550001", content="")
        await ch.send(msg)
        assert client.posts == []

    @pytest.mark.asyncio
    async def test_send_to_group_uses_group_id(self):
        ch, client = self._make_send_channel()
        msg = OutboundMessage(channel="signal", chat_id="grp==", content="hi group")
        await ch.send(msg)
        params = client.posts[0]["json"]["params"]
        assert "groupId" in params
        assert "recipient" not in params

    @pytest.mark.asyncio
    async def test_send_to_dm_uses_recipient(self):
        ch, client = self._make_send_channel()
        msg = OutboundMessage(channel="signal", chat_id="+19995550001", content="hi")
        await ch.send(msg)
        params = client.posts[0]["json"]["params"]
        assert "recipient" in params

    @pytest.mark.asyncio
    async def test_send_with_media_includes_attachments(self):
        ch, client = self._make_send_channel()
        msg = OutboundMessage(
            channel="signal",
            chat_id="+19995550001",
            content="see attachment",
            media=["/tmp/file.jpg"],
        )
        await ch.send(msg)
        params = client.posts[0]["json"]["params"]
        assert params.get("attachments") == ["/tmp/file.jpg"]

    @pytest.mark.asyncio
    async def test_send_progress_message_does_not_stop_typing(self):
        ch, client = self._make_send_channel()
        stopped: list[str] = []

        async def record_stop(chat_id, **kwargs):
            stopped.append(chat_id)

        ch._stop_typing = record_stop  # type: ignore[method-assign]
        msg = OutboundMessage(
            channel="signal",
            chat_id="+19995550001",
            content="working...",
            metadata={"_progress": True},
        )
        await ch.send(msg)
        # Progress messages should NOT stop the typing indicator
        assert stopped == []

    @pytest.mark.asyncio
    async def test_send_final_message_stops_typing(self):
        ch, client = self._make_send_channel()
        stopped: list[str] = []

        async def record_stop(chat_id, send_stop=True):
            stopped.append(chat_id)

        ch._stop_typing = record_stop  # type: ignore[method-assign]
        msg = OutboundMessage(channel="signal", chat_id="+19995550001", content="done")
        await ch.send(msg)
        assert "+19995550001" in stopped

    @pytest.mark.asyncio
    async def test_send_logs_daemon_error_without_raising(self):
        ch = _make_channel()
        # The daemon returns {"error": {...}} in the JSON body — this is not a Python
        # exception; send() logs it but does not raise (only HTTP-level exceptions raise).
        ch._http = _FakeHTTPClient(default_response={"error": {"message": "fail"}})
        msg = OutboundMessage(channel="signal", chat_id="+19995550001", content="hello")
        await ch.send(msg)  # must not raise


# ---------------------------------------------------------------------------
# stop()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_cancels_sse_task() -> None:
    ch = _make_channel()
    cancelled = False

    async def long_running():
        nonlocal cancelled
        try:
            await asyncio.sleep(9999)
        except asyncio.CancelledError:
            cancelled = True
            raise

    ch._sse_task = asyncio.create_task(long_running())
    # Yield so the task can enter its body (reach the first await) before cancel.
    await asyncio.sleep(0)
    ch._running = True

    await ch.stop()

    assert cancelled
    assert ch._running is False


@pytest.mark.asyncio
async def test_stop_closes_http_client() -> None:
    ch = _make_channel()
    client = _FakeHTTPClient()
    ch._http = client  # type: ignore[assignment]
    ch._running = True

    await ch.stop()

    assert client.closed


@pytest.mark.asyncio
async def test_stop_safe_when_no_sse_task() -> None:
    ch = _make_channel()
    ch._running = True
    # Should not raise even with no _sse_task
    await ch.stop()
    assert ch._running is False


# ---------------------------------------------------------------------------
# _send_request / _send_http_request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_request_increments_id() -> None:
    ch = _make_channel()
    client = _FakeHTTPClient()
    ch._http = client  # type: ignore[assignment]

    await ch._send_request("testMethod", {"key": "val"})
    await ch._send_request("testMethod", {"key": "val"})

    ids = [p["json"]["id"] for p in client.posts]
    assert ids == [1, 2]


@pytest.mark.asyncio
async def test_send_request_raises_when_not_connected() -> None:
    ch = _make_channel()
    # _http is None by default
    with pytest.raises(RuntimeError, match="Not connected"):
        await ch._send_request("testMethod")


# ---------------------------------------------------------------------------
# _handle_receive_notification — envelope shapes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_notification_sync_message_does_not_forward() -> None:
    ch = _make_channel(dm_enabled=True, dm_policy="open")
    handled: list[dict] = []
    ch._handle_message = lambda **kw: handled.append(kw)  # type: ignore[method-assign]

    notification = {
        "envelope": {
            "sourceNumber": "+19995550001",
            "syncMessage": {
                "sentMessage": {
                    "destination": "+19990000000",
                    "message": "sent from other device",
                }
            },
        }
    }
    await ch._handle_receive_notification(notification)
    assert handled == []


@pytest.mark.asyncio
async def test_handle_notification_no_source_skipped() -> None:
    ch = _make_channel(dm_enabled=True, dm_policy="open")
    handled: list[dict] = []
    ch._handle_message = lambda **kw: handled.append(kw)  # type: ignore[method-assign]

    notification = {"envelope": {"dataMessage": {"message": "ghost"}}}
    await ch._handle_receive_notification(notification)
    assert handled == []


# ---------------------------------------------------------------------------
# Config: allow_from property aggregation
# ---------------------------------------------------------------------------


def test_config_allow_from_aggregates_dm_and_group() -> None:
    config = SignalConfig(
        enabled=True,
        phone_number="+10000000000",
        dm=SignalDMConfig(enabled=True, policy="allowlist", allow_from=["+1111", "+2222"]),
        group=SignalGroupConfig(
            enabled=True, policy="allowlist", allow_from=["+3333", "+1111"]
        ),
    )
    combined = config.allow_from
    assert "+1111" in combined
    assert "+2222" in combined
    assert "+3333" in combined
    # Duplicates removed
    assert combined.count("+1111") == 1


def test_config_allow_from_wildcard_propagates() -> None:
    config = SignalConfig(
        enabled=True,
        phone_number="+10000000000",
        dm=SignalDMConfig(enabled=True, policy="open", allow_from=["*"]),
        group=SignalGroupConfig(enabled=True, policy="open", allow_from=[]),
    )
    assert "*" in config.allow_from
