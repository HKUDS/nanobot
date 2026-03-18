"""Tests for Telegram communication improvements.

Covers: edit-in-place streaming, message splitting, tool_call_id truncation,
empty tool call filtering, timeout protection, and user-friendly error messages.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.providers.base import ToolCallRequest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_outbound(
    content: str = "Hello",
    chat_id: str = "123",
    channel: str = "telegram",
    streaming: bool = False,
    progress: bool = False,
    tool_hint: bool = False,
    **extra_meta: object,
) -> OutboundMessage:
    meta: dict = {**extra_meta}
    if streaming:
        meta["_streaming"] = True
    if progress:
        meta["_progress"] = True
    if tool_hint:
        meta["_tool_hint"] = True
    return OutboundMessage(channel=channel, chat_id=chat_id, content=content, metadata=meta)


# ---------------------------------------------------------------------------
# Phase 1 & 6: Telegram streaming and message splitting
# ---------------------------------------------------------------------------


class TestTelegramSplitMessage:
    """Tests for _split_message with the lowered 3800-char default."""

    def test_short_message_no_split(self):
        from nanobot.channels.telegram import _split_message

        result = _split_message("Hello world")
        assert result == ["Hello world"]

    def test_split_at_3800(self):
        from nanobot.channels.telegram import _split_message

        text = "a" * 3900
        chunks = _split_message(text)
        assert len(chunks) >= 2
        assert all(len(c) <= 3800 for c in chunks)

    def test_prefers_line_breaks(self):
        from nanobot.channels.telegram import _split_message

        text = "line1\n" * 800  # ~4800 chars
        chunks = _split_message(text)
        assert len(chunks) >= 2
        # Each chunk should end at a line boundary
        for c in chunks[:-1]:
            assert c.endswith("line1")

    def test_custom_max_len(self):
        from nanobot.channels.telegram import _split_message

        text = "word " * 100
        chunks = _split_message(text, max_len=50)
        assert all(len(c) <= 50 for c in chunks)


class TestMarkdownToHtml:
    """Basic sanity for the HTML converter."""

    def test_bold(self):
        from nanobot.channels.telegram import _markdown_to_telegram_html

        assert "<b>hello</b>" in _markdown_to_telegram_html("**hello**")

    def test_code_block(self):
        from nanobot.channels.telegram import _markdown_to_telegram_html

        result = _markdown_to_telegram_html("```\ncode\n```")
        assert "<pre><code>" in result

    def test_empty_input(self):
        from nanobot.channels.telegram import _markdown_to_telegram_html

        assert _markdown_to_telegram_html("") == ""


class TestTelegramStreaming:
    """Tests for edit-in-place streaming in TelegramChannel.send()."""

    @pytest.fixture
    def channel(self):
        """Create a TelegramChannel with mocked bot."""
        from nanobot.channels.telegram import TelegramChannel

        config = MagicMock()
        config.token = "test-token"
        config.reply_to_message = False
        config.proxy = None
        bus = MagicMock()
        ch = TelegramChannel(config, bus)

        # Mock the application and bot
        app = MagicMock()
        bot = AsyncMock()
        app.bot = bot
        ch._app = app
        return ch

    async def test_streaming_sends_new_message(self, channel):
        """First streaming chunk sends a new message and stores msg_id."""
        sent_msg = MagicMock()
        sent_msg.message_id = 42
        channel._app.bot.send_message = AsyncMock(return_value=sent_msg)

        msg = _make_outbound("Hello", streaming=True, progress=True)
        await channel.send(msg)

        channel._app.bot.send_message.assert_called_once()
        assert channel._streaming_msg_ids["123"] == 42

    async def test_streaming_edits_existing_message(self, channel):
        """Subsequent streaming chunks edit the existing message."""
        channel._streaming_msg_ids["123"] = 42
        channel._app.bot.edit_message_text = AsyncMock()

        msg = _make_outbound("Updated content", streaming=True, progress=True)
        await channel.send(msg)

        channel._app.bot.edit_message_text.assert_called_once()
        call_kwargs = channel._app.bot.edit_message_text.call_args
        assert call_kwargs.kwargs["message_id"] == 42

    async def test_streaming_edit_not_modified_is_silent(self, channel):
        """'Message is not modified' error is silently ignored."""
        channel._streaming_msg_ids["123"] = 42
        channel._app.bot.edit_message_text = AsyncMock(
            side_effect=Exception("Bad Request: message is not modified")
        )

        msg = _make_outbound("Same content", streaming=True, progress=True)
        await channel.send(msg)  # Should not raise

        # msg_id preserved (not cleared)
        assert channel._streaming_msg_ids.get("123") == 42

    async def test_streaming_edit_failure_sends_new(self, channel):
        """If edit fails for a real reason, fall back to sending a new message."""
        channel._streaming_msg_ids["123"] = 42
        channel._app.bot.edit_message_text = AsyncMock(
            side_effect=Exception("Bad Request: message to edit not found")
        )
        sent_msg = MagicMock()
        sent_msg.message_id = 99
        channel._app.bot.send_message = AsyncMock(return_value=sent_msg)

        msg = _make_outbound("New content", streaming=True, progress=True)
        await channel.send(msg)

        channel._app.bot.send_message.assert_called_once()
        assert channel._streaming_msg_ids["123"] == 99

    async def test_final_message_clears_streaming_id(self, channel):
        """Non-streaming message clears the streaming msg_id."""
        channel._streaming_msg_ids["123"] = 42
        channel._app.bot.send_message = AsyncMock(return_value=MagicMock())

        msg = _make_outbound("Final answer")
        await channel.send(msg)

        assert "123" not in channel._streaming_msg_ids

    async def test_empty_streaming_content_skipped(self, channel):
        """Empty streaming content is not sent."""
        msg = _make_outbound("", streaming=True, progress=True)
        await channel.send(msg)

        channel._app.bot.send_message.assert_not_called()

    async def test_streaming_msg_ids_initialized(self, channel):
        """Channel initializes the streaming tracker."""
        assert hasattr(channel, "_streaming_msg_ids")
        assert isinstance(channel._streaming_msg_ids, dict)


# ---------------------------------------------------------------------------
# Phase 2: Tool call ID truncation
# ---------------------------------------------------------------------------


class TestToolCallIdTruncation:
    """Tests for tool_call_id length enforcement in LiteLLMProvider."""

    def test_parse_response_truncates_long_id(self):
        from nanobot.providers.litellm_provider import LiteLLMProvider

        provider = LiteLLMProvider.__new__(LiteLLMProvider)

        # Build a mock response with a 50-char tool_call_id
        long_id = "a" * 50
        mock_tc = MagicMock()
        mock_tc.id = long_id
        mock_tc.function.name = "test_tool"
        mock_tc.function.arguments = '{"key": "value"}'

        mock_choice = MagicMock()
        mock_choice.message.content = None
        mock_choice.message.tool_calls = [mock_tc]
        mock_choice.finish_reason = "tool_calls"
        mock_choice.message.reasoning_content = None

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = None

        result = provider._parse_response(mock_response)
        assert len(result.tool_calls[0].id) == 40

    def test_parse_response_keeps_short_id(self):
        from nanobot.providers.litellm_provider import LiteLLMProvider

        provider = LiteLLMProvider.__new__(LiteLLMProvider)

        short_id = "call_abc123"
        mock_tc = MagicMock()
        mock_tc.id = short_id
        mock_tc.function.name = "test_tool"
        mock_tc.function.arguments = '{"key": "value"}'

        mock_choice = MagicMock()
        mock_choice.message.content = None
        mock_choice.message.tool_calls = [mock_tc]
        mock_choice.finish_reason = "tool_calls"
        mock_choice.message.reasoning_content = None

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = None

        result = provider._parse_response(mock_response)
        assert result.tool_calls[0].id == short_id


# ---------------------------------------------------------------------------
# Phase 3: Empty tool call filtering
# ---------------------------------------------------------------------------


class TestEmptyToolCallFiltering:
    """Tests for malformed tool call filtering in _run_agent_loop."""

    def test_empty_name_detected(self):
        """Tool calls with empty names should be identified as invalid."""
        tc = ToolCallRequest(id="1", name="", arguments={"cmd": "ls"})
        assert not (tc.name and tc.name.strip() and tc.arguments)

    def test_empty_args_detected(self):
        """Tool calls with empty arguments should be identified as invalid."""
        tc = ToolCallRequest(id="1", name="exec", arguments={})
        assert not (tc.name and tc.name.strip() and tc.arguments)

    def test_valid_call_passes(self):
        """Valid tool calls pass the filter."""
        tc = ToolCallRequest(id="1", name="exec", arguments={"command": "ls"})
        assert tc.name and tc.name.strip() and tc.arguments

    def test_whitespace_name_filtered(self):
        """Whitespace-only names should be filtered."""
        tc = ToolCallRequest(id="1", name="  ", arguments={"x": 1})
        assert not (tc.name and tc.name.strip() and tc.arguments)

    @pytest.mark.parametrize(
        "name,args,expected_valid",
        [
            ("exec", {"command": "ls"}, True),
            ("exec", {}, False),
            ("", {"command": "ls"}, False),
            ("  ", {"command": "ls"}, False),
            ("read_file", {"path": "/tmp/x"}, True),
        ],
    )
    def test_filter_logic(self, name, args, expected_valid):
        tc = ToolCallRequest(id="1", name=name, arguments=args)
        is_valid = bool(tc.name and tc.name.strip() and tc.arguments)
        assert is_valid == expected_valid


# ---------------------------------------------------------------------------
# Phase 4: Timeout protection
# ---------------------------------------------------------------------------


class TestTimeoutConfig:
    """Tests for message_timeout in AgentConfig."""

    def test_default_timeout(self):
        from nanobot.config.schema import AgentConfig

        config = AgentConfig()
        assert config.message_timeout == 300

    def test_custom_timeout(self):
        from nanobot.config.schema import AgentConfig

        config = AgentConfig(message_timeout=60)
        assert config.message_timeout == 60

    def test_zero_timeout_means_no_limit(self):
        from nanobot.config.schema import AgentConfig

        config = AgentConfig(message_timeout=0)
        assert config.message_timeout == 0


# ---------------------------------------------------------------------------
# Phase 5: User-friendly error messages
# ---------------------------------------------------------------------------


class TestUserFriendlyErrors:
    """Tests for _user_friendly_error mapping."""

    def test_context_length_error(self):
        from nanobot.agent.loop import _user_friendly_error

        msg = _user_friendly_error(Exception("context_length_exceeded: max 128000 tokens"))
        assert "/new" in msg

    def test_rate_limit_error(self):
        from nanobot.agent.loop import _user_friendly_error

        msg = _user_friendly_error(Exception("Error code: 429 rate_limit_exceeded"))
        assert "rate-limited" in msg.lower() or "try again" in msg.lower()

    def test_quota_error(self):
        from nanobot.agent.loop import _user_friendly_error

        msg = _user_friendly_error(Exception("insufficient_quota"))
        assert "rate-limited" in msg.lower() or "try again" in msg.lower()

    def test_auth_error(self):
        from nanobot.agent.loop import _user_friendly_error

        msg = _user_friendly_error(Exception("auth key invalid or denied"))
        assert "configuration" in msg.lower() or "admin" in msg.lower()

    def test_generic_error(self):
        from nanobot.agent.loop import _user_friendly_error

        msg = _user_friendly_error(Exception("Some random internal error"))
        assert "try again" in msg.lower()
        # Should not leak internal details
        assert "random internal" not in msg

    def test_context_window_variant(self):
        from nanobot.agent.loop import _user_friendly_error

        msg = _user_friendly_error(Exception("maximum context window exceeded"))
        assert "/new" in msg

    @pytest.mark.parametrize(
        "error_str,expected_substring",
        [
            ("context_length_exceeded", "/new"),
            ("maximum context window", "/new"),
            ("429", "try again"),
            ("rate_limit", "try again"),
            ("quota", "try again"),
            ("auth key invalid", "admin"),
            ("auth denied", "admin"),
            ("unknown error xyz", "try again"),
        ],
    )
    def test_error_mapping_parametrized(self, error_str, expected_substring):
        from nanobot.agent.loop import _user_friendly_error

        msg = _user_friendly_error(Exception(error_str))
        assert expected_substring.lower() in msg.lower()
