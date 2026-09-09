"""Gateway settings expose device authorization and cancel by owned flow ID."""

import threading

from nanobot.config.loader import save_config
from nanobot.config.schema import Config
from nanobot.webui.settings_api import complete_oauth_provider, login_oauth_provider
from nanobot.webui.settings_services import WebUIOAuthFlowRegistry


def test_interactive_copilot_returns_prompt_and_scopes_cancellation(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    stopped = threading.Event()

    def login(*, on_authorization, cancelled, **_kwargs):
        on_authorization("https://github.com/login/device", "ABCD-EFGH", 60)
        cancelled.wait(3)
        stopped.set()
        raise RuntimeError("cancelled")

    monkeypatch.setattr("nanobot.providers.github_copilot_oauth.login_github_copilot", login)
    monkeypatch.setattr(
        "nanobot.providers.github_copilot_provider.get_github_copilot_login_status",
        lambda: None,
    )
    registry = WebUIOAuthFlowRegistry()
    payload = login_oauth_provider(
        {"provider": ["github_copilot"], "interactive_flow": ["true"]},
        oauth_flows=registry, config_path=config_path,
    )
    assert payload["status"] == "authorization_required"
    assert payload["user_code"] == "ABCD-EFGH"
    assert payload["completion_input"] == "device_code"
    assert "device-secret" not in str(payload)
    query = {"provider": ["github_copilot"], "flow_id": [payload["flow_id"]]}
    assert complete_oauth_provider(query, oauth_flows=registry)["status"] == "pending"
    assert registry.get("openai_codex", payload["flow_id"]) is None
    result = complete_oauth_provider({**query, "cancel": ["true"]}, oauth_flows=registry)
    assert result["status"] == "cancelled"
    assert registry.get("github_copilot", payload["flow_id"]) is None
    assert stopped.wait(1)
