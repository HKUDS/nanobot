"""Tests for methods moved from ProfileStore to ConflictManager."""

from __future__ import annotations

from unittest.mock import MagicMock

from nanobot.memory.conflicts import ConflictManager


def _make_mgr(profile_store=None):
    ps = profile_store or MagicMock()
    return ConflictManager(
        ps,
        sanitize_mem0_text_fn=lambda t: t,
        normalize_metadata_fn=lambda m, **kw: (m, False),
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


def _make_real_store(tmp_path):
    """Build a minimal ProfileStore for delegation tests."""
    from nanobot.memory.profile_io import ProfileStore

    store = ProfileStore()
    return store


class TestApplyProfileUpdates:
    def _make_mgr_with_store(self, tmp_path):
        from nanobot.memory.conflicts import ConflictManager

        store = _make_real_store(tmp_path)
        mgr = ConflictManager(
            store,
            sanitize_mem0_text_fn=lambda t: t,
            normalize_metadata_fn=lambda m, **kw: (m, False),
            sanitize_metadata_fn=lambda m: m,
        )
        store._conflict_mgr = mgr
        return mgr, store

    def test_returns_tuple_of_three_ints(self, tmp_path):
        mgr, _ = self._make_mgr_with_store(tmp_path)
        profile = {
            "preferences": [],
            "stable_facts": [],
            "active_projects": [],
            "relationships": [],
            "constraints": [],
            "conflicts": [],
            "meta": {
                "preferences": {},
                "stable_facts": {},
                "active_projects": {},
                "relationships": {},
                "constraints": {},
            },
        }
        result = mgr._apply_profile_updates(
            profile,
            {"preferences": ["likes hiking"]},
            enable_contradiction_check=False,
        )
        assert isinstance(result, tuple) and len(result) == 3
        added, conflicts, touched = result
        assert isinstance(added, int)
        assert isinstance(conflicts, int)
        assert isinstance(touched, int)

    def test_adds_new_preference(self, tmp_path):
        mgr, _ = self._make_mgr_with_store(tmp_path)
        profile = {
            "preferences": [],
            "stable_facts": [],
            "active_projects": [],
            "relationships": [],
            "constraints": [],
            "conflicts": [],
            "meta": {
                "preferences": {},
                "stable_facts": {},
                "active_projects": {},
                "relationships": {},
                "constraints": {},
            },
        }
        added, conflicts, touched = mgr._apply_profile_updates(
            profile,
            {"preferences": ["likes coffee"]},
            enable_contradiction_check=False,
        )
        assert added >= 1
        assert "likes coffee" in profile["preferences"]

    def test_no_duplicate_added(self, tmp_path):
        mgr, _ = self._make_mgr_with_store(tmp_path)
        profile = {
            "preferences": ["likes coffee"],
            "stable_facts": [],
            "active_projects": [],
            "relationships": [],
            "constraints": [],
            "conflicts": [],
            "meta": {
                "preferences": {},
                "stable_facts": {},
                "active_projects": {},
                "relationships": {},
                "constraints": {},
            },
        }
        added, conflicts, touched = mgr._apply_profile_updates(
            profile,
            {"preferences": ["likes coffee"]},
            enable_contradiction_check=False,
        )
        assert added == 0
        assert profile["preferences"].count("likes coffee") == 1

    def test_unknown_key_is_skipped(self, tmp_path):
        mgr, _ = self._make_mgr_with_store(tmp_path)
        profile = {
            "preferences": [],
            "stable_facts": [],
            "active_projects": [],
            "relationships": [],
            "constraints": [],
            "conflicts": [],
            "meta": {
                "preferences": {},
                "stable_facts": {},
                "active_projects": {},
                "relationships": {},
                "constraints": {},
            },
        }
        # "hobbies" is not a valid PROFILE_KEYS key — should be ignored
        added, conflicts, touched = mgr._apply_profile_updates(
            profile,
            {"hobbies": ["hiking"]},
            enable_contradiction_check=False,
        )
        assert added == 0
