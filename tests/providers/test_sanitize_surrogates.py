"""Regression tests for lone UTF-16 surrogate scrubbing in provider payloads.

These lock down two behaviors:

1. ``nanobot.utils.helpers.sanitize_surrogates`` / ``sanitize_surrogates_deep``
   produce strings that can round-trip through ``str.encode('utf-8')`` even
   when the input contains unpaired surrogates.

2. ``LLMProvider._sanitize_empty_content`` applies the deep sanitize as a
   defense-in-depth pass so that ``UnicodeEncodeError: 'utf-8' codec can't
   encode characters ... surrogates not allowed`` cannot escape into the
   HTTP client when messages contain emoji-heavy history plus a lone
   surrogate leak (e.g. from Windows console input or a truncated JSON
   round-trip).
"""

from __future__ import annotations

import pytest

from nanobot.providers.base import LLMProvider
from nanobot.utils.helpers import (
    sanitize_surrogates,
    sanitize_surrogates_deep,
)


class TestSanitizeSurrogates:
    def test_paired_surrogates_reconstructed_to_emoji(self):
        # \uD83E\uDD16 is the UTF-16 surrogate pair for 🤖 (U+1F916).
        raw = "hello \ud83e\udd16 world"
        cleaned = sanitize_surrogates(raw)
        assert cleaned == "hello 🤖 world"
        cleaned.encode("utf-8")  # must not raise

    def test_lone_surrogate_replaced_with_fffd(self):
        raw = "hello \ud83e world"  # lone high surrogate
        cleaned = sanitize_surrogates(raw)
        assert "\ud83e" not in cleaned
        # replacement char U+FFFD substitutes the unpaired surrogate
        assert "\ufffd" in cleaned
        cleaned.encode("utf-8")  # must not raise

    def test_normal_text_returned_unchanged_identity(self):
        raw = "plain ascii + 中文 + 🤖"
        assert sanitize_surrogates(raw) == raw

    def test_non_string_returned_as_is(self):
        assert sanitize_surrogates(None) is None  # type: ignore[arg-type]
        assert sanitize_surrogates(42) == 42  # type: ignore[arg-type]


class TestSanitizeSurrogatesDeep:
    def test_clean_input_returns_same_object(self):
        payload = {"role": "user", "content": [{"type": "text", "text": "hi 🤖"}]}
        result = sanitize_surrogates_deep(payload)
        # No allocation on clean input: same object identity.
        assert result is payload

    def test_lone_surrogate_in_nested_content_cleaned(self):
        dirty = {
            "role": "user",
            "content": [
                {"type": "text", "text": "hello \ud83e world"},
                {"type": "text", "text": "normal"},
            ],
        }
        cleaned = sanitize_surrogates_deep(dirty)
        assert cleaned is not dirty  # rebuilt
        first = cleaned["content"][0]["text"]
        assert "\ud83e" not in first
        # Full payload must be UTF-8 encodable.
        import json

        json.dumps(cleaned).encode("utf-8")

    def test_paired_surrogates_in_list_collapse_to_emoji(self):
        dirty = ["a", "b \ud83e\udd16", "c"]
        cleaned = sanitize_surrogates_deep(dirty)
        assert cleaned == ["a", "b 🤖", "c"]

    def test_deep_recursion_on_tuple_and_dict(self):
        dirty = (
            {"k": "\ud83e"},
            ["nested", "\ud83e\udd16"],
            "\ud83e clean",
        )
        cleaned = sanitize_surrogates_deep(dirty)
        # tuple preserved as tuple
        assert isinstance(cleaned, tuple)
        assert "\ud83e" not in cleaned[0]["k"]
        assert cleaned[1][1] == "🤖"


class TestProviderSanitizeEmptyContent:
    """The provider-boundary defense-in-depth pass.

    Lone surrogates leaking into any string leaf of a request message must
    not survive ``_sanitize_empty_content``; otherwise the HTTP client will
    raise ``UnicodeEncodeError`` when serializing the request body.
    """

    def test_lone_surrogate_in_string_content_scrubbed(self):
        messages = [
            {"role": "user", "content": "leak \ud83e here"},
        ]
        result = LLMProvider._sanitize_empty_content(messages)
        text = result[0]["content"]
        assert "\ud83e" not in text
        text.encode("utf-8")  # would raise pre-fix

    def test_lone_surrogate_in_content_block_scrubbed(self):
        messages = [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "hi \ud83e there"},
                ],
            },
        ]
        result = LLMProvider._sanitize_empty_content(messages)
        text = result[0]["content"][0]["text"]
        assert "\ud83e" not in text
        text.encode("utf-8")

    def test_paired_surrogates_reconstructed_in_content(self):
        messages = [
            {"role": "user", "content": "robot \ud83e\udd16 hello"},
        ]
        result = LLMProvider._sanitize_empty_content(messages)
        assert result[0]["content"] == "robot 🤖 hello"

    def test_clean_input_semantics_unchanged(self):
        messages = [
            {"role": "user", "content": "plain 🤖 content"},
            {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
        ]
        result = LLMProvider._sanitize_empty_content(messages)
        assert result[0]["content"] == "plain 🤖 content"
        assert result[1]["content"][0]["text"] == "ok"

    def test_full_request_body_is_utf8_encodable_after_sanitize(self):
        """End-to-end: an emoji-heavy history plus a lone surrogate must
        no longer break utf-8 encoding of the outgoing HTTP request body."""
        import json

        messages = [
            {"role": "system", "content": "You are a 🐱 assistant."},
            {"role": "user", "content": "🤖 fixed?"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "answer with a lone \ud83e half"},
                ],
            },
        ]
        cleaned = LLMProvider._sanitize_empty_content(messages)
        # This is the operation that previously raised UnicodeEncodeError.
        json.dumps({"model": "x", "messages": cleaned}).encode("utf-8")


class TestBackwardCompatReExport:
    def test_cli_reexport_points_to_shared_helper(self):
        """The CLI module continues to expose ``_sanitize_surrogates`` as a
        thin alias so existing imports (e.g. ``SafeFileHistory`` in the
        legacy tests) keep working."""
        from nanobot.cli.commands import _sanitize_surrogates as cli_alias

        assert cli_alias is sanitize_surrogates
        assert cli_alias("hello \ud83e\udd16") == "hello 🤖"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
