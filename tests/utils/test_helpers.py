"""Tests for utility helper functions."""


from blackcat.utils.helpers import (
    parse_session_key,
    safe_filename,
    truncate_string,
)
from blackcat.utils.paths import ensure_dir

# ── ensure_dir ─────────────────────────────────────────────────────


def test_ensure_dir_creates(tmp_path):
    target = tmp_path / "a" / "b" / "c"
    result = ensure_dir(target)
    assert result == target
    assert target.is_dir()


def test_ensure_dir_existing(tmp_path):
    result = ensure_dir(tmp_path)
    assert result == tmp_path


# ── safe_filename ──────────────────────────────────────────────────


def test_safe_filename_basic():
    assert safe_filename("hello") == "hello"


def test_safe_filename_unsafe_chars():
    result = safe_filename('file<name>:with/"bad"|chars?*')
    assert "<" not in result
    assert ">" not in result
    assert ":" not in result
    assert '"' not in result
    assert "|" not in result
    assert "?" not in result
    assert "*" not in result


def test_safe_filename_replaces_with_underscore():
    result = safe_filename("a:b")
    assert result == "a_b"


# ── truncate_string ────────────────────────────────────────────────


def test_truncate_short():
    assert truncate_string("hello", 10) == "hello"


def test_truncate_long():
    result = truncate_string("a" * 200, 100)
    assert len(result) == 100
    assert result.endswith("...")


def test_truncate_exact():
    assert truncate_string("hello", 5) == "hello"


def test_truncate_custom_suffix():
    result = truncate_string("a" * 20, 10, suffix=" [...]")
    assert result.endswith(" [...]")
    assert len(result) == 10


# ── parse_session_key ──────────────────────────────────────────────


def test_parse_session_key_basic():
    channel, chat_id = parse_session_key("telegram:12345")
    assert channel == "telegram"
    assert chat_id == "12345"


def test_parse_session_key_with_colon_in_id():
    channel, chat_id = parse_session_key("discord:guild:channel")
    assert channel == "discord"
    assert chat_id == "guild:channel"


def test_parse_session_key_invalid():
    import pytest

    with pytest.raises(ValueError, match="Invalid session key"):
        parse_session_key("nocolon")
