"""Block-aligned eviction keeps the replay-window prefix byte-stable (issue #4222).

The legacy count-based slice advances its start index by one on every turn once a
conversation passes ``max_messages``, so the replayed prefix shifts every turn and a
byte-prefix prompt cache misses continuously. ``eviction_stride`` quantizes that
boundary to whole blocks, so the prefix is identical across the turns within a block.
"""

from __future__ import annotations

from nanobot.session.manager import SessionManager
from nanobot.utils.helpers import recent_message_start_index


def _msgs(n: int) -> list[dict]:
    return [{"role": "user", "content": f"m{i}"} for i in range(n)]


def test_window_slides_one_at_a_time_without_stride() -> None:
    # Legacy behavior (the #4222 bug): start advances by one every appended turn.
    assert recent_message_start_index(_msgs(20), 10) == 10
    assert recent_message_start_index(_msgs(21), 10) == 11  # shifted -> cache miss


def test_window_is_quantized_to_blocks_with_stride() -> None:
    max_messages, stride = 10, 4
    starts = [
        recent_message_start_index(_msgs(n), max_messages, eviction_stride=stride)
        for n in range(20, 28)  # raw start would be 10,11,12,13,14,15,16,17
    ]
    # Floored to multiples of the stride: the start only moves every `stride` turns.
    assert starts == [8, 8, 12, 12, 12, 12, 16, 16]


def test_quantized_start_only_ever_keeps_more_messages() -> None:
    # The block alignment can only move the start earlier, so no history is lost.
    max_messages, stride = 10, 4
    for n in range(11, 40):
        raw = recent_message_start_index(_msgs(n), max_messages)
        quantized = recent_message_start_index(_msgs(n), max_messages, eviction_stride=stride)
        assert quantized <= raw
        assert n - quantized <= max_messages + stride  # overshoot is bounded


def test_get_history_prefix_is_byte_stable_within_a_block(tmp_path) -> None:
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("stride-stable")
    for i in range(20):
        session.add_message("user", f"m{i}")

    before = session.get_history(max_messages=10, eviction_stride=4)
    session.add_message("user", "m20")
    after = session.get_history(max_messages=10, eviction_stride=4)

    # Same quantized start (8) -> the next turn is a clean append: the whole prior
    # window is the byte-identical prefix of the new one, so the cache stays warm.
    assert after[: len(before)] == before


def test_get_history_prefix_shifts_without_stride(tmp_path) -> None:
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("stride-legacy")
    for i in range(20):
        session.add_message("user", f"m{i}")

    before = session.get_history(max_messages=10, eviction_stride=1)
    session.add_message("user", "m20")
    after = session.get_history(max_messages=10, eviction_stride=1)

    # Legacy slide-by-one: the window shifted, so the prefix is NOT preserved.
    assert after[: len(before)] != before
