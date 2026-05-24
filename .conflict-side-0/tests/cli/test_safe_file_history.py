"""Regression tests for SafeFileHistory (issue #2846).

Surrogate characters in CLI input must not crash history file writes.
"""

from nanobot.cli.commands import SafeFileHistory, _sanitize_surrogates


class TestSanitizeSurrogates:
    def test_paired_surrogates_reconstructed(self):
        """Windows console produces \\ud83d\\udc08 for U+1F408 — must be restored."""
        result = _sanitize_surrogates("你为什么会用 🐈")
        assert result == "你为什么会用 🐈"

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

    def test_emoji_preserved(self, tmp_path):
        hist = SafeFileHistory(str(tmp_path / "history"))
        hist.store_string("hello 🐈 nanobot")
        entries = list(hist.load_history_strings())
        assert entries[0] == "hello 🐈 nanobot"

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
