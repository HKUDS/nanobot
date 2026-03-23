"""Tests for Phase B — claim-evidence coherence in compression.

Covers:
- ``_collect_tail_tool_call_ids`` extracts IDs from tail
- ``_paired_drop_tools`` preserves coherence, marks omissions
- ``_dynamic_preserve_recent`` scans for last tool-call cycle
"""

from __future__ import annotations

from nanobot.agent.compression import (
    _collect_tail_tool_call_ids,
    _paired_drop_tools,
)
from nanobot.agent.turn_orchestrator import _dynamic_preserve_recent

# ---------------------------------------------------------------------------
# _collect_tail_tool_call_ids
# ---------------------------------------------------------------------------


class TestCollectTailToolCallIds:
    def test_empty_tail(self) -> None:
        assert _collect_tail_tool_call_ids([]) == set()

    def test_extracts_from_tool_results(self) -> None:
        tail = [
            {"role": "tool", "content": "ok", "tool_call_id": "tc1"},
            {"role": "tool", "content": "ok", "tool_call_id": "tc2"},
        ]
        assert _collect_tail_tool_call_ids(tail) == {"tc1", "tc2"}

    def test_extracts_from_assistant_tool_calls(self) -> None:
        tail = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "tc3", "type": "function", "function": {"name": "read_file"}},
                    {"id": "tc4", "type": "function", "function": {"name": "exec"}},
                ],
            },
        ]
        assert _collect_tail_tool_call_ids(tail) == {"tc3", "tc4"}

    def test_ignores_messages_without_ids(self) -> None:
        tail = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        assert _collect_tail_tool_call_ids(tail) == set()

    def test_mixed_tail(self) -> None:
        tail = [
            {
                "role": "assistant",
                "tool_calls": [{"id": "tc5", "type": "function", "function": {"name": "f"}}],
            },
            {"role": "tool", "content": "result", "tool_call_id": "tc5"},
            {"role": "user", "content": "next question"},
        ]
        assert _collect_tail_tool_call_ids(tail) == {"tc5"}


# ---------------------------------------------------------------------------
# _paired_drop_tools
# ---------------------------------------------------------------------------


class TestPairedDropTools:
    def test_empty(self) -> None:
        assert _paired_drop_tools([], []) == []

    def test_drops_tool_results_not_in_tail(self) -> None:
        middle = [
            {"role": "tool", "content": "old result", "tool_call_id": "tc1"},
            {"role": "user", "content": "question"},
        ]
        tail: list[dict] = []
        result = _paired_drop_tools(middle, tail)
        # Tool result tc1 not referenced in tail → dropped
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_keeps_tool_results_referenced_in_tail(self) -> None:
        middle = [
            {"role": "tool", "content": "needed result", "tool_call_id": "tc1"},
            {"role": "user", "content": "question"},
        ]
        tail = [
            {
                "role": "assistant",
                "tool_calls": [{"id": "tc1", "type": "function", "function": {"name": "f"}}],
            },
        ]
        result = _paired_drop_tools(middle, tail)
        # tc1 is in tail → kept
        assert len(result) == 2
        tool_msgs = [m for m in result if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["tool_call_id"] == "tc1"

    def test_annotates_orphaned_assistant_tool_calls(self) -> None:
        middle = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "tc1", "type": "function", "function": {"name": "read_file"}},
                    {"id": "tc2", "type": "function", "function": {"name": "exec"}},
                ],
            },
            {"role": "tool", "content": "result1", "tool_call_id": "tc1"},
            {"role": "tool", "content": "result2", "tool_call_id": "tc2"},
        ]
        # Only tc1 is in tail
        tail = [{"role": "tool", "content": "reused", "tool_call_id": "tc1"}]
        result = _paired_drop_tools(middle, tail)

        # tc1 result kept, tc2 result dropped
        tool_msgs = [m for m in result if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["tool_call_id"] == "tc1"

        # Assistant tool_calls: tc2 should be annotated with _result_omitted
        assistant = result[0]
        calls = assistant["tool_calls"]
        tc1_call = [c for c in calls if c["id"] == "tc1"][0]
        tc2_call = [c for c in calls if c["id"] == "tc2"][0]
        assert tc1_call["function"].get("_result_omitted") is None
        assert tc2_call["function"]["_result_omitted"] is True

    def test_non_tool_messages_preserved(self) -> None:
        middle = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
            {"role": "tool", "content": "dropped", "tool_call_id": "tc1"},
        ]
        result = _paired_drop_tools(middle, [])
        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"

    def test_original_messages_not_mutated(self) -> None:
        middle = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "tc1", "type": "function", "function": {"name": "f"}},
                ],
            },
            {"role": "tool", "content": "dropped", "tool_call_id": "tc1"},
        ]
        # Deep copy check
        import copy

        original = copy.deepcopy(middle)
        _paired_drop_tools(middle, [])
        assert middle == original


# ---------------------------------------------------------------------------
# _dynamic_preserve_recent
# ---------------------------------------------------------------------------


class TestDynamicPreserveRecent:
    def test_short_messages_returns_floor(self) -> None:
        msgs = [{"role": "user", "content": "hi"}]
        assert _dynamic_preserve_recent(msgs) == 6

    def test_no_tool_calls_returns_floor(self) -> None:
        msgs = [
            {"role": "system", "content": "sys"},
            *[{"role": "user", "content": f"msg{i}"} for i in range(20)],
        ]
        assert _dynamic_preserve_recent(msgs) == 6

    def test_includes_last_tool_call_cycle(self) -> None:
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "old question"},
            {"role": "assistant", "content": "old answer"},
            # Tool call cycle at position 3
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "tc1", "type": "function", "function": {"name": "f"}}],
            },
            {"role": "tool", "content": "result", "tool_call_id": "tc1"},
            {"role": "assistant", "content": "based on the result..."},
            {"role": "user", "content": "follow-up"},
        ]
        result = _dynamic_preserve_recent(msgs)
        # Should preserve from index 3 to end = 4 messages, but floor is 6
        assert result == 6

    def test_large_tool_cycle_respected(self) -> None:
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "old reply"},
        ]
        # Add a big tool cycle at position 3
        msgs.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": f"tc{i}", "type": "function", "function": {"name": "f"}}
                    for i in range(8)
                ],
            }
        )
        for i in range(8):
            msgs.append({"role": "tool", "content": f"r{i}", "tool_call_id": f"tc{i}"})
        msgs.append({"role": "assistant", "content": "final"})
        msgs.append({"role": "user", "content": "next"})

        result = _dynamic_preserve_recent(msgs)
        # From the assistant w/ tool_calls (idx 3) to end = 14-3 = 11 messages
        assert result == 11

    def test_capped_at_cap(self) -> None:
        msgs = [{"role": "system", "content": "sys"}]
        # Tool call at index 1, followed by 40 messages
        msgs.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "tc1", "type": "function", "function": {"name": "f"}}],
            }
        )
        for i in range(40):
            msgs.append({"role": "user", "content": f"msg{i}"})
        result = _dynamic_preserve_recent(msgs, cap=30)
        assert result == 30

    def test_custom_floor(self) -> None:
        msgs = [{"role": "user", "content": f"m{i}"} for i in range(3)]
        assert _dynamic_preserve_recent(msgs, floor=10) == 10
