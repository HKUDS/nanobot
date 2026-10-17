from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from mcp.shared.auth import OAuthToken as MCPOAuthToken
from oauth_cli_kit import get_token
from oauth_cli_kit.models import OAuthToken

from nanobot.agent.tools.mcp_oauth import MCPOAuthStorage, delete_mcp_oauth_credentials
from nanobot.config import home as home_module
from nanobot.config.loader import load_config
from nanobot.providers.factory import make_provider
from nanobot.providers.oauth_model_catalog import get_oauth_model_catalog
from nanobot.providers.oauth_storage import codex_token_storage


def _token(access: str, *, expired: bool = False) -> OAuthToken:
    return OAuthToken(
        access=access,
        refresh=f"refresh-{access}",
        expires=0 if expired else int(time.time() * 1000) + 3_600_000,
        account_id=f"account-{access}",
    )


def test_missing_and_corrupt_instance_tokens_never_import_user_credentials(tmp_path, monkeypatch):
    user_home = tmp_path / "user"
    codex_auth = user_home / ".codex" / "auth.json"
    codex_auth.parent.mkdir(parents=True)
    codex_auth.write_text(json.dumps({"tokens": {
        "access_token": "foreign-access", "refresh_token": "foreign-refresh", "account_id": "foreign",
    }}))
    decoy = tmp_path / "decoy.json"
    decoy.write_text(json.dumps({"access": "foreign", "refresh": "foreign", "expires": 9999999999999}))
    monkeypatch.setenv("HOME", str(user_home))
    monkeypatch.setenv("OAUTH_CLI_KIT_TOKEN_PATH", str(decoy))
    instance_home = tmp_path / "instance"
    storage = codex_token_storage(instance_home)
    assert storage.load() is None
    assert not instance_home.exists()
    storage.get_token_path().parent.mkdir(parents=True)
    storage.get_token_path().write_text("{corrupt")
    assert storage.load() is None
    assert storage.get_token_path().read_text() == "{corrupt"
    storage.save(_token("owned"))
    assert get_token(storage=storage).access == "owned"
    assert json.loads(decoy.read_text())["access"] == "foreign"


def test_refresh_retains_captured_home_and_same_home_lock(tmp_path, monkeypatch):
    import oauth_cli_kit.flow as flow

    first = codex_token_storage(tmp_path / "a")
    second = codex_token_storage(tmp_path / "b")
    first.save(_token("a", expired=True))
    second.save(_token("b"))
    entered = threading.Event()
    finish = threading.Event()
    same_home_loaded = threading.Event()
    same_home = codex_token_storage(tmp_path / "a")
    load = same_home.load
    refreshes = []

    def load_same_home():
        token = load()
        same_home_loaded.set()
        return token

    def refresh(refresh_token, provider, proxy):
        refreshes.append(refresh_token)
        entered.set()
        assert finish.wait(2)
        return _token("rotated-a")

    monkeypatch.setattr(flow, "_refresh_token", refresh)
    monkeypatch.setattr(same_home, "load", load_same_home)
    monkeypatch.setattr(home_module, "_home_path", tmp_path / "b")
    monkeypatch.setenv("OAUTH_CLI_KIT_TOKEN_PATH", str(second.get_token_path()))
    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(get_token, storage=first)
        assert entered.wait(2)
        two = pool.submit(get_token, storage=same_home)
        assert same_home_loaded.wait(2)
        finish.set()
        assert one.result().access == two.result().access == "rotated-a"
    assert refreshes == ["refresh-a"]
    assert second.load().access == "b"


@pytest.mark.asyncio
async def test_factory_providers_keep_home_after_another_config_is_selected(tmp_path, monkeypatch):
    from nanobot.providers import openai_codex_provider

    config_path = tmp_path / "external.json"
    config_path.write_text(json.dumps({"agents": {"defaults": {
        "provider": "openai_codex", "model": "openai-codex/gpt-5.6-sol",
    }}}))
    a = load_config(config_path, home=tmp_path / "a")
    b = load_config(config_path, home=tmp_path / "b")
    codex_token_storage(a.instance_home).save(_token("a"))
    codex_token_storage(b.instance_home).save(_token("b"))
    provider_a, provider_b = make_provider(a), make_provider(b)
    monkeypatch.setattr(home_module, "_home_path", b.instance_home)
    monkeypatch.setenv("OAUTH_CLI_KIT_TOKEN_PATH", str(codex_token_storage(b.instance_home).get_token_path()))
    authorization = []

    async def request(url, headers, body, **kwargs):
        authorization.append(headers["Authorization"])
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "done"}]}]}

    monkeypatch.setattr(openai_codex_provider, "_request_codex", request)
    try:
        await provider_a.chat([{"role": "user", "content": "hello"}])
        await provider_b.chat([{"role": "user", "content": "hello"}])
        assert authorization == ["Bearer a", "Bearer b"]
    finally:
        await provider_a.aclose()
        await provider_b.aclose()


def test_catalog_fetch_uses_same_instance_as_cache_identity(tmp_path, monkeypatch):
    from nanobot.providers import openai_codex_provider

    home_a, home_b = tmp_path / "a", tmp_path / "b"
    codex_token_storage(home_a).save(_token("a"))
    codex_token_storage(home_b).save(_token("b"))
    monkeypatch.setattr(home_module, "_home_path", home_b)
    monkeypatch.setenv("OAUTH_CLI_KIT_TOKEN_PATH", str(codex_token_storage(home_b).get_token_path()))
    original_client = httpx.Client
    calls = []

    def handle(request):
        calls.append(request.headers["Authorization"])
        name = request.headers["Authorization"].split()[-1]
        return httpx.Response(200, json={"models": [{"slug": f"model-{name}", "display_name": name}]})

    monkeypatch.setattr(openai_codex_provider.httpx, "Client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(handle),
    ))
    a = get_oauth_model_catalog("openai_codex", home=home_a, refresh=True)
    b = get_oauth_model_catalog("openai_codex", home=home_b, refresh=True)
    reused = get_oauth_model_catalog("openai_codex", home=home_a)
    assert a.find("model-a") is not None
    assert b.find("model-b") is not None
    assert reused.source == "cache"
    assert calls == ["Bearer a", "Bearer b"]


@pytest.mark.asyncio
async def test_mcp_storage_retains_home_and_logout_fences_only_that_home(tmp_path, monkeypatch):
    a, b = tmp_path / "a", tmp_path / "b"
    first = MCPOAuthStorage("server", "https://mcp.example/mcp", home=a)
    second = MCPOAuthStorage("server", "https://mcp.example/mcp", home=b)
    monkeypatch.setattr(home_module, "_home_path", b)
    await first.set_tokens(MCPOAuthToken(access_token="a"))
    await second.set_tokens(MCPOAuthToken(access_token="b"))
    assert (await MCPOAuthStorage("server", "https://mcp.example/mcp", home=a).get_tokens()).access_token == "a"
    assert delete_mcp_oauth_credentials("server", home=a)
    await first.set_tokens(MCPOAuthToken(access_token="late-a"))
    assert await first.get_tokens() is None
    assert (await second.get_tokens()).access_token == "b"


def test_copilot_login_commits_to_captured_home_after_selection_changes(tmp_path, monkeypatch):
    from nanobot.providers import github_copilot_oauth
    from nanobot.providers.github_copilot_provider import get_github_copilot_login_status

    first, second = tmp_path / "a", tmp_path / "b"
    flow = github_copilot_oauth.GitHubCopilotOAuthFlow(home=first)

    def login(**kwargs):
        kwargs["on_authorization"]("https://github.example/login", "device-code", 900)
        return _token("a")

    monkeypatch.setattr(github_copilot_oauth, "login_github_copilot", login)
    flow.start()
    monkeypatch.setattr(home_module, "_home_path", second)
    deadline = time.monotonic() + 2
    while flow.complete() is None:
        assert time.monotonic() < deadline
        time.sleep(0.01)
    assert get_github_copilot_login_status(home=first).access == "a"
    assert get_github_copilot_login_status(home=second) is None
    assert not second.exists()


def test_xai_refresh_and_logout_keep_explicit_home(tmp_path, monkeypatch):
    from nanobot.providers import xai_oauth

    first, second = tmp_path / "a", tmp_path / "b"
    token_path = xai_oauth.get_xai_oauth_storage_path(first)
    token_path.parent.mkdir(parents=True)
    token_path.write_text(json.dumps({"access": "a", "refresh": "refresh-a", "expires": 0}))
    other_path = xai_oauth.get_xai_oauth_storage_path(second)
    other_path.parent.mkdir(parents=True)
    other_path.write_text(json.dumps({"access": "b", "refresh": "refresh-b", "expires": 9999999999999}))
    monkeypatch.setattr(home_module, "_home_path", second)
    monkeypatch.setattr(xai_oauth, "_refresh_token", lambda token, proxy: xai_oauth.XAIToken(
        access=f"rotated-{token.access}", refresh="rotated-refresh", expires=9999999999999,
    ))
    assert xai_oauth.get_xai_oauth_token(storage_path=token_path).access == "rotated-a"
    assert xai_oauth.get_xai_oauth_login_status(home=first).access == "rotated-a"
    assert xai_oauth.logout_xai_oauth(home=first)
    assert xai_oauth.get_xai_oauth_login_status(home=first) is None
    assert xai_oauth.get_xai_oauth_login_status(home=second).access == "b"
