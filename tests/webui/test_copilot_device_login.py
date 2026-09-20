"""The WebUI exposes only user-facing device data and owns cancellation."""

import threading

import pytest

from nanobot.config.schema import Config
from nanobot.webui.settings_models import complete_oauth_provider, login_oauth_provider
from nanobot.webui.settings_services import WebUIOAuthFlowRegistry


def test_copilot_prompt_poll_and_owned_cancellation(monkeypatch):
    stopped = threading.Event()

    def login(*, on_authorization, cancelled, persist, **_kwargs):
        assert persist is False
        on_authorization("https://github.com/login/device", "ABCD-EFGH", 60)
        cancelled.wait(2)
        stopped.set()
        raise RuntimeError("cancelled")

    monkeypatch.setattr("nanobot.providers.github_copilot_oauth.login_github_copilot", login)
    registry = WebUIOAuthFlowRegistry()
    payload = login_oauth_provider(
        Config(), {"provider": ["github_copilot"]}, oauth_flows=registry,
        config_path=None, settings_payload=lambda **_: {},
    )
    assert set(payload) == {
        "status", "provider", "flow_id", "authorization_url", "user_code",
        "expires_in", "completion_input",
    }
    assert payload["user_code"] == "ABCD-EFGH"
    assert payload["completion_input"] == "device_code"
    query = {"provider": ["github_copilot"], "flow_id": [payload["flow_id"]]}
    kwargs = dict(oauth_flows=registry, config_path=None, settings_payload=lambda **_: {})
    try:
        assert complete_oauth_provider(query, **kwargs)["status"] == "pending"
        with pytest.raises(ValueError, match="expired"):
            complete_oauth_provider({**query, "provider": ["openai_codex"], "cancel": ["true"]}, **kwargs)
        assert registry.get("github_copilot", payload["flow_id"]) is not None
        result = complete_oauth_provider({**query, "cancel": ["true"]}, **kwargs)
        assert result["status"] == "cancelled"
        assert registry.get("github_copilot", payload["flow_id"]) is None
        assert stopped.wait(1)
    finally:
        registry.clear("github_copilot")
