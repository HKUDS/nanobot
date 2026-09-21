"""Device authorization exposes its prompt before waiting for browser approval."""

import threading
import time
from types import SimpleNamespace

import httpx
import pytest

from nanobot.providers import github_copilot_provider as provider
from nanobot.providers.github_copilot_oauth import GitHubCopilotOAuthFlow


def test_device_prompt_precedes_approval_and_success_persists_token(monkeypatch):
    saved = []
    approved = False

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/device/code"):
            return httpx.Response(200, json={
                "device_code": "device-secret", "user_code": "ABCD-EFGH",
                "verification_uri": "https://github.com/login/device",
                "interval": 1, "expires_in": 60,
            })
        if request.url.path.endswith("/access_token"):
            return httpx.Response(200, json={"access_token": "account-secret"} if approved
                                  else {"error": "authorization_pending"})
        return httpx.Response(200, json={"login": "test-account"})

    client = httpx.Client(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(provider.httpx, "Client", lambda **_kwargs: client)
    monkeypatch.setattr(provider, "get_storage", lambda: SimpleNamespace(save=saved.append))
    monkeypatch.setattr(provider.webbrowser, "open", lambda *_args: (_ for _ in ()).throw(
        AssertionError("The gateway must not open the user's browser")
    ))
    flow = GitHubCopilotOAuthFlow()
    try:
        flow.start()
        assert flow.user_code == "ABCD-EFGH"
        assert flow.authorization_url == "https://github.com/login/device"
        assert flow.complete() is None
        assert saved == []
        approved = True
        deadline = time.monotonic() + 3
        token = flow.complete()
        while token is None and time.monotonic() < deadline:
            time.sleep(0.01)
            token = flow.complete()
        assert token is not None
        assert token.account_id == "test-account"
        assert saved == [token]
    finally:
        flow.cancel()


def test_cancelling_device_flow_interrupts_polling_without_saving(monkeypatch):
    saved = []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/device/code"):
            return httpx.Response(200, json={
                "device_code": "device-secret", "user_code": "ABCD-EFGH",
                "verification_uri": "https://github.com/login/device",
                "interval": 30, "expires_in": 60,
            })
        return httpx.Response(200, json={"error": "authorization_pending"})

    client = httpx.Client(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(provider.httpx, "Client", lambda **_kwargs: client)
    monkeypatch.setattr(provider, "get_storage", lambda: SimpleNamespace(save=saved.append))
    flow = GitHubCopilotOAuthFlow()
    flow.start()
    flow.cancel()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            flow.complete()
        except RuntimeError as exc:
            assert "cancelled" in str(exc)
            break
        time.sleep(0.01)
    else:
        raise AssertionError("Device polling did not stop after cancellation")
    assert saved == []
    assert flow.expired


def test_approval_after_cancellation_cannot_overwrite_saved_credentials(monkeypatch):
    from nanobot.providers import github_copilot_oauth as oauth

    approved = threading.Event()
    finished = threading.Event()
    saved = []

    def login(*, on_authorization, persist, **_kwargs):
        assert persist is False
        on_authorization("https://github.com/login/device", "ABCD-EFGH", 60)
        approved.wait(2)
        finished.set()
        return SimpleNamespace(access="new-account-secret")

    monkeypatch.setattr(oauth, "login_github_copilot", login)
    monkeypatch.setattr(provider, "get_storage", lambda: SimpleNamespace(save=saved.append))
    flow = GitHubCopilotOAuthFlow()
    try:
        flow.start()
        flow.cancel()
        approved.set()
        assert finished.wait(1)
        with pytest.raises(RuntimeError, match="cancelled"):
            flow.complete()
        assert saved == []
    finally:
        approved.set()
        flow.cancel()


def test_device_flow_does_not_expose_upstream_failure_details(monkeypatch):
    from nanobot.providers import github_copilot_oauth as oauth

    def login(**_kwargs):
        raise RuntimeError("upstream echoed synthetic-secret")

    monkeypatch.setattr(oauth, "login_github_copilot", login)
    flow = GitHubCopilotOAuthFlow()
    with pytest.raises(RuntimeError, match="GitHub sign-in failed") as failure:
        flow.start()
    assert "synthetic-secret" not in str(failure.value)
    with pytest.raises(RuntimeError, match="GitHub sign-in failed"):
        flow.complete()
