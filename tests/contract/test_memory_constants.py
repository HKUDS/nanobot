"""Contract tests for memory domain constants.

Verifies that all memory constants are defined in a single location
and that cross-component data contracts hold.
"""

from __future__ import annotations

from nanobot.memory.constants import (
    CONFLICT_STATUS_NEEDS_USER,
    CONFLICT_STATUS_OPEN,
    CONFLICT_STATUS_RESOLVED,
    EPISODIC_STATUS_OPEN,
    EPISODIC_STATUS_RESOLVED,
    EVENT_TYPES,
    MEMORY_STABILITY,
    MEMORY_TYPES,
    PROFILE_KEYS,
    PROFILE_STATUS_ACTIVE,
    PROFILE_STATUS_CONFLICTED,
    PROFILE_STATUS_STALE,
)


class TestConstantsExist:
    """All domain constants are importable from constants.py."""

    def test_profile_keys_is_tuple(self) -> None:
        assert isinstance(PROFILE_KEYS, tuple)
        assert len(PROFILE_KEYS) == 5
        assert "preferences" in PROFILE_KEYS
        assert "stable_facts" in PROFILE_KEYS
        assert "active_projects" in PROFILE_KEYS
        assert "relationships" in PROFILE_KEYS
        assert "constraints" in PROFILE_KEYS

    def test_event_types(self) -> None:
        assert isinstance(EVENT_TYPES, frozenset)
        assert EVENT_TYPES == {
            "preference",
            "fact",
            "task",
            "decision",
            "constraint",
            "relationship",
        }

    def test_memory_types(self) -> None:
        assert isinstance(MEMORY_TYPES, frozenset)
        assert MEMORY_TYPES == {"semantic", "episodic", "reflection"}

    def test_memory_stability(self) -> None:
        assert isinstance(MEMORY_STABILITY, frozenset)
        assert MEMORY_STABILITY == {"high", "medium", "low"}

    def test_conflict_statuses(self) -> None:
        assert CONFLICT_STATUS_OPEN == "open"
        assert CONFLICT_STATUS_NEEDS_USER == "needs_user"
        assert CONFLICT_STATUS_RESOLVED == "resolved"

    def test_episodic_statuses(self) -> None:
        assert EPISODIC_STATUS_OPEN == "open"
        assert EPISODIC_STATUS_RESOLVED == "resolved"

    def test_profile_statuses(self) -> None:
        assert PROFILE_STATUS_ACTIVE == "active"
        assert PROFILE_STATUS_CONFLICTED == "conflicted"
        assert PROFILE_STATUS_STALE == "stale"


class TestEventTypeConsistency:
    """The MemoryEvent Pydantic model and constants agree on valid types."""

    def test_event_type_literal_matches_set(self) -> None:
        """EventType Literal and EVENT_TYPES frozenset contain the same values."""
        from typing import get_args

        from nanobot.memory.event import EventType

        literal_values = set(get_args(EventType))
        assert literal_values == EVENT_TYPES

    def test_memory_type_literal_matches_set(self) -> None:
        from typing import get_args

        from nanobot.memory.event import MemoryType

        literal_values = set(get_args(MemoryType))
        assert literal_values == MEMORY_TYPES

    def test_stability_literal_matches_set(self) -> None:
        from typing import get_args

        from nanobot.memory.event import Stability

        literal_values = set(get_args(Stability))
        assert literal_values == MEMORY_STABILITY
