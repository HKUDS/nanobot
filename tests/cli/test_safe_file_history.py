"""Regression tests for SafeFileHistory (issue #2846).

Surrogate characters in CLI input must not crash history file writes.
"""

from nanobot.cli.commands import SafeFileHistory as LegacySafeFileHistory
from nanobot.cli.terminal import SafeFileHistory


def test_commands_keeps_safe_file_history_import_compatible() -> None:
    assert LegacySafeFileHistory is SafeFileHistory


class TestSafeFileHistory:
    def test_surrogate_replaced(self, tmp_path):
        hist = SafeFileHistory(str(tmp_path / "history"))
        hist.store_string("hello \udce9 world")
        entries = list(hist.load_history_strings())
        assert len(entries) == 1
        assert "\udce9" not in entries[0]
        assert "hello" in entries[0]
        assert "world" in entries[0]

    def test_normal_text_unchanged(self, tmp_path):
        hist = SafeFileHistory(str(tmp_path / "history"))
        hist.store_string("normal ascii text")
        entries = list(hist.load_history_strings())
        assert entries[0] == "normal ascii text"

    def test_windows_surrogate_pair_round_trips_as_emoji(self, tmp_path):
        history_path = tmp_path / "history"
        hist = SafeFileHistory(str(history_path))
        hist.store_string("hello \ud83d\udc08 nanobot")

        history_path.read_bytes().decode("utf-8")
        reloaded = SafeFileHistory(str(history_path))
        assert list(reloaded.load_history_strings()) == ["hello 🐈 nanobot"]

    def test_mixed_unicode_preserved(self, tmp_path):
        hist = SafeFileHistory(str(tmp_path / "history"))
        hist.store_string("你好 hello こんにちは 🎉")
        entries = list(hist.load_history_strings())
        assert entries[0] == "你好 hello こんにちは 🎉"

    def test_multiple_surrogates(self, tmp_path):
        hist = SafeFileHistory(str(tmp_path / "history"))
        hist.store_string("\udce9\udcf1\udcff")
        entries = list(hist.load_history_strings())
        assert len(entries) == 1
        assert not any(char in entries[0] for char in "\udce9\udcf1\udcff")
