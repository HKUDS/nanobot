"""Tests for _is_output_empty heuristic in turn_runner."""

from __future__ import annotations

from nanobot.agent.turn_runner import _is_output_empty


class TestIsOutputEmpty:
    """Verify the substring-based empty-result detection."""

    # ── Definitely empty ────────────────────────────────────────────

    def test_blank_string(self):
        assert _is_output_empty("") is True

    def test_whitespace_only(self):
        assert _is_output_empty("   \n\t  ") is True

    def test_no_matches_found_with_period(self):
        """The exact Obsidian CLI output that broke the old exact-match."""
        assert _is_output_empty("No matches found.") is True

    def test_no_matches_found_with_newline(self):
        assert _is_output_empty("No matches found.\n") is True

    def test_no_matches_found_without_period(self):
        assert _is_output_empty("No matches found") is True

    def test_no_results(self):
        assert _is_output_empty("No results") is True

    def test_not_found(self):
        assert _is_output_empty("File not found") is True

    def test_zero_results(self):
        assert _is_output_empty("0 results found") is True

    def test_nothing_found(self):
        assert _is_output_empty("Nothing found for your query") is True

    def test_no_data(self):
        assert _is_output_empty("No data available") is True

    def test_case_insensitive(self):
        assert _is_output_empty("NO MATCHES FOUND") is True

    def test_no_file(self):
        assert _is_output_empty("No file exists at that path") is True

    # ── Definitely NOT empty ────────────────────────────────────────

    def test_real_data_short(self):
        assert _is_output_empty("Paris") is False

    def test_real_data_medium(self):
        assert _is_output_empty("DS10540/\nOpportunity Brief.md\nTimekeeping.md") is False

    def test_real_data_long(self):
        content = "The project DS10540 is about digital signatures " * 5
        assert _is_output_empty(content) is False

    def test_long_output_with_not_found_substring(self):
        """Long output that happens to contain 'not found' should NOT be empty."""
        content = (
            "File analysis complete. 3 references found. "
            "Note: 'readme.txt' was not found in the archive but "
            "all other files processed successfully with full content."
        )
        assert _is_output_empty(content) is False

    def test_numeric_output(self):
        assert _is_output_empty("42") is False

    def test_json_output(self):
        assert _is_output_empty('{"status": "ok", "count": 5}') is False
