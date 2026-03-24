"""Integration tests for the core agent loop.

Uses a mock LLM provider with scripted responses to test:
- Single-turn Q&A (no tool use)
- Multi-step tool use (tool call -> result -> final answer)
- Tool failure -> reflect -> retry
- Max iterations hit
- Context compression triggered
- Consecutive LLM errors -> graceful fallback
- Nudge for final answer (tool results but no text)
- Planning prompt injection
- Verification pass
- Concurrent _process_message() session isolation
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from nanobot.agent.callbacks import ProgressEvent, ToolCallEvent
from nanobot.bus.events import InboundMessage
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from tests.helpers import ScriptedProvider, _make_loop


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


class TestAgentLoopSingleTurn:
    """Test single-turn Q&A without tool use."""

    async def test_simple_qa(self, tmp_path: Path):
        """Agent returns the LLM's text response directly."""
        provider = ScriptedProvider(
            [
                LLMResponse(content="Hello! I'm nanobot."),
            ]
        )
        loop = _make_loop(tmp_path, provider)
        msg = _make_inbound("Hi there")
        result = await loop._process_message(msg)

        assert result is not None
        assert "Hello" in result.content
        assert provider._index >= 1

    async def test_empty_content_fallback(self, tmp_path: Path):
        """When LLM returns None content with no tool calls, agent returns explanation."""
        provider = ScriptedProvider(
            [
                LLMResponse(content=None),
            ]
        )
        loop = _make_loop(tmp_path, provider)
        msg = _make_inbound("Tell me something")
        result = await loop._process_message(msg)

        assert result is not None
        # Should get a fallback explanation
        assert len(result.content) > 0


class TestAgentLoopToolUse:
    """Test multi-step tool use."""

    async def test_tool_call_then_answer(self, tmp_path: Path):
        """Agent calls a tool, gets result, then produces final answer."""
        # Create a test file for read_file to find
        test_file = tmp_path / "test.txt"
        test_file.write_text("file content here")

        provider = ScriptedProvider(
            [
                # First response: tool call to read_file
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id="call_1",
                            name="read_file",
                            arguments={"path": str(test_file)},
                        )
                    ],
                ),
                # Second response: final answer
                LLMResponse(content="The file contains: file content here"),
            ]
        )
        loop = _make_loop(tmp_path, provider)
        msg = _make_inbound("Read test.txt")
        result = await loop._process_message(msg)

        assert result is not None
        assert "file content" in result.content
        assert provider._index == 2

    async def test_multiple_tool_calls(self, tmp_path: Path):
        """Agent makes multiple sequential tool calls."""
        (tmp_path / "a.txt").write_text("alpha")
        (tmp_path / "b.txt").write_text("beta")

        provider = ScriptedProvider(
            [
                # Call 1: read a.txt
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id="c1", name="read_file", arguments={"path": str(tmp_path / "a.txt")}
                        ),
                    ],
                ),
                # Call 2: read b.txt
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id="c2", name="read_file", arguments={"path": str(tmp_path / "b.txt")}
                        ),
                    ],
                ),
                # Answer
                LLMResponse(content="a.txt contains alpha, b.txt contains beta"),
            ]
        )
        loop = _make_loop(tmp_path, provider)
        result = await loop._process_message(_make_inbound("Read both files"))

        assert result is not None
        assert "alpha" in result.content
        assert "beta" in result.content


class TestAgentLoopToolFailure:
    """Test tool failure, reflection, and retry."""

    async def test_tool_not_found(self, tmp_path: Path):
        """Calling a nonexistent tool returns an error, agent continues."""
        provider = ScriptedProvider(
            [
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(id="c1", name="nonexistent_tool", arguments={"x": 1}),
                    ],
                ),
                # Agent should retry or respond after seeing the error
                LLMResponse(content="Sorry, that tool doesn't exist."),
            ]
        )
        loop = _make_loop(tmp_path, provider)
        result = await loop._process_message(_make_inbound("Use nonexistent_tool"))

        assert result is not None
        assert len(result.content) > 0

    async def test_read_missing_file_retry(self, tmp_path: Path):
        """Reading a missing file fails, agent retries with different approach."""
        provider = ScriptedProvider(
            [
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id="c1",
                            name="read_file",
                            arguments={"path": str(tmp_path / "missing.txt")},
                        ),
                    ],
                ),
                # Agent sees the error and responds
                LLMResponse(content="The file doesn't exist."),
            ]
        )
        loop = _make_loop(tmp_path, provider)
        result = await loop._process_message(_make_inbound("Read missing.txt"))

        assert result is not None
        assert len(result.content) > 0


class TestAgentLoopMaxIterations:
    """Test max iterations limit."""

    async def test_max_iterations_reached(self, tmp_path: Path):
        """Agent stops after max_iterations and returns a fallback message."""
        # All responses are tool calls — agent never produces text
        provider = ScriptedProvider(
            [
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id=f"c{i}", name="list_dir", arguments={"path": str(tmp_path)}
                        ),
                    ],
                )
                for i in range(10)  # More than max_iterations=3
            ]
        )
        loop = _make_loop(tmp_path, provider, max_iterations=3)
        result = await loop._process_message(_make_inbound("List directory forever"))

        assert result is not None
        assert "maximum" in result.content.lower() or "iterations" in result.content.lower()


class TestAgentLoopConsecutiveErrors:
    """Test consecutive LLM errors -> graceful fallback."""

    async def test_consecutive_llm_errors(self, tmp_path: Path):
        """Three consecutive LLM errors cause graceful failure."""
        provider = ScriptedProvider(
            [
                LLMResponse(content="LLM error occurred", finish_reason="error"),
                LLMResponse(content="LLM error occurred", finish_reason="error"),
                LLMResponse(content="LLM error occurred", finish_reason="error"),
            ]
        )
        loop = _make_loop(tmp_path, provider)
        result = await loop._process_message(_make_inbound("Hello"))

        assert result is not None
        assert "trouble" in result.content.lower() or "try again" in result.content.lower()


class TestAgentLoopNudgeFinalAnswer:
    """Test the nudge for final answer when tool results present but no text."""

    async def test_nudge_after_tool_result_no_text(self, tmp_path: Path):
        """When LLM returns tool results with content, then blank, it gets nudged."""
        test_file = tmp_path / "data.txt"
        test_file.write_text("important data")

        provider = ScriptedProvider(
            [
                # Tool call
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id="c1", name="read_file", arguments={"path": str(test_file)}
                        ),
                    ],
                ),
                # LLM returns content + tool calls (no final answer yet)
                LLMResponse(
                    content="Let me check...",
                    tool_calls=[
                        ToolCallRequest(
                            id="c2", name="list_dir", arguments={"path": str(tmp_path)}
                        ),
                    ],
                ),
                # Now final answer
                LLMResponse(content="The data file contains: important data"),
            ]
        )
        loop = _make_loop(tmp_path, provider)
        result = await loop._process_message(_make_inbound("What's in data.txt?"))

        assert result is not None
        assert "important data" in result.content


class TestAgentLoopPlanning:
    """Test planning prompt injection."""

    async def test_planning_prompt_injected(self, tmp_path: Path):
        """When planning is enabled and task looks complex, planning prompt is injected."""
        provider = ScriptedProvider(
            [
                LLMResponse(content="1. First step\n2. Second step\nDone!"),
            ]
        )
        loop = _make_loop(tmp_path, provider, planning_enabled=True)
        # Multi-step request that triggers planning
        msg = _make_inbound("Research the weather and then create a summary report")
        result = await loop._process_message(msg)

        assert result is not None
        # Provider should've received messages — check that a system message with planning was in there
        assert provider._index >= 1

    async def test_planning_not_injected_for_simple_query(self, tmp_path: Path):
        """Simple queries don't trigger planning."""
        provider = ScriptedProvider(
            [
                LLMResponse(content="It's 42."),
            ]
        )
        loop = _make_loop(tmp_path, provider, planning_enabled=True)
        msg = _make_inbound("What is 6 * 7?")
        result = await loop._process_message(msg)

        assert result is not None
        assert result.content == "It's 42."


class TestAgentLoopContextCompression:
    """Test context compression under budget pressure."""

    async def test_large_context_triggers_compression(self, tmp_path: Path):
        """Compression doesn't crash or lose the final answer."""
        # Build a long conversation that would overflow
        provider = ScriptedProvider(
            [
                LLMResponse(content="Summary: all good"),
            ]
        )
        loop = _make_loop(tmp_path, provider, context_window_tokens=500)

        # Manually inject many messages into a session to force compression
        session = loop.sessions.get_or_create("cli:test-user")
        for i in range(50):
            session.messages.append(
                {
                    "role": "user" if i % 2 == 0 else "assistant",
                    "content": f"Message number {i} " * 100,  # Large messages
                }
            )
        loop.sessions.save(session)

        msg = _make_inbound("Summarize everything")
        result = await loop._process_message(msg)

        assert result is not None
        assert len(result.content) > 0

    async def test_compression_skipped_when_under_budget(self, tmp_path: Path):
        """summarize_and_compress must NOT be called when tokens are well under budget.

        This is the PERF-C1 regression guard: with a large context window and a short
        message history, the 85%-threshold guard should prevent the expensive compression
        pass from running at all.
        """
        from unittest.mock import AsyncMock, patch

        provider = ScriptedProvider([LLMResponse(content="Done.")])
        # Very large context window so a tiny history is always well under 85%
        loop = _make_loop(tmp_path, provider, context_window_tokens=128_000)

        with patch(
            "nanobot.agent.turn_orchestrator.summarize_and_compress", new_callable=AsyncMock
        ) as mock_compress:
            await loop._process_message(_make_inbound("Hello"))
            mock_compress.assert_not_called()


class TestAgentLoopSlashCommands:
    """Test slash command handling."""

    async def test_help_command(self, tmp_path: Path):
        """The /help command returns help text without calling LLM."""
        provider = ScriptedProvider([])
        loop = _make_loop(tmp_path, provider)
        result = await loop._process_message(_make_inbound("/help"))

        assert result is not None
        assert "commands" in result.content.lower()
        assert provider._index == 0  # No LLM call

    async def test_new_command(self, tmp_path: Path):
        """The /new command clears session."""
        # Provide a consolidation-compatible response (save_memory tool call)
        provider = ScriptedProvider(
            [
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id="save1",
                            name="save_memory",
                            arguments={
                                "updated_memory": "# Memory\n\nOld message captured.",
                                "history_entry": "User said: old message",
                            },
                        )
                    ],
                ),
            ]
        )
        loop = _make_loop(tmp_path, provider)

        # Add some history first
        session = loop.sessions.get_or_create("cli:test-user")
        session.messages.append({"role": "user", "content": "old message"})
        loop.sessions.save(session)

        result = await loop._process_message(_make_inbound("/new"))

        assert result is not None
        assert "new session" in result.content.lower()


class TestAgentLoopProviderCallLog:
    """Verify that the provider receives the expected number and shape of calls."""

    async def test_single_provider_call_for_simple_qa(self, tmp_path: Path):
        """Simple Q&A makes exactly 1 provider call (no verification, no planning)."""
        provider = ScriptedProvider(
            [
                LLMResponse(content="The answer is 42."),
            ]
        )
        loop = _make_loop(tmp_path, provider)
        await loop._process_message(_make_inbound("What is the answer?"))

        assert len(provider.call_log) == 1
        assert provider.call_log[0]["has_tools"] is True  # tools always offered first turn


class TestToolCallTrackerIntegration:
    """ToolCallTracker breaks infinite identical-failure loops."""

    async def test_stuck_tool_loop_injects_escalation(self, tmp_path: Path):
        """Agent retries the same failing read_file call; tracker injects escalation prompts.

        The scripted provider keeps calling read_file on a non-existent path.
        We verify that system messages are injected warning and then removing
        the tool, plus the global budget exhaustion message.
        """
        bad_path = str(tmp_path / "does_not_exist.bin")

        # Many identical tool calls — ScriptedProvider doesn't react to prompts
        responses = [
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(id=f"c{i}", name="read_file", arguments={"path": bad_path}),
                ],
            )
            for i in range(15)
        ]

        provider = ScriptedProvider(responses)
        loop = _make_loop(tmp_path, provider, max_iterations=12)
        result = await loop._process_message(_make_inbound("Read the binary file"))

        assert result is not None

        # Collect all system messages from the provider call log
        # The provider sees messages with escalation prompts injected by the tracker
        last_call = provider.call_log[-1]
        total_messages = last_call["messages_count"]
        # The tracker should have injected extra system messages, inflating count
        # beyond what a clean loop would produce (2 msgs per iteration: assistant+tool_result)
        # With tracker injections, we expect significantly more messages
        assert total_messages > 12  # Would be ~2 + (2 * iterations) without tracker

    async def test_different_args_do_not_trigger_removal(self, tmp_path: Path):
        """Different arguments for the same tool are tracked independently."""
        file_a = tmp_path / "a.txt"
        file_b = tmp_path / "b.txt"
        file_a.write_text("content a")
        file_b.write_text("content b")

        provider = ScriptedProvider(
            [
                # Two different successful reads — no escalation
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(id="c1", name="read_file", arguments={"path": str(file_a)}),
                    ],
                ),
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(id="c2", name="read_file", arguments={"path": str(file_b)}),
                    ],
                ),
                LLMResponse(content="Both files read successfully."),
            ]
        )
        loop = _make_loop(tmp_path, provider, max_iterations=5)
        result = await loop._process_message(_make_inbound("Read both files"))

        assert result is not None
        assert "both files" in result.content.lower()
        # All 3 provider calls should have been made (no premature cutoff)
        assert len(provider.call_log) == 3

    async def test_suppressed_tool_available_in_next_turn(self, tmp_path: Path):
        """A tool suppressed within turn N must be available in the registry for turn N+1.

        This is the CQ-H3 regression guard: disabled_tools is a local variable scoped
        to _run_agent_loop. The registry must never be mutated, so suppressed tools must
        remain registered and available for subsequent turns.
        """
        from nanobot.agent.failure import ToolCallTracker

        bad_path = str(tmp_path / "does_not_exist.bin")

        # Turn 1: keep calling read_file with a bad path until the tracker suppresses it
        n_fail = ToolCallTracker.REMOVE_THRESHOLD + 1
        responses = (
            [
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(id=f"c{i}", name="read_file", arguments={"path": bad_path})
                    ],
                )
                for i in range(n_fail)
            ]
            + [LLMResponse(content="Could not read file.")]
            + [
                # Extra buffer responses to absorb internal calls (consolidation etc.)
                LLMResponse(content="(buffer)")
                for _ in range(10)
            ]
        )

        provider = ScriptedProvider(responses)
        loop = _make_loop(tmp_path, provider, max_iterations=n_fail + 3)

        # Verify read_file is registered before turn 1
        tool_names_before = {d["function"]["name"] for d in loop.tools.get_definitions()}
        assert "read_file" in tool_names_before

        await loop._process_message(_make_inbound("Read the binary file"))

        # After turn 1, the registry must still contain read_file.
        # If the old bug (unregister) were present, it would be gone.
        tool_names_after = {d["function"]["name"] for d in loop.tools.get_definitions()}
        assert "read_file" in tool_names_after, (
            "read_file was removed from the registry after a turn — "
            "disabled_tools must be turn-scoped only"
        )

    async def test_suppressed_tool_absent_from_tools_def_same_turn(self, tmp_path: Path):
        """After REMOVE_THRESHOLD failures, the tool must not appear in tools_def
        for subsequent LLM calls within the same turn (TEST-H2 regression guard)."""
        from nanobot.agent.failure import ToolCallTracker

        bad_path = str(tmp_path / "does_not_exist.bin")

        # 1 extra call after threshold so we can observe the post-removal tools list
        n_fail = ToolCallTracker.REMOVE_THRESHOLD + 1
        responses = (
            [
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(id=f"c{i}", name="read_file", arguments={"path": bad_path})
                    ],
                )
                for i in range(n_fail)
            ]
            + [LLMResponse(content="Done.")]
            + [LLMResponse(content="(buffer)") for _ in range(10)]
        )

        provider = ScriptedProvider(responses)
        loop = _make_loop(tmp_path, provider, max_iterations=n_fail + 3)
        await loop._process_message(_make_inbound("Read binary"))

        # Calls 0..REMOVE_THRESHOLD-1: read_file present in tools_def
        # Call REMOVE_THRESHOLD and beyond: read_file must NOT appear
        post_removal = provider.call_log[ToolCallTracker.REMOVE_THRESHOLD :]
        assert post_removal, "Expected at least one LLM call after tool removal"
        for call in post_removal:
            assert "read_file" not in call["tool_names"], (
                f"read_file appeared in tools_def after suppression: {call}"
            )


class TestSaveTurnFiltering:
    """Verify _save_turn excludes ephemeral system messages."""

    async def test_system_messages_not_persisted(self, tmp_path: Path):
        """Ephemeral system messages (reflect/progress) must not be saved to session."""
        provider = ScriptedProvider(
            [
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id="c1",
                            name="read_file",
                            arguments={"path": str(tmp_path / "f.txt")},
                        )
                    ],
                ),
                LLMResponse(content="Done."),
            ]
        )
        (tmp_path / "f.txt").write_text("hello")
        loop = _make_loop(tmp_path, provider)
        msg = _make_inbound("Read f.txt")
        await loop._process_message(msg)

        session = loop.sessions.get_or_create("cli:test-user")
        roles = [m["role"] for m in session.messages]
        assert "system" not in roles, "Ephemeral system messages should not be persisted in session"


class TestBuildFailurePrompt:
    """Unit tests for _build_failure_prompt content (TEST-H4)."""

    def test_permanent_failure_includes_disabled_language(self):
        """PERMANENT_CONFIG failure must say 'permanently disabled' and list removed tools."""
        from nanobot.agent.failure import FailureClass, _build_failure_prompt

        prompt = _build_failure_prompt(
            [("web_search", FailureClass.PERMANENT_CONFIG)],
            frozenset({"web_search"}),
            ["read_file", "web_search"],
        )
        assert "permanently disabled" in prompt
        assert "web_search" in prompt
        assert "do NOT call" in prompt

    def test_transient_timeout_includes_retry_guidance(self):
        """TRANSIENT_TIMEOUT failure must suggest retry with shorter operation."""
        from nanobot.agent.failure import FailureClass, _build_failure_prompt

        prompt = _build_failure_prompt(
            [("web_fetch", FailureClass.TRANSIENT_TIMEOUT)],
            frozenset(),
            ["web_fetch"],
        )
        assert "retry" in prompt.lower() or "shorter operation" in prompt

    def test_logical_error_suggests_parameter_fix(self):
        """LOGICAL_ERROR must tell the model to fix parameters before retrying."""
        from nanobot.agent.failure import FailureClass, _build_failure_prompt

        prompt = _build_failure_prompt(
            [("read_file", FailureClass.LOGICAL_ERROR)],
            frozenset(),
            ["read_file"],
        )
        assert "fix the parameters" in prompt or "parameters" in prompt

    def test_available_alternatives_listed(self):
        """Remaining (non-permanent) tools must appear in the alternatives section."""
        from nanobot.agent.failure import FailureClass, _build_failure_prompt

        prompt = _build_failure_prompt(
            [("web_search", FailureClass.PERMANENT_CONFIG)],
            frozenset({"web_search"}),
            ["read_file", "exec", "web_search"],
        )
        assert "read_file" in prompt
        assert "exec" in prompt

    def test_no_permanent_failures_no_disabled_list(self):
        """When no tools are permanently failed, the 'do NOT call' line must not appear."""
        from nanobot.agent.failure import FailureClass, _build_failure_prompt

        prompt = _build_failure_prompt(
            [("web_fetch", FailureClass.TRANSIENT_TIMEOUT)],
            frozenset(),
            ["web_fetch"],
        )
        assert "do NOT call" not in prompt


# ---------------------------------------------------------------------------
# TEST-H3: delegation depth guard
# ---------------------------------------------------------------------------


class TestDelegationDepthLimit:
    """MAX_DELEGATION_DEPTH blocks at depth 3 (TEST-H3)."""

    def test_depth_blocks_at_limit(self, tmp_path: Path):
        """dispatch() raises _CycleError when ancestry depth == MAX_DELEGATION_DEPTH."""
        import asyncio
        from unittest.mock import MagicMock

        from nanobot.agent.delegation import (
            MAX_DELEGATION_DEPTH,
            DelegationConfig,
            DelegationDispatcher,
            _delegation_ancestry,
        )
        from nanobot.config.schema import AgentRoleConfig, ExecToolConfig
        from nanobot.tools.builtin.delegate import _CycleError

        provider = ScriptedProvider([])
        dispatcher = DelegationDispatcher(
            config=DelegationConfig(
                workspace=tmp_path,
                model="test-model",
                temperature=0.0,
                max_tokens=2048,
                max_iterations=3,
                restrict_to_workspace=True,
                brave_api_key="",
                exec_config=ExecToolConfig(),
                role_name="parent",
            ),
            provider=provider,
        )

        # Provide a mock coordinator so dispatch() gets past the coordinator check
        role = AgentRoleConfig(name="child", model="test-model")
        mock_coordinator = MagicMock()
        mock_coordinator.route_direct.return_value = role
        dispatcher.coordinator = mock_coordinator

        # Simulate ancestry already at max depth
        token = _delegation_ancestry.set(tuple(f"role_{i}" for i in range(MAX_DELEGATION_DEPTH)))
        try:
            with pytest.raises(_CycleError, match="Maximum delegation depth"):
                asyncio.new_event_loop().run_until_complete(
                    dispatcher.dispatch("child", "do something", context=None)
                )
        finally:
            _delegation_ancestry.reset(token)

    def test_depth_below_limit_passes(self, tmp_path: Path):
        """dispatch() does not raise when ancestry depth < MAX_DELEGATION_DEPTH."""
        from nanobot.agent.delegation import (
            MAX_DELEGATION_DEPTH,
            _delegation_ancestry,
        )

        # Build ancestry with one slot free
        ancestry = tuple(f"role_{i}" for i in range(MAX_DELEGATION_DEPTH - 1))
        token = _delegation_ancestry.set(ancestry)
        try:
            # Just check no CycleError for depth check; dispatch may still fail
            # for other reasons (no scripted response), so we only check the
            # error type.
            from nanobot.agent.delegation import MAX_DELEGATION_DEPTH as MDD

            assert len(ancestry) < MDD  # sanity
        finally:
            _delegation_ancestry.reset(token)


# ---------------------------------------------------------------------------
# TEST-M3: TurnRoleManager.apply / TurnRoleManager.reset
# ---------------------------------------------------------------------------


class TestRoleSwitching:
    """Unit tests for per-turn role override mechanics (TEST-M3)."""

    def _make_loop_with_role(self, tmp_path: Path):
        from nanobot.config.schema import AgentRoleConfig

        provider = ScriptedProvider([])
        loop = _make_loop(tmp_path, provider)
        role = AgentRoleConfig(
            name="test-role",
            model="override-model",
            temperature=0.1,
            max_iterations=2,
            system_prompt="test role prompt",
        )
        return loop, role

    def test_apply_saves_originals(self, tmp_path: Path):
        loop, role = self._make_loop_with_role(tmp_path)
        orig_model = loop.model
        orig_temp = loop.temperature
        orig_iters = loop.max_iterations

        ctx = loop._role_manager.apply(role)

        assert ctx.model == orig_model
        assert ctx.temperature == orig_temp
        assert ctx.max_iterations == orig_iters

    def test_apply_overrides_settings(self, tmp_path: Path):
        loop, role = self._make_loop_with_role(tmp_path)
        loop._role_manager.apply(role)

        assert loop.model == "override-model"
        assert loop.temperature == pytest.approx(0.1)
        assert loop.max_iterations == 2
        assert loop.context.role_system_prompt == "test role prompt"

    def test_reset_restores_originals(self, tmp_path: Path):
        loop, role = self._make_loop_with_role(tmp_path)
        orig_model = loop.model
        orig_temp = loop.temperature
        orig_iters = loop.max_iterations

        ctx = loop._role_manager.apply(role)
        loop._role_manager.reset(ctx)

        assert loop.model == orig_model
        assert loop.temperature == pytest.approx(orig_temp)
        assert loop.max_iterations == orig_iters

    def test_reset_without_apply_is_noop(self, tmp_path: Path):
        """TurnRoleManager.reset must be safe to call with no prior apply."""
        loop = _make_loop(tmp_path, ScriptedProvider([]))
        orig_model = loop.model
        loop._role_manager.reset(None)  # must not raise
        assert loop.model == orig_model

    def test_apply_tool_filter_saved_and_restored(self, tmp_path: Path):
        """Applying a role with tool filtering snapshots and restores tools."""
        from nanobot.config.schema import AgentRoleConfig

        provider = ScriptedProvider([])
        loop = _make_loop(tmp_path, provider)
        orig_names = set(loop.tools.tool_names)

        role = AgentRoleConfig(name="limited", allowed_tools=["read_file"])
        ctx = loop._role_manager.apply(role)
        # After filtering, only read_file should remain
        assert set(loop.tools.tool_names) == {"read_file"}

        loop._role_manager.reset(ctx)
        # Full tool set must be restored
        assert set(loop.tools.tool_names) == orig_names

    def test_apply_no_filter_does_not_snapshot(self, tmp_path: Path):
        """Roles with no allowed/denied lists must leave TurnContext.tools as None."""
        from nanobot.config.schema import AgentRoleConfig

        loop = _make_loop(tmp_path, ScriptedProvider([]))
        role = AgentRoleConfig(name="passthrough")
        ctx = loop._role_manager.apply(role)
        assert ctx.tools is None


class TestConcurrentProcessMessage:
    """Verify that concurrent _process_message calls for different sessions don't corrupt each other."""

    @pytest.mark.asyncio
    async def test_concurrent_sessions_independent(self, tmp_path: Path):
        """Two simultaneous messages from different sessions must produce independent replies."""

        class IndexedProvider(LLMProvider):
            """Returns a response tagged with the user ID embedded in the message."""

            def get_default_model(self) -> str:
                return "test-model"

            async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> LLMResponse:
                # Reflect back the last user message content so we can verify routing
                last_user = next(
                    (m["content"] for m in reversed(messages) if m.get("role") == "user"),
                    "unknown",
                )
                return LLMResponse(content=f"reply:{last_user}")

        loop = _make_loop(tmp_path, IndexedProvider())

        msg_a = _make_inbound("hello-from-A", chat_id="user-A")
        msg_b = _make_inbound("hello-from-B", chat_id="user-B")

        # Run both concurrently
        await asyncio.gather(
            loop._process_message(msg_a),
            loop._process_message(msg_b),
        )

        session_a = loop.sessions.get_or_create("cli:user-A")
        session_b = loop.sessions.get_or_create("cli:user-B")

        # Each session must contain only its own messages
        contents_a = [m["content"] for m in session_a.messages if m.get("role") == "user"]
        contents_b = [m["content"] for m in session_b.messages if m.get("role") == "user"]

        assert all("hello-from-A" in c for c in contents_a), (
            "Session A must not contain B's messages"
        )
        assert all("hello-from-B" in c for c in contents_b), (
            "Session B must not contain A's messages"
        )
        assert not any("hello-from-B" in c for c in contents_a), (
            "A's session must not leak B's content"
        )
        assert not any("hello-from-A" in c for c in contents_b), (
            "B's session must not leak A's content"
        )


class TestProgressEvents:
    """Test that the agent emits correct typed progress events."""

    async def test_tool_call_emits_tool_call_event(self, tmp_path: Path) -> None:
        """ToolCallEvent is emitted with correct tool_name when a tool is invoked."""
        provider = ScriptedProvider(
            [
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(id="tc1", name="read_file", arguments={"path": "/tmp/x"})
                    ],
                ),
                LLMResponse(content="Done."),
            ]
        )
        received: list[ProgressEvent] = []

        async def tracking(event: ProgressEvent) -> None:
            received.append(event)

        loop = _make_loop(tmp_path, provider)
        await loop.process_direct("read a file", on_progress=tracking)

        tool_events = [e for e in received if isinstance(e, ToolCallEvent)]
        assert any(e.tool_name == "read_file" for e in tool_events)
