"""Contract tests for MessageProcessor.

These tests verify the interface and high-level pipeline behaviour of
MessageProcessor using mock collaborators.  They are intentionally written
BEFORE the class exists (TDD) and are expected to fail with an ImportError
until Task 3 creates nanobot/agent/message_processor.py.

Expected initial failure:
    ImportError: cannot import name 'MessageProcessor' from
                 'nanobot.agent.message_processor'
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from nanobot.agent.message_processor import MessageProcessor

from nanobot.bus.events import InboundMessage, OutboundMessage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_processor(tmp_path: Path) -> MessageProcessor:
    """Build a minimal MessageProcessor backed by mocks."""
    orchestrator = MagicMock()
    orchestrator.run = AsyncMock(return_value=MagicMock(reply="hello from mock", error=None))

    context = MagicMock()
    sessions = MagicMock()
    sessions.get_or_create = MagicMock(return_value=MagicMock(messages=[], key="cli:direct"))

    tools = MagicMock()
    consolidator = MagicMock()
    verifier = MagicMock()
    bus = MagicMock()
    bus.publish = AsyncMock()

    config = MagicMock()
    config.memory_enabled = False
    config.max_tokens = 4096
    config.verification_mode = "off"

    role_manager = MagicMock()
    provider = MagicMock()
    provider.get_default_model = MagicMock(return_value="test-model")

    return MessageProcessor(
        orchestrator=orchestrator,
        context=context,
        sessions=sessions,
        tools=tools,
        consolidator=consolidator,
        verifier=verifier,
        bus=bus,
        config=config,
        workspace=tmp_path,
        role_name="default",
        role_manager=role_manager,
        provider=provider,
        model="test-model",
    )


def _make_inbound(text: str, channel: str = "cli", chat_id: str = "test-user") -> InboundMessage:
    return InboundMessage(
        channel=channel,
        chat_id=chat_id,
        sender_id="user-1",
        content=text,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMessageProcessorContract:
    """Contract tests for the MessageProcessor interface."""

    async def test_process_direct_returns_string(self, tmp_path: Path) -> None:
        """process_direct() must return a str for a basic message."""
        processor = _make_processor(tmp_path)
        result = await processor.process_direct("hello")
        assert isinstance(result, str)

    async def test_process_direct_uses_default_session_key(self, tmp_path: Path) -> None:
        """process_direct() uses 'cli:direct' as the default session_key."""
        processor = _make_processor(tmp_path)
        # Capture which session key was requested from the session manager
        captured_keys: list[str] = []
        original = processor.sessions.get_or_create

        def _capture(key: str, *args, **kwargs):  # type: ignore[no-untyped-def]
            captured_keys.append(key)
            return original(key, *args, **kwargs)

        processor.sessions.get_or_create = _capture

        await processor.process_direct("hello")

        # The session manager must have been asked for the default key
        assert any("cli:direct" in k for k in captured_keys), (
            f"Expected 'cli:direct' in session keys; got {captured_keys}"
        )

    async def test_process_returns_outbound_or_none(self, tmp_path: Path) -> None:
        """process() must return OutboundMessage or None."""
        processor = _make_processor(tmp_path)
        msg = _make_inbound("what is 2+2?")
        result = await processor.process(msg)
        assert result is None or isinstance(result, OutboundMessage)

    async def test_process_direct_forced_role(self, tmp_path: Path) -> None:
        """process_direct() must accept forced_role without raising a TypeError."""
        processor = _make_processor(tmp_path)
        # Should complete without error; we don't assert on the return value beyond type
        result = await processor.process_direct("hello", forced_role="assistant")
        assert isinstance(result, str)
