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
