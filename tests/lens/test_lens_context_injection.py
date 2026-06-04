"""Tests for Lens context injection - how lens metadata is injected into LLM context."""

from pathlib import Path
from unittest.mock import patch

import pytest

from blackcat.agent.context import ContextBuilder
from blackcat.config.schema import LensConfig
from blackcat.lens.client import LensClient


class TestContextManagerRuntimeContext:
    """Test runtime context building - what gets injected into LLM messages."""

    def test_build_runtime_context_basic(self, tmp_path):
        """Should build basic runtime context with time."""
        ctx = ContextBuilder(workspace=tmp_path)
        with patch("blackcat.agent.context.current_time_str") as mock_time:
            mock_time.return_value = "2026-04-26 10:00 (Sunday) (UTC, +00:00)"

            result = ctx._build_runtime_context(
                channel=None,
                chat_id=None,
                timezone=None,
            )

        assert "Current Time:" in result
        assert "2026-04-26 10:00" in result
        assert "Channel" not in result
        assert "Chat ID" not in result
        assert "Resumed Session" not in result

    def test_build_runtime_context_with_channel_info(self, tmp_path):
        """Should include channel and chat_id when provided."""
        ctx = ContextBuilder(workspace=tmp_path)
        with patch("blackcat.agent.context.current_time_str") as mock_time:
            mock_time.return_value = "2026-04-26 10:00 (Sunday) (UTC, +00:00)"

            result = ctx._build_runtime_context(
                channel="discord",
                chat_id="123456789",
                timezone=None,
            )

        assert "Current Time:" in result
        assert "Channel: discord" in result
        assert "Chat ID: 123456789" in result

    def test_build_runtime_context_tags(self, tmp_path):
        """Should use proper context tags."""
        ctx = ContextBuilder(workspace=tmp_path)
        with patch("blackcat.agent.context.current_time_str") as mock_time:
            mock_time.return_value = "2026-04-26 10:00"

            result = ctx._build_runtime_context(
                channel=None,
                chat_id=None,
                timezone=None,
            )

        assert "[Runtime Context" in result
        assert "[/Runtime Context]" in result


class TestContextManagerLensClient:
    """Test lens client attachment to context."""

    def test_set_lens_client(self):
        """Should attach lens client to context."""
        config = LensConfig(enabled=True, workspaces={"test": "/tmp/test"})
        lens_client = LensClient(config)

        ctx = ContextBuilder(workspace=Path("/tmp/test"))
        ctx.set_lens_client(lens_client)

        assert ctx.lens_client is lens_client
        assert ctx.lens_client.config == config

    def test_lens_client_none_by_default(self):
        """Should have no lens client by default."""
        ctx = ContextBuilder(workspace=Path("/tmp/test"))
        assert ctx.lens_client is None


class TestLensContextInjection:
    """Test what lens-specific context is (or isn't) injected."""

    def test_lens_client_not_used_in_context_building(self):
        """Verify lens client is attached but NOT used in _build_runtime_context.

        This is the current behavior: lens_client is available on ContextBuilder
        but no lens-specific metadata (diagnostics, workspace status, etc.) is
        injected into the LLM context automatically.
        """
        config = LensConfig(enabled=True, workspaces={"test": "/tmp/test"})
        lens_client = LensClient(config)

        ctx = ContextBuilder(workspace=Path("/tmp/test"))
        ctx.set_lens_client(lens_client)

        # Build context - should NOT include lens info
        with patch("blackcat.agent.context.current_time_str") as mock_time:
            mock_time.return_value = "2026-04-26 10:00"

            result = ctx._build_runtime_context(
                channel=None,
                chat_id=None,
                timezone=None,
                session_summary=None,
            )

        # Verify: no lens-specific info injected
        assert "workspace" not in result.lower()
        assert "diagnostic" not in result.lower()
        assert "lens" not in result.lower()
        assert "LSP" not in result.lower()

    def test_lens_client_available_for_tools(self):
        """Lens client should be available for tools to query on-demand."""
        config = LensConfig(enabled=True, workspaces={"test": "/tmp/test"})
        lens_client = LensClient(config)

        ctx = ContextBuilder(workspace=Path("/tmp/test"))
        ctx.set_lens_client(lens_client)

        # Tools can access lens_client directly
        assert ctx.lens_client is not None
        assert ctx.lens_client.workspace_paths == {"test": "/tmp/test"}


class TestBuildMessagesWithLens:
    """Test build_messages flow with lens client attached."""

    @pytest.mark.asyncio
    async def test_build_messages_injects_runtime_context(self):
        """Should include runtime context in system prompt."""
        config = LensConfig(enabled=True, workspaces={"test": "/tmp/test"})
        lens_client = LensClient(config)

        ctx = ContextBuilder(workspace=Path("/tmp/test"))
        ctx.set_lens_client(lens_client)

        with patch("blackcat.agent.context.current_time_str") as mock_time:
            mock_time.return_value = "2026-04-26 10:00"

            messages = await ctx.build_messages(
                history=[],
                current_message="Hello",
                channel="discord",
                chat_id="123",
            )

        # System message is first and contains runtime context
        assert messages[0]["role"] == "system"
        system_content = messages[0]["content"]
        assert "Current Time:" in system_content
        assert "2026-04-26 10:00" in system_content
        # Channel/chat_id included when both provided
        assert "Channel: discord" in system_content
        assert "Chat ID: 123" in system_content
        # User message is last with just the content
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == "Hello"

    @pytest.mark.asyncio
    async def test_build_messages_with_session_history(self):
        """Should include session history in messages."""
        config = LensConfig(enabled=True, workspaces={"test": "/tmp/test"})
        lens_client = LensClient(config)

        ctx = ContextBuilder(workspace=Path("/tmp/test"))
        ctx.set_lens_client(lens_client)

        with patch("blackcat.agent.context.current_time_str") as mock_time:
            mock_time.return_value = "2026-04-26 10:00"

            messages = await ctx.build_messages(
                history=[
                    {"role": "user", "content": "Hello"},
                    {"role": "assistant", "content": "Hi there!"},
                ],
                current_message="How are you?",
                channel="discord",
                chat_id="123",
            )

        # Should have: system (with runtime ctx), user, assistant, user (current with runtime ctx)
        assert len(messages) >= 3
        assert messages[0]["role"] == "system"
        # The history messages are preserved
        user_msgs = [m for m in messages if m.get("content") == "Hello"]
        assert len(user_msgs) >= 1


class TestLensContextPotentialEnhancements:
    """Test potential future lens context injection patterns."""

    def test_potential_workspace_status_injection(self):
        """Example of how lens workspace status COULD be injected."""
        config = LensConfig(enabled=True, workspaces={"test": "/tmp/test"})
        lens_client = LensClient(config)

        # Current behavior: workspace info NOT injected
        # This test documents what WOULD be needed:
        workspace_count = len(lens_client.workspace_paths)

        # This is NOT currently done - just documenting the pattern
        assert workspace_count == 1
        assert "test" in lens_client.workspace_paths

    def test_potential_diagnostic_summary_injection(self):
        """Example of how lens diagnostics COULD be injected."""
        # Current behavior: diagnostics are queried on-demand via tools
        # NOT automatically injected into context

        # Pattern for future injection:
        # 1. Call lens_client.get_diagnostics() for each workspace
        # 2. Summarize error/warning counts
        # 3. Inject into runtime context

        # This test just documents that this is NOT current behavior
        config = LensConfig(enabled=True, workspaces={"test": "/tmp/test"})
        lens_client = LensClient(config)

        ctx = ContextBuilder(workspace=Path("/tmp/test"))
        ctx.set_lens_client(lens_client)

        with patch("blackcat.agent.context.current_time_str") as mock_time:
            mock_time.return_value = "2026-04-26 10:00"

            result = ctx._build_runtime_context(
                channel=None,
                chat_id=None,
                timezone=None,
                session_summary=None,
            )

        # Verify: no diagnostic summary
        assert "error" not in result.lower()
        assert "warning" not in result.lower()
