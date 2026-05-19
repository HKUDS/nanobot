"""Tests for the Signal channel implementation."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.bus.events import InboundMessage, OutboundMessage
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


def _make_channel_with_capture(**overrides) -> tuple[SignalChannel, list[dict]]:
    """Build a SignalChannel with _handle_message captured into a list and a
    no-op _start_typing, used by every receive-flow test class.
    """
    ch = _make_channel(**overrides)
    handled: list[dict] = []

    async def capture(**kwargs):
        handled.append(kwargs)

    async def noop_typing(chat_id):
        pass

    ch._handle_message = capture  # type: ignore[method-assign]
    ch._start_typing = noop_typing  # type: ignore[method-assign]
    return ch, handled


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
    attachments_dir: str | None = None,
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
        attachments_dir=attachments_dir,
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

    def test_zero_buffer_size_rejected_by_validator(self):
        with pytest.raises(ValueError, match="group_message_buffer_size"):
            _make_channel(group_buffer_size=0)

    def test_negative_buffer_size_rejected_by_validator(self):
        with pytest.raises(ValueError, match="group_message_buffer_size"):
            _make_channel(group_buffer_size=-1)

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


class TestIsAllowed:
    """The base-channel allowlist gate is overridden to understand Signal's
    pipe-joined composite sender_ids and the +/no-+ phone variants.
    """

    def test_denies_when_allowlist_empty(self):
        ch = _make_channel(dm_enabled=True, dm_policy="allowlist")
        assert ch.is_allowed("+19995550001") is False

    def test_denies_when_no_policy_allows(self):
        """When both dm and group are disabled, is_allowed denies."""
        ch = _make_channel(dm_enabled=False, group_enabled=False)
        assert ch.is_allowed("+19995550001") is False

    def test_allows_wildcard(self):
        ch = _make_channel(dm_policy="allowlist", dm_allow_from=["*"])
        assert ch.is_allowed("+19995550001|some-uuid") is True

    def test_allows_composite_sender_against_split_allowlist(self):
        """Composite sender_id, single-id allow_from — must match either part."""
        ch = _make_channel(
            dm_policy="allowlist",
            dm_allow_from=["+19995550001"],
        )
        assert ch.is_allowed("+19995550001|1872ba20-uuid") is True

    def test_allows_composite_sender_against_composite_allowlist_entry(self):
        """Backward compat: pipe-joined composite allowlist entries still match."""
        composite = "+19995550001|1872ba20-uuid"
        ch = _make_channel(dm_policy="allowlist", dm_allow_from=[composite])
        assert ch.is_allowed(composite) is True

    def test_allows_when_only_uuid_part_is_listed(self):
        ch = _make_channel(dm_policy="allowlist", dm_allow_from=["1872ba20-uuid"])
        assert ch.is_allowed("+19995550001|1872ba20-uuid") is True

    def test_denies_when_no_part_matches(self):
        ch = _make_channel(dm_policy="allowlist", dm_allow_from=["+12223334444"])
        assert ch.is_allowed("+19995550001|1872ba20-uuid") is False

    def test_allowlist_union_includes_group_ids(self):
        """allow_from is the union of dm.allow_from and group.allow_from."""
        ch = _make_channel(
            group_enabled=True,
            group_policy="allowlist",
            group_allow_from=["group-id-base64=="],
        )
        assert "group-id-base64==" in ch.config.allow_from


class TestEndToEndDMRouting:
    """End-to-end tests that keep the real _handle_message chain (no mock),
    verifying that _check_inbound_policy + _handle_message work together
    correctly for DM routing.  The override of _handle_message publishes
    directly to bus (policy already checked); denied DMs call
    super()._handle_message which issues a pairing code.
    """

    @pytest.mark.asyncio
    async def test_open_dm_policy_publishes_to_bus(self):
        """Open DM: _check_inbound_policy passes → _handle_message publishes."""
        ch = _make_channel(dm_enabled=True, dm_policy="open")

        async def noop_typing(chat_id):
            pass

        ch._start_typing = noop_typing  # type: ignore[method-assign]
        published: list[InboundMessage] = []

        async def capture_publish(msg: InboundMessage):
            published.append(msg)

        ch.bus.publish_inbound = capture_publish  # type: ignore[method-assign]

        params = _dm_envelope(source_number="+19995550001", message="hello")
        await ch._handle_receive_notification(params)

        assert len(published) == 1
        assert published[0].content == "hello"
        assert published[0].sender_id == "+19995550001"

    @pytest.mark.asyncio
    async def test_allowlist_dm_denied_triggers_pairing(self):
        """Allowlist DM: denied sender triggers pairing code via send()."""
        ch = _make_channel(dm_enabled=True, dm_policy="allowlist", dm_allow_from=[])
        ch._http = _FakeHTTPClient()  # type: ignore[assignment]

        async def noop_typing(chat_id):
            pass

        ch._start_typing = noop_typing  # type: ignore[method-assign]
        published: list[InboundMessage] = []

        async def capture_publish(msg: InboundMessage):
            published.append(msg)

        ch.bus.publish_inbound = capture_publish  # type: ignore[method-assign]

        params = _dm_envelope(source_number="+19995550002", message="hello")
        await ch._handle_receive_notification(params)

        # Should NOT publish to bus — sender is not on allowlist.
        assert published == []
        # Should have sent a pairing code via send (captured in HTTP posts).
        assert len(ch._http.posts) == 1  # type: ignore[attr-defined]
        sent_text = ch._http.posts[0]["json"]["params"]["message"]  # type: ignore[attr-defined]
        assert "pairing" in sent_text.lower() or "pair" in sent_text.lower()

    @pytest.mark.asyncio
    async def test_allowlist_dm_denied_with_group_open_still_pairs(self):
        """dm.policy="allowlist" + group.policy="open": denied DM sender
        must still get a pairing code, not be leaked by the group open check."""
        ch = _make_channel(
            dm_enabled=True,
            dm_policy="allowlist",
            dm_allow_from=[],
            group_enabled=True,
            group_policy="open",
        )
        ch._http = _FakeHTTPClient()  # type: ignore[assignment]

        async def noop_typing(chat_id):
            pass

        ch._start_typing = noop_typing  # type: ignore[method-assign]
        published: list[InboundMessage] = []

        async def capture_publish(msg: InboundMessage):
            published.append(msg)

        ch.bus.publish_inbound = capture_publish  # type: ignore[method-assign]

        params = _dm_envelope(source_number="+19995550002", message="hello")
        await ch._handle_receive_notification(params)

        assert published == []
        assert len(ch._http.posts) == 1  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_open_group_policy_publishes_to_bus(self):
        """Open group: group message from unknown sender publishes to bus."""
        ch = _make_channel(
            group_enabled=True,
            group_policy="open",
            require_mention=False,
        )

        async def noop_typing(chat_id):
            pass

        ch._start_typing = noop_typing  # type: ignore[method-assign]
        published: list[InboundMessage] = []

        async def capture_publish(msg: InboundMessage):
            published.append(msg)

        ch.bus.publish_inbound = capture_publish  # type: ignore[method-assign]

        params = _group_envelope(group_id="grp==", message="hello group")
        await ch._handle_receive_notification(params)

        assert len(published) == 1
        assert "hello group" in published[0].content


class TestCheckInboundPolicy:
    """Direct tests for the policy gate that _handle_data_message now delegates to."""

    def _call(
        self,
        ch: SignalChannel,
        *,
        sender_id: str = "+19995550001",
        sender_number: str = "+19995550001",
        group_id: str | None = None,
        is_group_message: bool = False,
        message_text: str = "hi",
        mentions: list | None = None,
        sender_name: str | None = "Alice",
        timestamp: int | None = 1000,
    ) -> tuple[bool, str]:
        return ch._check_inbound_policy(
            sender_id=sender_id,
            sender_number=sender_number,
            group_id=group_id,
            is_group_message=is_group_message,
            message_text=message_text,
            mentions=mentions or [],
            sender_name=sender_name,
            timestamp=timestamp,
        )

    def test_dm_open_allows(self):
        ch = _make_channel(dm_enabled=True, dm_policy="open")
        allowed, chat_id = self._call(ch)
        assert allowed is True
        assert chat_id == "+19995550001"

    def test_dm_disabled_blocks(self):
        ch = _make_channel(dm_enabled=False)
        allowed, _ = self._call(ch)
        assert allowed is False

    def test_dm_allowlist_blocks_unknown_sender(self):
        ch = _make_channel(dm_policy="allowlist", dm_allow_from=["+12223334444"])
        allowed, _ = self._call(ch, sender_id="+19995550001")
        assert allowed is False

    def test_dm_allowlist_allows_known_sender(self):
        ch = _make_channel(dm_policy="allowlist", dm_allow_from=["+19995550001"])
        allowed, _ = self._call(ch, sender_id="+19995550001")
        assert allowed is True

    def test_group_disabled_blocks(self):
        ch = _make_channel(group_enabled=False)
        allowed, _ = self._call(ch, is_group_message=True, group_id="g1")
        assert allowed is False

    def test_group_open_with_mention_allows(self):
        ch = _make_channel(
            group_enabled=True,
            group_policy="open",
            phone_number="+10000000000",
            require_mention=True,
        )
        allowed, chat_id = self._call(
            ch,
            is_group_message=True,
            group_id="g1",
            message_text="hello @bot",
            mentions=[{"number": "+10000000000", "start": 6, "length": 4}],
        )
        assert allowed is True
        assert chat_id == "g1"

    def test_group_open_without_mention_blocks(self):
        ch = _make_channel(group_enabled=True, group_policy="open", require_mention=True)
        allowed, _ = self._call(ch, is_group_message=True, group_id="g1", message_text="plain talk")
        assert allowed is False

    def test_group_command_bypasses_mention_requirement(self):
        ch = _make_channel(group_enabled=True, group_policy="open", require_mention=True)
        allowed, _ = self._call(ch, is_group_message=True, group_id="g1", message_text="/help")
        assert allowed is True

    def test_allowed_group_appends_to_buffer(self):
        """Side effect: when a group message is allowed, it lands in the buffer."""
        ch = _make_channel(group_enabled=True, group_policy="open", require_mention=False)
        self._call(ch, is_group_message=True, group_id="g1", message_text="first")
        self._call(ch, is_group_message=True, group_id="g1", message_text="second")
        assert len(ch._group_buffers["g1"]) == 2

    def test_blocked_group_does_not_append_to_buffer(self):
        """Side effect: when a group is disabled, the buffer must not change."""
        ch = _make_channel(group_enabled=False)
        self._call(ch, is_group_message=True, group_id="g1", message_text="hi")
        assert "g1" not in ch._group_buffers


class TestAttachmentsDir:
    def test_default_attachments_dir(self):
        ch = _make_channel()
        expected = Path.home() / ".local/share/signal-cli/attachments"
        assert ch._signal_attachments_dir() == expected

    def test_configured_attachments_dir(self, tmp_path):
        ch = _make_channel(attachments_dir=str(tmp_path / "custom"))
        assert ch._signal_attachments_dir() == tmp_path / "custom"

    def test_attachments_dir_expands_user(self):
        ch = _make_channel(attachments_dir="~/signal-attachments")
        assert ch._signal_attachments_dir() == Path.home() / "signal-attachments"


class TestHandleDataMessageDM:
    def _make_dm_channel(self, policy="open", allow_from=None) -> tuple[SignalChannel, list]:
        return _make_channel_with_capture(
            dm_enabled=True, dm_policy=policy, dm_allow_from=allow_from or []
        )

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
    async def test_dm_allowlist_rejected_triggers_pairing(self):
        # Denied DM senders go through super()._handle_message which checks
        # is_allowed → sends pairing code via self.send().
        ch, handled = self._make_dm_channel(policy="allowlist", allow_from=["+10000000001"])
        ch._http = _FakeHTTPClient()  # type: ignore[attr-defined]
        params = _dm_envelope(source_number="+19995550002")
        await ch._handle_receive_notification(params)
        # The denied DM path calls super()._handle_message, not self._handle_message,
        # so the capture list stays empty. Verify pairing code was sent via HTTP.
        assert handled == []
        assert len(ch._http.posts) == 1  # type: ignore[attr-defined]
        sent_text = ch._http.posts[0]["json"]["params"]["message"]  # type: ignore[attr-defined]
        assert "pairing" in sent_text.lower() or "pair" in sent_text.lower()

    @pytest.mark.asyncio
    async def test_dm_paired_sender_allowed_without_allowlist_entry(self, monkeypatch):
        # Once a sender completes pairing they should pass is_allowed on every
        # subsequent message — otherwise the pairing reply loops forever.
        approved = {"+19995550002"}
        monkeypatch.setattr(
            "nanobot.channels.signal.is_approved",
            lambda channel, sender_id: sender_id in approved,
        )
        ch = _make_channel(dm_enabled=True, dm_policy="allowlist", dm_allow_from=[])
        assert ch.is_allowed("+19995550002") is True
        # Variant forms (with/without "+") must still match a stored approval.
        assert ch.is_allowed("19995550002") is True
        # Unpaired sender stays denied.
        assert ch.is_allowed("+19995559999") is False

    @pytest.mark.asyncio
    async def test_dm_allowlist_matches_without_plus_prefix(self):
        """An allowlist entry without '+' must match a sender that carries '+'."""
        ch, handled = self._make_dm_channel(policy="allowlist", allow_from=["19995550001"])
        params = _dm_envelope(source_number="+19995550001")
        await ch._handle_receive_notification(params)
        assert len(handled) == 1

    @pytest.mark.asyncio
    async def test_dm_allowlist_matches_with_plus_prefix(self):
        """An allowlist entry with '+' must match a sender without '+'."""
        ch, handled = self._make_dm_channel(policy="allowlist", allow_from=["+19995550001"])
        params = _dm_envelope(source_number="+19995550001", source_uuid=None)
        # Replace envelope's sourceNumber with the non-prefixed form by editing
        # the constructed dict directly so _collect_sender_id_parts sees it.
        params["envelope"]["sourceNumber"] = "19995550001"
        await ch._handle_receive_notification(params)
        assert len(handled) == 1

    @pytest.mark.asyncio
    async def test_dm_allowlist_matches_uuid_case_insensitive(self):
        """UUID matching must be case-insensitive."""
        uuid = "ABCDEF12-3456-7890-ABCD-EF1234567890"
        ch, handled = self._make_dm_channel(policy="allowlist", allow_from=[uuid.lower()])
        params = _dm_envelope(source_number="+19995550001", source_uuid=uuid)
        await ch._handle_receive_notification(params)
        assert len(handled) == 1

    @pytest.mark.asyncio
    async def test_dm_allowlist_matches_pipe_joined_composite_entry(self):
        """Allowlist entries written as ``phone|uuid`` composites still work.

        Some configs pre-date the per-part splitting and store the full
        sender_id composite as a single allow_from entry. Keep matching it.
        """
        composite = "+19995550001|1872ba20-f52a-4bad-b434-bf7f808c8b22"
        ch, handled = self._make_dm_channel(policy="allowlist", allow_from=[composite])
        params = _dm_envelope(
            source_number="+19995550001",
            source_uuid="1872ba20-f52a-4bad-b434-bf7f808c8b22",
        )
        await ch._handle_receive_notification(params)
        assert len(handled) == 1

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
        return _make_channel_with_capture(
            group_enabled=True,
            group_policy=policy,
            group_allow_from=allow_from or [],
            require_mention=require_mention,
        )

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
# Lifecycle / SSE
# ---------------------------------------------------------------------------


class _FakeSSEResponse:
    """Minimal stand-in for httpx Response under stream()."""

    def __init__(self, lines: list[str], status_code: int = 200) -> None:
        self.status_code = status_code
        self._lines = lines

    async def aiter_lines(self):
        for line in self._lines:
            yield line


def _fake_streaming_client(lines: list[str], *, status_code: int = 200) -> MagicMock:
    """Return an httpx.AsyncClient stand-in whose .stream() yields a FakeSSEResponse."""
    response = _FakeSSEResponse(lines, status_code=status_code)

    @asynccontextmanager
    async def _ctx(*_args, **_kwargs):
        yield response

    http = MagicMock()
    http.stream = lambda *a, **kw: _ctx(*a, **kw)
    return http


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_returns_early_when_phone_missing(self):
        """start() with an empty phone number must not enter the HTTP loop."""
        ch = _make_channel(phone_number="")
        await ch.start()
        assert ch._running is False
        assert ch._http is None
        assert ch._sse_task is None


class TestSSEReceiveLoop:
    @pytest.mark.asyncio
    async def test_dispatches_valid_envelope(self):
        ch = _make_channel()
        ch._running = True

        captured: list[dict] = []

        async def capture(params):
            captured.append(params)

        ch._handle_receive_notification = capture  # type: ignore[method-assign]
        ch._http = _fake_streaming_client(
            ['data: {"envelope":{"sourceNumber":"+19995550001"}}', ""]
        )

        # Loop ends when lines exhaust; the surrounding _start_http_mode would
        # treat that as a disconnect, but the loop itself raises ConnectionError
        # when the stream closes while still running.
        with pytest.raises(ConnectionError):
            await ch._sse_receive_loop()
        assert captured == [{"envelope": {"sourceNumber": "+19995550001"}}]

    @pytest.mark.asyncio
    async def test_handles_invalid_json_frame(self):
        """An unparseable SSE frame is logged and skipped without crashing."""
        ch = _make_channel()
        ch._running = True

        captured: list[dict] = []

        async def capture(params):
            captured.append(params)

        ch._handle_receive_notification = capture  # type: ignore[method-assign]
        ch._http = _fake_streaming_client(
            [
                "data: this-is-not-json",
                "",  # event boundary triggers parse attempt
                'data: {"envelope":{"sourceNumber":"+1"}}',
                "",
            ]
        )

        with pytest.raises(ConnectionError):
            await ch._sse_receive_loop()
        # Bad frame skipped; good frame still dispatched.
        assert captured == [{"envelope": {"sourceNumber": "+1"}}]

    @pytest.mark.asyncio
    async def test_non_200_status_raises(self):
        ch = _make_channel()
        ch._running = True
        ch._http = _fake_streaming_client([], status_code=503)
        with pytest.raises(ConnectionError, match="status 503"):
            await ch._sse_receive_loop()

    @pytest.mark.asyncio
    async def test_no_http_client_raises(self):
        ch = _make_channel()
        ch._http = None
        with pytest.raises(RuntimeError, match="HTTP client not initialized"):
            await ch._sse_receive_loop()


# ---------------------------------------------------------------------------
# Command handling
# ---------------------------------------------------------------------------


class TestCommandHandling:
    @pytest.mark.asyncio
    async def test_dm_command_forwarded_to_bus(self):
        """Slash commands in DMs are forwarded to the bus for AgentLoop to handle."""
        ch, forwarded = _make_channel_with_capture(dm_enabled=True, dm_policy="open")
        params = _dm_envelope(source_number="+19995550001", message="/reset")
        await ch._handle_receive_notification(params)
        assert len(forwarded) == 1
        assert forwarded[0]["content"].strip() == "/reset"

    @pytest.mark.asyncio
    async def test_group_command_bypasses_mention_requirement(self):
        """Slash commands in groups bypass the mention requirement and reach the bus."""
        ch, forwarded = _make_channel_with_capture(
            group_enabled=True, group_policy="open", require_mention=True
        )
        params = _group_envelope(source_number="+19995550001", group_id="grp==", message="/reset")
        await ch._handle_receive_notification(params)
        assert len(forwarded) == 1
        assert "/reset" in forwarded[0]["content"]

    @pytest.mark.asyncio
    async def test_command_denied_for_disallowed_dm_sender(self):
        """Commands from senders not on the DM allowlist are dropped."""
        ch, forwarded = _make_channel_with_capture(dm_enabled=False)
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
    async def test_send_split_message_redistributes_text_styles(self):
        """Long message split across chunks: each chunk gets its own textStyle
        with offsets rebased to that chunk."""
        ch, client = self._make_send_channel()
        ch._MAX_MESSAGE_LEN = 12  # type: ignore[attr-defined]
        msg = OutboundMessage(
            channel="signal",
            chat_id="+19995550001",
            content="**head** middle and **tail**",
        )
        await ch.send(msg)
        assert len(client.posts) >= 2
        # Chunk 0 has BOLD for "head"; chunk 1+ must also carry BOLD for "tail".
        bold_chunks = [
            p["json"]["params"]
            for p in client.posts
            if any("BOLD" in s for s in p["json"]["params"].get("textStyle", []))
        ]
        assert len(bold_chunks) >= 2, (
            "expected BOLD ranges in more than one chunk; got "
            f"{[p['json']['params'] for p in client.posts]}"
        )
        # Each emitted range must point inside its own chunk's text.
        for params in bold_chunks:
            chunk_text = params["message"]
            for entry in params["textStyle"]:
                s, ln, _ = entry.split(":", 2)
                start, length = int(s), int(ln)
                end_units = start + length
                assert end_units <= len(chunk_text.encode("utf-16-le")) // 2

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
    async def test_send_raises_on_daemon_error(self):
        # _send_http_request turns every exception into {"error": ...}, so this branch
        # is the only place ChannelManager retry can be triggered — must raise.
        ch = _make_channel()
        ch._http = _FakeHTTPClient(default_response={"error": {"message": "fail"}})
        msg = OutboundMessage(channel="signal", chat_id="+19995550001", content="hello")
        with pytest.raises(RuntimeError, match="signal-cli send failed"):
            await ch.send(msg)


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
        group=SignalGroupConfig(enabled=True, policy="allowlist", allow_from=["+3333", "+1111"]),
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
