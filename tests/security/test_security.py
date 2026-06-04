"""Tests for security fixes: deny-by-default, path traversal, message sanitization."""

from unittest.mock import MagicMock

import pytest

from blackcat.utils.paths import resolve_path

# ── Deny-by-default is_allowed ────────────────────────────────────


def _make_channel(allow_from: list[str]):
    """Create a concrete channel subclass for testing is_allowed."""
    from blackcat.channels.base import BaseChannel

    class _TestChannel(BaseChannel):
        name = "test"

        async def start(self): pass
        async def stop(self): pass
        async def _send_impl(self, msg): pass
        async def send(self, msg): pass

    config = MagicMock()
    config.allow_from = allow_from
    config.typing_interval = 0
    bus = MagicMock()
    return _TestChannel(config, bus)


def test_is_allowed_empty_denies_all():
    ch = _make_channel([])
    assert ch.is_allowed("anyone") is False


def test_is_allowed_wildcard_allows_all():
    ch = _make_channel(["*"])
    assert ch.is_allowed("anyone") is True


def test_is_allowed_exact_match():
    ch = _make_channel(["alice", "bob"])
    assert ch.is_allowed("alice") is True
    assert ch.is_allowed("charlie") is False


def test_is_allowed_pipe_separated():
    """Pipe-separated sender IDs require exact match (no special parsing)."""
    ch = _make_channel(["alice|12345"])
    assert ch.is_allowed("alice|12345") is True


def test_is_allowed_pipe_no_match():
    ch = _make_channel(["bob"])
    assert ch.is_allowed("alice|12345") is False


def test_is_allowed_missing_config_attr():
    """Channel config without allow_from attr should deny all."""
    ch = _make_channel([])
    ch.config = object()  # no allow_from attr at all
    assert ch.is_allowed("anyone") is False


# ── Path traversal fix ────────────────────────────────────────────


def test_resolve_path_inside_allowed(tmp_path):
    target = tmp_path / "subdir" / "file.txt"
    target.parent.mkdir(parents=True)
    target.touch()
    result = resolve_path(str(target), allowed_dir=tmp_path)
    assert result == target.resolve()


def test_resolve_path_traversal_blocked(tmp_path):
    """Paths that escape the allowed directory should be rejected."""
    evil = tmp_path / ".." / "etc" / "passwd"
    with pytest.raises(PermissionError, match="outside allowed directory"):
        resolve_path(str(evil), allowed_dir=tmp_path)


def test_resolve_path_prefix_attack(tmp_path):
    """workspace_evil should not pass check against workspace."""
    evil_dir = tmp_path.parent / (tmp_path.name + "_evil")
    evil_dir.mkdir(exist_ok=True)
    evil_file = evil_dir / "secrets.txt"
    evil_file.touch()
    with pytest.raises(PermissionError, match="outside allowed directory"):
        resolve_path(str(evil_file), allowed_dir=tmp_path)


def test_resolve_path_no_restriction(tmp_path):
    """Without allowed_dir, any path should resolve."""
    target = tmp_path / "file.txt"
    target.touch()
    result = resolve_path(str(target))
    assert result == target.resolve()


def test_resolve_path_relative_with_workspace(tmp_path):
    target = tmp_path / "notes.txt"
    target.touch()
    result = resolve_path("notes.txt", workspace=tmp_path)
    assert result == target.resolve()


# ── Message sanitization ──────────────────────────────────────────


def test_sanitize_null_assistant_content():
    """None content stays None (only empty strings are sanitized)."""
    from blackcat.providers.openai_compat_provider import OpenAICompatProvider

    messages = [{"role": "assistant", "content": None}]
    result = OpenAICompatProvider(api_key="test")._sanitize_empty_content(messages)
    assert result[0]["content"] is None


def test_sanitize_null_assistant_with_tool_calls():
    """Assistant message with tool_calls and null content should keep None."""
    from blackcat.providers.openai_compat_provider import OpenAICompatProvider

    messages = [{"role": "assistant", "content": None, "tool_calls": [{"id": "c1"}]}]
    result = OpenAICompatProvider(api_key="test")._sanitize_empty_content(messages)
    assert result[0]["content"] is None  # tool_calls present, None is ok


def test_sanitize_empty_string_user():
    from blackcat.providers.openai_compat_provider import OpenAICompatProvider

    messages = [{"role": "user", "content": ""}]
    result = OpenAICompatProvider(api_key="test")._sanitize_empty_content(messages)
    assert result[0]["content"] == "(empty)"


def test_sanitize_normal_messages_unchanged():
    from blackcat.providers.openai_compat_provider import OpenAICompatProvider

    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]
    result = OpenAICompatProvider(api_key="test")._sanitize_empty_content(messages)
    assert result == messages
