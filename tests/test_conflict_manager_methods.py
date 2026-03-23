"""Tests for methods moved from ProfileStore to ConflictManager."""

from __future__ import annotations

from unittest.mock import MagicMock

from nanobot.agent.memory.conflicts import ConflictManager


def _make_mgr(profile_store=None):
    mem0 = MagicMock()
    ps = profile_store or MagicMock()
    return ConflictManager(
        ps,
        mem0,
        sanitize_mem0_text_fn=lambda t: t,
        normalize_metadata_fn=lambda m: m,
        sanitize_metadata_fn=lambda m: m,
    )


class TestConflictPair:
    def test_identical_values_return_false(self):
        mgr = _make_mgr()
        assert mgr._conflict_pair("coffee", "coffee") is False

    def test_different_values_no_negation_return_false(self):
        # No negation markers — not a conflict pair
        mgr = _make_mgr()
        assert mgr._conflict_pair("coffee", "tea") is False

    def test_similar_values_return_false(self):
        # Near-identical after normalisation should not be a conflict
        mgr = _make_mgr()
        assert mgr._conflict_pair("I like coffee", "I like coffee") is False

    def test_negation_with_overlap_returns_true(self):
        # One side has "not", other doesn't, with enough token overlap
        mgr = _make_mgr()
        assert mgr._conflict_pair("I like coffee", "I do not like coffee") is True

    def test_empty_values_return_false(self):
        mgr = _make_mgr()
        assert mgr._conflict_pair("", "tea") is False
        assert mgr._conflict_pair("coffee", "") is False


class TestHasOpenConflict:
    def test_returns_false_when_no_conflicts(self):
        mgr = _make_mgr()
        profile = {"conflicts": []}
        assert mgr.has_open_conflict(profile, "preferences") is False

    def test_returns_true_when_open_conflict_exists(self):
        mgr = _make_mgr()
        profile = {
            "conflicts": [{"field": "preferences", "status": "open", "old": "coffee", "new": "tea"}]
        }
        assert mgr.has_open_conflict(profile, "preferences") is True

    def test_returns_false_when_conflict_resolved(self):
        mgr = _make_mgr()
        profile = {
            "conflicts": [
                {"field": "preferences", "status": "resolved", "old": "coffee", "new": "tea"}
            ]
        }
        assert mgr.has_open_conflict(profile, "preferences") is False

    def test_returns_false_for_different_field(self):
        mgr = _make_mgr()
        profile = {
            "conflicts": [{"field": "stable_facts", "status": "open", "old": "a", "new": "b"}]
        }
        assert mgr.has_open_conflict(profile, "preferences") is False

    def test_returns_true_for_needs_user_status(self):
        mgr = _make_mgr()
        profile = {
            "conflicts": [{"field": "preferences", "status": "needs_user", "old": "x", "new": "y"}]
        }
        assert mgr.has_open_conflict(profile, "preferences") is True

    def test_returns_false_when_no_conflicts_key(self):
        mgr = _make_mgr()
        profile = {}
        assert mgr.has_open_conflict(profile, "preferences") is False
