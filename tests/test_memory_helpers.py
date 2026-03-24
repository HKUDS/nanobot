"""Tests for nanobot.memory.helpers — shared memory utilities."""

from __future__ import annotations

from datetime import datetime, timezone

from nanobot.memory.helpers import (
    _contains_any,
    _estimate_tokens,
    _extract_query_keywords,
    _norm_text,
    _safe_float,
    _to_datetime,
    _to_str_list,
    _tokenize,
    _utc_now_iso,
)


class TestUtcNowIso:
    def test_returns_iso_format(self) -> None:
        result = _utc_now_iso()
        # Should be parseable as ISO-8601.
        parsed = datetime.fromisoformat(result)
        assert parsed.tzinfo is not None

    def test_utc_timezone(self) -> None:
        result = _utc_now_iso()
        parsed = datetime.fromisoformat(result)
        assert parsed.tzinfo == timezone.utc


class TestSafeFloat:
    def test_normal_value(self) -> None:
        assert _safe_float(3.14, 0.0) == 3.14

    def test_string_numeric(self) -> None:
        assert _safe_float("2.5", 0.0) == 2.5

    def test_none_returns_default(self) -> None:
        assert _safe_float(None, 0.7) == 0.7

    def test_invalid_string_returns_default(self) -> None:
        assert _safe_float("not-a-number", 1.0) == 1.0

    def test_int_coercion(self) -> None:
        assert _safe_float(42, 0.0) == 42.0


class TestNormText:
    def test_lowercases(self) -> None:
        assert _norm_text("Hello World") == "hello world"

    def test_collapses_whitespace(self) -> None:
        assert _norm_text("  foo   bar  ") == "foo bar"

    def test_strips_edges(self) -> None:
        assert _norm_text("  trimmed  ") == "trimmed"


class TestTokenize:
    def test_splits_and_lowercases(self) -> None:
        result = _tokenize("Hello World Test")
        assert "hello" in result
        assert "world" in result
        assert "test" in result

    def test_excludes_single_char(self) -> None:
        result = _tokenize("a b cc")
        assert "a" not in result
        assert "b" not in result
        assert "cc" in result


class TestToStrList:
    def test_none_returns_empty(self) -> None:
        assert _to_str_list(None) == []

    def test_string_returns_empty(self) -> None:
        assert _to_str_list("not a list") == []

    def test_list_of_strings(self) -> None:
        assert _to_str_list(["foo", "bar"]) == ["foo", "bar"]

    def test_strips_items(self) -> None:
        assert _to_str_list(["  a  ", " b "]) == ["a", "b"]

    def test_filters_empty(self) -> None:
        assert _to_str_list(["x", "", "  ", "y"]) == ["x", "y"]

    def test_filters_non_strings(self) -> None:
        assert _to_str_list(["ok", 42, None]) == ["ok"]


class TestToDatetime:
    def test_iso_string(self) -> None:
        dt = _to_datetime("2024-01-15T10:30:00+00:00")
        assert dt is not None
        assert dt.year == 2024
        assert dt.month == 1

    def test_z_suffix(self) -> None:
        dt = _to_datetime("2024-01-15T10:30:00Z")
        assert dt is not None

    def test_none_returns_none(self) -> None:
        assert _to_datetime(None) is None

    def test_empty_returns_none(self) -> None:
        assert _to_datetime("") is None

    def test_invalid_returns_none(self) -> None:
        assert _to_datetime("not-a-date") is None


class TestEstimateTokens:
    def test_empty_string(self) -> None:
        assert _estimate_tokens("") == 0

    def test_approximation(self) -> None:
        text = "a" * 100
        result = _estimate_tokens(text)
        assert result == 25

    def test_minimum_one(self) -> None:
        assert _estimate_tokens("hi") >= 1

    def test_none_input(self) -> None:
        # None is falsy so ``text or ""`` yields "" → 0 tokens.
        assert _estimate_tokens(None) == 0  # type: ignore[arg-type]


class TestContainsAny:
    def test_present(self) -> None:
        assert _contains_any("hello world", ("world",)) is True

    def test_absent(self) -> None:
        assert _contains_any("hello world", ("foo",)) is False

    def test_case_insensitive(self) -> None:
        assert _contains_any("Hello World", ("hello",)) is True

    def test_empty_needles(self) -> None:
        assert _contains_any("anything", ()) is False

    def test_none_text(self) -> None:
        assert _contains_any("", ("x",)) is False


class TestExtractQueryKeywords:
    def test_filters_stopwords(self) -> None:
        result = _extract_query_keywords("what is the weather in London")
        assert "london" in result
        assert "weather" in result
        assert "what" not in result
        assert "the" not in result

    def test_excludes_short_tokens(self) -> None:
        result = _extract_query_keywords("is it ok to go")
        # all tokens <= 2 chars or stopwords
        assert len(result) == 0

    def test_preserves_significant(self) -> None:
        result = _extract_query_keywords("python debugging techniques")
        assert "python" in result
        assert "debugging" in result
        assert "techniques" in result
