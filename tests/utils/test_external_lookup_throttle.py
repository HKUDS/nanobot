"""Tests for repeated external lookup throttling."""

from __future__ import annotations

from nanobot.utils.runtime import (
    external_lookup_signature,
    repeated_external_lookup_error,
)


def test_web_fetch_none_url_has_no_signature_and_does_not_affect_real_url():
    counts: dict[str, int] = {}

    assert external_lookup_signature("web_fetch", {"url": None}) is None
    assert repeated_external_lookup_error("web_fetch", {"url": None}, counts) is None
    assert counts == {}

    real_url = {"url": "https://example.com/page"}
    assert external_lookup_signature("web_fetch", real_url) == "web_fetch:https://example.com/page"
    assert repeated_external_lookup_error("web_fetch", real_url, counts) is None
    assert counts == {"web_fetch:https://example.com/page": 1}
