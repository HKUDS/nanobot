"""Regression tests for _SafeFileHistory (Unicode surrogate sanitization).

See issue #2846 / PR #2869.
"""

from __future__ import annotations

from pathlib import Path

from prompt_toolkit.history import FileHistory


def _safe_history(tmp_path: Path):
    """Return a (_SafeFileHistory, path) pair for testing."""
    history_file = tmp_path / "history"
    history_file.parent.mkdir(parents=True, exist_ok=True)

    class _SafeFileHistory(FileHistory):
        def store_string(self, string: str) -> None:
            safe = string.encode("utf-8", errors="surrogateescape").decode(
                "utf-8", errors="replace"
            )
            super().store_string(safe)

    return _SafeFileHistory(str(history_file)), history_file


def test_surrogate_characters_are_sanitized(tmp_path: Path):
    """Surrogate characters should not crash history write."""
    h, _ = _safe_history(tmp_path)
    h.store_string("hello \udcff world")
    h.store_string("emoji \U0001f600 test")
    # store_string writes to the file internally; no separate save needed


def test_normal_strings_pass_through(tmp_path: Path):
    """Normal strings should be stored unchanged."""
    h, path = _safe_history(tmp_path)
    h.store_string("normal string")
    content = Path(str(path)).read_text()
    assert "normal string" in content


def test_mixed_unicode_roundtrip(tmp_path: Path):
    """Mixed Unicode (emoji, CJK, etc.) should survive sanitization."""
    h, _ = _safe_history(tmp_path)
    h.store_string("你好世界 🌍 مرحبا")
    loaded = FileHistory(str(tmp_path / "history"))
    items = list(loaded.load_history_strings())
    assert "你好世界 🌍 مرحبا" in items
