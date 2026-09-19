"""Feishu/Lark QR onboarding: verification URL handling."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from nanobot.channels.feishu import runtime as feishu_runtime


def _begin_response(uri: str) -> dict:
    return {
        "device_code": "dc-test",
        "verification_uri_complete": uri,
        "interval": 5,
        "expire_in": 3600,
    }


@pytest.mark.parametrize(
    "returned",
    [
        "https://open.feishu.cn/page/launcher?user_code=ABCD-EFGH",
        "https://open.larksuite.com/page/launcher?user_code=ABCD-EFGH",
    ],
)
def test_launcher_url_rewritten_to_cli_page(returned: str) -> None:
    """The registration endpoint returns /page/launcher, which rejects these
    device codes instantly; the CLI page is the one that works."""
    with patch.object(feishu_runtime, "_post_registration",
                      return_value=_begin_response(returned)):
        start = feishu_runtime._begin_registration("feishu")
    assert start["qr_url"].startswith(
        returned.split("/page/")[0] + "/page/cli?user_code="
    )


def test_cli_url_passed_through_unchanged() -> None:
    uri = "https://open.feishu.cn/page/cli?user_code=ABCD-EFGH"
    with patch.object(feishu_runtime, "_post_registration",
                      return_value=_begin_response(uri)):
        start = feishu_runtime._begin_registration("feishu")
    assert start["qr_url"] == uri


@pytest.mark.parametrize("uri", [
    "https://open.feishu.cn/page/cli?return_to=/page/launcher?user_code=OTHER",
    "https://open.feishu.cn/other/page/launcher?user_code=ABCD",
    "https://other.example/page/launcher?user_code=ABCD",
])
def test_other_urls_and_embedded_query_values_are_not_rewritten(uri):
    with patch.object(feishu_runtime, "_post_registration", return_value=_begin_response(uri)):
        assert feishu_runtime._begin_registration()["qr_url"] == uri


@pytest.mark.parametrize("domain,host", [
    ("feishu", "open.feishu.cn"), ("lark", "open.larksuite.com"),
])
def test_launcher_rewrite_preserves_opaque_query_and_fragment(domain, host):
    suffix = "?user_code=AB%2BCD&return_to=/page/launcher?other=1#confirm"
    uri = f"https://{host}/page/launcher{suffix}"
    with patch.object(feishu_runtime, "_post_registration", return_value=_begin_response(uri)):
        start = feishu_runtime._begin_registration(domain)
    assert start["qr_url"] == f"https://{host}/page/cli{suffix}"
    assert start["device_code"] == "dc-test"
    assert start["interval"] == 5


@pytest.mark.parametrize("ttl_fields,expected", [
    ({"expires_in": 3600}, 3600),
    ({"expire_in": 1200}, 1200),
    ({"expires_in": 3600, "expire_in": 1200}, 3600),
    ({}, 600),
])
def test_registration_uses_server_expiry_with_legacy_fallback(ttl_fields, expected):
    response = _begin_response("https://open.feishu.cn/page/launcher?user_code=ABCD")
    response.pop("expire_in")
    response.update(ttl_fields)
    with patch.object(feishu_runtime, "_post_registration", return_value=response):
        assert feishu_runtime._begin_registration()["expire_in"] == expected
