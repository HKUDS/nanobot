"""Tests for MessageTool delivery feedback (DeliveryResult integration)."""

from __future__ import annotations

from nanobot.bus.events import DeliveryResult, OutboundMessage
from nanobot.errors import DeliverySkippedError
from nanobot.tools.builtin.message import MessageTool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tool(callback=None) -> MessageTool:
    return MessageTool(
        send_callback=callback,
        default_channel="telegram",
        default_chat_id="123",
    )


# ---------------------------------------------------------------------------
# Tests: ToolResult.ok() only when delivery succeeds
# ---------------------------------------------------------------------------


async def test_ok_on_successful_delivery() -> None:
    """MessageTool returns ToolResult.ok when deliver() reports success."""

    async def _deliver(msg: OutboundMessage) -> DeliveryResult:
        return DeliveryResult(success=True, channel=msg.channel, chat_id=msg.chat_id)

    tool = _tool(_deliver)
    result = await tool.execute(content="hello")
    assert result.success
    assert "delivered" in result.output.lower()
    assert "telegram:123" in result.output


async def test_ok_includes_media_info() -> None:
    async def _deliver(msg: OutboundMessage) -> DeliveryResult:
        return DeliveryResult(success=True, channel=msg.channel, chat_id=msg.chat_id)

    tool = _tool(_deliver)
    result = await tool.execute(content="see attached", media=["a.png", "b.jpg"])
    assert result.success
    assert "2 attachments" in result.output


# ---------------------------------------------------------------------------
# Tests: ToolResult.fail() when delivery fails
# ---------------------------------------------------------------------------


async def test_fail_on_delivery_failure() -> None:
    """MessageTool returns ToolResult.fail when deliver() reports failure."""

    async def _deliver(msg: OutboundMessage) -> DeliveryResult:
        return DeliveryResult(
            success=False, channel=msg.channel, chat_id=msg.chat_id, error="SMTP timeout"
        )

    tool = _tool(_deliver)
    result = await tool.execute(content="hello")
    assert not result.success
    assert "SMTP timeout" in result.output


async def test_fail_on_delivery_skipped_error() -> None:
    """MessageTool returns ToolResult.fail when callback raises DeliverySkippedError."""

    async def _deliver(_msg: OutboundMessage) -> DeliveryResult:
        raise DeliverySkippedError("consent not granted")

    tool = _tool(_deliver)
    result = await tool.execute(content="hello")
    assert not result.success
    assert "consent not granted" in result.output


async def test_fail_on_unexpected_exception() -> None:
    """MessageTool catches unexpected exceptions and returns ToolResult.fail."""

    async def _deliver(_msg: OutboundMessage) -> DeliveryResult:
        raise ConnectionError("network down")

    tool = _tool(_deliver)
    result = await tool.execute(content="hello")
    assert not result.success
    assert "network down" in result.output


# ---------------------------------------------------------------------------
# Tests: Legacy callback (returns None) — backward compat
# ---------------------------------------------------------------------------


async def test_legacy_callback_returns_ok() -> None:
    """Legacy callbacks that return None still report ok (fire-and-forget)."""

    async def _legacy(msg: OutboundMessage) -> None:
        pass

    tool = _tool(_legacy)
    result = await tool.execute(content="hello")
    assert result.success
    assert "sent" in result.output.lower()


# ---------------------------------------------------------------------------
# Tests: sent_in_turn tracking
# ---------------------------------------------------------------------------


async def test_sent_in_turn_set_on_success() -> None:
    async def _deliver(msg: OutboundMessage) -> DeliveryResult:
        return DeliveryResult(success=True, channel=msg.channel, chat_id=msg.chat_id)

    tool = _tool(_deliver)
    tool.start_turn()
    assert not tool._sent_in_turn
    await tool.execute(content="hello")
    assert tool._sent_in_turn


async def test_sent_in_turn_not_set_on_failure() -> None:
    async def _deliver(msg: OutboundMessage) -> DeliveryResult:
        return DeliveryResult(success=False, channel=msg.channel, chat_id=msg.chat_id, error="fail")

    tool = _tool(_deliver)
    tool.start_turn()
    await tool.execute(content="hello")
    assert not tool._sent_in_turn


# ---------------------------------------------------------------------------
# Tests: validation paths and error handling
# ---------------------------------------------------------------------------


async def test_message_tool_paths() -> None:
    tool = MessageTool()

    missing_target = await tool.execute(content="hello")
    assert not missing_target.success

    tool.set_context("telegram", "123")
    no_callback = await tool.execute(content="hello")
    assert not no_callback.success

    sent: list[object] = []

    async def _send(msg):
        sent.append(msg)

    tool.set_send_callback(_send)
    tool.start_turn()
    ok = await tool.execute(content="hello", media=["a.png"])
    assert ok.success
    assert "attachments" in ok.output
    assert len(sent) == 1


async def test_message_tool_send_error() -> None:
    async def _bad(_msg):
        raise RuntimeError("boom")

    tool = MessageTool(send_callback=_bad, default_channel="telegram", default_chat_id="123")
    out = await tool.execute(content="hello")
    assert not out.success
    assert "Error sending message" in out.output
