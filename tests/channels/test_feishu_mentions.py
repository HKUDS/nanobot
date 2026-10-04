"""Display names in Feishu mentions must remain literal message text."""

from types import SimpleNamespace

import pytest

from nanobot.channels.feishu.runtime import FeishuChannel


@pytest.mark.parametrize("name", [r"Dev\Ops", r"Dev\1", r"Dev\nOps"])
def test_mention_display_name_preserves_backslashes(name):
    mention = SimpleNamespace(
        key="@_user_1",
        name=name,
        id=SimpleNamespace(open_id="ou_example", user_id="user_example"),
    )

    result = FeishuChannel._resolve_mentions(
        "Hello @_user_1! Keep @_user_10 unchanged.", [mention]
    )

    assert result == (
        f"Hello @{name} (ou_example, user id: user_example)! "
        "Keep @_user_10 unchanged."
    )
