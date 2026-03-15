"""Test that get_history() does not return orphaned tool messages (#2007).

When max_messages slicing cuts right after an assistant tool_call message,
the remaining tool-role messages have no preceding assistant — sending them
to the LLM triggers:

    "Message has tool role, but there was no previous assistant message
     with a tool call!"
"""

from nanobot.providers.base import LLMProvider
from nanobot.session.manager import Session


def _build_session_with_tool_exchange() -> Session:
    """Build a session with user/assistant/tool interleaving."""
    session = Session(key="test:orphan")
    # 10 rounds of: user -> assistant(tool_call) -> tool -> assistant
    for i in range(10):
        session.add_message("user", f"question {i}")
        session.add_message(
            "assistant",
            "",
            tool_calls=[{"id": f"call_{i}", "function": {"name": "search", "arguments": "{}"}}],
        )
        session.add_message("tool", f"result {i}", tool_call_id=f"call_{i}", name="search")
        session.add_message("assistant", f"answer {i}")
    return session


def _validate_tool_message_invariant(messages: list[dict]) -> None:
    """Validate the LLM API invariant: every tool message must be preceded
    by an assistant message with a matching tool_calls entry.

    This is the exact check that causes the 400 error in #2007:
    "Message has tool role, but there was no previous assistant message
     with a tool call!"
    """
    for idx, msg in enumerate(messages):
        if msg.get("role") != "tool":
            continue
        tool_call_id = msg.get("tool_call_id")
        # Walk backwards to find the preceding assistant with tool_calls
        found = False
        for j in range(idx - 1, -1, -1):
            prev = messages[j]
            if prev.get("role") == "assistant" and prev.get("tool_calls"):
                call_ids = {tc["id"] for tc in prev["tool_calls"] if isinstance(tc, dict)}
                if tool_call_id in call_ids:
                    found = True
                    break
            # If we hit a user message, the assistant is missing
            if prev.get("role") == "user":
                break
        assert found, (
            f"Message at index {idx} has tool role with tool_call_id={tool_call_id!r}, "
            f"but there is no preceding assistant message with a matching tool call! "
            f"This would cause a 400 error from the LLM API."
        )


class TestOrphanedToolMessages:
    """Regression tests for #2007."""

    def test_no_leading_tool_role_in_history(self) -> None:
        """get_history() must never start with a tool-role message."""
        session = _build_session_with_tool_exchange()
        # 40 messages total. Slice to 3 so it lands on [tool, assistant, user].
        history = session.get_history(max_messages=3)
        assert history[0]["role"] != "tool", (
            f"History starts with orphaned tool message: {history[0]}"
        )

    def test_slice_starting_at_tool_skips_to_next_valid(self) -> None:
        """When slice starts at a tool message, it should skip to user or assistant."""
        session = _build_session_with_tool_exchange()
        # max_messages=2: last 2 messages are [tool, assistant] or [assistant, user] etc.
        # Try several slice sizes that could land on a tool message.
        for size in range(1, 15):
            history = session.get_history(max_messages=size)
            if history:
                assert history[0]["role"] in ("user", "assistant"), (
                    f"max_messages={size}: history starts with role={history[0]['role']}"
                )

    def test_tool_messages_preserved_when_assistant_present(self) -> None:
        """Tool messages should be kept when their preceding assistant is in the slice."""
        session = _build_session_with_tool_exchange()
        # Full history should contain all tool messages
        history = session.get_history(max_messages=500)
        tool_msgs = [m for m in history if m["role"] == "tool"]
        assert len(tool_msgs) == 10

    def test_empty_session_returns_empty(self) -> None:
        """Edge case: empty session should return empty list."""
        session = Session(key="test:empty")
        assert session.get_history() == []

    def test_only_tool_messages_returns_empty(self) -> None:
        """If session somehow has only tool messages, history should be empty."""
        session = Session(key="test:tools-only")
        session.messages = [
            {"role": "tool", "content": "result", "tool_call_id": "c1", "name": "fn"},
            {"role": "tool", "content": "result2", "tool_call_id": "c2", "name": "fn"},
        ]
        history = session.get_history()
        assert len(history) == 0


class TestEndToEndToolMessageValidation:
    """End-to-end: get_history() -> provider sanitization -> LLM API invariant check.

    Simulates the real user scenario from #2007: a long Feishu conversation with
    tool calls, where max_messages slicing produces orphaned tool messages.
    """

    def test_e2e_long_conversation_all_slice_sizes(self) -> None:
        """For every possible slice size, the history must pass LLM API validation."""
        session = _build_session_with_tool_exchange()
        total = len(session.messages)  # 40

        for size in range(1, total + 5):
            history = session.get_history(max_messages=size)
            # Run through provider sanitization (same as real request path)
            sanitized = LLMProvider._sanitize_empty_content(history)
            _validate_tool_message_invariant(sanitized)

    def test_e2e_slice_lands_exactly_on_tool_message(self) -> None:
        """Reproduce #2007: slice starts with tool message after its assistant was cut."""
        session = Session(key="test:e2e-exact")
        # Build: [user, assistant(tool_call), tool, assistant, user, assistant]
        session.add_message("user", "first question")
        session.add_message(
            "assistant", "",
            tool_calls=[{"id": "call_0", "function": {"name": "search", "arguments": "{}"}}],
        )
        session.add_message("tool", "search result", tool_call_id="call_0", name="search")
        session.add_message("assistant", "here is the answer")
        session.add_message("user", "follow up")
        session.add_message("assistant", "follow up answer")

        # max_messages=4 -> last 4: [tool, assistant, user, assistant]
        # Before fix: tool message would be kept as orphan -> 400 error
        history = session.get_history(max_messages=4)
        sanitized = LLMProvider._sanitize_empty_content(history)
        _validate_tool_message_invariant(sanitized)
        # Should skip orphaned tool, start at assistant "here is the answer"
        assert len(sanitized) == 3
        assert sanitized[0]["role"] == "assistant"
        assert sanitized[0]["content"] == "here is the answer"

    def test_e2e_multiple_tool_calls_in_one_turn(self) -> None:
        """Assistant calls multiple tools in one turn; slice must not orphan any."""
        session = Session(key="test:e2e-multi")
        session.add_message("user", "do two things")
        session.add_message(
            "assistant", "",
            tool_calls=[
                {"id": "call_a", "function": {"name": "tool_a", "arguments": "{}"}},
                {"id": "call_b", "function": {"name": "tool_b", "arguments": "{}"}},
            ],
        )
        session.add_message("tool", "result a", tool_call_id="call_a", name="tool_a")
        session.add_message("tool", "result b", tool_call_id="call_b", name="tool_b")
        session.add_message("assistant", "done")
        session.add_message("user", "thanks")
        session.add_message("assistant", "you're welcome")

        # max_messages=5 -> last 5: [tool, tool, assistant, user, assistant]
        # Both tool messages are orphans
        history = session.get_history(max_messages=5)
        sanitized = LLMProvider._sanitize_empty_content(history)
        _validate_tool_message_invariant(sanitized)

    def test_e2e_long_tool_chain_no_user_in_slice(self) -> None:
        """Exact #2007 reproduction: long tool chain where slice has NO user message.

        This is the real Feishu scenario — assistant calls tools repeatedly,
        max_messages cuts into the middle of the chain. Old logic only looked
        for role=='user' to align, so when there's no user in the slice the
        for-loop never breaks and orphaned tool messages are sent to the LLM.
        """
        session = Session(key="test:e2e-no-user")
        # Normal conversation first
        for i in range(10):
            session.add_message("user", f"q{i}")
            session.add_message("assistant", f"a{i}")
        # Then a long tool-use chain (no user messages)
        session.add_message("user", "complex task")
        session.add_message(
            "assistant", "",
            tool_calls=[{"id": "c1", "function": {"name": "search", "arguments": "{}"}}],
        )
        session.add_message("tool", "r1", tool_call_id="c1", name="search")
        session.add_message(
            "assistant", "",
            tool_calls=[{"id": "c2", "function": {"name": "analyze", "arguments": "{}"}}],
        )
        session.add_message("tool", "r2", tool_call_id="c2", name="analyze")
        session.add_message(
            "assistant", "",
            tool_calls=[{"id": "c3", "function": {"name": "summarize", "arguments": "{}"}}],
        )
        session.add_message("tool", "r3", tool_call_id="c3", name="summarize")
        session.add_message("assistant", "final answer")

        # Slice sizes 2, 4, 6 all start with orphan tool, no user in slice
        for size in [2, 4, 6]:
            history = session.get_history(max_messages=size)
            sanitized = LLMProvider._sanitize_empty_content(history)
            assert not sanitized or sanitized[0]["role"] != "tool", (
                f"max_messages={size}: history starts with orphaned tool message"
            )
            _validate_tool_message_invariant(sanitized)

    def test_e2e_with_consolidation_offset(self) -> None:
        """Simulate a consolidated session where only recent messages remain."""
        session = _build_session_with_tool_exchange()
        # Pretend first 20 messages were consolidated
        session.last_consolidated = 20

        for size in range(1, 25):
            history = session.get_history(max_messages=size)
            sanitized = LLMProvider._sanitize_empty_content(history)
            _validate_tool_message_invariant(sanitized)


class TestTurnCompleteSlicing:
    """Tests for turn-complete history slicing (#2007 enhancement).

    Ensures that when max_messages slicing lands on an assistant(tool_calls),
    all its tool responses are present — otherwise the entire turn is skipped.
    """

    def test_complete_turn_at_start_is_kept(self) -> None:
        """Assistant(tool_calls) at start with all tool responses → kept."""
        session = Session(key="test:complete-turn")
        session.add_message("user", "earlier question")
        session.add_message("assistant", "earlier answer")
        session.add_message(
            "assistant", "",
            tool_calls=[{"id": "call_1", "function": {"name": "search", "arguments": "{}"}}],
        )
        session.add_message("tool", "result", tool_call_id="call_1", name="search")
        session.add_message("assistant", "done")
        session.add_message("user", "follow up")

        # max_messages=4 -> last 4: [assistant(tool_calls), tool, assistant, user]
        # This is a complete turn starting with assistant(tool_calls), should be kept
        history = session.get_history(max_messages=4)
        assert len(history) == 4
        assert history[0]["role"] == "assistant"
        assert history[0].get("tool_calls")
        assert history[1]["role"] == "tool"
        assert history[2]["role"] == "assistant"
        _validate_tool_message_invariant(history)

    def test_incomplete_turn_at_start_is_skipped(self) -> None:
        """Assistant(tool_calls) at start with missing tool responses → skipped."""
        session = Session(key="test:incomplete-turn")
        session.add_message("user", "first")
        session.add_message(
            "assistant", "",
            tool_calls=[{"id": "call_1", "function": {"name": "search", "arguments": "{}"}}],
        )
        session.add_message("tool", "result", tool_call_id="call_1", name="search")
        session.add_message("assistant", "answer")
        session.add_message("user", "second")
        session.add_message("assistant", "final")

        # max_messages=4 -> last 4: [tool, assistant, user, assistant]
        # The tool is orphaned (its assistant was cut), should skip to "answer"
        history = session.get_history(max_messages=4)
        assert len(history) == 3
        assert history[0]["role"] == "assistant"
        assert history[0]["content"] == "answer"
        assert not history[0].get("tool_calls")
        _validate_tool_message_invariant(history)

    def test_parallel_tool_calls_incomplete_is_skipped(self) -> None:
        """Assistant with multiple tool_calls, some missing → entire turn skipped."""
        session = Session(key="test:parallel-incomplete")
        session.add_message("user", "do two things")
        session.add_message(
            "assistant", "",
            tool_calls=[
                {"id": "call_a", "function": {"name": "tool_a", "arguments": "{}"}},
                {"id": "call_b", "function": {"name": "tool_b", "arguments": "{}"}},
            ],
        )
        session.add_message("tool", "result a", tool_call_id="call_a", name="tool_a")
        session.add_message("tool", "result b", tool_call_id="call_b", name="tool_b")
        session.add_message("assistant", "done")
        session.add_message("user", "thanks")
        session.add_message("assistant", "welcome")

        # Total: 7 messages [0-6]
        # max_messages=5 -> last 5: indices [2-6] = [tool_b, assistant, user, assistant, ...]
        # Wait — index 2 is tool_a, not tool_b. Let me recount:
        # [0]=user, [1]=assistant(tc), [2]=tool_a, [3]=tool_b, [4]=assistant, [5]=user, [6]=assistant
        # max_messages=5 -> last 5: indices [2-6] = [tool_a, tool_b, assistant, user, assistant]
        # tool_a and tool_b are orphaned (their assistant was cut)
        history = session.get_history(max_messages=5)
        # Should skip orphaned tools and start at assistant "done"
        assert len(history) == 3
        assert history[0]["role"] == "assistant"
        assert history[0]["content"] == "done"
        _validate_tool_message_invariant(history)

    def test_parallel_tool_calls_complete_is_kept(self) -> None:
        """Assistant with multiple tool_calls, all present → kept."""
        session = Session(key="test:parallel-complete")
        session.add_message("user", "earlier")
        session.add_message("assistant", "earlier answer")
        session.add_message(
            "assistant", "",
            tool_calls=[
                {"id": "call_a", "function": {"name": "tool_a", "arguments": "{}"}},
                {"id": "call_b", "function": {"name": "tool_b", "arguments": "{}"}},
            ],
        )
        session.add_message("tool", "result a", tool_call_id="call_a", name="tool_a")
        session.add_message("tool", "result b", tool_call_id="call_b", name="tool_b")
        session.add_message("assistant", "done")
        session.add_message("user", "thanks")

        # Total: 7 messages [0-6]
        # max_messages=5 -> last 5: indices [2-6] = [assistant(tool_calls), tool_a, tool_b, assistant, user]
        # Complete turn with both tools present, should be kept
        history = session.get_history(max_messages=5)
        assert len(history) == 5
        assert history[0]["role"] == "assistant"
        assert len(history[0].get("tool_calls", [])) == 2
        assert history[1]["role"] == "tool"
        assert history[2]["role"] == "tool"
        _validate_tool_message_invariant(history)

        # max_messages=4 -> last 4: indices [3-6] = [tool_a, tool_b, assistant, user]
        # tool_a and tool_b are orphaned (their assistant was cut), should skip
        history = session.get_history(max_messages=4)
        assert history[0]["role"] in ("user", "assistant")
        if history[0]["role"] == "assistant":
            assert not history[0].get("tool_calls")  # plain assistant
        _validate_tool_message_invariant(history)

    def test_multiple_incomplete_turns_skipped(self) -> None:
        """Multiple incomplete turns at start → all skipped to first valid boundary."""
        session = Session(key="test:multi-incomplete")
        # Build: user, then complete turn 1, complete turn 2, then valid messages
        session.add_message("user", "start")
        session.add_message(
            "assistant", "",
            tool_calls=[{"id": "c1", "function": {"name": "f1", "arguments": "{}"}}],
        )
        session.add_message("tool", "r1", tool_call_id="c1", name="f1")
        session.add_message(
            "assistant", "",
            tool_calls=[{"id": "c2", "function": {"name": "f2", "arguments": "{}"}}],
        )
        session.add_message("tool", "r2", tool_call_id="c2", name="f2")
        session.add_message("assistant", "final")
        session.add_message("user", "question")
        session.add_message("assistant", "answer")

        # Total: 8 messages [0-7]
        # max_messages=6 -> last 6: indices [2-7] = [tool(c1), assistant(c2), tool(c2), assistant, user, assistant]
        # tool(c1) is orphaned (its assistant was cut)
        # assistant(c2)+tool(c2) is a complete turn, should be kept
        history = session.get_history(max_messages=6)
        # Should skip orphaned tool(c1) and start at assistant(c2)
        assert history[0]["role"] == "assistant"
        assert history[0].get("tool_calls")
        assert history[0]["tool_calls"][0]["id"] == "c2"
        _validate_tool_message_invariant(history)

        # max_messages=4 -> last 4: indices [4-7] = [tool(c2), assistant, user, assistant]
        # tool(c2) is orphaned, should skip to assistant "final"
        history = session.get_history(max_messages=4)
        assert history[0]["role"] in ("user", "assistant")
        if history[0]["role"] == "assistant":
            assert not history[0].get("tool_calls")
        _validate_tool_message_invariant(history)

    def test_assistant_with_extra_tool_responses_is_valid(self) -> None:
        """Assistant(tool_calls) followed by its tool responses is valid.

        Tests that the logic correctly validates complete turns.
        """
        session = Session(key="test:extra-tools")
        session.add_message("user", "question")
        session.add_message(
            "assistant", "",
            tool_calls=[{"id": "call_1", "function": {"name": "search", "arguments": "{}"}}],
        )
        session.add_message("tool", "result 1", tool_call_id="call_1", name="search")
        session.add_message("assistant", "answer")
        session.add_message("user", "follow up")

        # max_messages=5 -> all messages
        history = session.get_history(max_messages=5)
        # Should keep the complete turn
        assert history[0]["role"] == "user"
        assert history[1]["role"] == "assistant"
        assert history[1].get("tool_calls")
        assert history[2]["role"] == "tool"
        _validate_tool_message_invariant(history)

    def test_max_messages_landing_on_incomplete_assistant(self) -> None:
        """Exact scenario: max_messages lands right on assistant(tool_calls) with missing tools."""
        session = Session(key="test:exact-landing")
        for i in range(5):
            session.add_message("user", f"q{i}")
            session.add_message("assistant", f"a{i}")
        # Add complete turn
        session.add_message(
            "assistant", "",
            tool_calls=[{"id": "c1", "function": {"name": "search", "arguments": "{}"}}],
        )
        session.add_message("tool", "result", tool_call_id="c1", name="search")
        session.add_message("assistant", "done")
        session.add_message("user", "next")

        # max_messages=4 -> last 4: [assistant(tool_calls), tool, assistant, user]
        # This is complete, should be kept
        history = session.get_history(max_messages=4)
        assert history[0]["role"] == "assistant"
        assert history[0].get("tool_calls")
        _validate_tool_message_invariant(history)

        # max_messages=2 -> last 2: [assistant "done", user]
        # No tool calls, should be kept
        history = session.get_history(max_messages=2)
        assert len(history) == 2
        assert history[0]["role"] == "assistant"
        assert not history[0].get("tool_calls")
        _validate_tool_message_invariant(history)

        # max_messages=3 -> last 3: [tool, assistant "done", user]
        # tool is orphaned, should skip to assistant
        history = session.get_history(max_messages=3)
        assert history[0]["role"] in ("user", "assistant")
        if history[0]["role"] == "assistant":
            assert not history[0].get("tool_calls")
        _validate_tool_message_invariant(history)
