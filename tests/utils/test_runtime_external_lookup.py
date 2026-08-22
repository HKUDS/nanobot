"""Tests for external lookup throttling helpers."""

from __future__ import annotations

from nanobot.utils.runtime import (
    external_lookup_signature,
    repeated_external_lookup_error,
)


def test_web_fetch_signature_ignores_none_url():
    assert external_lookup_signature("web_fetch", {"url": None}) is None


def test_web_fetch_signature_ignores_non_string_url():
    assert external_lookup_signature("web_fetch", {"url": 123}) is None


def test_web_fetch_signature_ignores_empty_url():
    assert external_lookup_signature("web_fetch", {"url": "   "}) is None


def test_web_fetch_non_string_url_does_not_create_cache_entry():
    counts: dict[str, int] = {}

    assert repeated_external_lookup_error("web_fetch", {"url": 123}, counts) is None
    assert counts == {}

    assert (
        repeated_external_lookup_error(
            "web_fetch",
            {"url": "https://example.com"},
            counts,
        )
        is None
    )
    assert counts == {"web_fetch:https://example.com": 1}
