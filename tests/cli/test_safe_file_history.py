"""Regression tests for SafeFileHistory (issue #2846).

Surrogate characters in CLI input must not crash history file writes.
"""

from nanobot.cli.commands import SafeFileHistory as LegacySafeFileHistory
from nanobot.cli.terminal import SafeFileHistory, _sanitize_surrogates


def test_commands_keeps_safe_file_history_import_compatible() -> None:
    assert LegacySafeFileHistory is SafeFileHistory


class TestSanitizeSurrogates:
    def test_lone_surrogates_replaced(self):
        result = _sanitize_surrogates("hello \udce9 world")
        assert "\udce9" not in result
        assert "hello" in result
        assert "world" in result

    def test_normal_text_unchanged(self):
        assert _sanitize_surrogates("normal ascii text") == "normal ascii text"

    def test_emoji_already_correct(self):
        """Properly encoded emoji should pass through unchanged."""
        assert _sanitize_surrogates("hello 🐈 nanobot") == "hello 🐈 nanobot"

    def test_mixed_unicode_preserved(self):
        assert _sanitize_surrogates("你好 hello こんにちは 🎉") == "你好 hello こんにちは 🎉"

    def test_multiple_lone_surrogates(self):
        result = _sanitize_surrogates("\udce9\udcf1\udcff")
        assert "\udce9" not in result
        assert "\udcf1" not in result
        assert "\udcff" not in result


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
        """Raw UTF-16 console input must survive a UTF-8 history write and reload."""
        history_path = tmp_path / "history"
        hist = SafeFileHistory(str(history_path))
        hist.store_string("hello \ud83d\udc08 nanobot")

        history_path.read_bytes().decode("utf-8")  # Strict decoding must not raise.
        reloaded = SafeFileHistory(str(history_path))
        assert list(reloaded.load_history_strings()) == ["hello 🐈 nanobot"]

    def test_mixed_unicode_preserved(self, tmp_path):
        """CJK + emoji + latin should all pass through cleanly."""
        hist = SafeFileHistory(str(tmp_path / "history"))
        hist.store_string("你好 hello こんにちは 🎉")
        entries = list(hist.load_history_strings())
        assert entries[0] == "你好 hello こんにちは 🎉"

    def test_multiple_surrogates(self, tmp_path):
        hist = SafeFileHistory(str(tmp_path / "history"))
        hist.store_string("\udce9\udcf1\udcff")
        entries = list(hist.load_history_strings())
        assert len(entries) == 1
        assert "\udce9" not in entries[0]
