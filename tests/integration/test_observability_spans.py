"""IT-19: TraceContext correlation ID management.

Verifies that TraceContext.new_request() generates unique request IDs and
that set/get round-trips correlation IDs correctly.

Does not require LLM API key.
"""

from __future__ import annotations

import pytest

from nanobot.observability.tracing import TraceContext

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTraceContextNewRequest:
    def test_new_request_returns_request_id(self) -> None:
        """new_request() returns a non-empty request ID string."""
        rid = TraceContext.new_request(session_id="sess-1", agent_id="main")

        assert isinstance(rid, str)
        assert len(rid) > 0

    def test_new_request_sets_context(self) -> None:
        """new_request() populates the context dict with all IDs."""
        rid = TraceContext.new_request(session_id="sess-2", agent_id="web")

        ctx = TraceContext.get()
        assert ctx["request_id"] == rid
        assert ctx["session_id"] == "sess-2"
        assert ctx["agent_id"] == "web"

    def test_unique_ids_across_calls(self) -> None:
        """Each call to new_request() produces a different request ID."""
        ids = set()
        for _ in range(50):
            rid = TraceContext.new_request(session_id="s", agent_id="a")
            ids.add(rid)

        assert len(ids) == 50


class TestTraceContextSetGet:
    def test_set_and_get_roundtrip(self) -> None:
        """Values set via TraceContext.set() are returned by get()."""
        TraceContext.set(request_id="req-abc", session_id="sess-xyz", agent_id="code")

        ctx = TraceContext.get()
        assert ctx["request_id"] == "req-abc"
        assert ctx["session_id"] == "sess-xyz"
        assert ctx["agent_id"] == "code"

    def test_partial_set_preserves_other_fields(self) -> None:
        """Setting one field does not clear the others."""
        TraceContext.set(request_id="r1", session_id="s1", agent_id="a1")
        TraceContext.set(agent_id="a2")

        ctx = TraceContext.get()
        assert ctx["request_id"] == "r1"
        assert ctx["session_id"] == "s1"
        assert ctx["agent_id"] == "a2"

    def test_get_returns_dict_with_expected_keys(self) -> None:
        """get() always returns a dict with request_id, session_id, agent_id keys."""
        TraceContext.new_request(session_id="s", agent_id="a")

        ctx = TraceContext.get()
        assert set(ctx.keys()) == {"request_id", "session_id", "agent_id"}
