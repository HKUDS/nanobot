from nanobot.channels.contracts import ChannelValidationContext
from nanobot.channels.feishu.validation import validate


def test_saved_fields_do_not_claim_a_live_connection():
    result = validate(
        {"appId": "cli_not_verified", "appSecret": "not_verified"},
        ChannelValidationContext(),
    )
    assert result["status"] == "configured"
    assert result["can_enable"] is True
    assert "not_verified" not in str(result["checks"])


def test_missing_secret_still_needs_setup():
    result = validate({"appId": "cli_test"}, ChannelValidationContext())
    assert result["status"] == "needs_setup"
    assert result["can_enable"] is False
