from nanobot.webui.browser_companion import is_top_level_user_navigation, session_cookie_name
from nanobot.webui.gateway_tokens import GatewayTokenStore


def test_companion_session_can_refresh_until_expiry() -> None:
    tokens = GatewayTokenStore()
    session = tokens.issue_companion_session(30)
    assert tokens.companion_session_is_valid(session) is True
    assert tokens.companion_session_is_valid(session) is True


def test_companion_session_capacity_is_bounded() -> None:
    tokens = GatewayTokenStore(max_companion_sessions=1)
    tokens.issue_companion_session(30)
    assert tokens.can_issue_companion_session() is False


def test_companion_navigation_policy_is_fail_closed() -> None:
    direct = {
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Site": "none",
    }
    assert is_top_level_user_navigation(direct) is True
    assert is_top_level_user_navigation({}) is False
    assert is_top_level_user_navigation({**direct, "Sec-Fetch-Site": "cross-site"}) is False


def test_companion_cookie_is_isolated_by_webui_port() -> None:
    assert session_cookie_name(8765) != session_cookie_name(8766)
