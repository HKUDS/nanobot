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
        # Should skip all tool messages since there's no user/assistant
        assert len(history) == 0 or history[0]["role"] in ("user", "assistant")


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
        # Build: [user, assistant(tool_call), tool, assistant, user, ...]
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
        # First message must not be tool
        assert sanitized[0]["role"] != "tool"

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
