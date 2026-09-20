"""The WebUI exposes only user-facing device data and owns cancellation."""

import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from nanobot.config.schema import Config
from nanobot.webui.settings_contracts import WebUISettingsError
from nanobot.webui.settings_models import (
    complete_oauth_provider,
    login_oauth_provider,
    logout_oauth_provider,
)
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


@pytest.mark.parametrize("action", ["logout", "replacement"])
def test_cancels_copilot_login_while_device_prompt_is_loading(monkeypatch, tmp_path, action):
    entered = threading.Event()
    release_prompt = threading.Event()
    finished = threading.Event()
    saved = []

    def login(*, on_authorization, **_kwargs):
        if not entered.is_set():
            entered.set()
            assert release_prompt.wait(3)
            finished.set()
        on_authorization("https://github.com/login/device", "ABCD-EFGH", 60)
        return SimpleNamespace(access="late-account-secret")

    monkeypatch.setattr("nanobot.providers.github_copilot_oauth.login_github_copilot", login)
    monkeypatch.setattr("nanobot.providers.github_copilot_provider.get_storage", lambda: SimpleNamespace(
        get_token_path=lambda: tmp_path / "copilot.json", save=saved.append,
    ))
    registry = WebUIOAuthFlowRegistry()
    kwargs = dict(oauth_flows=registry, config_path=None, settings_payload=lambda **_: {})
    query = {"provider": ["github_copilot"]}
    with ThreadPoolExecutor(max_workers=1) as pool:
        started = pool.submit(login_oauth_provider, Config(), query, **kwargs)
        try:
            assert entered.wait(2)
            if action == "logout":
                logout_oauth_provider(query, **kwargs)
            else:
                replacement = login_oauth_provider(Config(), query, **kwargs)
                assert registry.get("github_copilot", replacement["flow_id"]) is not None
            # Cancellation must end the start request without waiting for the
            # outstanding GitHub device-code response to return.
            with pytest.raises(WebUISettingsError, match="GitHub sign-in failed"):
                started.result(timeout=1)
            assert saved == []
        finally:
            release_prompt.set()
            assert finished.wait(1)
            registry.clear("github_copilot")


def test_failed_copilot_start_removes_registered_flow(monkeypatch):
    from nanobot.providers.github_copilot_oauth import GitHubCopilotOAuthFlow

    registered = []
    registry = WebUIOAuthFlowRegistry()
    register = registry.register

    def capture(provider, flow_id, flow):
        registered.append((provider, flow_id, flow))
        register(provider, flow_id, flow)

    def fail_start(_self):
        raise RuntimeError("upstream failure")

    monkeypatch.setattr(registry, "register", capture)
    monkeypatch.setattr(GitHubCopilotOAuthFlow, "start", fail_start)
    with pytest.raises(WebUISettingsError, match="GitHub sign-in failed"):
        login_oauth_provider(
            Config(), {"provider": ["github_copilot"]}, oauth_flows=registry,
            config_path=None, settings_payload=lambda **_: {},
        )
    assert len(registered) == 1
    provider, flow_id, flow = registered[0]
    assert registry.get(provider, flow_id) is None
    assert flow.expired
