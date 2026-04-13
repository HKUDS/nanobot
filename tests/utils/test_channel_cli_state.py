from nanobot.utils import channel_cli_state


def test_build_status_marks_authorized_when_env_and_token_are_ready(monkeypatch):
    monkeypatch.setattr(
        channel_cli_state,
        "load_multi_config",
        lambda: {
            "apps": [
                {
                    "name": "hiperone-feishu-cli",
                    "appId": "cli_app_123",
                    "appSecret": {"source": "keychain", "id": "secret-ref"},
                    "users": [
                        {
                            "userOpenId": "ou_user_1",
                            "userName": "Tester",
                        }
                    ],
                }
            ]
        },
    )
    monkeypatch.setattr(
        channel_cli_state,
        "resolve_secret",
        lambda app: "plain-secret",
    )
    monkeypatch.setattr(
        channel_cli_state,
        "read_user_token",
        lambda app_id, user_open_id: {
            "scope": "search:message offline_access",
            "tokenStatus": "valid",
        },
    )

    state = channel_cli_state.build_status("feishu", "hiperone-feishu-cli")

    assert state["configured"] is True
    assert state["env_ready"] is True
    assert state["authorized"] is True
    assert state["user_open_id"] == "ou_user_1"
    assert state["scope"] == "search:message offline_access"


def test_resolve_authorized_user_prefers_user_with_valid_token(monkeypatch):
    token_map = {
        "ou_expired": {"scope": "search:message", "tokenStatus": "expired"},
        "ou_valid": {"scope": "search:message offline_access", "tokenStatus": "valid"},
    }
    monkeypatch.setattr(
        channel_cli_state,
        "read_user_token",
        lambda app_id, user_open_id: token_map.get(user_open_id, {}),
    )

    user_open_id, user_name, token = channel_cli_state.resolve_authorized_user(
        "cli_app_123",
        [
            {"userOpenId": "ou_expired", "userName": "Expired User"},
            {"userOpenId": "ou_valid", "userName": "Valid User"},
        ],
    )

    assert user_open_id == "ou_valid"
    assert user_name == "Valid User"
    assert token == {"scope": "search:message offline_access", "tokenStatus": "valid"}
