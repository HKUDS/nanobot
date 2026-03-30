"""Tests for CorrectionOrchestrator."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from nanobot.memory.persistence.profile_correction import CorrectionOrchestrator
from nanobot.memory.persistence.profile_io import ProfileStore


def _make_profile_store(tmp_path: Path) -> ProfileStore:
    from nanobot.memory.db import MemoryDatabase

    mem_dir = tmp_path / "memory"
    mem_dir.mkdir(exist_ok=True)
    db = MemoryDatabase(mem_dir / "memory.db", dims=32)
    return ProfileStore(db=db)


class TestCorrectionOrchestrator:
    def test_apply_returns_dict_with_expected_keys(self, tmp_path):
        store = _make_profile_store(tmp_path)
        extractor = MagicMock()
        extractor.extract_explicit_preference_corrections.return_value = []
        extractor.extract_explicit_fact_corrections.return_value = []
        corrector = CorrectionOrchestrator(
            profile_store=store,
            extractor=extractor,
            ingester=MagicMock(),
            coercer=MagicMock(),
            conflict_mgr=MagicMock(),
            snapshot=MagicMock(),
        )
        result = corrector.apply_live_user_correction("some text")
        assert isinstance(result, dict)
        assert "applied" in result
        assert "conflicts" in result

    def test_apply_returns_zero_counts_when_no_corrections_extracted(self, tmp_path):
        store = _make_profile_store(tmp_path)
        extractor = MagicMock()
        extractor.extract_explicit_preference_corrections.return_value = []
        extractor.extract_explicit_fact_corrections.return_value = []
        corrector = CorrectionOrchestrator(
            profile_store=store,
            extractor=extractor,
            ingester=MagicMock(),
            coercer=MagicMock(),
            conflict_mgr=MagicMock(),
            snapshot=MagicMock(),
        )
        result = corrector.apply_live_user_correction("random text with no corrections")
        assert result["applied"] == 0
        assert result["conflicts"] == 0

    def test_profile_store_facade_delegates_to_corrector(self, tmp_path):
        store = _make_profile_store(tmp_path)
        corrector = MagicMock()
        corrector.apply_live_user_correction.return_value = {"applied": 1, "conflicts": 0}
        store.set_corrector(corrector)
        result = store.apply_live_user_correction("I prefer tea")
        corrector.apply_live_user_correction.assert_called_once_with(
            "I prefer tea", channel="", chat_id="", enable_contradiction_check=True
        )
        assert result == {"applied": 1, "conflicts": 0}
